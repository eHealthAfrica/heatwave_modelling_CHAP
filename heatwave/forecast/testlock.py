"""Test-split lock and append-only evaluation log (EVAL-05).

The test years (2021-2026) may be read only after the pre-registration is committed and the
lock is opened. The lock is a mechanical safeguard for the loaders plus an audit trail, not a
security boundary: raw ``targets.lead_label`` arrays are not guarded, and anyone with write
access to the data root can edit the files. Every access attempt is appended to a
hash-chained JSONL log so tampering with its history is detectable.

The lock is closed by default. It opens only while all of these hold: ``TEST_LOCK.json``
exists; the current config hash and the model bundle sha256 equal the recorded ones;
``docs/forecast/PREREGISTRATION.md`` is tracked, committed in HEAD, unmodified in the
working tree, holds no placeholder token and (read from the committed blob, not the working
tree) carries the labelled lines ``config sha256: <hash>`` and ``model bundle sha256: <hash>``
for the current config and the bundle being opened; and the evaluation
log has an intact hash chain that still contains the head hash recorded in ``TEST_LOCK.json``
at open time (a missing, truncated or edited log re-closes the lock). Changing any of
them re-closes the lock.

The ``repo_root`` and ``data_root`` keyword parameters exist only so tests can point at tmp
repos and data roots; loaders (dataset, predictions, harness, scripts) never pass them.
All git access goes through the private ``_git_runner``, which tests replace; there is no
public way to inject a git callable and no bypass flag for the test split.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from heatwave.forecast import artifacts
from heatwave.forecast.config import ForecastConfig, config_hash
from heatwave.forecast.data import sha256_file

PREREG_RELPATH = "docs/forecast/PREREGISTRATION.md"
TEMPLATE_RELPATH = "docs/forecast/PREREGISTRATION.template.md"
LOCK_NAME = "TEST_LOCK.json"
LOG_NAME = "evaluation_log.jsonl"
PLACEHOLDER = "<<FILL>>"
SCHEMA_VERSION = 1
EVENTS = (
    "score", "lock_opened", "test_access_refused", "test_access_granted", "test_evaluation_opened",
)
OUTCOMES = ("scored", "granted", "refused", "blanked", "opened")
GENESIS = "0" * 64

_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_MAX_OPENED_BY = 200

_LOCK_FIELDS = (
    "schema_version", "opened_utc", "preregistration_path", "preregistration_blob_sha",
    "config_sha256", "model_bundle_path", "model_bundle_sha256", "opened_by", "log_head_sha256",
)


class TestLockError(RuntimeError):
    """Raised when test-split data is requested while the lock is closed."""

    __test__ = False  # not a pytest test class when imported into test modules


def _default_data_root() -> Path:
    from heatwave.config import settings

    return Path(settings.local_data_dir)


def _git_runner(args: list[str], repo_root: Path) -> str | None:
    return artifacts._git(args, repo_root)


def _root(data_root) -> Path:
    return Path(data_root) if data_root is not None else _default_data_root()


def forecast_runs_dir(data_root=None) -> Path:
    root = _root(data_root)
    runs = (root / artifacts.RUNS_SUBDIR).resolve()
    repo = artifacts.REPO_ROOT.resolve()
    frozen = (root / "frozen").resolve()
    for forbidden, label in ((repo, "the repository"), (frozen, "the frozen data folder")):
        if runs == forbidden or forbidden in runs.parents:
            raise ValueError(f"forecast_runs must not live inside {label}: {runs}")
    return runs


def lock_path(data_root=None) -> Path:
    return forecast_runs_dir(data_root) / LOCK_NAME


def log_path(data_root=None) -> Path:
    return forecast_runs_dir(data_root) / LOG_NAME


# ----------------------------------------------------------------------------- log
def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _last_line(path: Path) -> bytes | None:
    if not path.exists():
        return None
    last = None
    with open(path, "rb") as f:
        for raw in f:
            raw = raw.rstrip(b"\r\n")
            if raw:
                last = raw
    return last


def log_event(
    event: str,
    *,
    outcome: str,
    split=None,
    predictor=None,
    lead=None,
    n_rows=None,
    run_id=None,
    config_sha256=None,
    purpose=None,
    reason=None,
    data_root=None,
) -> dict:
    """Append one record to the evaluation log (hash-chained, fsynced) and return it."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}; allowed: {EVENTS}")
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; allowed: {OUTCOMES}")
    path = log_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    prev = _last_line(path)
    record = {
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        "outcome": outcome,
        "split": split,
        "predictor": predictor,
        "lead": lead,
        "n_rows": n_rows,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "purpose": purpose,
        "reason": reason,
        "prev_sha256": GENESIS if prev is None else _sha_bytes(prev),
    }
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return record


