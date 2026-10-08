"""Synthetic leakage suite (FEAT-04 a-g) with mutation checks proving the checks have teeth."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from heatwave.forecast import splits, targets
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import build_issue_table, lead_row_index, lead_rows
from heatwave.forecast.features import REGISTRY, build_feature_store
from heatwave.forecast.fixtures import synthetic_panel, synthetic_static_sources
from heatwave.forecast.leakage import (
    LeakageError,
    check_poison_invariance,
    check_registry,
    check_row_truncation_invariance,
    check_train_only_statistics,
    check_truncation_invariance,
)
from heatwave.forecast.registry import FeatureSpec
from heatwave.forecast.static import build_static_table

CLIM_END = date(1999, 1, 4)
N_RANDOM_ORIGINS = 50


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel()


@pytest.fixture(scope="module")
def static(panel):
    geo, rows = synthetic_static_sources()
    return build_static_table(geo, rows, panel.wards)


@pytest.fixture(scope="module")
def clim(panel):
    return Climatology.fit(panel, CLIM_END)


@pytest.fixture(scope="module")
def origins(panel):
    T = panel.values.shape[1]
    rng = np.random.default_rng(20260506)
    random_o = rng.choice(np.arange(159, T), size=N_RANDOM_ORIGINS, replace=False)
    forced = [panel.week_pos(lab) for lab in ("1992-W53", "1998-W53", "1999-W01")] + [T - 1] + list(range(6))
    return sorted({int(x) for x in [*random_o, *forced]})


def _builder(clim, static, registry):
    return lambda p: build_feature_store(p, clim, static, registry=registry).arrays


# ----------------------------------------------------------------------------- (a) (b)
def test_a_truncation_invariance(panel, clim, static, origins):
    check_truncation_invariance(_builder(clim, static, REGISTRY), panel, origins)


def test_b_poison_future(panel, clim, static, origins):
    check_poison_invariance(_builder(clim, static, REGISTRY), panel, origins)


# ----------------------------------------------------------------------------- (c)
def test_c_train_only_statistics(panel):
    check_train_only_statistics(lambda p: Climatology.fit(p, CLIM_END), panel, CLIM_END)


def test_c_fold_climatology_train_only(cfg):
    p = synthetic_panel(last_week="2021-W20")
    folds = {f.year: f for f in splits.cv_folds(cfg.splits)}
    for year in (2005, 2014, 2020):
        end = folds[year].climatology_end
        check_train_only_statistics(lambda q, end=end: Climatology.fit(q, end), p, end)


# ----------------------------------------------------------------------------- (d)
def test_d_registry_guard():
    check_registry(REGISTRY)
    assert all(type(s.max_lookahead) is int and s.max_lookahead == 0 for s in REGISTRY)
    assert "lga_average_ward" in REGISTRY
    good = REGISTRY.get("hd_lag0")
    bad = FeatureSpec("leak_x", good.family, "panel", 1, 2, "x", good.fn)
    with pytest.raises(ValueError):
        REGISTRY.copy().register(bad)
    for name in ("year_index", "ward_id", "wardcode", "location", "year"):
        with pytest.raises(ValueError):
            REGISTRY.copy().register(FeatureSpec(name, good.family, "panel", 0, 2, "x", good.fn))
    # check_registry also rejects a spec that bypassed register()
    reg = REGISTRY.copy()
    reg._specs["sneaky"] = FeatureSpec("sneaky", good.family, "panel", 1, 2, "x", good.fn)
    with pytest.raises(LeakageError):
        check_registry(reg)


# ----------------------------------------------------------------------------- (e) mutations
def _lead1(ctx):
    x = ctx.var("heatwave_days").astype(np.float32)
    out = np.full_like(x, np.nan)
    out[:, :-1] = x[:, 1:]
    return out


def _centered(ctx):
    x = ctx.var("mean_heat_index").astype(np.float32)
    out = np.full_like(x, np.nan)
    out[:, 1:-1] = (x[:, :-2] + x[:, 1:-1] + x[:, 2:]) / 3.0
    return out


def _full_mean(ctx):
    x = ctx.var("mean_heat_index").astype(np.float32)
    return np.broadcast_to(x.mean(axis=1, keepdims=True), x.shape).copy()


def _leaky_registry(name, fn):
    reg = REGISTRY.copy()
    reg.register(FeatureSpec(name, "recent_heat", "panel", 0, 1, "injected leak", fn))
    return reg


@pytest.mark.parametrize(
    "name,fn",
    [("leak_hd_lead1", _lead1), ("leak_centered_roll3", _centered), ("leak_full_mean", _full_mean)],
)
def test_e_mutation_caught_by_a_and_b(name, fn, panel, clim, static, origins):
    build = _builder(clim, static, _leaky_registry(name, fn))
    sample = origins[::3]
    with pytest.raises(LeakageError) as ei:
        check_truncation_invariance(build, panel, sample)
    assert name in str(ei.value)
    with pytest.raises(LeakageError) as ei:
        check_poison_invariance(build, panel, sample)
    assert name in str(ei.value)
    # still caught with the documented tolerance fallback
    with pytest.raises(LeakageError):
        check_truncation_invariance(build, panel, sample, atol=1e-6)


def test_e_mutation_lead_shift_caught(panel, clim, static, origins):
    build = _builder(clim, static, _leaky_registry("leak_hd_lead1", _lead1))
    with pytest.raises(LeakageError):
        check_truncation_invariance(build, panel, origins[:8])


def test_e_mutation_centered_caught(panel, clim, static, origins):
    build = _builder(clim, static, _leaky_registry("leak_centered_roll3", _centered))
    with pytest.raises(LeakageError):
        check_poison_invariance(build, panel, origins[:8])


def test_e_mutation_full_mean_caught(panel, clim, static, origins):
    build = _builder(clim, static, _leaky_registry("leak_full_mean", _full_mean))
    with pytest.raises(LeakageError):
        check_truncation_invariance(build, panel, origins[:8])


def test_e_mutation_climatology_fit_past_end_caught(panel):
    def bad_fit(p):  # fits on the whole panel regardless of the train end
        return Climatology.fit(p, date.fromisocalendar(2003, 21, 1))

    with pytest.raises(LeakageError):
        check_train_only_statistics(bad_fit, panel, CLIM_END)


def test_e_mutation_climatology_fit_past_end_by_one_year_caught(panel):
    with pytest.raises(LeakageError):
        check_train_only_statistics(lambda p: Climatology.fit(p, date(2000, 1, 3)), panel, CLIM_END)


# ----------------------------------------------------------------------------- (f)
@pytest.fixture(scope="module")
def long_panel():
    return synthetic_panel(last_week="2021-W20")


@pytest.fixture(scope="module")
def long_setup(long_panel, cfg):
    geo, rows = synthetic_static_sources()
    st = build_static_table(geo, rows, long_panel.wards)
    clim = Climatology.fit(long_panel, cfg.splits.train_end)
    return st, build_feature_store(long_panel, clim, st)


def test_f_split_integrity(long_panel, long_setup, cfg):
    st, store = long_setup
    i_train, _ = splits.cutoff_indices(cfg.splits)
    for lead in cfg.leads:
        frames = {s: lead_rows(long_panel, store, st, cfg, lead, s, feature_names=["hd_lag0"]) for s in splits.SPLIT_NAMES}
        sets = {s: set(df["target_week"]) for s, df in frames.items()}
        assert all(sets.values()), lead
        assert not (sets["train"] & sets["validate"]) and not (sets["train"] & sets["test"])
        assert not (sets["validate"] & sets["test"])
        assert frames["train"]["target_week_index"].max() < i_train - cfg.splits.embargo_weeks
        for df in frames.values():
            starts = pd.to_datetime(df["target_week_start"])
            assert (starts.dt.dayofweek == 0).all()
        w53 = pd.concat(frames.values())
        w53 = w53[w53["target_week"] == "2020-W53"]
        assert len(w53) > 0 and set(w53["split"]) == {"validate"}
    for c in (cfg.splits.train_end, cfg.splits.validate_end):
        assert c.weekday() == 0


def test_f_cv_fold_integrity(long_panel, cfg):
    emb = cfg.splits.embargo_weeks
    folds = splits.cv_folds(cfg.splits)
    assert folds[0].climatology_end.weekday() == 0
    for fold in (folds[0], folds[9], folds[-1]):
        for lead in cfg.leads:
            _, o_tr = lead_row_index(long_panel, cfg, lead, "train", fold=fold)
            _, o_va = lead_row_index(long_panel, cfg, lead, "validate", fold=fold)
            t_tr = np.unique(long_panel.week_index[o_tr] + lead)
            t_va = np.unique(long_panel.week_index[o_va] + lead)
            assert t_tr.size and t_va.size
            assert not (set(t_tr) & set(t_va))
            assert t_tr.max() < t_va.min() - emb
            assert t_tr.max() < fold.validate_start_index - emb


# ----------------------------------------------------------------------------- (g)
def test_g_target_alignment(long_panel, long_setup, cfg):
    st, store = long_setup
    p = long_panel
    iv = list(p.variables).index("heatwave_days")
    wk = pd.DataFrame(
        {
            "ward": np.repeat(np.asarray(p.wards, dtype=object), p.values.shape[1]),
            "week_start": np.tile(pd.to_datetime(p.week_start.astype("datetime64[ns]")), len(p.wards)),
            "hw": (p.values[:, :, iv].ravel() >= 3),
        }
    )
    for lead in cfg.leads:
        df = lead_rows(p, store, st, cfg, lead, "validate", feature_names=["hd_lag0"])
        df = df.sample(min(len(df), 400), random_state=0)
        m = df.assign(week_start=pd.to_datetime(df["target_week_start"])).merge(
            wk, on=["ward", "week_start"], how="left", validate="many_to_one"
        )
        assert m["hw"].notna().all()
        assert (m["heatwave_week"].to_numpy() == m["hw"].to_numpy().astype(int)).all()
        assert (df["target_week_index"] - df["last_obs_week_index"] == lead).all()


# ----------------------------------------------------------------------------- row level
def test_row_level_truncation(static, cfg, panel):
    # the dataset guard needs a climatology fitted at splits.train_end
    c2 = Climatology.fit(panel, cfg.splits.train_end)

    def build_rows(p, origin_positions):
        st = build_feature_store(p, c2, static)
        return build_issue_table(p, st, static, cfg, origin_positions=origin_positions)

    rng = np.random.default_rng(7)
    org = sorted(int(x) for x in rng.choice(np.arange(159, panel.values.shape[1]), 8, replace=False))
    org += [panel.values.shape[1] - 1, panel.week_pos("1998-W53")]
    check_row_truncation_invariance(build_rows, panel, sorted(set(org)))
