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


# ---------------------------------------------------------------- rejection matrix
def _base() -> dict:
    return yaml.safe_load(FORECAST_CONFIG_PATH.read_text(encoding="utf-8"))


def _set(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def _del(d, path):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[k]
    del d[keys[-1]]


_SHA = "82583fbf5deedce2ee1a3cee2ad2b12e36c9c2c83ef14e9f6b102a1eb4a7f137"

_BAD = [
    ("leads", []), ("leads", [1, 1, 2]), ("leads", [0, 1]), ("leads", [2, 1]),
    ("leads", [1, True]), ("leads", [1.5]),
    ("latency_days", -1), ("latency_days", True), ("latency_days", 8.5),
    ("gate.primary_leads", [7]), ("gate.primary_leads", []),
    ("gate.ci_level", 1.0), ("gate.ci_level", 0),
    ("gate.metric", "accuracy"), ("gate.reference", "climatology_only"),
    ("splits.validate_years", [2014, 2020]), ("splits.test_years", [2020, 2026]),
    ("splits.train_years", [2014, 1991]), ("splits.validate_years", [2016, 2020]),
    ("splits.train_end", date(2014, 12, 30)), ("splits.train_end", date(2014, 12, 22)),
    ("splits.validate_end", date(2020, 12, 28)),
    ("splits.train_end", date(2021, 1, 4)),
    ("splits.embargo_weeks", -1), ("splits.embargo_weeks", 5), ("splits.embargo_weeks", True),
    ("data.version", "covariates-v2"), ("data.version", "../outputs"),
    ("data.version", "covariates-v1.0/../x"),
    ("data.frozen_subdir", ".."), ("data.frozen_subdir", "a/b"),
    ("data.expected_parquet_sha256", "82583fbf"), ("data.expected_parquet_sha256", _SHA.upper()),
    ("baselines.names", []), ("baselines.names", ["climatology", "climatology"]),
    ("baselines.names", ["magic"]), ("baselines.recent_climatology_years", 0),
    ("retrain_policy.pre_test_refit_years", [1991, 2014]),
    ("retrain_policy.freeze_hyperparameters", False),
    ("retrain_policy.operational_label", "tested"),
    ("models", {}), ("models.unknown_model", {"a": 1}),
    ("models.lightgbm.learning_rate", [0.1]), ("models.lightgbm.learning_rate", float("nan")),
    ("models.lightgbm.num_leafs", 15), ("models.lightgbm.seed", 1),
    ("models.lightgbm.n_jobs", 4), ("models.lightgbm.num_threads", 2),
    ("models.lightgbm.random_state", 3), ("models.lightgbm.deterministic", False),
    ("models.lightgbm.num_leaves", "15"), ("models.lightgbm.num_leaves", 15.5),
    ("models.lightgbm.learning_rate", "fast"), ("models.lightgbm.learning_rate", "inf"),
    ("models.lightgbm.subsample", True), ("models.logistic_regression.C", "big"),
    ("models.logistic_regression.penalty", 2), ("models.logistic_regression.random_state", 1),
    ("models.logistic_regression.n_jobs", 2),
    ("seed", -1), ("seed", True), ("seed", "42"),
    ("extra", 1), ("splits.foo", 1),
]


@pytest.mark.parametrize("path, value", _BAD, ids=[f"{p}={v!r}" for p, v in _BAD])
def test_rejects_bad_value(tmp_path, path, value):
    d = _base()
    _set(d, path, value)
    p = tmp_path / "f.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    with pytest.raises(ValueError):
        load_forecast_config(p)


def test_rejects_missing_top_level_key(tmp_path):
    d = _base()
    _del(d, "gate")
    p = tmp_path / "f.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    with pytest.raises(ValueError):
        load_forecast_config(p)


def test_rejects_list_top_level(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_forecast_config(p)


def test_safe_load_refuses_python_tag(tmp_path):
    p = tmp_path / "evil.yaml"
    p.write_text('x: !!python/object/apply:os.system ["echo pwned"]\n', encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_forecast_config(p)


def test_deterministic_must_be_present(tmp_path):
    d = _base()
    _del(d, "models.lightgbm.deterministic")
    p = tmp_path / "f.yaml"
    p.write_text(yaml.safe_dump(d), encoding="utf-8")
    with pytest.raises(ValueError, match="deterministic"):
        load_forecast_config(p)


def test_scientific_notation_strings_become_floats(tmp_path):
    """WR-03: PyYAML (YAML 1.1) reads 1e-5 as a str; the loader must turn it into a float."""
    text = FORECAST_CONFIG_PATH.read_text(encoding="utf-8")
    assert yaml.safe_load("x: 1e-5")["x"] == "1e-5"  # the pitfall being guarded
    p = tmp_path / "f.yaml"
    p.write_text(text.replace("learning_rate: 0.05", "learning_rate: 5e-2", 1), encoding="utf-8")
    cfg = load_forecast_config(p)
    lr = cfg.models.params("lightgbm")["learning_rate"]
    assert isinstance(lr, float) and lr == 0.05
    assert config_hash(cfg) == config_hash(load_forecast_config())
    p.write_text(text.replace("reg_lambda: 1.0", "reg_lambda: 1e-5", 1), encoding="utf-8")
    assert load_forecast_config(p).models.params("lightgbm")["reg_lambda"] == 1e-5


@pytest.mark.parametrize(
    "anchor, dup",
    [("seed: 20261002", "seed: 1"), ("  threshold:", "  threshold: 0.5"), ("    num_leaves: 15", "    num_leaves: 31")],
    ids=["top-level", "gate", "models"],
)
def test_duplicate_yaml_keys_rejected(tmp_path, anchor, dup):
    """WR-04: a duplicated key must raise instead of silently keeping the last value."""
    text = FORECAST_CONFIG_PATH.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith(anchor))
    p = tmp_path / "f.yaml"
    p.write_text(text.replace(line, f"{line}{chr(10)}{dup}", 1), encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="duplicate"):
        load_forecast_config(p)


def test_existing_config_untouched():
    import subprocess

    try:
        r = subprocess.run(
            ["git", "diff", "--exit-code", "--", "config.yaml", "heatwave/config.py", "tests/test_config.py"],
            cwd=FORECAST_CONFIG_PATH.parent, capture_output=True,
        )
    except FileNotFoundError:
        pytest.skip("git unavailable")
    if r.returncode not in (0, 1):
        pytest.skip("not a git checkout")
    assert r.returncode == 0