def read_log(data_root=None) -> list[dict]:
    path = log_path(data_root)
    if not path.exists():
        return []
    out = []
    with open(path, "rb") as f:
        for raw in f:
            raw = raw.rstrip(b"\r\n")
            if raw:
                out.append(json.loads(raw.decode("utf-8")))
    return out


def _scan_chain(path: Path) -> tuple[bool, list[str]]:
    """(chain_intact, sha256 of every line in order). A missing file is an intact empty chain."""
    hashes: list[str] = []
    if not path.exists():
        return True, hashes
    prev_hash = GENESIS
    with open(path, "rb") as f:
        for raw in f:
            raw = raw.rstrip(b"\r\n")
            if not raw:
                continue
            try:
                rec = json.loads(raw.decode("utf-8"))
            except ValueError:
                return False, hashes
            if not isinstance(rec, dict) or rec.get("prev_sha256") != prev_hash:
                return False, hashes
            prev_hash = _sha_bytes(raw)
            hashes.append(prev_hash)
    return True, hashes


def verify_log_chain(data_root=None) -> bool:
    return _scan_chain(log_path(data_root))[0]


def log_head_sha256(data_root=None) -> str | None:
    """sha256 of the last log line (the value the next record chains to), None for no log."""
    last = _last_line(log_path(data_root))
    return None if last is None else _sha_bytes(last)


def _log_consistent_with_lock(rec: dict, data_root) -> tuple[bool, str]:
    """Fail-safe log check for an existing lock: intact chain that still contains the recorded head."""
    path = log_path(data_root)
    if not path.exists():
        return False, "evaluation log missing"
    intact, hashes = _scan_chain(path)
    if not intact:
        return False, "evaluation log hash chain is broken"
    if rec["log_head_sha256"] not in hashes:
        return False, "evaluation log truncated or replaced (recorded head not found)"
    return True, "ok"


def count_test_runs(data_root=None) -> int:
    """Number of opened test evaluations: ``test_evaluation_opened`` events, one per evaluation.

    Loader grants and per-predictor ``scored`` records are not runs and are not counted
    (WR-07). Raises TestLockError when the log hash chain is broken, so a count read from a
    tampered log is never reported as a fact.
    """
    if not verify_log_chain(data_root):
        raise TestLockError("evaluation log hash chain is broken; refusing to report a test-run count")
    return sum(
        1
        for r in read_log(data_root)
        if r.get("event") == "test_evaluation_opened" and r.get("outcome") == "opened"
        and r.get("split") == "test"
    )


def count_scored(split: str, *, run_id=None, lead=None, data_root=None) -> int:
    """Number of ``scored`` records for a split (optionally one run and/or lead); chain-verified."""
    if not verify_log_chain(data_root):
        raise TestLockError("evaluation log hash chain is broken; refusing to report a score count")
    return sum(
        1
        for r in read_log(data_root)
        if r.get("event") == "score" and r.get("outcome") == "scored" and r.get("split") == split
        and (run_id is None or r.get("run_id") == run_id)
        and (lead is None or r.get("lead") == lead)
    )


