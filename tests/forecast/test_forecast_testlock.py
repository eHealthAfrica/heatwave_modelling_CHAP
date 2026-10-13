"""Tests for heatwave.forecast.testlock (EVAL-05): lock semantics, log chain, isolation.

Quick tests stub the private ``_git_runner``; real-git tests are marked slow.
"""
import dataclasses
import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

from heatwave.forecast import artifacts, testlock
from heatwave.forecast.config import config_hash
from heatwave.forecast.testlock import TestLockError


class FakeGit:
    """Callable(args, repo_root) standing in for testlock._git_runner."""

    def __init__(self, repo_root, tracked=True, head="a" * 40, worktree="a" * 40):
        self.toplevel = str(repo_root)
        self.tracked = tracked
        self.head = head
        self.worktree = worktree
        self.blob = None  # committed text for `git show`; None = same as the working-tree file
        self.calls = []

    def __call__(self, args, repo_root):
        self.calls.append(list(args))
        if args[0] == "show":
            if self.blob is not None:
                return self.blob
            p = Path(self.toplevel) / testlock.PREREG_RELPATH
            return p.read_text(encoding="utf-8") if p.exists() else None
        if args[0] == "rev-parse" and args[1] == "--show-toplevel":
            return self.toplevel + "\n"
        if args[0] == "ls-files":
            return (testlock.PREREG_RELPATH + "\n") if self.tracked else None
        if args[0] == "rev-parse":
            return None if self.head is None else self.head + "\n"
        if args[0] == "hash-object":
            return None if self.worktree is None else self.worktree + "\n"
        return None


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "docs" / "forecast").mkdir(parents=True)
    return r


BUNDLE_BYTES = b"bundle-bytes"
BUNDLE_SHA = hashlib.sha256(BUNDLE_BYTES).hexdigest()


def prereg_text(cfg, bundle_sha=BUNDLE_SHA, eol="\n"):
    """A pre-registration body with both labelled frozen identifiers (default bundle content)."""
    return (
        "# pre-registration" + eol
        + "- config sha256: " + config_hash(cfg) + eol
        + "- model bundle sha256: " + bundle_sha + eol
    )


def write_prereg(repo, text):
    (repo / testlock.PREREG_RELPATH).write_text(text, encoding="utf-8")


def make_bundle(data_root, content=BUNDLE_BYTES):
    p = testlock.forecast_runs_dir(data_root) / "run1" / "bundle.bin"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


@pytest.fixture
def fake(monkeypatch, repo):
    f = FakeGit(repo)
    monkeypatch.setattr(testlock, "_git_runner", f)
    return f


@pytest.fixture
def opened(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, prereg_text(forecast_cfg))
    bundle = make_bundle(testlock_root)
    rec = testlock.open_lock(
        forecast_cfg, model_bundle_path=bundle, opened_by="unit", repo_root=repo
    )
    return rec, bundle


# ----------------------------------------------------------------------------- closed
def test_closed_by_default_without_git(forecast_cfg, testlock_root, repo, fake):
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert ok is False and "not opened" in reason
    assert fake.calls == []


@pytest.mark.parametrize(
    "fn", [testlock.open_lock, testlock.lock_status, testlock.require_open, testlock.labels_unlocked]
)
def test_no_git_parameter(fn):
    assert "git" not in inspect.signature(fn).parameters


def test_require_open_refuses_and_logs(forecast_cfg, testlock_root, repo, fake):
    with pytest.raises(TestLockError):
        testlock.require_open(forecast_cfg, "unit", repo_root=repo)
    recs = testlock.read_log()
    assert len(recs) == 1
    assert recs[0]["event"] == "test_access_refused"
    assert recs[0]["split"] == "test" and recs[0]["outcome"] == "refused"


# ----------------------------------------------------------------------------- open
def test_open_lock_writes_record_and_logs(forecast_cfg, testlock_root, repo, opened):
    rec, bundle = opened
    assert testlock.lock_path().exists()
    assert rec["config_sha256"] == config_hash(forecast_cfg)
    assert rec["model_bundle_path"] == "run1/bundle.bin"
    assert [r["event"] for r in testlock.read_log()] == ["lock_opened"]
    got = testlock.require_open(forecast_cfg, "unit", repo_root=repo)
    assert got["model_bundle_sha256"] == rec["model_bundle_sha256"]
    last = testlock.read_log()[-1]
    assert last["event"] == "test_access_granted" and last["outcome"] == "granted"
    assert testlock.count_test_runs() == 0  # a loader grant is not a test run (WR-07)


