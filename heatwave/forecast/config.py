"""Validated forecast settings loaded from the repo-root forecast.yaml (DATA-03).

Frozen dataclasses in the style of ``heatwave.config.ClimatologyConfig``. The file is
parsed with a ``yaml.SafeLoader`` subclass only (safe_load semantics, duplicate keys rejected). This module never imports ``heatwave.config``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
FORECAST_CONFIG_PATH = _REPO_ROOT / "forecast.yaml"

_BASELINE_NAMES = frozenset(
    {"climatology", "recent_climatology", "persistence", "damped_persistence", "trend_season"}
)
_MODEL_NAMES = frozenset({"logistic_regression", "lightgbm"})
_VERSION_RE = re.compile(r"^covariates-v\d+\.\d+$")
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that raises on duplicate mapping keys (still safe: no python tags)."""

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, _value_node in node.value:
                key = self.construct_object(key_node, deep=True)
                try:
                    hash(key)
                except TypeError:
                    continue  # super() raises the standard "unhashable key" error
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        f"found duplicate key {key!r}", key_node.start_mark,
                    )
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _check_int(name: str, value, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _check_int_seq(name: str, value, minimum: int = 1) -> None:
    if not isinstance(value, tuple) or len(value) == 0:
        raise ValueError(f"{name} must be a non-empty list, got {value!r}")
    for v in value:
        _check_int(f"{name} item", v, minimum)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates, got {value!r}")
    if list(value) != sorted(value):
        raise ValueError(f"{name} must be strictly ascending, got {value!r}")


def _check_years(name: str, value) -> None:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{name} must be a [start, end] pair, got {value!r}")
    for v in value:
        _check_int(f"{name} item", v, 1)
    if value[0] > value[1]:
        raise ValueError(f"{name} start must be <= end, got {value!r}")


def _check_finite_number(name: str, value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


@dataclass(frozen=True)
class DataConfig:
    version: str
    frozen_subdir: str
    expected_parquet_sha256: str

    def __post_init__(self):
        if not isinstance(self.version, str) or not _VERSION_RE.match(self.version):
            raise ValueError(f"data.version must match covariates-vN.N, got {self.version!r}")
        if not isinstance(self.frozen_subdir, str) or not _SUBDIR_RE.match(self.frozen_subdir):
            raise ValueError(f"data.frozen_subdir must be a plain folder name, got {self.frozen_subdir!r}")
        if not isinstance(self.expected_parquet_sha256, str) or not _SHA_RE.match(
            self.expected_parquet_sha256
        ):
            raise ValueError("data.expected_parquet_sha256 must be 64 lowercase hex chars")


@dataclass(frozen=True)
class SplitsConfig:
    train_years: tuple
    validate_years: tuple
    test_years: tuple
    train_end: date
    validate_end: date
    embargo_weeks: int
    cv_first_year: int

    def __post_init__(self):
        _check_years("splits.train_years", self.train_years)
        _check_years("splits.validate_years", self.validate_years)
        _check_years("splits.test_years", self.test_years)
        if self.train_years[1] + 1 != self.validate_years[0]:
            raise ValueError(
                "splits.validate_years must start the year after train_years ends (no gap or overlap)"
            )
        if self.validate_years[1] + 1 != self.test_years[0]:
            raise ValueError(
                "splits.test_years must start the year after validate_years ends (no gap or overlap)"
            )
        for name, value, year in (
            ("train_end", self.train_end, self.validate_years[0]),
            ("validate_end", self.validate_end, self.test_years[0]),
        ):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError(f"splits.{name} must be a date, got {value!r}")
            if value.weekday() != 0:
                raise ValueError(f"splits.{name} must be a Monday, got {value}")
            expected = date.fromisocalendar(year, 1, 1)
            if value != expected:
                raise ValueError(
                    f"splits.{name} must be {expected} (Monday of ISO week 1 of {year}), got {value}"
                )
        _check_int("splits.embargo_weeks", self.embargo_weeks, 0)
        _check_int("splits.cv_first_year", self.cv_first_year)
        if not (self.train_years[0] < self.cv_first_year <= self.validate_years[1]):
            raise ValueError(
                f"splits.cv_first_year must satisfy {self.train_years[0]} < cv_first_year <= "
                f"{self.validate_years[1]}, got {self.cv_first_year}"
            )

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

    def __post_init__(self):
        if not isinstance(self.names, tuple) or len(self.names) == 0:
            raise ValueError(f"baselines.names must be a non-empty list, got {self.names!r}")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"baselines.names must be unique, got {self.names!r}")
        for n in self.names:
            if n not in _BASELINE_NAMES:
                raise ValueError(f"unknown baseline {n!r}; allowed: {sorted(_BASELINE_NAMES)}")
        _check_int("baselines.recent_climatology_years", self.recent_climatology_years, 1)


@dataclass(frozen=True)
class GateConfig:
    primary_leads: tuple
    metric: str
    reference: str
    threshold: float
    ci_level: float
    ci_must_exclude_threshold: bool

    def __post_init__(self):
        _check_int_seq("gate.primary_leads", self.primary_leads)
        if self.metric != "brier_skill_score":
            raise ValueError(f"gate.metric must be 'brier_skill_score', got {self.metric!r}")
        if self.reference != "best_baseline":
            raise ValueError(f"gate.reference must be 'best_baseline', got {self.reference!r}")
        _check_finite_number("gate.threshold", self.threshold)
        _check_finite_number("gate.ci_level", self.ci_level)
        if not (0 < self.ci_level < 1):
            raise ValueError(f"gate.ci_level must be in (0, 1), got {self.ci_level}")
        if not isinstance(self.ci_must_exclude_threshold, bool):
            raise ValueError("gate.ci_must_exclude_threshold must be a bool")


@dataclass(frozen=True)
class RetrainPolicy:
    pre_test_refit_years: tuple
    freeze_hyperparameters: bool
    operational_refit: str
    operational_label: str

    def __post_init__(self):
        _check_years("retrain_policy.pre_test_refit_years", self.pre_test_refit_years)
        if self.freeze_hyperparameters is not True:
            raise ValueError("retrain_policy.freeze_hyperparameters must be true")
        if self.operational_refit != "all_years":
            raise ValueError(
                f"retrain_policy.operational_refit must be 'all_years', got {self.operational_refit!r}"
            )
        if self.operational_label != "not independently tested":
            raise ValueError("retrain_policy.operational_label must be 'not independently tested'")


# Allowed hyper-parameters per model with their kinds. "float" accepts ints and numeric
# strings such as "1e-5" (YAML 1.1 reads those as str) and normalises them to float.
# Seeds and thread counts are deliberately absent: the global ``seed`` is the only seed.
_PARAM_SPECS = {
    "logistic_regression": {
        "C": "float", "penalty": "str", "solver": "str", "max_iter": "int", "tol": "float",
        "l1_ratio": "float", "fit_intercept": "bool", "class_weight": "str",
    },
    "lightgbm": {
        "num_leaves": "int", "learning_rate": "float", "n_estimators": "int",
        "min_child_samples": "int", "min_child_weight": "float", "min_split_gain": "float",
        "subsample": "float", "subsample_freq": "int", "colsample_bytree": "float",
        "reg_lambda": "float", "reg_alpha": "float", "max_depth": "int", "max_bin": "int",
        "scale_pos_weight": "float", "is_unbalance": "bool", "class_weight": "str",
        "deterministic": "bool", "force_row_wise": "bool", "boosting_type": "str",
        "verbosity": "int",
    },
}
_REQUIRED_TRUE = {"lightgbm": ("deterministic",)}


def _normalise_param(model: str, key: str, value):
    """Validate one hyper-parameter against its kind; return the normalised value."""
    spec = _PARAM_SPECS[model]
    if key not in spec:
        raise ValueError(f"models.{model}: unknown parameter {key!r}; allowed: {sorted(spec)}")
    kind = spec[key]
    where = f"models.{model}.{key}"
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{where} must be a bool, got {value!r}")
        return value
    if kind == "str":
        if not isinstance(value, str):
            raise ValueError(f"{where} must be a str, got {value!r}")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where} must be an int, got {value!r}")
        return value
    # float
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ValueError(f"{where} must be numeric, got {value!r}") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{where} must be a finite number, got {value!r}")
    return value


