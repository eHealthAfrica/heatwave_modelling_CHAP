"""Validated forecast settings loaded from the repo-root forecast.yaml (DATA-03).

Frozen dataclasses in the style of ``heatwave.config.ClimatologyConfig``. The file is
parsed with ``yaml.safe_load`` only. This module never imports ``heatwave.config``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from heatwave.forecast.weeks import EPOCH_WEEK_START  # noqa: F401  (week index contract)

_REPO_ROOT = Path(__file__).resolve().parents[2]
FORECAST_CONFIG_PATH = _REPO_ROOT / "forecast.yaml"


@dataclass(frozen=True)
class DataConfig:
    version: str
    frozen_subdir: str
    expected_parquet_sha256: str


@dataclass(frozen=True)
class SplitsConfig:
    train_years: tuple
    validate_years: tuple
    test_years: tuple
    train_end: date
    validate_end: date
    embargo_weeks: int

    def split_for_week_start(self, d) -> str:
        """Return 'train', 'validate' or 'test' for a Monday week_start."""
        if isinstance(d, datetime) or not isinstance(d, date):
            raise ValueError(f"week_start must be a datetime.date, got {d!r}")
        if d.weekday() != 0:
            raise ValueError(f"week_start {d} is not a Monday")
        lo = date.fromisocalendar(self.train_years[0], 1, 1)
        hi = date.fromisocalendar(self.test_years[1] + 1, 1, 1)
        if not (lo <= d < hi):
            raise ValueError(f"week_start {d} is outside [{lo}, {hi})")
        if d < self.train_end:
            return "train"
        if d < self.validate_end:
            return "validate"
        return "test"


@dataclass(frozen=True)
class BaselinesConfig:
    names: tuple
    recent_climatology_years: int


@dataclass(frozen=True)
class GateConfig:
    primary_leads: tuple
    metric: str
    reference: str
    threshold: float
    ci_level: float
    ci_must_exclude_threshold: bool


@dataclass(frozen=True)
class RetrainPolicy:
    pre_test_refit_years: tuple
    freeze_hyperparameters: bool
    operational_refit: str
    operational_label: str


@dataclass(frozen=True)
class ModelsConfig:
    entries: tuple  # tuple of (model_name, tuple of sorted (key, value) pairs)

    def params(self, name: str) -> dict:
        for model_name, pairs in self.entries:
            if model_name == name:
                return dict(pairs)
        raise KeyError(name)


@dataclass(frozen=True)
class ForecastConfig:
    data: DataConfig
    splits: SplitsConfig
    leads: tuple
    latency_days: int
    baselines: BaselinesConfig
    gate: GateConfig
    retrain_policy: RetrainPolicy
    models: ModelsConfig
    seed: int


def _as_date(section: str, key: str, value) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{section}.{key} must be a date, got datetime {value!r}")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{section}.{key}: invalid ISO date {value!r}") from exc
    raise ValueError(f"{section}.{key} must be a date, got {value!r}")


def _as_tuple(section: str, key: str, value) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{section}.{key} must be a list, got {value!r}")
    return tuple(value)


def _build(cls, raw, section_name: str, date_keys=(), tuple_keys=()):
    """Build a dataclass from a mapping, rejecting unknown and missing keys."""
    if not isinstance(raw, dict):
        raise ValueError(f"section {section_name!r} must be a mapping, got {raw!r}")
    names = [f.name for f in dataclasses.fields(cls)]
    for key in raw:
        if key not in names:
            raise ValueError(f"unknown key {key!r} in section {section_name!r}")
    for key in names:
        if key not in raw:
            raise ValueError(f"missing key {key!r} in section {section_name!r}")
    kwargs = {}
    for key in names:
        value = raw[key]
        if key in date_keys:
            value = _as_date(section_name, key, value)
        elif key in tuple_keys:
            value = _as_tuple(section_name, key, value)
        kwargs[key] = value
    return cls(**kwargs)


def _build_models(raw) -> ModelsConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"section 'models' must be a mapping, got {raw!r}")
    entries = []
    for name in sorted(raw, key=str):
        params = raw[name]
        if not isinstance(params, dict):
            raise ValueError(f"models.{name} must be a mapping, got {params!r}")
        entries.append((name, tuple(sorted(params.items(), key=lambda kv: str(kv[0])))))
    return ModelsConfig(entries=tuple(entries))


_TOP_KEYS = [f.name for f in dataclasses.fields(ForecastConfig)]


def load_forecast_config(path: Path = FORECAST_CONFIG_PATH) -> ForecastConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f.read())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top level must be a mapping, got {type(raw).__name__}")
    for key in raw:
        if key not in _TOP_KEYS:
            raise ValueError(f"unknown top-level key {key!r}")
    for key in _TOP_KEYS:
        if key not in raw:
            raise ValueError(f"missing top-level key {key!r}")
    return ForecastConfig(
        data=_build(DataConfig, raw["data"], "data"),
        splits=_build(
            SplitsConfig, raw["splits"], "splits",
            date_keys=("train_end", "validate_end"),
            tuple_keys=("train_years", "validate_years", "test_years"),
        ),
        leads=_as_tuple("top", "leads", raw["leads"]),
        latency_days=raw["latency_days"],
        baselines=_build(BaselinesConfig, raw["baselines"], "baselines", tuple_keys=("names",)),
        gate=_build(GateConfig, raw["gate"], "gate", tuple_keys=("primary_leads",)),
        retrain_policy=_build(
            RetrainPolicy, raw["retrain_policy"], "retrain_policy",
            tuple_keys=("pre_test_refit_years",),
        ),
        models=_build_models(raw["models"]),
        seed=raw["seed"],
    )


def config_to_dict(cfg: ForecastConfig) -> dict:
    """Canonical JSON/YAML-safe dict (dates as ISO strings, tuples as lists)."""

    def conv(v: Any):
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, tuple):
            return [conv(x) for x in v]
        return v

    out: dict = {}
    for f in dataclasses.fields(cfg):
        value = getattr(cfg, f.name)
        if f.name == "models":
            out["models"] = {name: {k: conv(v) for k, v in pairs} for name, pairs in value.entries}
        elif dataclasses.is_dataclass(value):
            out[f.name] = {g.name: conv(getattr(value, g.name)) for g in dataclasses.fields(value)}
        else:
            out[f.name] = conv(value)
    return out


def config_hash(cfg: ForecastConfig) -> str:
    payload = json.dumps(config_to_dict(cfg), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