def test_open_lock_idempotent_and_conflict(forecast_cfg, testlock_root, repo, opened):
    rec, bundle = opened
    again = testlock.open_lock(
        forecast_cfg, model_bundle_path=bundle, opened_by="other", repo_root=repo
    )
    assert again == rec
    bundle.write_bytes(b"different")
    write_prereg(repo, prereg_text(forecast_cfg, hashlib.sha256(b"different").hexdigest()))
    with pytest.raises(TestLockError, match="different hashes"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)


def test_open_lock_refuses_placeholder_and_missing_hash(forecast_cfg, testlock_root, repo, fake):
    bundle = make_bundle(testlock_root)
    write_prereg(repo, prereg_text(forecast_cfg) + testlock.PLACEHOLDER + "\n")
    with pytest.raises(TestLockError, match="placeholder"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)
    write_prereg(repo, "no hash here\n")
    with pytest.raises(TestLockError, match="config hash"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)
    assert not testlock.lock_path().exists()
    assert {r["outcome"] for r in testlock.read_log()} == {"refused"}


def test_open_lock_refuses_dirty_or_untracked(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, config_hash(forecast_cfg))
    bundle = make_bundle(testlock_root)
    fake.worktree = "b" * 40
    with pytest.raises(TestLockError):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)
    fake.worktree = "a" * 40
    fake.tracked = False
    with pytest.raises(TestLockError):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)


def test_open_lock_bundle_must_be_inside_runs(forecast_cfg, testlock_root, repo, fake, tmp_path):
    write_prereg(repo, config_hash(forecast_cfg))
    outside = tmp_path / "elsewhere.bin"
    outside.write_bytes(b"x")
    with pytest.raises(TestLockError, match="inside forecast_runs"):
        testlock.open_lock(forecast_cfg, model_bundle_path=outside, opened_by="u", repo_root=repo)


# ----------------------------------------------------------------------------- tamper re-closes
def test_config_change_recloses(forecast_cfg, testlock_root, repo, opened):
    cfg2 = dataclasses.replace(forecast_cfg, seed=forecast_cfg.seed + 1)
    ok, reason = testlock.lock_status(cfg2, repo_root=repo)
    assert not ok and "config changed" in reason
    with pytest.raises(TestLockError):
        testlock.require_open(cfg2, "unit", repo_root=repo)


def test_bundle_change_recloses(forecast_cfg, testlock_root, repo, opened):
    _, bundle = opened
    bundle.write_bytes(b"tampered")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "bundle" in reason


def test_head_vs_worktree_mismatch_recloses(forecast_cfg, testlock_root, repo, opened, fake):
    fake.worktree = "c" * 40
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "pre-registration" in reason


def test_head_blob_change_recloses(forecast_cfg, testlock_root, repo, opened, fake):
    fake.head = fake.worktree = "d" * 40  # clean but a different committed version
    ok, _ = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok


def test_malformed_lock_recloses(forecast_cfg, testlock_root, repo, opened):
    testlock.lock_path().write_text("{not json", encoding="utf-8")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "malformed" in reason
    with pytest.raises(TestLockError):
        testlock.require_open(forecast_cfg, "unit", repo_root=repo)


def test_lock_with_escaping_bundle_path_is_malformed(forecast_cfg, testlock_root, repo, opened):
    p = testlock.lock_path()
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["model_bundle_path"] = "../outside.bin"
    p.write_text(json.dumps(rec), encoding="utf-8")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "malformed" in reason


# ----------------------------------------------------------------------------- labels_unlocked
def test_labels_unlocked_closed_and_open(forecast_cfg, testlock_root, repo, fake):
    assert testlock.labels_unlocked(forecast_cfg, "issue_table", repo_root=repo) is False
    last = testlock.read_log()[-1]
    assert last["outcome"] == "blanked" and last["event"] == "test_access_refused"


def test_labels_unlocked_open(forecast_cfg, testlock_root, repo, opened):
    assert testlock.labels_unlocked(forecast_cfg, "issue_table", repo_root=repo) is True
    assert testlock.read_log()[-1]["outcome"] == "granted"


