"""Shared pytest configuration: auto-skip for tests needing the frozen dataset."""
from pathlib import Path

import pytest

from heatwave.config import settings

FROZEN_VERSION = "covariates-v1.0"


def frozen_dataset_dir() -> Path:
    return settings.local_data_dir.resolve() / "frozen" / FROZEN_VERSION


def frozen_data_available() -> bool:
    d = frozen_dataset_dir()
    return (d / "covariate_table.parquet").exists() and (d / "MANIFEST.json").exists()


def pytest_collection_modifyitems(config, items):
    if frozen_data_available():
        return
    skip = pytest.mark.skip(
        reason=f"frozen {FROZEN_VERSION} data not found at {frozen_dataset_dir()}"
    )
    for item in items:
        if "frozen" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def frozen_dir() -> Path:
    if not frozen_data_available():
        pytest.skip(f"frozen {FROZEN_VERSION} data not found at {frozen_dataset_dir()}")
    return frozen_dataset_dir()
