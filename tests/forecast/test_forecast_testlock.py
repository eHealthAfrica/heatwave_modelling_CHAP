"""Tests for heatwave.forecast.testlock (EVAL-05): lock semantics, log chain, isolation.

Quick tests stub the private ``_git_runner``; real-git tests are marked slow.
"""
import dataclasses
import inspect
import json

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
        self.calls = []

    def __call__(self, args, repo_root):
        self.calls.append(list(args))
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


def write_prereg(repo, text):
    (repo / testlock.PREREG_RELPATH).write_text(text, encoding="utf-8")


def make_bundle(data_root, content=b"bundle-bytes"):
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
    write_prereg(repo, f"config sha256: {config_hash(forecast_cfg)}\n")
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
    assert testlock.count_test_runs() == 1


def test_open_lock_idempotent_and_conflict(forecast_cfg, testlock_root, repo, opened):
    rec, bundle = opened
    again = testlock.open_lock(
        forecast_cfg, model_bundle_path=bundle, opened_by="other", repo_root=repo
    )
    assert again == rec
    bundle.write_bytes(b"different")
    with pytest.raises(TestLockError, match="different hashes"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="u", repo_root=repo)


def test_open_lock_refuses_placeholder_and_missing_hash(forecast_cfg, testlock_root, repo, fake):
    bundle = make_bundle(testlock_root)
    write_prereg(repo, f"{config_hash(forecast_cfg)} {testlock.PLACEHOLDER}\n")
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


def test_count_test_runs_counts_only_test_granted_or_scored(testlock_root):
    testlock.log_event("score", outcome="scored", split="validate")
    testlock.log_event("score", outcome="scored", split="test")
    testlock.log_event("test_access_granted", outcome="granted", split="test")
    testlock.log_event("test_access_refused", outcome="refused", split="test")
    testlock.log_event("test_access_refused", outcome="blanked", split="test")
    assert testlock.count_test_runs() == 2


def test_forecast_runs_dir_refuses_repo_and_frozen(tmp_path):
    with pytest.raises(ValueError):
        testlock.forecast_runs_dir(artifacts.REPO_ROOT / "somewhere")
    ok = testlock.forecast_runs_dir(tmp_path)
    assert ok == (tmp_path / artifacts.RUNS_SUBDIR).resolve()


def test_session_root_is_isolated_from_real_data_root():
    from heatwave.config import settings

    assert testlock._default_data_root() != settings.local_data_dir


# ----------------------------------------------------------------------------- template / repo
def test_phase10_has_no_real_preregistration():
    """Phase 14 replaces this test when it commits the real pre-registration file."""
    assert not (artifacts.REPO_ROOT / testlock.PREREG_RELPATH).exists()


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
    _commit_prereg(real_repo, f"hash {config_hash(forecast_cfg)}\n".encode())
    _open(forecast_cfg, real_repo, testlock_root)
    assert testlock.require_open(forecast_cfg, "slow", repo_root=real_repo)["opened_by"] == "slow"


@pytest.mark.slow
def test_real_git_modified_after_commit_refused(forecast_cfg, testlock_root, real_repo):
    _commit_prereg(real_repo, f"hash {config_hash(forecast_cfg)}\n".encode())
    _open(forecast_cfg, real_repo, testlock_root)
    (real_repo / testlock.PREREG_RELPATH).write_bytes(
        f"hash {config_hash(forecast_cfg)}\nedited\n".encode()
    )
    with pytest.raises(TestLockError):
        testlock.require_open(forecast_cfg, "slow", repo_root=real_repo)


@pytest.mark.slow
def test_real_git_untracked_and_staged_only_refused(forecast_cfg, testlock_root, real_repo):
    (real_repo / "README").write_text("x", encoding="utf-8")
    _git(real_repo, "add", "README")
    _git(real_repo, "commit", "-q", "-m", "init")
    path = real_repo / testlock.PREREG_RELPATH
    path.write_bytes(f"hash {config_hash(forecast_cfg)}\n".encode())
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
    _commit_prereg(repo, f"hash {config_hash(forecast_cfg)}\r\nline\r\n".encode())
    _open(forecast_cfg, repo, testlock_root)
    assert testlock.lock_status(forecast_cfg, repo_root=repo) == (True, "open")


@pytest.mark.slow
def test_real_git_template_copy_refused(forecast_cfg, testlock_root, real_repo):
    template = (artifacts.REPO_ROOT / testlock.TEMPLATE_RELPATH).read_bytes()
    _commit_prereg(real_repo, template + f"\n{config_hash(forecast_cfg)}\n".encode())
    bundle = make_bundle(testlock_root)
    with pytest.raises(TestLockError, match="placeholder"):
        testlock.open_lock(forecast_cfg, model_bundle_path=bundle, opened_by="s", repo_root=real_repo)


@pytest.mark.slow
def test_real_git_config_change_after_open_refused(forecast_cfg, testlock_root, real_repo):
    _commit_prereg(real_repo, f"hash {config_hash(forecast_cfg)}\n".encode())
    _open(forecast_cfg, real_repo, testlock_root)
    cfg2 = dataclasses.replace(forecast_cfg, seed=forecast_cfg.seed + 1)
    with pytest.raises(TestLockError):
        testlock.require_open(cfg2, "slow", repo_root=real_repo)