# ----------------------------------------------------------------------------- pre-registration
def preregistration_status(repo_root=artifacts.REPO_ROOT) -> dict:
    repo_root = Path(repo_root)
    out = {"tracked": False, "head_blob": None, "worktree_blob": None, "clean": False, "reason": ""}
    top = _git_runner(["rev-parse", "--show-toplevel"], repo_root)
    if top is None:
        out["reason"] = "git unavailable or not a repository"
        return out
    try:
        same = Path(top.strip()).samefile(repo_root)
    except OSError:
        same = False
    if not same:
        out["reason"] = "repo_root is not a git repository root"
        return out
    tracked = _git_runner(["ls-files", "--error-unmatch", "--", PREREG_RELPATH], repo_root)
    out["tracked"] = tracked is not None and bool(tracked.strip())
    head = _git_runner(["rev-parse", "HEAD:" + PREREG_RELPATH], repo_root)
    head_blob = head.strip() if head is not None else None
    out["head_blob"] = head_blob if head_blob and _SHA40.match(head_blob) else None
    work = _git_runner(["hash-object", "--", PREREG_RELPATH], repo_root)
    work_blob = work.strip() if work is not None else None
    out["worktree_blob"] = work_blob if work_blob and _SHA40.match(work_blob) else None
    if not out["tracked"]:
        out["reason"] = "pre-registration is not tracked by git"
    elif out["head_blob"] is None:
        out["reason"] = "pre-registration is not committed in HEAD"
    elif out["head_blob"] != out["worktree_blob"]:
        out["reason"] = "pre-registration differs from the committed version"
    else:
        out["clean"] = True
        out["reason"] = "clean"
    return out


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _has_labelled_hash(text: str, label: str, digest: str) -> bool:
    """True when a line reads ``[- ]<label>: <digest>`` (optionally backticked); comments ignored."""
    pat = re.compile(
        r"^[ \t]*(?:[-*][ \t]+)?" + re.escape(label) + r":[ \t]*`?" + re.escape(digest) + r"`?[ \t]*$",
        re.MULTILINE,
    )
    return pat.search(_HTML_COMMENT.sub("", text)) is not None


def _preregistration_text_ok(cfg: ForecastConfig, repo_root, bundle_sha256: str) -> tuple[bool, str]:
    """Check the COMMITTED blob (``git show HEAD:<path>``), never the working tree (WR-05).

    The blob must hold no placeholder token and must carry both frozen identifiers on their own
    labelled lines: ``config sha256: <current config hash>`` and
    ``model bundle sha256: <hash of the bundle being opened>``.
    """
    text = _git_runner(["show", "HEAD:" + PREREG_RELPATH], Path(repo_root))
    if text is None:
        return False, "pre-registration unreadable"
    if PLACEHOLDER in text:
        return False, "pre-registration still contains a placeholder"
    if not _has_labelled_hash(text, "config sha256", config_hash(cfg)):
        return False, "pre-registration does not contain the current config hash"
    if not _has_labelled_hash(text, "model bundle sha256", bundle_sha256):
        return False, "pre-registration does not contain the model bundle hash"
    return True, "ok"


# ----------------------------------------------------------------------------- lock
def _read_lock(data_root) -> tuple[dict | None, str]:
    path = lock_path(data_root)
    if not path.exists():
        return None, "test lock not opened"
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "lock file malformed"
    ok = isinstance(rec, dict) and all(k in rec for k in _LOCK_FIELDS)
    if ok:
        bundle = rec["model_bundle_path"]
        ok = (
            rec["schema_version"] == SCHEMA_VERSION
            and isinstance(rec["preregistration_blob_sha"], str)
            and bool(_SHA40.match(rec["preregistration_blob_sha"]))
            and isinstance(rec["config_sha256"], str)
            and bool(_SHA64.match(rec["config_sha256"]))
            and isinstance(rec["model_bundle_sha256"], str)
            and bool(_SHA64.match(rec["model_bundle_sha256"]))
            and isinstance(rec["log_head_sha256"], str)
            and bool(_SHA64.match(rec["log_head_sha256"]))
            and isinstance(bundle, str)
            and bool(bundle)
            # Check Windows rules as well as the native ones, so drive-letter and
            # backslash-anchored paths are malformed on every platform (CI runs Linux).
            and not PureWindowsPath(bundle).drive
            and not PureWindowsPath(bundle).anchor
            and not Path(bundle).anchor
            and not Path(bundle).is_absolute()
            and ".." not in Path(bundle).parts
            and ".." not in PureWindowsPath(bundle).parts
            and rec["preregistration_path"] == PREREG_RELPATH
        )
    if not ok:
        return None, "lock file malformed"
    return rec, "ok"


