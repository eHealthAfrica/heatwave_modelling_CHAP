"""Run folders and RUN_MANIFEST provenance for forecast runs (DATA-04).

Run folders live under ``<local_data_dir>/forecast_runs/<run_id>/`` and are never
committed; a data root inside the repository is refused.
"""
from __future__ import annotations

import importlib.metadata
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from heatwave.forecast.config import ForecastConfig, config_hash

RUNS_SUBDIR = "forecast_runs"
REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED_PACKAGES = ("numpy", "pandas", "pyarrow", "scikit-learn", "lightgbm", "shap")
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{8}(_\d{2})?$")


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
    head = _git(["rev-parse", "HEAD"], repo_root)
    commit = head.strip() if head is not None else None
    status = _git(["status", "--porcelain", "--untracked-files=no"], repo_root)
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


_ = platform  # used by the manifest builder
