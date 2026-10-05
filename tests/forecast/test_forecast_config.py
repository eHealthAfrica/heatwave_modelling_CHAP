"""Tests for heatwave.forecast.config (DATA-03): valid load, hash, round-trip."""
import copy
import dataclasses
import json
import re
from datetime import date

import pytest
import yaml

from heatwave.forecast.config import (
    FORECAST_CONFIG_PATH,
    ForecastConfig,
    config_hash,
    config_to_dict,
    load_forecast_config,
)


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


def test_load_default_returns_forecast_config(cfg):
    assert isinstance(cfg, ForecastConfig)
    assert FORECAST_CONFIG_PATH.name == "forecast.yaml"


def test_data_section(cfg):
    assert cfg.data.version == "covariates-v1.0"
    assert cfg.data.frozen_subdir == "frozen"
    assert cfg.data.expected_parquet_sha256.startswith("82583fbf")
    assert re.fullmatch(r"[0-9a-f]{64}", cfg.data.expected_parquet_sha256)


def test_scalar_values(cfg):
    assert cfg.leads == (1, 2, 3, 4, 5, 6)
    assert cfg.latency_days == 8
    assert cfg.gate.primary_leads == (2, 3)
    assert cfg.splits.embargo_weeks == 6
    assert cfg.splits.train_end == date(2014, 12, 29)
    assert cfg.splits.validate_end == date(2021, 1, 4)
    assert cfg.seed == 20261002


def test_baselines(cfg):
    assert cfg.baselines.names == (
        "climatology", "recent_climatology", "persistence", "damped_persistence", "trend_season",
    )
    assert cfg.baselines.recent_climatology_years == 10


def test_model_params(cfg):
    lgb = cfg.models.params("lightgbm")
    assert lgb["deterministic"] is True
    assert lgb["num_leaves"] == 15
    assert "C" in cfg.models.params("logistic_regression")


@pytest.mark.parametrize(
    "d, expected",
    [
        (date(2014, 12, 22), "train"),
        (date(2014, 12, 29), "validate"),
        (date(2020, 12, 28), "validate"),
        (date(2021, 1, 4), "test"),
        (date(2026, 9, 14), "test"),
        (date(1990, 12, 31), "train"),
    ],
)
def test_split_for_week_start(cfg, d, expected):
    assert cfg.splits.split_for_week_start(d) == expected


@pytest.mark.parametrize(
    "d",
    [date(2014, 12, 30), date(1990, 12, 24), date(2027, 1, 4), date(2030, 1, 7)],
    ids=["non-monday", "before-1991-W01", "on-2027-W01", "after"],
)
def test_split_for_week_start_rejects(cfg, d):
    with pytest.raises(ValueError):
        cfg.splits.split_for_week_start(d)


def test_frozen_and_hashable(cfg):
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.seed = 1
    assert isinstance(hash(cfg), int)


def test_config_to_dict_json_serialisable(cfg):
    d = config_to_dict(cfg)
    json.dumps(d)
    assert d["splits"]["train_end"] == "2014-12-29"
    assert d["leads"] == [1, 2, 3, 4, 5, 6]


def test_config_hash_stable(cfg):
    expected = __import__("hashlib").sha256(
        json.dumps(config_to_dict(cfg), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert config_hash(cfg) == expected
    assert re.fullmatch(r"[0-9a-f]{64}", config_hash(cfg))
    assert config_hash(load_forecast_config()) == config_hash(cfg)


def test_snapshot_round_trip(cfg, tmp_path):
    p = tmp_path / "snapshot.yaml"
    p.write_text(yaml.safe_dump(copy.deepcopy(config_to_dict(cfg))), encoding="utf-8")
    assert load_forecast_config(p) == cfg