def lock_status(
    cfg: ForecastConfig, *, data_root=None, repo_root=artifacts.REPO_ROOT
) -> tuple[bool, str]:
    """(is_open, reason). Cheapest checks first; the closed-lock path never calls git."""
    rec, why = _read_lock(data_root)
    if rec is None:
        return False, why
    if config_hash(cfg) != rec["config_sha256"]:
        return False, "config changed since the lock was opened"
    bundle = forecast_runs_dir(data_root) / rec["model_bundle_path"]
    try:
        bundle_ok = bundle.is_file() and sha256_file(bundle) == rec["model_bundle_sha256"]
    except OSError:
        bundle_ok = False
    if not bundle_ok:
        return False, "model bundle changed"
    log_ok, log_reason = _log_consistent_with_lock(rec, data_root)
    if not log_ok:
        return False, log_reason
    st = preregistration_status(repo_root)
    if not st["clean"] or st["head_blob"] != rec["preregistration_blob_sha"]:
        return False, "pre-registration missing, modified or not committed"
    ok, reason = _preregistration_text_ok(cfg, repo_root, rec["model_bundle_sha256"])
    if not ok:
        return False, reason
    return True, "open"


def _refuse_open(cfg, reason: str, data_root) -> None:
    log_event(
        "test_access_refused", outcome="refused", split="test", purpose="open_lock",
        config_sha256=config_hash(cfg), reason=reason, data_root=data_root,
    )
    raise TestLockError(f"cannot open the test lock: {reason}")


