"""Session-scoped fixtures for forecast tests (load the real panel once per session)."""
import pytest

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
