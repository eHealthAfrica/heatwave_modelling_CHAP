from __future__ import annotations

import importlib.metadata
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
