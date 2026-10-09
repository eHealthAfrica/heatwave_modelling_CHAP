"""Stored predictions: schema, safe paths, atomic writer, lock-aware loader, alignment."""
import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from heatwave.forecast import targets, testlock
from heatwave.forecast.artifacts import REPO_ROOT
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.evaluation import predictions as P
from heatwave.forecast.fixtures import synthetic_panel

RUN_ID = "20270101T000000Z_abcdef12"
SHA = "a" * 64


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(last_week="2027-W10")


def _rows(panel, cfg, lead, split, n=24):
    w, o = lead_row_index(panel, cfg, lead, split)
    return w[:n], o[:n]


def _meta(split="validate", lead=2, predictor="damped_persistence"):
    return P.PredictionMeta(RUN_ID, SHA, SHA, predictor, lead, split)


def _frame(panel, cfg, split="validate", lead=2, predictor="damped_persistence", n=24):
    w, o = _rows(panel, cfg, lead, split, n)
    p = np.linspace(0, 1, len(w), dtype=np.float32)
    return P.build_frame(panel, cfg, predictor, lead, split, w, o, p), (w, o)


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "forecast_runs" / RUN_ID
    d.mkdir(parents=True)
    return d


def test_build_frame_schema(panel, cfg):
    df, (w, o) = _frame(panel, cfg)
    assert tuple(df.columns) == P.COLUMNS
    for c, dt in P.DTYPES.items():
        if dt == "category":
            assert isinstance(df[c].dtype, pd.CategoricalDtype)
        else:
            assert str(df[c].dtype) == dt
    assert np.array_equal(df["y"].to_numpy(), targets.lead_label(panel, 2)[w, o].astype(np.int8))
    assert (df["target_week_index"] == df["origin_week_index"] + 2).all()
    assert df["fold"].isna().all()


def test_build_frame_rejects_bad_p(panel, cfg):
    w, o = _rows(panel, cfg, 2, "validate", 4)
    for p in ([0.1, np.nan, 0.2, 0.3], [0.1, 1.5, 0.2, 0.3], [0.1, 0.2]):
        with pytest.raises(ValueError):
            P.build_frame(panel, cfg, "x", 2, "validate", w, o, p)


def test_build_frame_test_split_locked(panel, cfg, testlock_root):
    w, o = _rows(panel, cfg, 2, "test", 4)
    with pytest.raises(testlock.TestLockError):
        P.build_frame(panel, cfg, "x", 2, "test", w, o, np.zeros(4))
    assert testlock.read_log(testlock_root)[-1]["outcome"] == "refused"


def test_prediction_path(run_dir, tmp_path):
    assert P.prediction_path(run_dir, "damped_persistence", 1, "validate") == (
        run_dir / "predictions" / "damped_persistence_L1_validate.parquet"
    )
    for args in [("../x", 1, "validate"), ("A B", 1, "validate"), ("ok", 1, "holdout")]:
        with pytest.raises(ValueError):
            P.prediction_path(run_dir, *args)
    bad = [
        tmp_path / "forecast_runs" / "notarun",
        tmp_path / "other" / RUN_ID,
        REPO_ROOT / "forecast_runs" / RUN_ID,
        tmp_path / "frozen" / "forecast_runs" / RUN_ID,
    ]
    for b in bad:
        with pytest.raises(ValueError):
            P.prediction_path(b, "ok", 1, "validate")


def test_write_and_read_metadata(panel, cfg, run_dir):
    df, _ = _frame(panel, cfg)
    path = P.write_predictions(df, _meta(), run_dir)
    assert not list(run_dir.rglob("*.tmp"))
    back = pq.read_table(path).to_pandas()
    assert str(back["p"].dtype) == "float32" and str(back["fold"].dtype) == "Int8"
    m = P.read_metadata(path)
    assert m == _meta()
    assert m.threshold is None and m.schema_version == 1


def test_read_metadata_rejects(panel, cfg, run_dir, tmp_path):
    df, _ = _frame(panel, cfg)
    path = P.write_predictions(df, _meta(), run_dir)
    table = pq.read_table(path)
    base = json.loads(pq.read_schema(path).metadata[P.METADATA_KEY])

    def variant(name, d):
        md = {} if d is None else {P.METADATA_KEY: json.dumps(d).encode()}
        out = tmp_path / name
        pq.write_table(table.replace_schema_metadata(md), out)
        return out

    for name, d in [
        ("nokey.parquet", None),
        ("badsha.parquet", {**base, "config_sha256": "G" * 64}),
        ("badver.parquet", {**base, "schema_version": 2}),
    ]:
        with pytest.raises(ValueError):
            P.read_metadata(variant(name, d))


