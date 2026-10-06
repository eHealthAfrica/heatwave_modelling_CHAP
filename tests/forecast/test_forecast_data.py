"""Frozen loader acceptance and refusal tests on a synthetic dataset."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from heatwave.forecast import data as fdata
from heatwave.forecast.config import DataConfig
from heatwave.forecast.data import (
    EXPECTED_ARROW_TYPES,
    EXPECTED_COLUMNS,
    VARIABLES,
    FrozenDataError,
    assert_frozen_source,
    frozen_dataset_dir,
    load_panel,
    sha256_file,
    verify_frozen_parquet,
)
from heatwave.forecast.fixtures import arrow_schema, build_synthetic_frozen

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ds(tmp_path):
    return build_synthetic_frozen(tmp_path)


def _dcfg(sha):
    return DataConfig("covariates-v1.0", "frozen", sha)


def _rewrite(ds, frame, schema=None, *, update_manifest=True, manifest_edit=None):
    """Rewrite parquet from `frame`; return new sha. Manifest hash/rows updated."""
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    pq.write_table(table, ds.parquet_path)
    sha = sha256_file(ds.parquet_path)
    m = json.loads(ds.manifest_path.read_text())
    if update_manifest:
        m["outputs_sha256"]["covariate_table.parquet"] = sha
    if manifest_edit:
        manifest_edit(m)
    ds.manifest_path.write_text(json.dumps(m))
    return sha


def _edit_manifest(ds, fn):
    m = json.loads(ds.manifest_path.read_text())
    fn(m)
    ds.manifest_path.write_text(json.dumps(m))


# ---- Task 1 -------------------------------------------------------------


def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(np.random.default_rng(1).bytes(3 * (1 << 20)))
    assert sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()


def test_synthetic_layout(ds, tmp_path):
    assert ds.data_root == tmp_path
    assert len(ds.wards) == 6
    assert len(ds.labels) == 109
    assert ds.labels[0] == "1991-W02" and ds.labels[-1] == "1993-W05"
    assert "1992-W53" in ds.labels
    assert len({w[:2] for w in ds.wards}) == 3
    assert ds.parquet_path == tmp_path / "frozen" / "covariates-v1.0" / "covariate_table.parquet"


def test_synthetic_schema_and_rows(ds):
    schema = pq.ParquetFile(ds.parquet_path).schema_arrow
    assert tuple(schema.names) == EXPECTED_COLUMNS
    assert {f.name: str(f.type) for f in schema} == EXPECTED_ARROW_TYPES
    assert pq.ParquetFile(ds.parquet_path).metadata.num_rows == 654


def test_synthetic_manifest_and_inputs(ds):
    m = json.loads(ds.manifest_path.read_text())
    assert m["version"] == "covariates-v1.0"
    assert m["table"]["nulls"] == 0 and m["table"]["rows"] == 654
    assert m["outputs_sha256"]["covariate_table.parquet"] == ds.sha256
    keys = m["inputs_sha256"]
    for k in (
        "wards.geojson",
        "era5_land_daily_gee/temperature_2m_max/1992.nc",
        "era5_land_daily_gee/temperature_2m_max/2026.nc",
    ):
        assert sha256_file(ds.data_root / k) == keys[k]
    assert (ds.dataset_dir / "inputs" / "wards.geojson").exists()
    assert (ds.dataset_dir / "inputs" / "era5_land_daily_gee/temperature_2m_max/2026.nc").exists()


def test_synthetic_rows_shuffled_within_week(ds):
    first = ds.frame[ds.frame.time_period == ds.labels[0]].location.tolist()
    assert first != sorted(first) or ds.frame[ds.frame.time_period == ds.labels[1]].location.tolist() != sorted(first)
    assert any(
        ds.frame[ds.frame.time_period == lab].location.tolist() != sorted(ds.wards) for lab in ds.labels
    )


def test_synthetic_deterministic(tmp_path):
    a = build_synthetic_frozen(tmp_path / "a")
    b = build_synthetic_frozen(tmp_path / "b")
    assert a.sha256 == b.sha256


# ---- Task 2: acceptance -------------------------------------------------


def test_load_panel_values(ds):
    p = load_panel(_dcfg(ds.sha256), data_root=ds.data_root)
    assert p.values.shape == (6, 109, 8)
    assert p.values.dtype == np.float32
    assert not np.isnan(p.values).any()
    assert p.wards == tuple(sorted(ds.wards))
    assert p.week_labels == ds.labels
    assert np.array_equal(p.week_index, np.arange(0, 109))
    assert p.week_start[0] == np.datetime64("1991-01-07")
    assert p.variables == VARIABLES
    assert p.sha256 == ds.sha256 and p.version == "covariates-v1.0"
    assert p.shape == (6, 109, 8)
    for row in ds.frame.itertuples(index=False):
        i, j = p.ward_pos(row.location), p.week_pos(row.time_period)
        for k, v in enumerate(VARIABLES):
            assert p.values[i, j, k] == np.float32(getattr(row, v))


@pytest.mark.parametrize("name", ["values", "week_index", "week_start"])
def test_panel_arrays_are_read_only(ds, name):
    """WR-05: consumers cannot mutate the shared panel in place."""
    p = load_panel(_dcfg(ds.sha256), data_root=ds.data_root)
    arr = getattr(p, name)
    assert not arr.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        arr[(0,) * arr.ndim] = arr[(0,) * arr.ndim]
    copy = arr.copy()
    copy[(0,) * copy.ndim] = copy[(0,) * copy.ndim]  # explicit copies stay writable


def test_week_53_contiguity(ds):
    p = load_panel(_dcfg(ds.sha256), data_root=ds.data_root)
    assert p.week_pos("1992-W53") + 1 == p.week_pos("1993-W01")


def test_frozen_dataset_dir(ds, tmp_path):
    d = frozen_dataset_dir(_dcfg(ds.sha256), data_root=tmp_path)
    assert d == (tmp_path / "frozen" / "covariates-v1.0").resolve()
    from heatwave.config import settings

    assert frozen_dataset_dir(_dcfg(ds.sha256)) == (
        Path(settings.local_data_dir).resolve() / "frozen" / "covariates-v1.0"
    )


# ---- Task 2: refusals ---------------------------------------------------


def test_byte_flip_refused_before_parse(ds, monkeypatch):
    raw = bytearray(ds.parquet_path.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    ds.parquet_path.write_bytes(bytes(raw))

    def boom(*a, **k):
        raise AssertionError("parquet parsed before hash check")

    monkeypatch.setattr(pd, "read_parquet", boom)
    monkeypatch.setattr(pq, "read_table", boom)
    monkeypatch.setattr(pq, "ParquetFile", boom)
    with pytest.raises(FrozenDataError, match="sha256"):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_swap_after_hash_is_not_parsed(ds, monkeypatch):
    """CR-01: bytes are hashed once and parsed from the same buffer (no TOCTOU)."""
    original = ds.parquet_path.read_bytes()
    tampered = ds.frame.copy()
    tampered["mean_heat_index"] = tampered["mean_heat_index"] + 5.0
    swapped = {"done": False}

    def swap_on_disk():
        if not swapped["done"]:
            swapped["done"] = True
            pq.write_table(
                pa.Table.from_pandas(tampered, schema=arrow_schema(), preserve_index=False),
                ds.parquet_path,
            )

    real_pf, real_rt = pq.ParquetFile, pq.read_table

    def pf(*a, **k):
        swap_on_disk()
        return real_pf(*a, **k)

    def rt(*a, **k):
        swap_on_disk()
        return real_rt(*a, **k)

    monkeypatch.setattr(pq, "ParquetFile", pf)
    monkeypatch.setattr(pq, "read_table", rt)
    real_rp = pd.read_parquet

    def rp(*a, **k):
        swap_on_disk()
        return real_rp(*a, **k)

    monkeypatch.setattr(pd, "read_parquet", rp)
    panel = load_panel(_dcfg(ds.sha256), data_root=ds.data_root)
    assert ds.parquet_path.read_bytes() != original  # the swap really happened
    k = VARIABLES.index("mean_heat_index")
    row = ds.frame.iloc[0]
    assert panel.values[panel.ward_pos(row.location), panel.week_pos(row.time_period), k] == np.float32(
        row.mean_heat_index
    )
    assert panel.sha256 == ds.sha256


def test_tampered_pair_refused_by_yaml_anchor(ds):
    frame = ds.frame.copy()
    frame.loc[0, "mean_heat_index"] += 1.0
    _rewrite(ds, frame, arrow_schema())
    with pytest.raises(FrozenDataError, match="forecast.yaml"):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_missing_parquet(ds):
    ds.parquet_path.unlink()
    with pytest.raises(FrozenDataError, match="missing"):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_missing_manifest(ds):
    ds.manifest_path.unlink()
    with pytest.raises(FrozenDataError):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_manifest_version_mismatch(ds):
    _edit_manifest(ds, lambda m: m.update(version="covariates-v9.9"))
    with pytest.raises(FrozenDataError, match="version"):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_renamed_column_refused(ds):
    frame = ds.frame.rename(columns={"hot_nights": "hot_nights_x"})
    sha = _rewrite(ds, frame)
    with pytest.raises(FrozenDataError, match="schema"):
        load_panel(_dcfg(sha), data_root=ds.data_root)


def test_wrong_dtype_refused(ds):
    frame = ds.frame.copy()
    frame["heatwave_days"] = frame["heatwave_days"].astype("float64")
    sha = _rewrite(ds, frame)
    with pytest.raises(FrozenDataError, match="schema"):
        load_panel(_dcfg(sha), data_root=ds.data_root)


@pytest.mark.parametrize(
    "edit",
    [
        lambda m: m["table"].update(rows=m["table"]["rows"] + 1),
        lambda m: m["table"].update(wards=7),
        lambda m: m["table"].update(weeks=110),
        lambda m: m["table"].update(first_week="1991-W03"),
        lambda m: m["table"].update(last_week="1993-W04"),
    ],
    ids=["rows", "wards", "weeks", "first_week", "last_week"],
)
def test_manifest_count_mismatch(ds, edit):
    _edit_manifest(ds, edit)
    with pytest.raises(FrozenDataError):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


@pytest.mark.parametrize("key", ["rows", "wards", "weeks", "first_week", "last_week", "columns"])
def test_truncated_manifest_table_is_frozen_data_error(ds, key):
    """WR-06: missing table keys raise FrozenDataError, not a bare KeyError."""
    _edit_manifest(ds, lambda m: m["table"].pop(key))
    with pytest.raises(FrozenDataError, match=key):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


@pytest.mark.parametrize(
    "key, value",
    [("wards", "6"), ("weeks", None), ("rows", True), ("first_week", None), ("last_week", "1993-W99"),
     ("first_week", "garbage")],
)
def test_malformed_manifest_table_values(ds, key, value):
    _edit_manifest(ds, lambda m: m["table"].__setitem__(key, value))
    with pytest.raises(FrozenDataError, match=key):
        load_panel(_dcfg(ds.sha256), data_root=ds.data_root)


def test_dropped_week_not_contiguous(ds):
    drop = ds.labels[50]
    frame = ds.frame[ds.frame.time_period != drop].reset_index(drop=True)

    def edit(m):
        m["table"]["rows"] = len(frame)
        m["table"]["weeks"] = 108

    sha = _rewrite(ds, frame, arrow_schema(), manifest_edit=edit)
    with pytest.raises(FrozenDataError, match="contiguous"):
        load_panel(_dcfg(sha), data_root=ds.data_root)


def test_duplicate_cell_refused(ds):
    frame = ds.frame.copy()
    frame.iloc[1] = frame.iloc[0]  # same (ward, week) twice, another cell gone
    sha = _rewrite(ds, frame, arrow_schema())
    with pytest.raises(FrozenDataError, match="duplicate|missing cell"):
        load_panel(_dcfg(sha), data_root=ds.data_root)


@pytest.mark.parametrize(
    "bad, match",
    [(float("inf"), "non-finite"), (float("-inf"), "non-finite"), (1e39, "overflow")],
    ids=["inf", "-inf", "float32-overflow"],
)
def test_non_finite_values_refused(ds, bad, match):
    """CR-02: inf and values that overflow float32 never reach the Panel."""
    frame = ds.frame.copy()
    frame.loc[3, "total_precipitation_mm"] = bad
    sha = _rewrite(ds, frame, arrow_schema())
    with pytest.raises(FrozenDataError, match=match):
        load_panel(_dcfg(sha), data_root=ds.data_root)


def test_live_and_foreign_paths_refused(ds):
    cfg = _dcfg(ds.sha256)
    for bad in (
        REPO_ROOT / "outputs" / "covariate_table.csv",
        ds.dataset_dir / "covariate_table.csv",
        ds.data_root / "other.parquet",
        ds.data_root / "frozen" / "covariates-v0.9" / "covariate_table.parquet",
    ):
        with pytest.raises(FrozenDataError, match="frozen"):
            assert_frozen_source(bad, cfg, data_root=ds.data_root)
    assert assert_frozen_source(ds.parquet_path, cfg, data_root=ds.data_root) == ds.parquet_path.resolve()


def test_verify_returns_triplet(ds):
    path, manifest, sha = verify_frozen_parquet(_dcfg(ds.sha256), data_root=ds.data_root)
    assert path == ds.parquet_path.resolve() and sha == ds.sha256
    assert manifest["table"]["rows"] == 654


def test_data_module_never_writes():
    src = Path(fdata.__file__).read_text()
    assert "chmod" not in src
