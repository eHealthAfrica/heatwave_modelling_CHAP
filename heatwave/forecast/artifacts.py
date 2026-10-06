"""Run folders and RUN_MANIFEST provenance for forecast runs (DATA-04).

Run folders live under ``<local_data_dir>/forecast_runs/<run_id>/`` and are never
committed; a data root inside the repository is refused.
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from heatwave.config import settings
from heatwave.forecast.config import ForecastConfig, config_hash, config_to_dict

RUNS_SUBDIR = "forecast_runs"
REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_PACKAGES = ("numpy", "pandas", "pyarrow", "scikit-learn", "lightgbm", "shap")
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{8}(_\d{2})?$")
MANIFEST_NAME = "RUN_MANIFEST.json"
CONFIG_SNAPSHOT_NAME = "config.yaml"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class RunContext:
    run_id: str
    path: Path
    manifest: dict


def make_run_id(cfg: ForecastConfig, now: datetime | None = None) -> str:
    """UTC timestamp plus the first 8 hex chars of the config hash."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}_{config_hash(cfg)[:8]}"


def _git(args: list[str], repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_info(repo_root: Path = REPO_ROOT) -> dict:
    """Current commit and dirty flag; None values when git is unavailable."""
    top = _git(["rev-parse", "--show-toplevel"], repo_root)
    if top is None:
        return {"commit": None, "dirty": None}
    try:
        same = Path(top.strip()).samefile(Path(repo_root))
    except OSError:
        same = False
    if not same:  # repo_root only sits inside some other repository
        return {"commit": None, "dirty": None}
    head = _git(["rev-parse", "HEAD"], repo_root)
    commit = head.strip() if head is not None else None
    # Untracked files count (a new module is code the commit cannot reproduce); data and
    # artifact folders that are never part of the code are excluded.
    status = _git(
        ["status", "--porcelain", "--untracked-files=normal", "--", ".",
         ":(exclude)outputs", ":(exclude)keys"],
        repo_root,
    )
    dirty = bool(status.strip()) if status is not None else None
    return {"commit": commit or None, "dirty": dirty}


def library_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for pkg in TRACKED_PACKAGES:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = None
    return versions


def _utc_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_manifest(path: Path, manifest: dict) -> None:
    tmp = path / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path / MANIFEST_NAME)


def start_run(
    cfg: ForecastConfig,
    *,
    data_sha256: str,
    data_root: Path | None = None,
    now: datetime | None = None,
    repo_root: Path = REPO_ROOT,
) -> RunContext:
    """Create the run folder with config.yaml and a status=running RUN_MANIFEST.json."""
    if not isinstance(data_sha256, str) or not _SHA_RE.match(data_sha256):
        raise ValueError("data_sha256 must be 64 lowercase hex characters")
    if now is None:
        now = datetime.now(timezone.utc)
    root = Path(data_root) if data_root is not None else Path(settings.local_data_dir)
    base = (root / RUNS_SUBDIR).resolve()
    repo = Path(repo_root).resolve()
    if base == repo or repo in base.parents:
        raise ValueError(f"run folders must not be inside the repo ({repo}); got {base}")
    base.mkdir(parents=True, exist_ok=True)

    run_id = make_run_id(cfg, now=now)
    folder = base / run_id
    try:
        folder.mkdir(exist_ok=False)
    except FileExistsError:
        stem = run_id
        for i in range(1, 100):
            run_id = f"{stem}_{i:02d}"
            folder = base / run_id
            try:
                folder.mkdir(exist_ok=False)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("could not allocate a unique run folder")
    if not RUN_ID_PATTERN.match(run_id) or folder.resolve().parent != base:
        raise ValueError(f"unsafe run folder {folder}")

    snapshot = yaml.safe_dump(config_to_dict(cfg), sort_keys=False)
    (folder / CONFIG_SNAPSHOT_NAME).write_text(
        f"# Snapshot of forecast.yaml for run {run_id} (validated)\n" + snapshot,
        encoding="utf-8",
    )

    git = git_info(repo)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "running",
        "started_utc": _utc_str(now),
        "finished_utc": None,
        "seed": cfg.seed,
        "config_sha256": config_hash(cfg),
        "data": {"version": cfg.data.version, "parquet_sha256": data_sha256},
        "code": {"git_commit": git["commit"], "git_dirty": git["dirty"]},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": library_versions(),
        },
    }
    _write_manifest(folder, manifest)
    return RunContext(run_id=run_id, path=folder, manifest=manifest)


def finish_run(ctx: RunContext, status: str = "completed") -> None:
    if status not in {"completed", "failed"}:
        raise ValueError(f"status must be 'completed' or 'failed', got {status!r}")
    ctx.manifest["status"] = status
    ctx.manifest["finished_utc"] = _utc_str(datetime.now(timezone.utc))
    _write_manifest(ctx.path, ctx.manifest)


@contextlib.contextmanager
def run_folder(cfg: ForecastConfig, **kwargs):
    ctx = start_run(cfg, **kwargs)
    try:
        yield ctx
    except BaseException:
        finish_run(ctx, status="failed")
        raise
    else:
        finish_run(ctx)
