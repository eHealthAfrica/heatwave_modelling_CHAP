"""Five baselines: valid probabilities, train-only / as-of fits, hand counts (synthetic only)."""
from dataclasses import replace

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from heatwave.forecast import features, targets
from heatwave.forecast.baselines import (
    BASELINE_REGISTRY,
    TREND_C,
    ClimatologyBaseline,
    DampedPersistenceBaseline,
    FitContext,
    PersistenceBaseline,
    RecentClimatologyBaseline,
    TrendSeasonBaseline,
    fit_baselines,
    train_base_rate,
)
from heatwave.forecast.climatology import Climatology, iso_week_slots, pooling_matrix
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.evaluation.slices import season_of
from heatwave.forecast.fixtures import poison_future, subset_panel, synthetic_panel, synthetic_static_sources
from heatwave.forecast.static import GEOZONES, build_static_table

LEADS = (1, 6)


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(last_week="2027-W10")


@pytest.fixture(scope="module")
def static(panel):
    geo, rows = synthetic_static_sources()
    return build_static_table(geo, rows, panel.wards)


@pytest.fixture(scope="module")
def clim(panel, cfg):
    return Climatology.fit(panel, cfg.splits.train_end)


@pytest.fixture(scope="module")
def ctx(panel, static, clim, cfg):
    return FitContext(panel, static, clim, cfg)


@pytest.fixture(scope="module")
def last_train_target(ctx, cfg):
    return max(int(ctx.train_index(k)[1].max()) + k for k in cfg.leads)


@pytest.fixture(scope="module")
def pctx(panel, static, clim, cfg, last_train_target):
    # poisoned panel, CLEAN climatology object (never refit on poison)
    return FitContext(poison_future(panel, last_train_target), static, clim, cfg)


@pytest.fixture(scope="module")
def fitted(ctx):
    return fit_baselines(ctx)


@pytest.fixture(scope="module")
def pfitted(pctx):
    return fit_baselines(pctx)


@pytest.fixture(scope="module")
def val_rows(panel, cfg):
    return {k: lead_row_index(panel, cfg, k, "validate") for k in cfg.leads}


# ------------------------------------------------------------------ validity
def test_valid_probabilities_on_validate_rows(fitted, val_rows):
    assert tuple(fitted) == tuple(BASELINE_REGISTRY)
    for nm, b in fitted.items():
        for k in LEADS:
            w, o = val_rows[k]
            p = b.predict(k, w, o)
            assert len(p) == len(w) and p.dtype == np.float32, nm
            assert np.isfinite(p).all() and p.min() >= 0 and p.max() <= 1, (nm, k)


def test_unfitted_lead_raises(fitted):
    with pytest.raises(KeyError):
        fitted["persistence"].predict(99, np.array([0]), np.array([10]))


def test_registry_and_order(cfg, fitted):
    assert set(BASELINE_REGISTRY) == set(cfg.baselines.names)
    assert tuple(fitted) == tuple(cfg.baselines.names)
    for nm in features.REGISTRY.names():
        assert "trend_season" not in nm and "year" not in nm


def test_fit_context_guards(panel, static, cfg, clim):
    from dataclasses import replace as rep
    from datetime import timedelta

    bad = rep(clim, fit_end=cfg.splits.train_end - timedelta(weeks=52))
    with pytest.raises(ValueError):
        FitContext(panel, static, bad, cfg)


# ------------------------------------------------------------------ train-only fits
def test_train_only_fits_unchanged_under_poison(fitted, pfitted, val_rows):
    c, pc = fitted["climatology"], pfitted["climatology"]
    p, pp = fitted["persistence"], pfitted["persistence"]
    for k in LEADS:
        assert np.array_equal(c.rate[k], pc.rate[k], equal_nan=True)
        assert np.array_equal(p.table[k], pp.table[k])
        for nm in ("damped_persistence", "trend_season"):
            assert np.array_equal(fitted[nm].coef_[k], pfitted[nm].coef_[k])
            assert np.array_equal(fitted[nm].intercept_[k], pfitted[nm].intercept_[k])
    w, o = val_rows[1]
    # climatology uses no origin-time inputs, so its validation predictions are identical
    assert np.array_equal(fitted["climatology"].predict(1, w, o), pfitted["climatology"].predict(1, w, o))


