"""Dataset assembly: issue rows, per-lead rows, warm-up, embargo, fit-range guard, fold stores, cache."""
import json
from datetime import date

import numpy as np
import pytest

from heatwave.forecast import splits, targets, weeks
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import (
    LABEL_COLUMN,
    TIMING_COLUMNS,
    build_fold_store,
    build_issue_table,
    feature_cache_dir,
    lead_row_index,
    lead_rows,
    load_feature_store,
    save_feature_store,
    warmup_first_position,
)
from heatwave.forecast.features import REGISTRY, build_feature_store
from heatwave.forecast.fixtures import poison_future, synthetic_panel, synthetic_static_sources
from heatwave.forecast.static import build_static_table


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(last_week="2021-W20")


@pytest.fixture(scope="module")
def static(panel):
    geo, rows = synthetic_static_sources()
    return build_static_table(geo, rows, panel.wards)


@pytest.fixture(scope="module")
def clim(panel, cfg):
    return Climatology.fit(panel, cfg.splits.train_end)


@pytest.fixture(scope="module")
def store(panel, clim, static):
    return build_feature_store(panel, clim, static)


def test_warmup_position(panel):
    p = warmup_first_position(panel)
    assert p == 159
    assert panel.week_labels[p] == "1994-W04"


def test_train_rows_embargo_and_warmup(panel, cfg):
    i_train, _ = splits.cutoff_indices(cfg.splits)
    n = len(panel.wards)
    for lead in cfg.leads:
        w, o = lead_row_index(panel, cfg, lead, "train")
        assert len(w) == len(o)
        tgt = panel.week_index[o] + lead
        assert (tgt < i_train - cfg.splits.embargo_weeks).all()
        assert (o >= 159).all()
        assert (o + lead <= panel.values.shape[1] - 1).all()
        assert len(w) % n == 0
    w, o = lead_row_index(panel, cfg, 1, "train", drop_warmup=False)
    assert (o < 159).any()


def test_lead_rows_columns_and_values(panel, store, static, cfg):
    df = lead_rows(panel, store, static, cfg, 3, "train")
    assert len(df) > 0
    for c in ("ward", *TIMING_COLUMNS, LABEL_COLUMN, "split"):
        assert c in df.columns
    assert df.columns.is_unique
    for nm in REGISTRY.names():
        assert nm in df.columns, nm
    assert (df["lead_weeks"] == 3).all()
    assert (df["effective_days_ahead"] == 7 * 3 - 6).all()
    assert df[LABEL_COLUMN].dtype == np.int8
    assert set(df["split"]) == {"train"}
    for nm in ("mhi_anom_lag0", "lat", "target_season_sin"):
        assert df[nm].dtype == np.float32
    lab = targets.lead_label(panel, 3)
    for row in df.sample(20, random_state=0).itertuples():
        wp = panel.ward_pos(row.ward)
        op = panel.week_pos(row.last_obs_week)
        assert getattr(row, LABEL_COLUMN) == lab[wp, op]
        assert row.target_week_index == row.last_obs_week_index + 3


def test_validate_and_test_rows(panel, store, static, cfg):
    v = lead_rows(panel, store, static, cfg, 2, "validate")
    ts = v["target_week_start"].to_numpy().astype("datetime64[D]")
    assert (ts >= np.datetime64("2014-12-29")).all() and (ts < np.datetime64("2021-01-04")).all()
    assert "2020-W53" in set(v["target_week"])
    assert set(v["split"]) == {"validate"}
    t = lead_rows(panel, store, static, cfg, 2, "test")
    assert len(t) > 0 and set(t["split"]) == {"test"}


def test_issue_table(panel, store, static, cfg):
    T = panel.values.shape[1]
    origins = [200, 300, T - 1]
    df = build_issue_table(panel, store, static, cfg, origin_positions=origins)
    assert len(df) == len(panel.wards) * 3
    for k in cfg.leads:
        for pre in ("heatwave_week_l", "target_week_l", "split_l", "has_label_l"):
            assert f"{pre}{k}" in df.columns
    last = df[df["last_obs_week_index"] == panel.week_index[T - 1]]
    assert last["heatwave_week_l1"].isna().all()
    assert not last["has_label_l1"].any()
    assert (last["target_week_l1"] == weeks.index_to_label(int(panel.week_index[T - 1]) + 1)).all()
    mid = df[df["last_obs_week_index"] == panel.week_index[200]]
    assert mid["has_label_l6"].all() and not mid["heatwave_week_l6"].isna().any()
    with pytest.raises(ValueError):
        build_issue_table(panel, store, static, cfg, origin_positions=[T])