# ----------------------------------------------------------------------------- log
def test_log_chain_detects_edit_and_deletion(testlock_root):
    for i in range(4):
        testlock.log_event("score", outcome="scored", split="validate", predictor=f"p{i}")
    assert testlock.verify_log_chain() is True
    path = testlock.log_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = lines.copy()
    edited[1] = edited[1].replace('"p1"', '"px"')
    path.write_text("\n".join(edited) + "\n", encoding="utf-8")
    assert testlock.verify_log_chain() is False
    path.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")
    assert testlock.verify_log_chain() is False
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert testlock.verify_log_chain() is True


def test_log_event_validates_vocabulary(testlock_root):
    with pytest.raises(ValueError):
        testlock.log_event("bogus", outcome="scored")
    with pytest.raises(ValueError):
        testlock.log_event("score", outcome="bogus")


def test_count_test_runs_counts_only_opened_evaluations(testlock_root):
    testlock.log_event("score", outcome="scored", split="validate")
    testlock.log_event("score", outcome="scored", split="test")
    testlock.log_event("test_access_granted", outcome="granted", split="test")
    testlock.log_event("test_access_refused", outcome="refused", split="test")
    testlock.log_event("test_access_refused", outcome="blanked", split="test")
    assert testlock.count_test_runs() == 0
    testlock.log_event("test_evaluation_opened", outcome="opened", split="test", run_id="r1")
    assert testlock.count_test_runs() == 1


def test_forecast_runs_dir_refuses_repo_and_frozen(tmp_path):
    with pytest.raises(ValueError):
        testlock.forecast_runs_dir(artifacts.REPO_ROOT / "somewhere")
    ok = testlock.forecast_runs_dir(tmp_path)
    assert ok == (tmp_path / artifacts.RUNS_SUBDIR).resolve()


def test_session_root_is_isolated_from_real_data_root():
    from heatwave.config import settings

    assert testlock._default_data_root() != settings.local_data_dir


# ----------------------------------------------------------------------------- template / repo
def test_phase14_preregistration_is_complete_and_matches_config(forecast_cfg):
    """Phase 14 committed the real pre-registration; it must stay filled in and tied to the config."""
    text = (artifacts.REPO_ROOT / testlock.PREREG_RELPATH).read_text(encoding="utf-8")
    assert testlock.PLACEHOLDER not in text
    assert testlock._has_labelled_hash(text, "config sha256", config_hash(forecast_cfg))
    assert re.search(r"^- model bundle sha256: [0-9a-f]{64}$", text, re.MULTILINE)


def test_template_has_placeholders():
    t = artifacts.REPO_ROOT / testlock.TEMPLATE_RELPATH
    assert t.exists()
    text = t.read_text(encoding="utf-8")
    assert text.count(testlock.PLACEHOLDER) >= 2
    for heading in ("## Primary metric", "## Primary leads", "## Reference forecasts",
                    "## Confidence interval method", "## Go / no-go rule",
                    "## Confirmatory slices", "## Frozen identifiers", "## Retrain policy",
                    "## Test years"):
        assert heading in text
    assert "config sha256" in text and "model bundle sha256" in text


@pytest.mark.frozen
def test_real_log_has_no_test_runs():
    from pathlib import Path

    from heatwave.config import settings

    assert testlock.count_test_runs(data_root=Path(settings.local_data_dir)) == 0


# ----------------------------------------------------------------------------- real git (slow)
def _git(repo, *args):
    import subprocess

    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def real_repo(tmp_path, make_git_repo):
    r = make_git_repo(tmp_path / "repo")
    (r / "docs" / "forecast").mkdir(parents=True)
    return r


def _commit_prereg(repo, data: bytes):
    (repo / testlock.PREREG_RELPATH).write_bytes(data)
    _git(repo, "add", testlock.PREREG_RELPATH)
    _git(repo, "commit", "-q", "-m", "prereg")


def _open(cfg, repo, root):
    bundle = make_bundle(root)
    return testlock.open_lock(cfg, model_bundle_path=bundle, opened_by="slow", repo_root=repo)


