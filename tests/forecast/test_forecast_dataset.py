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


# --------------------------------------------------------------------------- review fixes
def test_wr01_store_bound_to_panel(panel, static, cfg, store):
    # same wards, same climatology fit_end, but built from a different (poisoned) panel
    bad_panel = poison_future(panel, 100)
    bad_store = build_feature_store(bad_panel, Climatology.fit(bad_panel, cfg.splits.train_end), static)
    assert tuple(bad_store.wards) == tuple(panel.wards)
    assert bad_store.clim_fit_range["fit_end"] == store.clim_fit_range["fit_end"]
    with pytest.raises(ValueError, match="different panel"):
        lead_rows(panel, bad_store, static, cfg, 1, "train")
    with pytest.raises(ValueError, match="different panel"):
        build_issue_table(panel, bad_store, static, cfg, origin_positions=[200])
    # a store whose week axis / shape does not match the panel is rejected too
    from dataclasses import replace

    short = replace(store, week_index=store.week_index[:-1])
    with pytest.raises(ValueError, match="week axis"):
        lead_rows(panel, short, static, cfg, 1, "train")
    arrays = {k: v[:, :-1] for k, v in store.arrays.items()}
    shaped = replace(store, arrays=arrays)
    with pytest.raises(ValueError, match="shape"):
        lead_rows(panel, shaped, static, cfg, 1, "train")


def test_wr04_panel_past_test_years(cfg, static):
    from heatwave.forecast import report

    ext = synthetic_panel(last_week="2027-W10")
    c = Climatology.fit(ext, cfg.splits.train_end)
    st = build_feature_store(ext, c, static)
    T = ext.values.shape[1]
    # strict assign_split still rejects; the lenient form labels the overflow
    with pytest.raises(ValueError):
        splits.assign_split(ext.week_index, cfg.splits)
    df = build_issue_table(ext, st, static, cfg, origin_positions=[200, T - 30, T - 1])
    last = df[df["last_obs_week_index"] == ext.week_index[T - 1]]
    assert (last["split_l1"] == "beyond_test").all() and not last["has_label_l1"].any()
    assert set(df["split_l1"]) <= {"train", "validate", "test", "beyond_test", "embargoed", "warmup"}
    # the report builders work and report the overflow rather than raising
    tabs = report.prevalence_tables(ext, static, cfg)
    assert "beyond_test" in set(tabs["by_split"]["split"])
    rc = report.row_count_table(ext, cfg)
    assert (rc["rows"] > 0).any()
    # modelling rows never include beyond_test targets
    hi = splits._bounds(cfg.splits)[1]
    for s in ("train", "validate", "test"):
        w, o = lead_row_index(ext, cfg, 6, s)
        assert (ext.week_index[o] + 6 < hi).all()
    assert (lead_rows(ext, st, static, cfg, 6, "test")["split"] == "test").all()


def test_wr02_issue_split_reflects_embargo_and_warmup(panel, store, static, cfg):
    i_train, _ = splits.cutoff_indices(cfg.splits)
    first = int(panel.week_index[0])
    emb_origin = i_train - 1 - 3 - first  # lead-3 target is the last training week -> embargoed
    ok_origin = i_train - cfg.splits.embargo_weeks - 3 - 1 - first  # last kept training target
    origins = [100, 158, 159, ok_origin, emb_origin]
    df = build_issue_table(panel, store, static, cfg, origin_positions=origins)

    def split_at(o, k=3):
        return set(df.loc[df["last_obs_week_index"] == panel.week_index[o], f"split_l{k}"])

    assert split_at(100) == {"warmup"} and split_at(158) == {"warmup"}
    assert split_at(159) == {"train"}
    assert split_at(ok_origin) == {"train"}
    assert split_at(emb_origin) == {"embargoed"}
    # consistent with the row selector for every lead
    for k in cfg.leads:
        w, o = lead_row_index(panel, cfg, k, "train")
        sel = set(zip(w.tolist(), o.tolist()))
        all_o = list(range(150, panel.values.shape[1] - 7))
        d = build_issue_table(panel, store, static, cfg, origin_positions=all_o, ward_positions=[0, 2])
        wpos = np.tile([0, 2], len(all_o))
        opos = np.repeat(all_o, 2)
        tr = (d[f"split_l{k}"] == "train").to_numpy() & d[f"has_label_l{k}"].to_numpy()
        got = set(zip(wpos[tr].tolist(), opos[tr].tolist()))
        assert got == {p for p in sel if p[0] in (0, 2) and p[1] in set(all_o)}


def test_wr03_compact_dtypes_and_row_guard(panel, store, static, cfg):
    import pandas as pd

    df = lead_rows(panel, store, static, cfg, 2, "train")
    assert not any(pd.api.types.is_object_dtype(t) for t in df.dtypes)
    for c in ("ward", "last_obs_week", "target_week", "split"):
        assert isinstance(df[c].dtype, pd.CategoricalDtype), c
    assert df["split"].dtype.categories.tolist()[:3] == ["train", "validate", "test"]
    assert set(df["split"]) == {"train"}
    iss = build_issue_table(panel, store, static, cfg, origin_positions=[200, 300])
    assert not any(pd.api.types.is_object_dtype(t) for t in iss.dtypes)
    for k in cfg.leads:
        assert isinstance(iss[f"split_l{k}"].dtype, pd.CategoricalDtype)
        assert isinstance(iss[f"target_week_l{k}"].dtype, pd.CategoricalDtype)
    # compact: far below one UCS4 string (32 bytes) per split cell
    assert iss[[f"split_l{k}" for k in cfg.leads]].memory_usage(deep=True).sum() < len(iss) * 6 * 2 + 4096
    # full-panel tables are guarded
    with pytest.raises(ValueError, match="max_rows"):
        build_issue_table(panel, store, static, cfg, origin_positions=range(panel.values.shape[1]), max_rows=1000)
    ok = build_issue_table(panel, store, static, cfg, origin_positions=[200], max_rows=len(panel.wards))
    assert len(ok) == len(panel.wards)


def test_wr06_custom_registry(panel, clim, static, cfg):
    import numpy as np
    from heatwave.forecast.registry import FeatureSpec

    reg = REGISTRY.copy()
    reg.register(
        FeatureSpec(
            name="hd_double_lag0", family="recent_heat", kind="panel", max_lookahead=0, window_weeks=1,
            description="test feature", fn=lambda ctx: 2.0 * ctx.var("heatwave_days"),
        )
    )
    cstore = build_feature_store(panel, clim, static, registry=reg)
    assert "hd_double_lag0" in cstore
    # the global registry does not know the feature: it must be rejected, not silently dropped
    with pytest.raises(KeyError):
        lead_rows(panel, cstore, static, cfg, 2, "train", feature_names=["hd_double_lag0"])
    df = lead_rows(panel, cstore, static, cfg, 2, "train", registry=reg)
    assert "hd_double_lag0" in df.columns and set(REGISTRY.names()) <= set(df.columns)
    hd = panel.values[:, :, list(panel.variables).index("heatwave_days")]
    wp = np.array([panel.ward_pos(w) for w in df["ward"]])
    op = np.array([panel.week_pos(w) for w in df["last_obs_week"]])
    assert np.array_equal(df["hd_double_lag0"].to_numpy(), 2.0 * hd[wp, op])
    iss = build_issue_table(panel, cstore, static, cfg, origin_positions=[200], registry=reg)
    assert "hd_double_lag0" in iss.columns
    with pytest.raises(KeyError):
        build_issue_table(panel, cstore, static, cfg, origin_positions=[200], feature_names=["hd_double_lag0"])
