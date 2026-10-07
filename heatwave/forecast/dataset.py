"""Model-ready rows: issue-row table, per-lead rows, per-fold stores, optional feature cache.

Rows carry only features gathered at the origin week from an as-of feature store.
Labels come from ``targets.lead_label`` alone. The store's climatology must have been
fitted at ``splits.train_end`` (main split) or at the fold's own ``climatology_end``
(cross-validation), otherwise ValueError (PITFALLS C3).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from heatwave.forecast import splits, targets
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.config import config_hash
from heatwave.forecast.features import (
    BASE_RATE_MIN_OBS,
    LONGEST_FIXED_WINDOW_WEEKS,
    REGISTRY,
    FeatureStore,
    base_rate,
    build_feature_store,
    season_features,
    static_feature_matrix,
)

TIMING_COLUMNS = (
    "last_obs_week_index",
    "last_obs_week",
    "issue_date",
    "target_week_index",
    "target_week",
    "target_week_start",
    "lead_weeks",
    "effective_days_ahead",
)
LABEL_COLUMN = "heatwave_week"
SPLIT_COLUMN = "split"
WARMUP = "warmup"  # issue-table origins before every window/base rate is defined
CACHE_SUBDIR = "forecast_cache"
MAX_ISSUE_ROWS = 3_000_000  # guard: a full 4841 x 1863 issue table is ~9M rows and several GB
ROW_SPLIT_CATEGORIES = splits.SPLIT_NAMES + (splits.EMBARGOED, splits.BEYOND_TEST, WARMUP)
_SEASON = ("target_season_sin", "target_season_cos")
_HEX = re.compile(r"^[0-9a-f]+$")
_NAME = re.compile(r"^[A-Za-z0-9_]+$")


# --------------------------------------------------------------------------- helpers
def warmup_first_position(panel) -> int:
    """First origin position with every fixed window and the base rate defined.

    Warm-up values stay NaN; nothing is forward-filled.
    """
    _, counts = base_rate(np.zeros(panel.values.shape[:2], dtype=np.float32), panel.week_start)
    ok = np.nonzero(counts >= BASE_RATE_MIN_OBS)[0]
    first_rate = int(ok[0]) if ok.size else panel.values.shape[1]
    return max(LONGEST_FIXED_WINDOW_WEEKS - 1, first_rate)


def _categorical(codes, categories) -> pd.Categorical:
    """Compact categorical column from integer codes (no per-row Python strings)."""
    return pd.Categorical.from_codes(np.asarray(codes), categories=list(categories))


def _split_categorical(per_origin_names, origin_pos) -> pd.Categorical:
    lookup = {nm: i for i, nm in enumerate(ROW_SPLIT_CATEGORIES)}
    codes = np.fromiter((lookup[nm] for nm in per_origin_names), dtype=np.int8, count=len(per_origin_names))
    return _categorical(codes[origin_pos], ROW_SPLIT_CATEGORIES)


def _as_date(x) -> date:
    if isinstance(x, date) and not hasattr(x, "hour"):
        return x
    if isinstance(x, str):
        return date.fromisoformat(x)
    if hasattr(x, "date"):
        return x.date()
    raise ValueError(f"cannot interpret {x!r} as a date")


def _check_lead(cfg, lead):
    if isinstance(lead, bool) or lead not in cfg.leads:
        raise ValueError(f"lead {lead!r} not in configured leads {tuple(cfg.leads)}")
    return int(lead)


def _check_store(panel, store, cfg, fold):
    if tuple(store.wards) != tuple(panel.wards):
        raise ValueError("store wards differ from panel wards")
    if store.data_sha256 != panel.sha256:
        raise ValueError("store was built from a different panel (data_sha256 mismatch)")
    # clim_fit_range["data_sha256"] is deliberately not compared: the row-level truncation
    # check reuses one climatology fitted at train_end across truncated panels.
    if not np.array_equal(np.asarray(store.week_index), np.asarray(panel.week_index)):
        raise ValueError("store week axis differs from the panel week axis")
    shape = tuple(panel.values.shape[:2])
    for nm in store.names:
        if tuple(store[nm].shape) != shape:
            raise ValueError(f"store array {nm!r} has shape {tuple(store[nm].shape)}, panel needs {shape}")
    expected = _as_date(fold.climatology_end if fold is not None else cfg.splits.train_end)
    got = _as_date(store.clim_fit_range["fit_end"])
    if got != expected:
        raise ValueError(
            f"store climatology fitted with end {got.isoformat()} but this selection requires "
            f"{expected.isoformat()} ({'fold ' + str(fold.year) if fold is not None else 'splits.train_end'})"
        )


def _feature_names(feature_names, registry=REGISTRY):
    names = tuple(registry.names() if feature_names is None else feature_names)
    for nm in names:
        if nm not in registry:
            raise KeyError(nm)
    return names


def lead_row_index(panel, cfg, lead, split, *, fold=None, drop_warmup=True):
    """(ward_pos, origin_pos) of labelled rows for one lead and split, ordered by origin then ward."""
    lead = _check_lead(cfg, lead)
    T = panel.values.shape[1]
    n = len(panel.wards)
    target_idx = np.asarray(panel.week_index, dtype=np.int64) + lead
    if fold is None:
        if split not in splits.SPLIT_NAMES:
            raise ValueError(f"unknown split {split!r}")
        # assign_split rejects indices beyond the configured years; only labelled origins matter
        labelled = targets.has_label(panel, lead)
        mask = np.zeros(T, dtype=bool)
        mask[labelled] = splits.split_masks(target_idx[labelled], cfg.splits)[split]
    else:
        if split not in ("train", "validate"):
            raise ValueError("fold selections support split 'train' or 'validate'")
        tr, va = splits.fold_masks(fold, target_idx)
        mask = (tr if split == "train" else va) & targets.has_label(panel, lead)
    if drop_warmup:
        mask[: warmup_first_position(panel)] = False
    origins = np.nonzero(mask)[0]
    return np.tile(np.arange(n), origins.size), np.repeat(origins, n)


# --------------------------------------------------------------------------- per-lead rows
def _gather_features(store, static, panel, names, ward_pos, origin_pos, target_start, lead, registry=REGISTRY):
    out = {}
    static_names = [nm for nm in names if registry.get(nm).kind == "static"]
    if static_names:
        mat = static_feature_matrix(static.align(panel.wards), static_names)
        for j, nm in enumerate(static_names):
            out[nm] = mat[ward_pos, j]
    sin, cos = season_features(target_start)
    for nm in names:
        kind = registry.get(nm).kind
        if kind == "panel":
            if nm not in store:
                raise KeyError(f"feature {nm!r} not in the store")
            out[nm] = np.asarray(store[nm][ward_pos, origin_pos], dtype=np.float32)
        elif kind == "calendar":
            if nm == "target_season_sin":
                out[nm] = sin
            elif nm == "target_season_cos":
                out[nm] = cos
            elif nm == "lead_weeks":
                out[nm] = np.full(len(ward_pos), lead, dtype=np.int64)
    return out


def lead_rows(
    panel, store, static, cfg, lead, split, *, fold=None, drop_warmup=True, feature_names=None, registry=REGISTRY
):
    """Per-lead row table (labelled rows only) with timing fields, label, split and features."""
    lead = _check_lead(cfg, lead)
    names = _feature_names(feature_names, registry)
    _check_store(panel, store, cfg, fold)
    ward_pos, origin_pos = lead_row_index(panel, cfg, lead, split, fold=fold, drop_warmup=drop_warmup)
    tf = targets.timing_fields(panel, lead, cfg.latency_days)
    cols = {"ward": _categorical(ward_pos, panel.wards)}
    cols["last_obs_week_index"] = tf.last_obs_week_index[origin_pos]
    cols["last_obs_week"] = _categorical(origin_pos, tf.last_obs_week)
    cols["issue_date"] = tf.issue_date[origin_pos]
    cols["target_week_index"] = tf.target_week_index[origin_pos]
    cols["target_week"] = _categorical(origin_pos, tf.target_week)
    cols["target_week_start"] = tf.target_week_start[origin_pos]
    cols["lead_weeks"] = np.full(len(ward_pos), lead, dtype=np.int64)
    cols["effective_days_ahead"] = tf.effective_days_ahead[origin_pos]
    label = targets.lead_label(panel, lead)[ward_pos, origin_pos]
    if np.isnan(label).any():
        raise ValueError("unlabelled row selected")
    cols[LABEL_COLUMN] = label.astype(np.int8)
    if fold is None:
        cols[SPLIT_COLUMN] = _split_categorical(
            splits.assign_split(tf.target_week_index, cfg.splits, strict=False), origin_pos
        )
    else:
        code = ROW_SPLIT_CATEGORIES.index(split)
        cols[SPLIT_COLUMN] = _categorical(np.full(len(ward_pos), code, dtype=np.int8), ROW_SPLIT_CATEGORIES)
    cols.update(
        _gather_features(store, static, panel, names, ward_pos, origin_pos, cols["target_week_start"], lead, registry)
    )
    return pd.DataFrame(cols, copy=False)  # copy=False: no block-consolidation doubling


# --------------------------------------------------------------------------- issue rows
def build_issue_table(
    panel, store, static, cfg, *, origin_positions, ward_positions=None, feature_names=None,
    registry=REGISTRY, max_rows=MAX_ISSUE_ROWS,
):
    """One row per (ward, origin) with all lead labels as columns (leads do not multiply rows).

    ``split_l{k}`` is one of train, embargoed, validate, test, beyond_test (target-week split with
    the 14-week training embargo applied) or warmup (origin before the feature warm-up ends).
    Only rows labelled train/validate/test with ``has_label_l{k}`` are usable for modelling.
    """
    names = _feature_names(feature_names, registry)
    _check_store(panel, store, cfg, None)
    T = panel.values.shape[1]
    origins = np.asarray(list(origin_positions), dtype=np.int64)
    if origins.size and (origins.min() < 0 or origins.max() >= T):
        raise ValueError("origin positions must lie within the panel")
    wp = np.arange(len(panel.wards)) if ward_positions is None else np.asarray(list(ward_positions), dtype=np.int64)
    n_rows = int(origins.size) * int(wp.size)
    if max_rows is not None and n_rows > max_rows:
        raise ValueError(
            f"issue table would have {n_rows:,} rows (> max_rows={max_rows:,}); pass a smaller "
            "origin_positions / ward_positions subset, or raise max_rows explicitly"
        )
    ward_pos = np.tile(wp, origins.size)
    origin_pos = np.repeat(origins, wp.size)
    base = targets.timing_fields(panel, cfg.leads[0], cfg.latency_days)
    warm = warmup_first_position(panel)
    cols = {"ward": _categorical(ward_pos, panel.wards)}
    cols["last_obs_week_index"] = base.last_obs_week_index[origin_pos]
    cols["last_obs_week"] = _categorical(origin_pos, base.last_obs_week)
    cols["issue_date"] = base.issue_date[origin_pos]
    for k in cfg.leads:
        tf = targets.timing_fields(panel, k, cfg.latency_days)
        cols[f"target_week_index_l{k}"] = tf.target_week_index[origin_pos]
        cols[f"target_week_l{k}"] = _categorical(origin_pos, tf.target_week)
        cols[f"target_week_start_l{k}"] = tf.target_week_start[origin_pos]
        cols[f"effective_days_ahead_l{k}"] = tf.effective_days_ahead[origin_pos]
        cols[f"{LABEL_COLUMN}_l{k}"] = targets.lead_label(panel, k)[ward_pos, origin_pos]
        cols[f"has_label_l{k}"] = targets.has_label(panel, k)[origin_pos]
        # same membership as lead_rows/lead_row_index: embargoed training targets and warm-up
        # origins are labelled as such, so filtering split_l{k} == "train" is leakage-safe
        per_origin = splits.issue_split_labels(tf.target_week_index, cfg.splits)
        per_origin[: min(warm, per_origin.size)] = WARMUP
        cols[f"{SPLIT_COLUMN}_l{k}"] = _split_categorical(per_origin, origin_pos)
    # calendar season features are per lead and live in lead_rows
    panel_names = tuple(nm for nm in names if registry.get(nm).kind in ("panel", "static"))
    cols.update(_issue_features(store, static, panel, panel_names, ward_pos, origin_pos, registry))
    return pd.DataFrame(cols, copy=False)


def _issue_features(store, static, panel, names, ward_pos, origin_pos, registry=REGISTRY):
    out = {}
    static_names = [nm for nm in names if registry.get(nm).kind == "static"]
    if static_names:
        mat = static_feature_matrix(static.align(panel.wards), static_names)
        for j, nm in enumerate(static_names):
            out[nm] = mat[ward_pos, j]
    for nm in names:
        if registry.get(nm).kind == "panel":
            if nm not in store:
                raise KeyError(f"feature {nm!r} not in the store")
            out[nm] = np.asarray(store[nm][ward_pos, origin_pos], dtype=np.float32)
    return out


# --------------------------------------------------------------------------- CV folds
def build_fold_store(panel, static, fold, *, registry=REGISTRY, names=None):
    """Refit the climatology on the fold's own training years and build its feature store.

    Phase 12 uses these for out-of-fold calibration; the main split uses the single fit at
    splits.train_end (PITFALLS C3).
    """
    clim = Climatology.fit(panel, fold.climatology_end)
    store = build_feature_store(panel, clim, static, registry=registry, names=names)
    return clim, store


# --------------------------------------------------------------------------- cache
def feature_cache_dir(cfg, panel, data_root=None) -> Path:
    from heatwave.config import settings
    from heatwave.forecast.artifacts import REPO_ROOT

    root = Path(data_root) if data_root is not None else Path(settings.local_data_dir)
    root = root.resolve()
    sha8 = panel.sha256[:8]
    cfg8 = config_hash(cfg)[:8]
    if not (_HEX.match(sha8) and _HEX.match(cfg8)):
        raise ValueError("cache key components must be hex digests")
    path = (root / CACHE_SUBDIR / sha8 / cfg8).resolve()
    repo = Path(REPO_ROOT).resolve()
    if path == repo or repo in path.parents:
        raise ValueError(f"feature cache must not be inside the repo ({repo}); got {path}")
    frozen = (root / cfg.data.frozen_subdir).resolve()
    if path == frozen or frozen in path.parents or cfg.data.frozen_subdir in path.parts:
        raise ValueError(f"feature cache must not be inside the frozen folder; got {path}")
    return path


def _wards_sha(wards) -> str:
    return hashlib.sha256("\n".join(wards).encode("utf-8")).hexdigest()


def _meta(store, clim, registry_names) -> dict:
    return {
        "data_sha256": store.data_sha256,
        "wards_sha256": _wards_sha(store.wards),
        "names": list(store.names),
        "clim_fit_range": json.loads(json.dumps(clim.fit_range())),
        "registry_names": list(registry_names),
    }


def _clim_dir(directory, clim) -> Path:
    return Path(directory) / f"clim_{_as_date(clim.fit_end).strftime('%Y%m%d')}"


def save_feature_store(store, clim, directory, *, registry_names) -> Path:
    sub = _clim_dir(directory, clim)
    sub.mkdir(parents=True, exist_ok=True)
    for nm in store.names:
        if not _NAME.match(nm):
            raise ValueError(f"unsafe feature name {nm!r}")
        np.save(sub / f"{nm}.npy", np.asarray(store[nm], dtype=np.float32), allow_pickle=False)
    tmp = sub / "store_meta.json.tmp"
    tmp.write_text(json.dumps(_meta(store, clim, registry_names), sort_keys=True), encoding="utf-8")
    os.replace(tmp, sub / "store_meta.json")
    return sub


def load_feature_store(directory, panel, clim, *, names, registry_names=None):
    """Return the cached FeatureStore or None on any mismatch (cache miss)."""
    sub = _clim_dir(directory, clim)
    meta_path = sub / "store_meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    names = tuple(names)
    if (
        meta.get("data_sha256") != panel.sha256
        or meta.get("wards_sha256") != _wards_sha(panel.wards)
        or tuple(meta.get("names", ())) != names
        or meta.get("clim_fit_range") != json.loads(json.dumps(clim.fit_range()))
        or (registry_names is not None and tuple(meta.get("registry_names", ())) != tuple(registry_names))
    ):
        return None
    shape = panel.values.shape[:2]
    arrays = {}
    for nm in names:
        if not _NAME.match(nm):
            return None
        try:
            arr = np.load(sub / f"{nm}.npy", allow_pickle=False)
        except (OSError, ValueError):
            return None
        if arr.dtype != np.float32 or arr.shape != shape:
            return None
        arr.flags.writeable = False
        arrays[nm] = arr
    return FeatureStore(
        arrays=arrays,
        wards=panel.wards,
        week_index=panel.week_index,
        week_labels=panel.week_labels,
        names=names,
        clim_fit_range=clim.fit_range(),
        data_sha256=panel.sha256,
    )