@pytest.mark.slow
def test_real_git_open_and_grant(forecast_cfg, testlock_root, real_repo):
    _commit_prereg(real_repo, prereg_text(forecast_cfg).encode())
    _open(forecast_cfg, real_repo, testlock_root)
    assert testlock.require_open(forecast_cfg, "slow", repo_root=real_repo)["opened_by"] == "slow"


@pytest.mark.slow
def test_real_git_modified_after_commit_refused(forecast_cfg, testlock_root, real_repo):
    _commit_prereg(real_repo, prereg_text(forecast_cfg).encode())
    _open(forecast_cfg, real_repo, testlock_root)
    (real_repo / testlock.PREREG_RELPATH).write_bytes(
        (prereg_text(forecast_cfg) + "edited" + chr(10)).encode()
    )
    with pytest.raises(TestLockError):
        testlock.require_open(forecast_cfg, "slow", repo_root=real_repo)


@pytest.mark.slow
def test_real_git_untracked_and_staged_only_refused(forecast_cfg, testlock_root, real_repo):
    (real_repo / "README").write_text("x", encoding="utf-8")
    _git(real_repo, "add", "README")
    _git(real_repo, "commit", "-q", "-m", "init")
    path = real_repo / testlock.PREREG_RELPATH
    path.write_bytes(prereg_text(forecast_cfg).encode())
    bundle = make_bundle(testlock_root)
    with pytest.raises(TestLockError):  # untracked
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="s", repo_root=real_repo)
    _git(real_repo, "add", testlock.PREREG_RELPATH)
    with pytest.raises(TestLockError):  # staged only, HEAD lacks the path
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="s", repo_root=real_repo)


@pytest.mark.slow
def test_real_git_crlf_working_copy_is_clean(forecast_cfg, testlock_root, tmp_path, make_git_repo):
    repo = make_git_repo(tmp_path / "crlf", autocrlf=True)
    (repo / "docs" / "forecast").mkdir(parents=True)
    _commit_prereg(repo, prereg_text(forecast_cfg, eol=chr(13) + chr(10)).encode())
    _open(forecast_cfg, repo, testlock_root)
    assert testlock.lock_status(forecast_cfg, repo_root=repo) == (True, "open")


@pytest.mark.slow
def test_real_git_template_copy_refused(forecast_cfg, testlock_root, real_repo):
    template = (artifacts.REPO_ROOT / testlock.TEMPLATE_RELPATH).read_bytes()
    _commit_prereg(real_repo, template + (chr(10) + prereg_text(forecast_cfg)).encode())
    bundle = make_bundle(testlock_root)
    with pytest.raises(TestLockError, match="placeholder"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="s", repo_root=real_repo)


@pytest.mark.slow
def test_real_git_config_change_after_open_refused(forecast_cfg, testlock_root, real_repo):
    _commit_prereg(real_repo, prereg_text(forecast_cfg).encode())
    _open(forecast_cfg, real_repo, testlock_root)
    cfg2 = dataclasses.replace(forecast_cfg, seed=forecast_cfg.seed + 1)
    with pytest.raises(TestLockError):
        testlock.require_open(cfg2, "slow", repo_root=real_repo)


# ----------------------------------------------------------------------------- review WR-04
def _log_lines():
    return testlock.log_path().read_text(encoding="utf-8").splitlines()


def _write_lines(lines):
    testlock.log_path().write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_lock_records_log_head(forecast_cfg, testlock_root, repo, opened):
    rec, _ = opened
    assert rec["log_head_sha256"] == testlock.log_head_sha256()
    assert json.loads(testlock.lock_path().read_text(encoding="utf-8"))["log_head_sha256"] == rec["log_head_sha256"]
    assert testlock.lock_status(forecast_cfg, repo_root=repo) == (True, "open")


def test_open_survives_later_appends(forecast_cfg, testlock_root, repo, opened):
    testlock.require_open(forecast_cfg, "unit", repo_root=repo)
    testlock.log_event("score", outcome="scored", split="validate")
    assert testlock.lock_status(forecast_cfg, repo_root=repo) == (True, "open")


def test_log_tail_truncation_recloses(forecast_cfg, testlock_root, repo, opened):
    testlock.require_open(forecast_cfg, "unit", repo_root=repo)
    lines = _log_lines()
    assert len(lines) == 2
    _write_lines(lines[:-2])  # drop lock_opened and the grant: the chain is still valid, the head is gone
    assert testlock.verify_log_chain() is True
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "truncated" in reason
    with pytest.raises(TestLockError):
        testlock.require_open(forecast_cfg, "unit", repo_root=repo)


