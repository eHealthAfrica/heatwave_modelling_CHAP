"""Stored predictions: one Parquet format for every predictor, with provenance and lock-aware I/O.

Files live only in <forecast_runs>/<run_id>/predictions/. Metadata is JSON under the schema key
``heatwave_forecast`` (JSON only). Loading test-split rows goes through the test lock.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from heatwave.forecast import splits, targets, testlock
from heatwave.forecast.artifacts import REPO_ROOT, RUN_ID_PATTERN, RUNS_SUBDIR
from heatwave.forecast.splits import SPLIT_NAMES

SCHEMA_VERSION = 1
METADATA_KEY = b"heatwave_forecast"
PREDICTIONS_SUBDIR = "predictions"
COLUMNS = (
    "predictor", "lead", "ward", "origin_week_index", "target_week_index",
    "target_week", "split", "p", "y", "fold",
)
DTYPES = {
    "predictor": "category",
    "lead": "int8",
    "ward": "category",
    "origin_week_index": "int16",
    "target_week_index": "int16",
    "target_week": "category",
    "split": "category",
    "p": "float32",
    "y": "int8",
    "fold": "Int8",
}
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PredictionMeta:
    run_id: str
    config_sha256: str
    data_sha256: str
    predictor: str
    lead: int
    split: str
    schema_version: int = SCHEMA_VERSION
    threshold: float | None = None

    def __post_init__(self):
        if not isinstance(self.run_id, str) or not RUN_ID_PATTERN.match(self.run_id):
            raise ValueError(f"bad run_id {self.run_id!r}")
        for nm in ("config_sha256", "data_sha256"):
            v = getattr(self, nm)
            if not isinstance(v, str) or not _SHA_RE.match(v):
                raise ValueError(f"{nm} must be 64 lowercase hex characters")
        if not isinstance(self.predictor, str) or not _NAME_RE.match(self.predictor):
            raise ValueError(f"bad predictor name {self.predictor!r}")
        if isinstance(self.lead, bool) or not isinstance(self.lead, int) or self.lead < 1:
            raise ValueError("lead must be an int >= 1")
        if self.split not in SPLIT_NAMES:
            raise ValueError(f"unknown split {self.split!r}")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version!r}")
        if self.threshold is not None and not isinstance(self.threshold, (int, float)):
            raise ValueError("threshold must be a number or None")


# --------------------------------------------------------------------------- frame builder
def build_frame(panel, cfg, predictor, lead, split, ward_pos, origin_pos, p, *, fold=None) -> pd.DataFrame:
    if split not in SPLIT_NAMES:
        raise ValueError(f"unknown split {split!r}")
    if not isinstance(predictor, str) or not _NAME_RE.match(predictor):
        raise ValueError(f"bad predictor name {predictor!r}")
    ward_pos = np.asarray(ward_pos, dtype=np.int64)
    origin_pos = np.asarray(origin_pos, dtype=np.int64)
    p = np.asarray(p, dtype=np.float32)
    n = len(p)
    if p.ndim != 1 or ward_pos.shape != (n,) or origin_pos.shape != (n,):
        raise ValueError("p, ward_pos and origin_pos must be 1-D and the same length")
    if not np.isfinite(p).all():
        raise ValueError("p contains NaN or inf")
    if n and (p.min() < 0 or p.max() > 1):
        raise ValueError("p must lie within [0, 1]")
    tf = targets.timing_fields(panel, lead, cfg.latency_days)
    wi = np.asarray(panel.week_index, dtype=np.int64)
    target_idx = tf.target_week_index[origin_pos]
    # date-based guard (WR-01): rows in the pinned test window need the lock whatever the split label
    if split == "test" or splits.protected_mask(target_idx).any():
        testlock.require_open(cfg, "build_predictions", predictor=predictor, lead=lead, n_rows=n)
    y = targets.lead_label(panel, lead)[ward_pos, origin_pos]
    if np.isnan(y).any():
        raise ValueError("labels are NaN at some requested rows")
    got = splits.assign_split(target_idx, cfg.splits)
    if (got != split).any():
        raise ValueError(f"some rows do not belong to split {split!r}")
    tw = np.asarray(tf.target_week, dtype=object)[origin_pos]
    fold_col = pd.array([fold] * n if fold is not None else [pd.NA] * n, dtype="Int8")
    df = pd.DataFrame({
        "predictor": pd.Categorical([predictor] * n, categories=[predictor]),
        "lead": np.full(n, lead, dtype=np.int8),
        "ward": pd.Categorical.from_codes(ward_pos, categories=list(panel.wards)),
        "origin_week_index": wi[origin_pos].astype(np.int16),
        "target_week_index": target_idx.astype(np.int16),
        "target_week": pd.Categorical(tw),
        "split": pd.Categorical([split] * n, categories=[split]),
        "p": p,
        "y": y.astype(np.int8),
        "fold": fold_col,
    })
    return df[list(COLUMNS)]


# --------------------------------------------------------------------------- paths and writer
def prediction_path(run_dir, predictor, lead, split) -> Path:
    if not isinstance(predictor, str) or not _NAME_RE.match(predictor):
        raise ValueError(f"bad predictor name {predictor!r}")
    if split not in SPLIT_NAMES:
        raise ValueError(f"unknown split {split!r}")
    if isinstance(lead, bool) or not isinstance(lead, (int, np.integer)) or lead < 1:
        raise ValueError("lead must be an int >= 1")
    run_dir = Path(run_dir)
    if not RUN_ID_PATTERN.match(run_dir.name):
        raise ValueError(f"run folder name {run_dir.name!r} is not a run id")
    if run_dir.parent.name != RUNS_SUBDIR:
        raise ValueError(f"run folder must sit directly under {RUNS_SUBDIR!r}")
    resolved = run_dir.resolve()
    if any(part.lower() == "frozen" for part in resolved.parts):
        raise ValueError("refusing to write predictions under a frozen path")
    repo = REPO_ROOT.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("refusing to write predictions inside the repository")
    path = run_dir / PREDICTIONS_SUBDIR / f"{predictor}_L{int(lead)}_{split}.parquet"
    if path.resolve().parent != resolved / PREDICTIONS_SUBDIR:
        raise ValueError("resolved prediction path escapes the run folder")
    return path


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    if tuple(df.columns) != COLUMNS:
        raise ValueError(f"columns must be {COLUMNS}, got {tuple(df.columns)}")
    df = df.copy()
    for col, dt in DTYPES.items():
        if dt == "category":
            if not isinstance(df[col].dtype, pd.CategoricalDtype):
                df[col] = df[col].astype("category")
        elif str(df[col].dtype) != dt:
            df[col] = df[col].astype(dt)
    return df


def _check_matches_meta(df: pd.DataFrame, meta: PredictionMeta) -> None:
    if (df["predictor"].astype(str) != meta.predictor).any():
        raise ValueError("predictor values differ from metadata")
    if (df["lead"] != meta.lead).any():
        raise ValueError("lead values differ from metadata")
    if (df["split"].astype(str) != meta.split).any():
        raise ValueError("split values differ from metadata")


def _derived_splits(target_week_index, cfg) -> np.ndarray:
    return splits.assign_split(np.asarray(target_week_index, dtype=np.int64), cfg.splits, strict=False)


def _check_split_labels(labels, target_week_index, cfg) -> None:
    """The split label of every row must equal the split derived from its target week (WR-02)."""
    derived = _derived_splits(target_week_index, cfg)
    if (derived != np.asarray(labels).astype(str)).any():
        raise ValueError("split column disagrees with target_week_index (derived from the pinned dates)")


def write_predictions(df: pd.DataFrame, meta: PredictionMeta, run_dir, *, cfg=None) -> Path:
    if tuple(df.columns) != COLUMNS:
        raise ValueError(f"columns must be {COLUMNS}, got {tuple(df.columns)}")
    for col, dt in DTYPES.items():
        ok = isinstance(df[col].dtype, pd.CategoricalDtype) if dt == "category" else str(df[col].dtype) == dt
        if not ok:
            raise ValueError(f"column {col!r} has dtype {df[col].dtype}, expected {dt}")
    _check_matches_meta(df, meta)
    if cfg is not None:
        _check_split_labels(df["split"].astype(str).to_numpy(), df["target_week_index"].to_numpy(), cfg)
    path = prediction_path(run_dir, meta.predictor, meta.lead, meta.split)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    table = table.replace_schema_metadata(
        {**existing, METADATA_KEY: json.dumps(asdict(meta), sort_keys=True).encode("utf-8")}
    )
    tmp = path.with_name(path.name + ".tmp")
    try:
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def read_metadata(path) -> PredictionMeta:
    md = pq.read_schema(path).metadata or {}
    raw = md.get(METADATA_KEY)
    if raw is None:
        raise ValueError("prediction file lacks heatwave_forecast metadata")
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("unreadable prediction metadata") from exc
    if not isinstance(d, dict):
        raise ValueError("prediction metadata must be a JSON object")
    fields = {"run_id", "config_sha256", "data_sha256", "predictor", "lead", "split",
              "schema_version", "threshold"}
    if set(d) != fields:
        raise ValueError(f"prediction metadata fields {sorted(d)} != {sorted(fields)}")
    return PredictionMeta(**d)


# --------------------------------------------------------------------------- loader and alignment
def load_predictions(path, cfg, *, data_root=None) -> tuple[pd.DataFrame, PredictionMeta]:
    meta = read_metadata(path)
    # Only the two key columns are read before the lock decision, so no label or probability is in
    # memory while the lock is closed. Protection is decided from the target weeks (pinned dates),
    # never from the file's own split label (WR-02).
    head = pq.read_table(path, columns=["target_week_index", "split"]).to_pandas()
    t = head["target_week_index"].to_numpy(dtype=np.int64)
    labels = head["split"].astype(str).to_numpy()
    derived = _derived_splits(t, cfg)
    protected = (
        meta.split == "test"
        or bool((labels == "test").any())
        or bool(splits.protected_mask(t).any())
        or bool(np.isin(derived, ("test", splits.BEYOND_TEST)).any())
    )
    if protected:
        testlock.require_open(
            cfg, "load_predictions", predictor=meta.predictor, lead=meta.lead,
            n_rows=int(t.size), run_id=meta.run_id, data_root=data_root,
        )
    if (derived != labels).any():
        raise ValueError("split column disagrees with target_week_index (derived from the pinned dates)")
    df = pq.read_table(path).to_pandas()
    df = _coerce(df)
    p = df["p"].to_numpy()
    if not np.isfinite(p).all() or (len(p) and (p.min() < 0 or p.max() > 1)):
        raise ValueError("p must be finite and within [0, 1]")
    if not df["y"].isin([0, 1]).all():
        raise ValueError("y must be 0 or 1")
    _check_matches_meta(df, meta)
    return df, meta


def align(ref: pd.DataFrame, cand: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Index arrays (r_idx, c_idx) such that ref.iloc[r_idx] and cand.iloc[c_idx] share keys."""
    if len(ref) != len(cand):
        raise ValueError("reference and candidate differ in length")
    if list(ref["ward"].cat.categories) != list(cand["ward"].cat.categories):
        raise ValueError("ward categories differ")
    rw, ro = ref["ward"].cat.codes.to_numpy(), ref["origin_week_index"].to_numpy()
    cw, co = cand["ward"].cat.codes.to_numpy(), cand["origin_week_index"].to_numpy()
    r_idx = np.lexsort((ro, rw))
    c_idx = np.lexsort((co, cw))
    rw, ro, cw, co = rw[r_idx], ro[r_idx], cw[c_idx], co[c_idx]
    if (np.diff(rw) == 0).any() and ((np.diff(rw) == 0) & (np.diff(ro) == 0)).any():
        raise ValueError("duplicate (ward, origin_week_index) keys")
    if not (np.array_equal(rw, cw) and np.array_equal(ro, co)):
        raise ValueError("reference and candidate keys differ")
    if not np.array_equal(ref["y"].to_numpy()[r_idx], cand["y"].to_numpy()[c_idx]):
        raise ValueError("labels differ between reference and candidate")
    return r_idx, c_idx
