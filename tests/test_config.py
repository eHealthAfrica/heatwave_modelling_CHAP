"""Config-loading edge cases: missing keys, malformed YAML, and
ClimatologyConfig's runtime validation (POLISH-01).

No Earth Engine credentials required -- these tests never call
`heatwave.auth.init_ee()` and never touch the real `config.yaml`; each
test that exercises `load_settings` writes its own temporary YAML file so
it cannot be affected by (or accidentally mutate the meaning of) the
project's actual configuration.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from heatwave.config import Bands, ClimatologyConfig, load_settings

VALID_CONFIG: dict = {
    "gcp_project_id": "test-project",
    "ward_asset_id": "projects/test-project/assets/wards",
    "era5_land_collection": "ECMWF/ERA5_LAND/DAILY_AGGR",
    "bands": {
        "tmax": "temperature_2m_max",
        "tmean": "temperature_2m",
        "dewpoint": "dewpoint_temperature_2m",
    },
    "start_date": "1980-01-01",
    "end_date": "2025-09-15",
    "climatology": {
        "baseline_start_year": 1991,
        "baseline_end_year": 2020,
        "percentile": 90,
        "pooling_window_days": 5,
        "min_consecutive_days": 3,
    },
}


def _write_config(tmp_path: Path, raw: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return config_path


def _without_key(d: dict, key: str) -> dict:
    copy = dict(d)
    del copy[key]
    return copy


# --- load_settings: happy path -----------------------------------------


def test_load_settings_parses_a_valid_config(tmp_path):
    config_path = _write_config(tmp_path, VALID_CONFIG)

    settings = load_settings(config_path)

    assert settings.gcp_project_id == "test-project"
    assert settings.ward_asset_id == "projects/test-project/assets/wards"
    assert settings.bands.tmax == "temperature_2m_max"
    assert settings.bands.tmean == "temperature_2m"
    assert settings.bands.dewpoint == "dewpoint_temperature_2m"
    assert settings.start_date == "1980-01-01"
    assert settings.end_date == "2025-09-15"
    assert settings.climatology.baseline_start_year == 1991
    assert settings.climatology.baseline_end_year == 2020
    assert settings.climatology.percentile == 90
    assert settings.climatology.pooling_window_days == 5
    assert settings.climatology.min_consecutive_days == 3


# --- load_settings: missing keys ----------------------------------------


@pytest.mark.parametrize(
    "missing_key",
    [
        "gcp_project_id",
        "ward_asset_id",
        "era5_land_collection",
        "bands",
        "start_date",
        "end_date",
        "climatology",
    ],
)
def test_load_settings_raises_on_missing_top_level_key(tmp_path, missing_key):
    config_path = _write_config(tmp_path, _without_key(VALID_CONFIG, missing_key))

    with pytest.raises(KeyError):
        load_settings(config_path)


@pytest.mark.parametrize("missing_band", ["tmax", "tmean", "dewpoint"])
def test_load_settings_raises_on_missing_band_key(tmp_path, missing_band):
    raw = dict(VALID_CONFIG)
    raw["bands"] = _without_key(VALID_CONFIG["bands"], missing_band)
    config_path = _write_config(tmp_path, raw)

    with pytest.raises(TypeError):
        load_settings(config_path)


@pytest.mark.parametrize(
    "missing_climatology_key",
    [
        "baseline_start_year",
        "baseline_end_year",
        "percentile",
        "pooling_window_days",
        "min_consecutive_days",
    ],
)
def test_load_settings_raises_on_missing_climatology_key(tmp_path, missing_climatology_key):
    raw = dict(VALID_CONFIG)
    raw["climatology"] = _without_key(VALID_CONFIG["climatology"], missing_climatology_key)
    config_path = _write_config(tmp_path, raw)

    with pytest.raises(TypeError):
        load_settings(config_path)


# --- load_settings: malformed YAML / missing file ------------------------


def test_load_settings_raises_on_malformed_yaml(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("gcp_project_id: [unclosed", encoding="utf-8")

    with pytest.raises(yaml.YAMLError):
        load_settings(config_path)


def test_load_settings_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "does_not_exist.yaml")


def test_load_settings_raises_on_empty_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")

    # An empty YAML document parses to `None`, so indexing it (`raw["gcp_project_id"]`)
    # must fail loudly rather than silently produce a Settings object full of Nones.
    with pytest.raises(TypeError):
        load_settings(config_path)


# --- ClimatologyConfig: runtime validation (WR-03) ------------------------


def _climatology_kwargs(**overrides) -> dict:
    base = dict(VALID_CONFIG["climatology"])
    base.update(overrides)
    return base


@pytest.mark.parametrize("percentile", [0, -1, 100, 101])
def test_climatology_config_rejects_percentile_out_of_range(percentile):
    with pytest.raises(ValueError, match="percentile"):
        ClimatologyConfig(**_climatology_kwargs(percentile=percentile))


@pytest.mark.parametrize("percentile", [1, 50, 99])
def test_climatology_config_accepts_percentile_at_valid_boundaries(percentile):
    config = ClimatologyConfig(**_climatology_kwargs(percentile=percentile))
    assert config.percentile == percentile


def test_climatology_config_rejects_baseline_start_after_end():
    with pytest.raises(ValueError, match="baseline_start_year"):
        ClimatologyConfig(
            **_climatology_kwargs(baseline_start_year=2020, baseline_end_year=1991)
        )


def test_climatology_config_accepts_baseline_start_equal_to_end():
    config = ClimatologyConfig(
        **_climatology_kwargs(baseline_start_year=2000, baseline_end_year=2000)
    )
    assert config.baseline_start_year == config.baseline_end_year == 2000


def test_climatology_config_rejects_negative_pooling_window():
    with pytest.raises(ValueError, match="pooling_window_days"):
        ClimatologyConfig(**_climatology_kwargs(pooling_window_days=-1))


def test_climatology_config_accepts_zero_pooling_window():
    config = ClimatologyConfig(**_climatology_kwargs(pooling_window_days=0))
    assert config.pooling_window_days == 0


@pytest.mark.parametrize("min_consecutive_days", [0, -1])
def test_climatology_config_rejects_min_consecutive_days_below_one(min_consecutive_days):
    with pytest.raises(ValueError, match="min_consecutive_days"):
        ClimatologyConfig(**_climatology_kwargs(min_consecutive_days=min_consecutive_days))


def test_climatology_config_accepts_min_consecutive_days_of_one():
    config = ClimatologyConfig(**_climatology_kwargs(min_consecutive_days=1))
    assert config.min_consecutive_days == 1


# --- Bands: missing/extra keys --------------------------------------------


def test_bands_requires_all_three_keys():
    with pytest.raises(TypeError):
        Bands(tmax="temperature_2m_max", tmean="temperature_2m")  # missing dewpoint


def test_bands_accepts_exactly_the_three_documented_keys():
    bands = Bands(
        tmax="temperature_2m_max",
        tmean="temperature_2m",
        dewpoint="dewpoint_temperature_2m",
    )
    assert bands.tmax == "temperature_2m_max"
    assert bands.tmean == "temperature_2m"
    assert bands.dewpoint == "dewpoint_temperature_2m"