def test_fit_end_guard_dates(panel, static, cfg, store):
    # equal case: ISO string fit_end vs date train_end
    assert isinstance(store.clim_fit_range["fit_end"], str)
    assert cfg.splits.train_end == date(2014, 12, 29)
    lead_rows(panel, store, static, cfg, 1, "train")
    # unequal case
    other = build_feature_store(panel, Climatology.fit(panel, date(1999, 1, 4)), static)
    for split in ("train", "validate", "test"):
        with pytest.raises(ValueError):
            lead_rows(panel, other, static, cfg, 1, split)


def test_errors(panel, store, static, cfg):
    with pytest.raises(KeyError):
        lead_rows(panel, store, static, cfg, 1, "train", feature_names=["nope"])
    for lead in (0, 7):
        with pytest.raises(ValueError):
            lead_rows(panel, store, static, cfg, lead, "train")
    with pytest.raises(ValueError):
        lead_rows(panel, store, static, cfg, 1, "bogus")


def test_fold_store_and_guard(panel, static, cfg, store):
    fold = [f for f in splits.cv_folds(cfg.splits) if f.year == 2010][0]
    clim, fstore = build_fold_store(panel, static, fold)
    assert clim.fit_end == fold.climatology_end
    assert clim.last_week_start < fold.validate_start
    df = lead_rows(panel, fstore, static, cfg, 2, "validate", fold=fold)
    assert len(df) > 0
    assert (df["target_week_index"] >= fold.validate_start_index).all()
    assert (df["target_week_index"] < fold.validate_end_index).all()
    tr = lead_rows(panel, fstore, static, cfg, 2, "train", fold=fold)
    assert (tr["target_week_index"] < fold.train_max_target_exclusive).all()
    with pytest.raises(ValueError):
        lead_rows(panel, store, static, cfg, 2, "validate", fold=fold)
    with pytest.raises(ValueError):
        lead_rows(panel, fstore, static, cfg, 2, "train")


def test_fold_poison_and_difference(panel, static, cfg):
    folds = {f.year: f for f in splits.cv_folds(cfg.splits)}
    f10, f05 = folds[2010], folds[2005]
    c10 = Climatology.fit(panel, f10.climatology_end)
    pos = f10.validate_start_index - int(panel.week_index[0]) - 1
    c10p = Climatology.fit(poison_future(panel, pos), f10.climatology_end)
    assert np.array_equal(c10.mean, c10p.mean) and np.array_equal(c10.std, c10p.std)
    c05 = Climatology.fit(panel, f05.climatology_end)
    assert not np.array_equal(c10.mean, c05.mean)


def test_cache_dir_and_roundtrip(panel, clim, store, cfg, tmp_path):
    d = feature_cache_dir(cfg, panel, data_root=tmp_path)
    from heatwave.forecast.config import config_hash

    assert d == (tmp_path / "forecast_cache" / panel.sha256[:8] / config_hash(cfg)[:8]).resolve()
    with pytest.raises(ValueError):
        feature_cache_dir(cfg, panel, data_root=load_repo_root() / "somewhere")
    with pytest.raises(ValueError):
        feature_cache_dir(cfg, panel, data_root=tmp_path / cfg.data.frozen_subdir / "x")

    sub = save_feature_store(store, clim, d, registry_names=REGISTRY.names())
    assert str(sub).startswith(str(d))
    loaded = load_feature_store(d, panel, clim, names=store.names)
    assert loaded is not None
    for nm in store.names:
        assert np.array_equal(loaded[nm], store[nm], equal_nan=True)
        assert not loaded[nm].flags.writeable
    # mismatches -> miss
    assert load_feature_store(d, panel, clim, names=store.names[:-1]) is None
    other_clim = Climatology.fit(panel, date(1999, 1, 4))
    assert load_feature_store(d, panel, other_clim, names=store.names) is None
    p2 = poison_future(panel, 100)
    assert load_feature_store(d, p2, clim, names=store.names) is None
    from heatwave.forecast.fixtures import subset_panel

    assert load_feature_store(d, subset_panel(panel, [0, 1]), clim, names=store.names) is None
    # tampered meta -> miss
    meta = sub / "store_meta.json"
    m = json.loads(meta.read_text())
    m["data_sha256"] = "0" * 64
    meta.write_text(json.dumps(m))
    assert load_feature_store(d, panel, clim, names=store.names) is None


def load_repo_root():
    from heatwave.forecast.artifacts import REPO_ROOT

    return REPO_ROOT