def test_log_deletion_recloses(forecast_cfg, testlock_root, repo, opened):
    testlock.log_path().unlink()
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "missing" in reason
    # a fresh log restarting at GENESIS must not reopen it either
    testlock.log_event("score", outcome="scored", split="validate")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "truncated" in reason


def test_log_edit_recloses(forecast_cfg, testlock_root, repo, opened):
    testlock.require_open(forecast_cfg, "unit", repo_root=repo)
    lines = _log_lines()
    lines[0] = lines[0].replace('"unit"', '"x"').replace("open_lock", "xxxx_lock")
    _write_lines(lines)
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "chain" in reason


def test_count_test_runs_refuses_broken_chain(testlock_root):
    for i in range(3):
        testlock.log_event("score", outcome="scored", split="test", predictor=f"p{i}")
    lines = _log_lines()
    _write_lines(lines[:1] + lines[2:])
    with pytest.raises(TestLockError, match="chain"):
        testlock.count_test_runs()


def test_open_lock_refuses_on_broken_chain(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, prereg_text(forecast_cfg))
    bundle = make_bundle(testlock_root)
    for i in range(3):
        testlock.log_event("score", outcome="scored", split="validate", predictor=f"p{i}")
    lines = _log_lines()
    _write_lines(lines[:1] + lines[2:])
    with pytest.raises(TestLockError, match="chain"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)
    assert not testlock.lock_path().exists()


def test_lock_missing_log_head_is_malformed(forecast_cfg, testlock_root, repo, opened):
    p = testlock.lock_path()
    rec = json.loads(p.read_text(encoding="utf-8"))
    del rec["log_head_sha256"]
    p.write_text(json.dumps(rec), encoding="utf-8")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "malformed" in reason


@pytest.mark.parametrize(
    "bundle",
    ["C:foo.bin", "C:/abs.bin", "/abs.bin", r"\\srv\share\x.bin", r"\abs.bin", r"..\x.bin"],
)
def test_lock_with_drive_or_anchor_bundle_path_is_malformed(forecast_cfg, testlock_root, repo, opened, bundle):
    p = testlock.lock_path()
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["model_bundle_path"] = bundle
    p.write_text(json.dumps(rec), encoding="utf-8")
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "malformed" in reason


@pytest.mark.frozen
def test_real_log_chain_is_intact_and_has_no_lock():
    """Read-only: the fail-safe must not treat the real hash-chained log as broken."""
    from pathlib import Path

    from heatwave.config import settings

    root = Path(settings.local_data_dir)
    assert testlock.verify_log_chain(root) is True
    assert not testlock.lock_path(root).exists()


# ----------------------------------------------------------------------------- review WR-05
def _open_attempt(cfg, repo, root, bundle=None):
    bundle = bundle or make_bundle(root)
    return testlock.open_lock(cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)


def test_open_requires_bundle_hash_in_preregistration(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, "- config sha256: " + config_hash(forecast_cfg) + chr(10))
    with pytest.raises(TestLockError, match="bundle hash"):
        _open_attempt(forecast_cfg, repo, testlock_root)
    write_prereg(repo, prereg_text(forecast_cfg, "f" * 64))  # a different bundle was registered
    with pytest.raises(TestLockError, match="bundle hash"):
        _open_attempt(forecast_cfg, repo, testlock_root)
    assert not testlock.lock_path().exists()


def test_open_rejects_hashes_that_only_appear_somewhere(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, "see " + config_hash(forecast_cfg) + " and " + BUNDLE_SHA + " in the appendix" + chr(10))
    with pytest.raises(TestLockError, match="config hash"):
        _open_attempt(forecast_cfg, repo, testlock_root)


def test_open_rejects_hashes_hidden_in_html_comment(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, "<!--" + chr(10) + prereg_text(forecast_cfg) + "-->" + chr(10))
    with pytest.raises(TestLockError, match="config hash"):
        _open_attempt(forecast_cfg, repo, testlock_root)