def open_lock(
    cfg: ForecastConfig,
    *,
    model_bundle_path,
    opened_by: str,
    data_root=None,
    repo_root=artifacts.REPO_ROOT,
) -> dict:
    if not isinstance(opened_by, str) or not opened_by.strip() or len(opened_by) > _MAX_OPENED_BY:
        raise ValueError(f"opened_by must be a non-empty string of at most {_MAX_OPENED_BY} chars")
    st = preregistration_status(repo_root)
    if not st["clean"]:
        _refuse_open(cfg, f"pre-registration: {st['reason']}", data_root)
    runs = forecast_runs_dir(data_root)
    bundle = Path(model_bundle_path)
    if not bundle.is_file():
        _refuse_open(cfg, "model bundle file does not exist", data_root)
    bundle = bundle.resolve()
    if runs not in bundle.parents:
        _refuse_open(cfg, "model bundle must lie inside forecast_runs", data_root)
    if bundle.name in (LOCK_NAME, LOG_NAME) or bundle.name.endswith(".tmp"):
        _refuse_open(cfg, "model bundle must not be the lock or the evaluation log", data_root)
    ok, reason = _preregistration_text_ok(cfg, repo_root, sha256_file(bundle))
    if not ok:
        _refuse_open(cfg, reason, data_root)
    record = {
        "schema_version": SCHEMA_VERSION,
        "opened_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "preregistration_path": PREREG_RELPATH,
        "preregistration_blob_sha": st["head_blob"],
        "config_sha256": config_hash(cfg),
        "model_bundle_path": bundle.relative_to(runs).as_posix(),
        "model_bundle_sha256": sha256_file(bundle),
        "opened_by": opened_by,
    }
    path = lock_path(data_root)
    if path.exists():
        existing, _ = _read_lock(data_root)
        same = existing is not None and all(
            existing[k] == record[k]
            for k in ("preregistration_blob_sha", "config_sha256", "model_bundle_path",
                      "model_bundle_sha256")
        )
        if same:
            return existing
        _refuse_open(cfg, "lock already opened with different hashes", data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not verify_log_chain(data_root):
        _refuse_open(cfg, "evaluation log hash chain is broken", data_root)
    # The lock_opened record is appended first; its line hash is the log head the lock records, so
    # truncating or replacing the log later re-closes the lock (WR-04).
    log_event(
        "lock_opened", outcome="opened", split="test", config_sha256=record["config_sha256"],
        purpose="open_lock", data_root=data_root,
    )
    record["log_head_sha256"] = log_head_sha256(data_root)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return record


def require_open(
    cfg: ForecastConfig,
    purpose: str,
    *,
    predictor=None,
    lead=None,
    n_rows=None,
    run_id=None,
    data_root=None,
    repo_root=artifacts.REPO_ROOT,
) -> dict:
    """Return the lock record or raise TestLockError; every call is logged."""
    is_open, reason = lock_status(cfg, data_root=data_root, repo_root=repo_root)
    common = dict(
        split="test", predictor=predictor, lead=lead, n_rows=n_rows, run_id=run_id,
        config_sha256=config_hash(cfg), purpose=purpose, reason=reason, data_root=data_root,
    )
    if not is_open:
        log_event("test_access_refused", outcome="refused", **common)
        raise TestLockError(f"test split is locked: {reason}")
    log_event("test_access_granted", outcome="granted", **common)
    rec, _ = _read_lock(data_root)
    return rec


def labels_unlocked(
    cfg: ForecastConfig, purpose: str, *, n_rows=None, data_root=None, repo_root=artifacts.REPO_ROOT
) -> bool:
    """Non-raising variant for blanking test labels: True when open, False (logged) when closed."""
    is_open, reason = lock_status(cfg, data_root=data_root, repo_root=repo_root)
    common = dict(
        split="test", n_rows=n_rows, config_sha256=config_hash(cfg), purpose=purpose,
        reason=reason, data_root=data_root,
    )
    if is_open:
        log_event("test_access_granted", outcome="granted", **common)
        return True
    log_event("test_access_refused", outcome="blanked", **common)
    return False


def count_test_scores(*, run_id=None, data_root=None) -> int:
    """Test-split ``scored`` records (optionally for one run); chain-verified."""
    return count_scored("test", run_id=run_id, data_root=data_root)


def open_test_evaluation(
    cfg: ForecastConfig,
    run_id: str,
    *,
    lead=None,
    data_root=None,
    repo_root=artifacts.REPO_ROOT,
) -> dict:
    """Start (or continue) THE one test evaluation; the one-shot rule is enforced here (WR-07).

    Requires the lock to be open. The first call logs one ``test_evaluation_opened`` event for
    ``run_id``. Further calls with the same ``run_id`` (the other leads of the same evaluation)
    continue it without a new event. Any other ``run_id`` is refused once an evaluation exists,
    and so is scoring the same lead twice. Refusals are logged and raise TestLockError.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("a test evaluation needs a run_id")
    require_open(
        cfg, "open_test_evaluation", lead=lead, run_id=run_id, data_root=data_root, repo_root=repo_root
    )
    chash = config_hash(cfg)

    def refuse(reason):
        log_event(
            "test_access_refused", outcome="refused", split="test", lead=lead, run_id=run_id,
            config_sha256=chash, purpose="open_test_evaluation", reason=reason, data_root=data_root,
        )
        raise TestLockError(f"test evaluation refused: {reason}")

    opened = [
        r for r in read_log(data_root)
        if r.get("event") == "test_evaluation_opened" and r.get("outcome") == "opened"
    ]
    if opened:
        if any(r.get("run_id") != run_id for r in opened):
            refuse("the test split was already evaluated by another run (one-shot rule)")
        if lead is not None and count_scored("test", run_id=run_id, lead=lead, data_root=data_root):
            refuse(f"lead {lead} was already scored on the test split in this evaluation")
        return opened[0]
    return log_event(
        "test_evaluation_opened", outcome="opened", split="test", lead=lead, run_id=run_id,
        config_sha256=chash, purpose="open_test_evaluation", data_root=data_root,
    )
