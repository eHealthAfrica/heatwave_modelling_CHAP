"""Synthetic frozen dataset with the real schema, for CI without the real data."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from heatwave.forecast import weeks
from heatwave.forecast.data import (
    EXPECTED_ARROW_TYPES,
    EXPECTED_COLUMNS,
    MANIFEST_NAME,
    PARQUET_NAME,
    sha256_file,
)

SYNTHETIC_WARDS = (
    "KNAAA001",
    "KNAAA002",
    "KTBBB001",
    "KTBBB002",
    "SOCCC001",
    "SOCCC002",
)

_PA_TYPES = {"string": pa.string(), "int64": pa.int64(), "double": pa.float64()}


@dataclass(frozen=True)
class SyntheticFrozen:
    data_root: Path
    dataset_dir: Path
    parquet_path: Path
    manifest_path: Path
    sha256: str
    wards: tuple
    labels: tuple
    frame: pd.DataFrame


def arrow_schema() -> pa.Schema:
    return pa.schema([(c, _PA_TYPES[EXPECTED_ARROW_TYPES[c]]) for c in EXPECTED_COLUMNS])


def _make_frame(wards, labels, seed) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for label in labels:
        order = rng.permutation(len(wards))
        n = len(wards)
        parts.append(
            pd.DataFrame(
                {
                    "time_period": [label] * n,
                    "location": [wards[i] for i in order],
                    "heatwave_days": rng.integers(0, 8, n).astype("int64"),
                    "mean_heat_index": np.round(rng.uniform(25, 55, n), 3),
                    "max_heat_index": np.round(rng.uniform(25, 55, n), 3),
                    "heatwave_event_count": rng.integers(0, 3, n).astype("int64"),
                    "hot_nights": rng.integers(0, 8, n).astype("int64"),
                    "total_precipitation_mm": np.round(rng.uniform(0, 120, n), 3),
                    "mean_relative_humidity": np.round(rng.uniform(10, 95, n), 3),
                    "mean_soil_moisture": np.round(rng.uniform(0.05, 0.45, n), 3),
                }
            )
        )
    return pd.concat(parts, ignore_index=True)[list(EXPECTED_COLUMNS)]


def build_synthetic_frozen(
    data_root,
    *,
    version: str = "covariates-v1.0",
    first_week: str = "1991-W02",
    last_week: str = "1993-W05",
    seed: int = 0,
    with_inputs: bool = True,
) -> SyntheticFrozen:
    data_root = Path(data_root)
    dataset_dir = data_root / "frozen" / version
    dataset_dir.mkdir(parents=True, exist_ok=True)
    start = weeks.label_to_index(first_week)
    stop = weeks.label_to_index(last_week)
    labels = weeks.index_labels(stop - start + 1, start=start)
    wards = SYNTHETIC_WARDS
    frame = _make_frame(wards, labels, seed)

    parquet_path = dataset_dir / PARQUET_NAME
    table = pa.Table.from_pandas(frame, schema=arrow_schema(), preserve_index=False)
    pq.write_table(table, parquet_path, compression="snappy")
    sha = sha256_file(parquet_path)

    inputs_sha: dict = {}
    if with_inputs:
        geo = data_root / "wards.geojson"
        geo.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
        files = {"wards.geojson": geo}
        for year in ("1992", "2026"):
            nc = data_root / "era5_land_daily_gee" / "temperature_2m_max" / f"{year}.nc"
            nc.parent.mkdir(parents=True, exist_ok=True)
            nc.write_bytes(f"synthetic-era5-{year}".encode() * 8)
            files[f"era5_land_daily_gee/temperature_2m_max/{year}.nc"] = nc
        for key, p in files.items():
            inputs_sha[key] = sha256_file(p)
        for key in ("wards.geojson", "era5_land_daily_gee/temperature_2m_max/2026.nc"):
            dst = dataset_dir / "inputs" / key
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(files[key], dst)

    manifest = {
        "version": version,
        "table": {
            "rows": int(len(frame)),
            "wards": len(wards),
            "weeks": len(labels),
            "first_week": labels[0],
            "last_week": labels[-1],
            "columns": list(EXPECTED_COLUMNS),
            "nulls": 0,
        },
        "outputs_sha256": {PARQUET_NAME: sha},
        "inputs_sha256": inputs_sha,
        "inputs_copied": "synthetic",
    }
    manifest_path = dataset_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return SyntheticFrozen(
        data_root=data_root,
        dataset_dir=dataset_dir,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        sha256=sha,
        wards=wards,
        labels=tuple(labels),
        frame=frame,
    )
