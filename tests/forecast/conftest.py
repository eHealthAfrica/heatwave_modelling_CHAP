"""Session-scoped fixtures for forecast tests (load the real panel once per session)."""
import subprocess

import pytest

from heatwave.forecast import testlock
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.data import load_panel


@pytest.fixture(scope="session")
def forecast_cfg():
    return load_forecast_config()


@pytest.fixture(scope="session")
def frozen_panel(forecast_cfg):
    from heatwave.config import settings

    d = settings.local_data_dir.resolve() / "frozen" / forecast_cfg.data.version
    if not ((d / "covariate_table.parquet").exists() and (d / "MANIFEST.json").exists()):
        pytest.skip(f"frozen {forecast_cfg.data.version} data not found at {d}")
    return load_panel(forecast_cfg.data)


@pytest.fixture(scope="session")
def frozen_static(forecast_cfg, frozen_panel):
    from heatwave.forecast.static import load_static

    return load_static(forecast_cfg.data, frozen_panel.wards)


@pytest.fixture(scope="session")
def frozen_clim(forecast_cfg, frozen_panel):
    from heatwave.forecast.climatology import Climatology

    return Climatology.fit(frozen_panel, forecast_cfg.splits.train_end)


@pytest.fixture(scope="session", autouse=True)
def _testlock_isolated_root(tmp_path_factory):
    """Point the test lock and evaluation log at a tmp data root for the whole session.

    Session scope so module-scoped fixtures are covered too; tests never touch the real
    <local_data_dir>/forecast_runs/evaluation_log.jsonl or TEST_LOCK.json.
    """
    root = tmp_path_factory.mktemp("testlock_session_root")
    mp = pytest.MonkeyPatch()
    mp.setattr(testlock, "_default_data_root", lambda: root)
    yield root
    mp.undo()


@pytest.fixture
def testlock_root(tmp_path, monkeypatch):
    """A fresh, empty patched data root for one test."""
    root = tmp_path / "data_root"
    root.mkdir()
    monkeypatch.setattr(testlock, "_default_data_root", lambda: root)
    return root


@pytest.fixture
def allow_test_rows(monkeypatch):
    """Open the test split for tests that legitimately need test rows (Phase 9 regressions).

    Callers must reference the functions through the module (testlock.require_open ...).
    """
    monkeypatch.setattr(testlock, "require_open", lambda *a, **k: {"stub": True})
    monkeypatch.setattr(testlock, "labels_unlocked", lambda *a, **k: True)


@pytest.fixture
def make_git_repo():
    """Factory: make_git_repo(path, *, autocrlf=False) -> path of a fresh git repo."""

    def _make(path, *, autocrlf=False):
        path.mkdir(parents=True, exist_ok=True)

        def run(*args):
            subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

        run("init", "-q")
        run("config", "user.name", "heatwave-test")
        run("config", "user.email", "test@example.invalid")
        run("config", "commit.gpgsign", "false")
        run("config", "core.autocrlf", "true" if autocrlf else "false")
        return path

    return _make