def test_status_reads_committed_blob_not_working_tree(forecast_cfg, testlock_root, repo, opened, fake):
    assert testlock.lock_status(forecast_cfg, repo_root=repo) == (True, "open")
    fake.blob = "- config sha256: " + config_hash(forecast_cfg) + chr(10)  # committed text lacks the bundle line
    ok, reason = testlock.lock_status(forecast_cfg, repo_root=repo)
    assert not ok and "bundle hash" in reason
    fake.blob = None


def test_open_audits_blob_even_if_working_tree_looks_right(forecast_cfg, testlock_root, repo, fake):
    write_prereg(repo, prereg_text(forecast_cfg))  # working tree is fine ...
    fake.blob = "nothing registered" + chr(10)  # ... but the committed bytes are not
    with pytest.raises(TestLockError, match="config hash"):
        _open_attempt(forecast_cfg, repo, testlock_root)


@pytest.mark.parametrize("name", [testlock.LOCK_NAME, testlock.LOG_NAME])
def test_bundle_cannot_be_lock_or_log_file(forecast_cfg, testlock_root, repo, fake, name):
    runs = testlock.forecast_runs_dir()
    runs.mkdir(parents=True, exist_ok=True)
    f = runs / name
    f.write_bytes(b"x")
    write_prereg(repo, prereg_text(forecast_cfg, hashlib.sha256(b"x").hexdigest()))
    with pytest.raises(TestLockError, match="lock or the evaluation log"):
        _open_attempt(forecast_cfg, repo, testlock_root, bundle=f)


# ----------------------------------------------------------------------------- review WR-07
RUN_A = "20270101T000000Z_aaaaaaaa"
RUN_B = "20270102T000000Z_bbbbbbbb"


def test_open_test_evaluation_needs_open_lock(forecast_cfg, testlock_root, repo, fake):
    with pytest.raises(TestLockError, match="locked"):
        testlock.open_test_evaluation(forecast_cfg, RUN_A, repo_root=repo)
    assert testlock.count_test_runs() == 0


def test_one_event_per_evaluation_and_many_grants_do_not_count(forecast_cfg, testlock_root, repo, opened):
    for lead in (1, 2, 3):
        testlock.open_test_evaluation(forecast_cfg, RUN_A, lead=lead, repo_root=repo)
        for _ in range(5):  # loader grants, one per predictor file
            testlock.require_open(forecast_cfg, "load_predictions", repo_root=repo)
        testlock.log_event("score", outcome="scored", split="test", lead=lead, run_id=RUN_A)
    events = [r for r in testlock.read_log() if r["event"] == "test_evaluation_opened"]
    assert len(events) == 1 and events[0]["run_id"] == RUN_A
    assert testlock.count_test_runs() == 1


def test_second_test_evaluation_is_refused(forecast_cfg, testlock_root, repo, opened):
    testlock.open_test_evaluation(forecast_cfg, RUN_A, lead=1, repo_root=repo)
    with pytest.raises(TestLockError, match="one-shot"):
        testlock.open_test_evaluation(forecast_cfg, RUN_B, lead=1, repo_root=repo)
    assert testlock.count_test_runs() == 1
    last = testlock.read_log()[-1]
    assert last["outcome"] == "refused" and last["run_id"] == RUN_B


def test_rescoring_same_lead_is_refused(forecast_cfg, testlock_root, repo, opened):
    testlock.open_test_evaluation(forecast_cfg, RUN_A, lead=1, repo_root=repo)
    testlock.log_event("score", outcome="scored", split="test", lead=1, run_id=RUN_A)
    with pytest.raises(TestLockError, match="already scored"):
        testlock.open_test_evaluation(forecast_cfg, RUN_A, lead=1, repo_root=repo)
    testlock.open_test_evaluation(forecast_cfg, RUN_A, lead=2, repo_root=repo)  # another lead is fine


def test_count_scored_by_split_run_and_lead(testlock_root):
    testlock.log_event("score", outcome="scored", split="validate", lead=1, run_id=RUN_A)
    testlock.log_event("score", outcome="scored", split="test", lead=1, run_id=RUN_A)
    testlock.log_event("score", outcome="scored", split="test", lead=2, run_id=RUN_B)
    assert testlock.count_scored("test") == 2
    assert testlock.count_scored("test", run_id=RUN_A) == 1
    assert testlock.count_scored("test", run_id=RUN_A, lead=2) == 0
    assert testlock.count_scored("validate") == 1