@dataclass(frozen=True)
class ModelsConfig:
    entries: tuple  # tuple of (model_name, tuple of sorted (key, value) pairs)

    def __post_init__(self):
        if not isinstance(self.entries, tuple) or len(self.entries) == 0:
            raise ValueError("models must be a non-empty mapping")
        for name, pairs in self.entries:
            if name not in _MODEL_NAMES:
                raise ValueError(f"unknown model {name!r}; allowed: {sorted(_MODEL_NAMES)}")
            for key, value in pairs:
                if not isinstance(key, str):
                    raise ValueError(f"models.{name}: parameter name must be str, got {key!r}")
                if type(_normalise_param(name, key, value)) is not type(value):
                    raise ValueError(
                        f"models.{name}.{key} must already be normalised, got {value!r}"
                    )
            values = dict(pairs)
            for required in _REQUIRED_TRUE.get(name, ()):
                if values.get(required) is not True:
                    raise ValueError(f"models.{name}.{required} must be true (reproducibility)")

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

    def __post_init__(self):
        _check_int_seq("leads", self.leads)
        _check_int("latency_days", self.latency_days, 0)
        _check_int("seed", self.seed, 0)
        if self.splits.embargo_weeks < max(self.leads):
            raise ValueError(
                f"splits.embargo_weeks ({self.splits.embargo_weeks}) must be >= max(leads) "
                f"({max(self.leads)})"
            )
        if not set(self.gate.primary_leads) <= set(self.leads):
            raise ValueError(
                f"gate.primary_leads {self.gate.primary_leads} must be a subset of leads {self.leads}"
            )
        expected = (self.splits.train_years[0], self.splits.validate_years[1])
        if self.retrain_policy.pre_test_refit_years != expected:
            raise ValueError(
                f"retrain_policy.pre_test_refit_years must be {list(expected)} "
                f"(train start..validate end), got {list(self.retrain_policy.pre_test_refit_years)}"
            )


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
        if name not in _MODEL_NAMES:
            raise ValueError(f"unknown model {name!r}; allowed: {sorted(_MODEL_NAMES)}")
        normalised = {
            k: _normalise_param(name, k, v) if isinstance(k, str) else v for k, v in params.items()
        }
        entries.append((name, tuple(sorted(normalised.items(), key=lambda kv: str(kv[0])))))
    return ModelsConfig(entries=tuple(entries))


_TOP_KEYS = [f.name for f in dataclasses.fields(ForecastConfig)]


def load_forecast_config(path: Path = FORECAST_CONFIG_PATH) -> ForecastConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.load(f.read(), Loader=_UniqueKeySafeLoader)  # noqa: S506 (SafeLoader subclass)
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