def test_loader_validate_and_lock(panel, cfg, run_dir, testlock_root, monkeypatch):
    df, _ = _frame(panel, cfg)
    path = P.write_predictions(df, _meta(), run_dir)
    out, meta = P.load_predictions(path, cfg)
    assert meta.split == "validate" and len(out) == len(df)
    assert testlock.read_log(testlock_root) == []

    # a test-split file (built with the lock stubbed open)
    with monkeypatch.context() as mp:
        mp.setattr(testlock, "require_open", lambda *a, **k: {})
        tdf, _ = _frame(panel, cfg, split="test", n=4)
    tpath = P.write_predictions(tdf, _meta("test"), run_dir)
    with pytest.raises(testlock.TestLockError):
        P.load_predictions(tpath, cfg)

    # tampered: metadata says validate, rows say test
    t = pa.Table.from_pandas(tdf, preserve_index=False).replace_schema_metadata(
        {P.METADATA_KEY: json.dumps(P.asdict(_meta("validate"))).encode()}
    )
    tam = run_dir / "predictions" / "tampered.parquet"
    pq.write_table(t, tam)
    with pytest.raises(testlock.TestLockError):
        P.load_predictions(tam, cfg)
    log = testlock.read_log(testlock_root)
    assert [r["outcome"] for r in log] == ["refused", "refused"]

    # open lock: the test file loads
    with monkeypatch.context() as mp:
        mp.setattr(testlock, "require_open", lambda *a, **k: {})
        got, m = P.load_predictions(tpath, cfg)
    assert m.split == "test" and len(got) == 4


def test_loader_rejects_bad_values(panel, cfg, run_dir):
    df, _ = _frame(panel, cfg)
    path = P.write_predictions(df, _meta(), run_dir)
    md = pq.read_schema(path).metadata
    bad = df.copy()
    bad["y"] = bad["y"].to_numpy().copy()
    bad.loc[bad.index[0], "y"] = 2
    bp = run_dir / "predictions" / "bad_y.parquet"
    pq.write_table(pa.Table.from_pandas(bad, preserve_index=False).replace_schema_metadata(md), bp)
    with pytest.raises(ValueError):
        P.load_predictions(bp, cfg)
    other = run_dir / "predictions" / "wrong_lead.parquet"
    md2 = {P.METADATA_KEY: json.dumps(P.asdict(_meta(lead=3))).encode()}
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False).replace_schema_metadata(md2), other)
    with pytest.raises(ValueError):
        P.load_predictions(other, cfg)


def test_align(panel, cfg):
    ref, _ = _frame(panel, cfg)
    cand = ref.sample(frac=1.0, random_state=0).reset_index(drop=True)
    r, c = P.align(ref, cand)
    assert np.array_equal(ref["ward"].cat.codes.to_numpy()[r], cand["ward"].cat.codes.to_numpy()[c])
    assert np.array_equal(ref["origin_week_index"].to_numpy()[r], cand["origin_week_index"].to_numpy()[c])
    with pytest.raises(ValueError):
        P.align(ref, cand.iloc[:-1])
    shifted = cand.copy()
    shifted["origin_week_index"] = (shifted["origin_week_index"] + 1).astype("int16")
    with pytest.raises(ValueError):
        P.align(ref, shifted)
    cats = cand.copy()
    cats["ward"] = cats["ward"].cat.rename_categories(lambda s: s + "_x")
    with pytest.raises(ValueError):
        P.align(ref, cats)
    flipped = cand.copy()
    flipped["y"] = (1 - flipped["y"]).astype("int8")
    with pytest.raises(ValueError):
        P.align(ref, flipped)


# ------------------------------------------------------- review WR-01: date-based protection
def _tampered_cfg(cfg):
    """A config whose splits relabel 2021-2026 as validation (bypasses SplitsConfig validation)."""
    import copy
    from datetime import date

    s = copy.copy(cfg.splits)
    object.__setattr__(s, "validate_years", (2015, 2026))
    object.__setattr__(s, "test_years", (2027, 2027))
    object.__setattr__(s, "validate_end", date(2027, 1, 4))
    out = copy.copy(cfg)
    object.__setattr__(out, "splits", s)
    return out


def test_relabelled_config_cannot_select_protected_rows(panel, cfg, testlock_root):
    bad = _tampered_cfg(cfg)
    with pytest.raises(testlock.TestLockError):
        lead_row_index(panel, bad, 2, "validate")
    assert testlock.read_log(testlock_root)[-1]["outcome"] == "refused"


def test_relabelled_config_cannot_build_validate_frame(panel, cfg, testlock_root):
    bad = _tampered_cfg(cfg)
    w, o = lead_row_index(panel, cfg, 2, "test")  # index-only; the real config
    with pytest.raises(testlock.TestLockError):
        P.build_frame(panel, bad, "x", 2, "validate", w[:4], o[:4], np.zeros(4))
    assert testlock.read_log(testlock_root)[-1]["outcome"] == "refused"
