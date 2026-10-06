from __future__ import annotations

import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from heatwave.forecast import artifacts
from heatwave.forecast.config import config_hash, load_forecast_config

NOW = datetime(2026, 10, 2, 12, 34, 56, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


def test_make_run_id(cfg):
    assert artifacts.make_run_id(cfg, now=NOW) == "20261002T123456Z_" + config_hash(cfg)[:8]
    assert artifacts.RUN_ID_PATTERN.match(artifacts.make_run_id(cfg, now=NOW))


def test_make_run_id_naive_raises(cfg):
    with pytest.raises(ValueError):
        artifacts.make_run_id(cfg, now=datetime(2026, 10, 2, 12, 34, 56))


def test_make_run_id_converts_to_utc(cfg):
    local = NOW.astimezone(timezone(timedelta(hours=2)))
    assert artifacts.make_run_id(cfg, now=local) == artifacts.make_run_id(cfg, now=NOW)


def test_git_info_real_repo():
    info = artifacts.git_info()
    assert len(info["commit"]) == 40
    assert isinstance(info["dirty"], bool)


def _git_cmd(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, check=True, capture_output=True,
    )


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_cmd(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1", encoding="utf-8")
    _git_cmd(repo, "add", "a.py")
    _git_cmd(repo, "commit", "-q", "-m", "init")
    return repo


def test_git_info_clean_then_untracked_python_file_is_dirty(tmp_repo):
    """WR-07: a new uncommitted module means the recorded commit cannot reproduce the run."""
    assert artifacts.git_info(tmp_repo)["dirty"] is False
    (tmp_repo / "new_feature.py").write_text("y = 2", encoding="utf-8")
    info = artifacts.git_info(tmp_repo)
    assert info["dirty"] is True and len(info["commit"]) == 40


def test_git_info_ignores_untracked_artifact_dirs(tmp_repo):
    (tmp_repo / "outputs").mkdir()
    (tmp_repo / "outputs" / "report.docx").write_bytes(b"x")
    assert artifacts.git_info(tmp_repo)["dirty"] is False


def test_git_info_refuses_parent_repo_head(tmp_repo):
    """WR-07: repo_root that merely sits inside another repo must not report the parent's HEAD."""
    inner = tmp_repo / "pkg"
    inner.mkdir()
    assert artifacts.git_info(inner) == {"commit": None, "dirty": None}


@pytest.mark.parametrize(
    "behaviour",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("git", 10),
        subprocess.CompletedProcess([], 128, "", "fatal"),
    ],
)
def test_git_info_unavailable(monkeypatch, behaviour):
    def fake(*a, **k):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    monkeypatch.setattr(artifacts.subprocess, "run", fake)
    assert artifacts.git_info() == {"commit": None, "dirty": None}


def test_library_versions():
    v = artifacts.library_versions()
    assert set(v) == set(artifacts.TRACKED_PACKAGES)
    assert v["numpy"] == "2.3.3"


def test_library_versions_missing_package(monkeypatch):
    real = importlib.metadata.version

    def fake(name):
        if name == "shap":
            raise importlib.metadata.PackageNotFoundError(name)
        return real(name)

    monkeypatch.setattr(artifacts.importlib.metadata, "version", fake)
    assert artifacts.library_versions()["shap"] is None


# ---- Task 2: run folders ----
SHA = "a" * 64


def _manifest(ctx):
    return json.loads((ctx.path / "RUN_MANIFEST.json").read_text(encoding="utf-8"))


def test_start_run_creates_files(cfg, tmp_path):
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    assert ctx.path.parent == (tmp_path / "forecast_runs").resolve()
    assert (ctx.path / "config.yaml").is_file()
    assert (ctx.path / "RUN_MANIFEST.json").is_file()


def test_manifest_contents(cfg, tmp_path):
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    m = _manifest(ctx)
    assert m["status"] == "running"
    assert m["schema_version"] == 1
    assert m["run_id"] == ctx.run_id
    assert m["data"] == {"version": "covariates-v1.0", "parquet_sha256": SHA}
    assert set(m["code"]) == {"git_commit", "git_dirty"}
    assert m["environment"]["python"] == platform.python_version()
    assert m["environment"]["platform"]
    assert set(m["environment"]["packages"]) == set(artifacts.TRACKED_PACKAGES)
    assert m["seed"] == cfg.seed
    assert m["config_sha256"] == config_hash(cfg)
    assert m["started_utc"].endswith("Z")
    assert m["finished_utc"] is None


def test_finish_run(cfg, tmp_path):
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    artifacts.finish_run(ctx)
    m = _manifest(ctx)
    assert m["status"] == "completed" and m["finished_utc"].endswith("Z")
    artifacts.finish_run(ctx, status="failed")
    assert _manifest(ctx)["status"] == "failed"
    assert not list(ctx.path.glob("*.tmp"))


def test_finish_run_bad_status(cfg, tmp_path):
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    with pytest.raises(ValueError):
        artifacts.finish_run(ctx, status="weird")


def test_run_folder_context(cfg, tmp_path):
    with artifacts.run_folder(cfg, data_sha256=SHA, data_root=tmp_path) as ctx:
        pass
    assert _manifest(ctx)["status"] == "completed"
    with pytest.raises(RuntimeError):
        with artifacts.run_folder(cfg, data_sha256=SHA, data_root=tmp_path) as ctx2:
            raise RuntimeError("boom")
    assert _manifest(ctx2)["status"] == "failed"


def test_config_snapshot_roundtrip(cfg, tmp_path):
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    assert load_forecast_config(ctx.path / "config.yaml") == cfg


def test_same_second_distinct_folders(cfg, tmp_path):
    a = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    b = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    assert a.run_id != b.run_id and b.run_id.endswith("_01")
    assert a.path.is_dir() and b.path.is_dir()
    assert artifacts.RUN_ID_PATTERN.match(b.run_id)


@pytest.mark.parametrize("sub", ["", "outputs"])
def test_repo_base_refused(cfg, sub):
    root = artifacts.REPO_ROOT / sub if sub else artifacts.REPO_ROOT
    with pytest.raises(ValueError, match="repo"):
        artifacts.start_run(cfg, data_sha256=SHA, data_root=root, now=NOW)
    assert not (root / "forecast_runs").exists()


@pytest.mark.parametrize("bad", ["abc", "A" * 64, "a" * 63])
def test_bad_sha_rejected(cfg, tmp_path, bad):
    with pytest.raises(ValueError):
        artifacts.start_run(cfg, data_sha256=bad, data_root=tmp_path, now=NOW)
    assert not (tmp_path / "forecast_runs").exists()


def test_start_run_without_git(cfg, tmp_path, monkeypatch):
    def fake(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(artifacts.subprocess, "run", fake)
    ctx = artifacts.start_run(cfg, data_sha256=SHA, data_root=tmp_path, now=NOW)
    m = _manifest(ctx)
    assert m["code"]["git_commit"] is None and m["code"]["git_dirty"] is None