def test_recent_climatology_as_of(ctx, panel, cfg, val_rows, fitted):
    w, o = val_rows[1]
    base = fitted["recent_climatology"]
    for t in (int(np.unique(o)[5]), int(np.unique(o)[len(np.unique(o)) // 2])):
        pb = RecentClimatologyBaseline().fit(FitContext(poison_future(panel, t), ctx.static, ctx.clim, cfg))
        for k in range(1, 7):
            m = o <= t
            a = base.predict(k, w[m], o[m])
            b = pb.predict(k, w[m], o[m])
            assert np.array_equal(a, b, equal_nan=True)


def test_recent_climatology_formula(ctx, panel, cfg, val_rows, fitted):
    hw = targets.heatwave_week_matrix(panel)
    br, cnt = features.base_rate(hw, panel.week_start, years=cfg.baselines.recent_climatology_years)
    sid = ctx.static.state_id
    p_state = np.empty(br.shape, dtype=np.float64)
    for s in np.unique(sid):
        p_state[sid == s] = br[sid == s].astype(np.float64).mean(axis=0)
    m = cfg.baselines.shrinkage_pseudo_count
    w, o = val_rows[3]
    got = fitted["recent_climatology"].predict(3, w, o)
    c = o + 3
    want = (br[w, c].astype(np.float64) * cnt[c] + m * p_state[w, c]) / (cnt[c] + m)
    np.testing.assert_allclose(got, want, rtol=1e-5, atol=1e-6)
    # m = 0 -> raw base rate at the target column
    cfg0 = replace(cfg, baselines=replace(cfg.baselines, shrinkage_pseudo_count=0))
    ctx0 = FitContext(panel, ctx.static, ctx.clim, cfg0)
    got0 = RecentClimatologyBaseline().fit(ctx0).predict(3, w, o)
    np.testing.assert_allclose(got0, br[w, c], rtol=1e-6)


# ------------------------------------------------------------------ hand counts
def test_climatology_hand_loop(ctx, panel, fitted):
    lead, ward = 2, 0
    _, o = ctx.train_index(lead)
    S = np.unique(o + lead)
    slots = iso_week_slots(panel.week_start).astype(int) - 1
    M = pooling_matrix()
    hw = targets.heatwave_week_matrix(panel)
    assert (slots[S] == 52).any(), "training targets must include a W53"
    for slot in (52, 0, 20):
        num = den = 0
        for c in S:
            if M[slot, slots[c]]:
                num += hw[ward, c]
                den += 1
        got = fitted["climatology"].rate[lead][ward, slot]
        assert got == pytest.approx(num / den)


def test_persistence_hand_count_tiny(panel, static, clim, cfg):
    sub = subset_panel(panel, [0, 3])
    tctx = FitContext(sub, static, clim, cfg)
    lead = 3
    w, o = tctx.train_index(lead)
    hw = targets.heatwave_week_matrix(sub)
    gz = [GEOZONES.index(g) for g in tctx.static.geozone]
    cnt = {}
    for wi, oi in zip(w, o):
        s = ["DJF", "MAM", "JJA", "SON"].index(season_of(sub.week_start[oi + lead : oi + lead + 1])[0])
        key = (int(hw[wi, oi]), s, gz[wi])
        a = cnt.setdefault(key, [0, 0])
        a[0] += int(hw[wi, oi + lead])
        a[1] += 1
    b = PersistenceBaseline().fit(tctx)
    for (y0, s, g), (pos, n) in cnt.items():
        assert b.table[lead][y0, s, g] == pytest.approx((pos + 0.5) / (n + 1))
    # prediction lookup on one row
    p = b.predict(lead, w[:1], o[:1])
    assert 0 < p[0] < 1


# ------------------------------------------------------------------ damped / trend
def test_damped_inputs(fitted):
    d = fitted["damped_persistence"]
    assert d.INPUTS == ("xhi_anom_lag0", "y0", "season_sin", "season_cos")
    assert d.coef_[1].shape == (1, 4)


def test_trend_aggregated_equals_row_level(ctx, fitted):
    t = fitted["trend_season"]
    for lead in LEADS:
        w, o = ctx.train_index(lead)
        cols = o + lead
        X = t._design(cols, t.gz[w])
        y = targets.heatwave_week_matrix(ctx.panel)[w, cols].astype(int)
        ref = LogisticRegression(C=TREND_C, solver="lbfgs", max_iter=1000).fit(X, y)
        np.testing.assert_allclose(t.coef_[lead], ref.coef_, atol=1e-4)
        np.testing.assert_allclose(t.intercept_[lead], ref.intercept_, atol=1e-4)


def test_train_base_rate(ctx):
    for lead in LEADS:
        w, o = ctx.train_index(lead)
        y = targets.lead_label(ctx.panel, lead)[w, o]
        assert train_base_rate(ctx, lead) == pytest.approx(float(y.mean()))
