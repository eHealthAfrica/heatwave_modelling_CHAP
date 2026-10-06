"""Hash-verified loader for the frozen covariate dataset (DATA-01, DATA-02).

Training only ever sees the byte-exact ``covariates-vN.N`` parquet. Files are
opened read-only ("rb"); nothing in this module writes or alters file permissions.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from heatwave.config import settings
from heatwave.forecast import weeks
from heatwave.forecast.config import DataConfig

PARQUET_NAME = "covariate_table.parquet"
MANIFEST_NAME = "MANIFEST.json"
ID_COLUMNS = ("time_period", "location")
VARIABLES = (
    "heatwave_days",
    "mean_heat_index",
    "max_heat_index",
    "heatwave_event_count",
    "hot_nights",
    "total_precipitation_mm",
    "mean_relative_humidity",
    "mean_soil_moisture",
)
EXPECTED_COLUMNS = ID_COLUMNS + VARIABLES
INTEGER_VARIABLES = ("heatwave_days", "heatwave_event_count", "hot_nights")
EXPECTED_ARROW_TYPES = {
    "time_period": "string",
    "location": "string",
    "heatwave_days": "int64",
    "mean_heat_index": "double",
    "max_heat_index": "double",
    "heatwave_event_count": "int64",
    "hot_nights": "int64",
    "total_precipitation_mm": "double",
    "mean_relative_humidity": "double",
    "mean_soil_moisture": "double",
}


class FrozenDataError(RuntimeError):
    """Raised when the frozen dataset fails any integrity or provenance check."""


def sha256_file(path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of the raw bytes of ``path``, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _root(data_root) -> Path:
    return Path(data_root if data_root is not None else settings.local_data_dir).resolve()


def frozen_dataset_dir(data_cfg: DataConfig, data_root=None) -> Path:
    """<root>/<frozen_subdir>/<version>, contained in the frozen subdir."""
    root = _root(data_root)
    d = (root / data_cfg.frozen_subdir / data_cfg.version).resolve()
    if d.parent != (root / data_cfg.frozen_subdir).resolve():
        raise FrozenDataError(f"frozen dataset dir escapes the frozen folder: {d}")
    return d


def read_manifest(dataset_dir) -> dict:
    path = Path(dataset_dir) / MANIFEST_NAME
    if not path.is_file():
        raise FrozenDataError(f"{MANIFEST_NAME} missing in {dataset_dir}")
    try:
        with open(path, "rb") as fh:
            manifest = json.loads(fh.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FrozenDataError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise FrozenDataError(f"{MANIFEST_NAME} must be a JSON object")
    return manifest


def assert_frozen_source(path, data_cfg: DataConfig, data_root=None) -> Path:
    """Accept only <root>/frozen/<version>/covariate_table.parquet."""
    p = Path(path)
    if p.suffix.lower() != ".parquet":
        raise FrozenDataError(
            f"{p} refused: live or CSV tables (e.g. outputs/covariate_table.csv) are never "
            f"used for training; only the frozen {data_cfg.version} parquet is accepted"
        )
    expected = frozen_dataset_dir(data_cfg, data_root) / PARQUET_NAME
    if p.resolve() != expected:
        raise FrozenDataError(f"{p} refused: not the frozen dataset parquet {expected}")
    return p.resolve()


def verify_frozen_parquet(data_cfg: DataConfig, data_root=None):
    """Hash then schema-check the frozen parquet. Returns (path, manifest, sha)."""
    path, manifest, sha, _raw = _verify_frozen_bytes(data_cfg, data_root)
    return path, manifest, sha


def _verify_frozen_bytes(data_cfg: DataConfig, data_root=None):
    """Read the parquet bytes ONCE, verify them, return (path, manifest, sha, raw).

    The caller must parse ``raw`` (never re-open the path): this pins the parsed
    bytes to the hashed bytes and leaves no open file handle behind.
    """
    dataset_dir = frozen_dataset_dir(data_cfg, data_root)
    manifest = read_manifest(dataset_dir)
    if manifest.get("version") != data_cfg.version:
        raise FrozenDataError(
            f"MANIFEST version {manifest.get('version')!r} != expected {data_cfg.version!r}"
        )
    path = dataset_dir / PARQUET_NAME
    if not path.is_file():
        raise FrozenDataError(f"frozen parquet missing: {path}")
    assert_frozen_source(path, data_cfg, data_root)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        want = manifest["outputs_sha256"][PARQUET_NAME]
    except (KeyError, TypeError) as exc:
        raise FrozenDataError("MANIFEST lacks outputs_sha256 for the parquet") from exc
    if sha != want:
        raise FrozenDataError(f"parquet sha256 {sha} != MANIFEST outputs_sha256 {want}")
    if sha != data_cfg.expected_parquet_sha256:
        raise FrozenDataError(
            f"parquet sha256 {sha} != forecast.yaml data.expected_parquet_sha256 "
            f"{data_cfg.expected_parquet_sha256}"
        )
    table = manifest.get("table")
    if not isinstance(table, dict):
        raise FrozenDataError("MANIFEST lacks a table section")
    pf = pq.ParquetFile(io.BytesIO(raw))
    schema = pf.schema_arrow
    names = tuple(schema.names)
    types = {f.name: str(f.type) for f in schema}
    if names != EXPECTED_COLUMNS or tuple(table.get("columns", ())) != EXPECTED_COLUMNS:
        raise FrozenDataError(f"schema columns mismatch: {names}")
    if types != EXPECTED_ARROW_TYPES:
        raise FrozenDataError(f"schema dtypes mismatch: {types}")
    if pf.metadata.num_rows != table.get("rows"):
        raise FrozenDataError(
            f"row count {pf.metadata.num_rows} != MANIFEST table.rows {table.get('rows')}"
        )
    return path, manifest, sha, raw


@dataclass(frozen=True, eq=False)
class Panel:
    values: np.ndarray  # (wards, weeks, variables) float32
    wards: tuple
    week_index: np.ndarray  # global week indices (weeks.py)
    week_labels: tuple
    week_start: np.ndarray  # datetime64[D]
    variables: tuple
    version: str
    sha256: str

    def __post_init__(self):
        object.__setattr__(self, "_ward_pos", {w: i for i, w in enumerate(self.wards)})
        object.__setattr__(self, "_week_pos", {w: i for i, w in enumerate(self.week_labels)})

    def ward_pos(self, code: str) -> int:
        return self._ward_pos[code]

    def week_pos(self, label: str) -> int:
        return self._week_pos[label]

    @property
    def shape(self):
        return self.values.shape


def load_panel(data_cfg: DataConfig, data_root=None) -> Panel:
    _path, manifest, sha, raw = _verify_frozen_bytes(data_cfg, data_root)
    table = manifest["table"]
    df = pq.read_table(io.BytesIO(raw), columns=list(EXPECTED_COLUMNS)).to_pandas()
    del raw
    if df.isna().any().any():
        raise FrozenDataError("frozen parquet contains nulls")
    wards = tuple(sorted(df["location"].unique()))
    if len(wards) != table["wards"]:
        raise FrozenDataError(f"ward count {len(wards)} != MANIFEST table.wards {table['wards']}")
    idx = weeks.labels_to_indices(df["time_period"].to_numpy())
    uniq = np.unique(idx)
    lo, hi = weeks.label_to_index(table["first_week"]), weeks.label_to_index(table["last_week"])
    if not np.array_equal(uniq, np.arange(lo, hi + 1)) or len(uniq) != table["weeks"]:
        raise FrozenDataError(
            f"week axis is not contiguous {table['first_week']}..{table['last_week']} "
            f"with {table['weeks']} weeks (found {len(uniq)})"
        )
    week_labels = tuple(weeks.index_to_label(int(i)) for i in uniq)
    if set(week_labels) != set(df["time_period"].unique()):
        raise FrozenDataError("week labels in file are not canonical ISO labels")
    n, w, v = len(wards), len(uniq), len(VARIABLES)
    if len(df) != n * w:
        raise FrozenDataError(f"duplicate or missing cell: {len(df)} rows != {n}*{w}")
    ward_pos = np.searchsorted(np.array(wards), df["location"].to_numpy())
    week_pos = idx - lo
    values = np.full((n, w, v), np.nan, dtype=np.float32)
    for k, name in enumerate(VARIABLES):
        values[ward_pos, week_pos, k] = df[name].to_numpy(dtype=np.float32)
    seen = np.zeros((n, w), dtype=bool)
    seen[ward_pos, week_pos] = True
    if not seen.all() or np.isnan(values).sum() != 0:
        raise FrozenDataError("duplicate or missing cell in (ward, week) grid")
    del df
    week_start = np.array(
        [np.datetime64(weeks.index_to_week_start(int(i)).isoformat(), "D") for i in uniq]
    )
    return Panel(
        values=values,
        wards=wards,
        week_index=uniq.astype(np.int64),
        week_labels=week_labels,
        week_start=week_start,
        variables=VARIABLES,
        version=data_cfg.version,
        sha256=sha,
    )
