"""Synthetic frozen dataset with the real schema, for CI without the real data."""

from __future__ import annotations

import hashlib
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
    VARIABLES,
    Panel,
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


# --------------------------------------------------------------------------- in-memory panels
def synthetic_panel(
    *,
    first_week: str = "1991-W02",
    last_week: str = "2003-W20",
    seed: int = 0,
    wards=SYNTHETIC_WARDS,
) -> Panel:
    """In-memory Panel (no parquet) with realistic ranges; includes 1992-W53 and 1998-W53."""
    wards = tuple(wards)
    start = weeks.label_to_index(first_week)
    stop = weeks.label_to_index(last_week)
    labels = weeks.index_labels(stop - start + 1, start=start)
    n, t = len(wards), len(labels)
    rng = np.random.default_rng(seed)
    iso_week = np.array([int(lab[-2:]) for lab in labels], dtype=float)
    season = np.broadcast_to(np.sin(2 * np.pi * (iso_week - 10) / 52.0), (n, t))
    p_t = 0.15 + 0.10 * season
    out = {}
    out["heatwave_days"] = rng.binomial(7, p_t).astype(float)
    out["hot_nights"] = rng.binomial(7, 0.2, size=(n, t)).astype(float)
    out["heatwave_event_count"] = rng.integers(0, 3, size=(n, t)).astype(float)
    mean_hi = 88 + 8 * season + rng.normal(0, 3, size=(n, t))
    out["mean_heat_index"] = mean_hi
    out["max_heat_index"] = mean_hi + rng.uniform(2, 8, size=(n, t))
    precip = rng.gamma(0.8, 15.0, size=(n, t))
    precip[rng.random((n, t)) < 0.3] = 0.0
    out["total_precipitation_mm"] = precip
    out["mean_relative_humidity"] = rng.uniform(10, 95, size=(n, t))
    out["mean_soil_moisture"] = rng.uniform(0.05, 0.45, size=(n, t))
    values = np.stack([out[v] for v in VARIABLES], axis=-1).astype(np.float32)
    week_start = np.array(
        [np.datetime64(weeks.index_to_week_start(i).isoformat(), "D") for i in range(start, stop + 1)]
    )
    return Panel(
        values=values,
        wards=wards,
        week_index=np.arange(start, stop + 1, dtype=np.int64),
        week_labels=tuple(labels),
        week_start=week_start,
        variables=VARIABLES,
        version="synthetic",
        sha256=hashlib.sha256(values.tobytes()).hexdigest(),
    )


def _derived_sha(panel: Panel, tag: str) -> str:
    return hashlib.sha256(f"{panel.sha256}:{tag}".encode()).hexdigest()


def truncate_panel(panel: Panel, last_pos: int) -> Panel:
    """New Panel with week positions 0..last_pos inclusive (arrays copied)."""
    if not 0 <= last_pos < panel.values.shape[1]:
        raise ValueError(f"last_pos {last_pos} out of range")
    k = last_pos + 1
    return Panel(
        values=panel.values[:, :k].copy(),
        wards=panel.wards,
        week_index=panel.week_index[:k].copy(),
        week_labels=panel.week_labels[:k],
        week_start=panel.week_start[:k].copy(),
        variables=panel.variables,
        version=panel.version,
        sha256=_derived_sha(panel, f"truncate:{last_pos}"),
    )


def poison_future(panel: Panel, last_pos: int, *, mode: str = "garbage", seed: int = 0) -> Panel:
    """New Panel whose weeks after last_pos are garbage (or NaN); earlier weeks are untouched."""
    if mode not in ("garbage", "nan"):
        raise ValueError(f"unknown poison mode {mode!r}")
    values = panel.values.copy()
    if mode == "nan":
        values[:, last_pos + 1 :] = np.nan
    else:
        rng = np.random.default_rng(seed)
        shape = values[:, last_pos + 1 :].shape
        values[:, last_pos + 1 :] = rng.normal(1e6, 1e5, shape).astype(np.float32)
    return Panel(
        values=values,
        wards=panel.wards,
        week_index=panel.week_index.copy(),
        week_labels=panel.week_labels,
        week_start=panel.week_start.copy(),
        variables=panel.variables,
        version=panel.version,
        sha256=_derived_sha(panel, f"poison:{mode}:{last_pos}:{seed}"),
    )


def subset_panel(panel: Panel, ward_positions) -> Panel:
    """New Panel keeping the listed wards (sorted, unique positions)."""
    pos = sorted({int(p) for p in ward_positions})
    if not pos or pos[0] < 0 or pos[-1] >= len(panel.wards):
        raise ValueError(f"ward positions out of range or empty: {list(ward_positions)!r}")
    return Panel(
        values=panel.values[pos].copy(),
        wards=tuple(panel.wards[i] for i in pos),
        week_index=panel.week_index.copy(),
        week_labels=panel.week_labels,
        week_start=panel.week_start.copy(),
        variables=panel.variables,
        version=panel.version,
        sha256=_derived_sha(panel, "subset:" + ",".join(map(str, pos))),
    )


# --------------------------------------------------------------------------- static metadata
def _square(lon: float, lat: float, d: float = 0.02) -> dict:
    ring = [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
    return {"type": "Polygon", "coordinates": [ring]}


def synthetic_static_sources(wards=SYNTHETIC_WARDS) -> tuple[dict, list[dict]]:
    """GeoJSON FeatureCollection and LGA-average rows matching the synthetic wards."""
    spec = {
        "KNAAA001": ("20001", "Kano", "NWZ", _square(8.5, 12.0)),
        "KNAAA002": ("20001", "Kano", "NWZ", _square(8.6, 12.0)),
        "KTBBB001": ("21002", "Katsina", "NEZ", _square(7.5, 10.5)),
        "KTBBB002": ("21002", "Katsina", "NEZ", _square(7.6, 10.5)),
        "SOCCC001": ("7023", "Sokoto", "NCZ", _square(5.5, 9.0)),
        "SOCCC002": ("7023", "Sokoto", "NCZ", {"type": "MultiPoint", "coordinates": []}),
    }
    features = []
    for w in wards:
        lga, state, zone, geom = spec[w]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "wardcode": w,
                    "lgacode": lga,
                    "lganame": f"LGA{lga}",
                    "statename": state,
                    "statecode": state[:2].upper(),
                    "geozone": zone,
                },
                "geometry": geom,
            }
        )
    return {"type": "FeatureCollection", "features": features}, [
        {"location": "SOCCC002", "lgacode": "7023"}
    ]


def add_synthetic_static(sf: SyntheticFrozen) -> SyntheticFrozen:
    """Write hash-registered wards.geojson and wards_lga_average.csv under sf's tmp data_root."""
    geo, lga_rows = synthetic_static_sources(sf.wards)
    text = json.dumps(geo)
    (sf.data_root / "wards.geojson").write_text(text, encoding="utf-8")
    inputs = sf.dataset_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    geo_path = inputs / "wards.geojson"
    geo_path.write_text(text, encoding="utf-8")
    csv_path = sf.dataset_dir / "wards_lga_average.csv"
    lines = ["location,lgacode"] + [f"{r['location']},{r['lgacode']}" for r in lga_rows]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = json.loads(sf.manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("inputs_sha256", {})["wards.geojson"] = sha256_file(geo_path)
    manifest.setdefault("outputs_sha256", {})["wards_lga_average.csv"] = sha256_file(csv_path)
    sf.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return sf
