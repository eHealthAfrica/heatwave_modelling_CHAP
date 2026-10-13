"""Per-lead logistic regression and the Phase 11 negative controls (synthetic only)."""
from dataclasses import replace

import numpy as np
import pytest

from heatwave.forecast import targets
from heatwave.forecast.baselines import FitContext
from heatwave.forecast.climatology import Climatology, iso_week_slots
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.features import REGISTRY, build_feature_store
from heatwave.forecast.fixtures import poison_future, synthetic_panel, synthetic_static_sources
from heatwave.forecast.models.logistic import (
    EXCLUDED_FEATURES,
    LogisticForecaster,
    ablation_ladder,
    full_feature_set,
    year_shuffle_map,
)
from heatwave.forecast.static import build_static_table

LEADS = (1, 2)


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
def store(panel, clim, static):
    return build_feature_store(panel, clim, static)


@pytest.fixture(scope="module")
def ctx(panel, static, clim, cfg):
    return FitContext(panel, static, clim, cfg)


@pytest.fixture(scope="module")
def model(store, ctx):
    return LogisticForecaster(store).fit(ctx, LEADS)


@pytest.fixture(scope="module")
def val_rows(panel, cfg):
    return {k: lead_row_index(panel, cfg, k, "validate") for k in LEADS}


def test_ladder_is_cumulative_and_ends_at_full_set():
    ladder = ablation_ladder()
    labels = [lbl for lbl, _ in ladder]
    assert labels == ["season", "+location", "+trend", "+persistence", "+heat", "+land"]
    for (_, a), (_, b) in zip(ladder, ladder[1:]):
        assert set(a) < set(b)
    full = set(full_feature_set())
    assert full == set(REGISTRY.names()) - set(EXCLUDED_FEATURES)
    assert len(full) == len(full_feature_set())  # no duplicates
    assert set(ladder[0][1]) == {"target_season_sin", "target_season_cos"}


def test_rejects_unconfigured_lead(store, ctx):
    with pytest.raises(ValueError):
        LogisticForecaster(store).fit(ctx, (99,))


def test_rejects_lead_feature_and_unknown_feature(store):
    with pytest.raises(ValueError):
        LogisticForecaster(store, feature_names=("lead_weeks",))
    with pytest.raises(KeyError):
        LogisticForecaster(store, feature_names=("no_such_feature",))


def test_valid_probabilities(model, val_rows):
    for k in LEADS:
        w, o = val_rows[k]
        p = model.predict(k, w, o)
        assert p.dtype == np.float32 and p.shape == w.shape
        assert np.isfinite(p).all() and (p > 0).all() and (p < 1).all()


def test_train_only_fit(panel, static, clim, cfg, store, model, ctx):
    """Poisoning every week after the last training target leaves the coefficients unchanged."""
    last = max(int(ctx.train_index(k)[1].max()) + k for k in LEADS)
    poisoned = poison_future(panel, last)
    pstore = build_feature_store(poisoned, clim, static)  # clean climatology, never refit on poison
    pm = LogisticForecaster(pstore).fit(FitContext(poisoned, static, clim, cfg), LEADS)
    for k in LEADS:
        np.testing.assert_allclose(pm.models[k].coef_, model.models[k].coef_, rtol=1e-6, atol=1e-8)
        np.testing.assert_allclose(pm.models[k].intercept_, model.models[k].intercept_, rtol=1e-6, atol=1e-8)


def test_deterministic(store, ctx, model, val_rows):
    again = LogisticForecaster(store).fit(ctx, LEADS)
    w, o = val_rows[1]
    np.testing.assert_array_equal(again.predict(1, w, o), model.predict(1, w, o))


def test_subsample_is_seeded_and_bounded(store, ctx):
    n = ctx.train_index(1)[0].size
    cap = n // 3
    a = LogisticForecaster(store, max_train_rows=cap).fit(ctx, (1,))
    b = LogisticForecaster(store, max_train_rows=cap).fit(ctx, (1,))
    assert a.n_train_[1] == cap
    np.testing.assert_array_equal(a.models[1].coef_, b.models[1].coef_)


def test_coefficients_sorted_by_magnitude(model):
    coefs = model.coefficients(1)
    mags = [abs(c) for _, c in coefs]
    assert mags == sorted(mags, reverse=True)
    assert {n for n, _ in coefs} == set(model.feature_names)


def test_year_shuffle_map_same_slot_other_year_same_split(panel, cfg):
    origins = lead_row_index(panel, cfg, 1, "validate")[1]
    lookup, self_mapped = year_shuffle_map(panel, origins, seed=7)
    uo = np.unique(origins)
    mapped = lookup[uo]
    assert (mapped >= 0).all()
    assert np.isin(mapped, uo).all()  # never leaves the split
    slots = iso_week_slots(panel.week_start)
    assert (slots[mapped] == slots[uo]).all()
    years = np.asarray(panel.week_start).astype("datetime64[D]").astype("datetime64[Y]")
    moved = mapped != uo
    assert (years[mapped][moved] != years[uo][moved]).all()
    assert self_mapped == int((~moved).sum())
    assert self_mapped < uo.size // 10
    outside = np.setdiff1d(np.arange(len(slots)), uo)
    assert (lookup[outside] == -1).all()
    again, _ = year_shuffle_map(panel, origins, seed=7)
    np.testing.assert_array_equal(again, lookup)


def test_shuffled_model_needs_split_origins(store, ctx, val_rows):
    sm = LogisticForecaster(store, name="logistic_shuffled", shuffle_seed=3).fit(ctx, (1,))
    w, o = val_rows[1]
    with pytest.raises(ValueError):
        sm.predict(1, w, o)
    p = sm.predict(1, w, o, split_origins=o)
    assert np.isfinite(p).all()
    with pytest.raises(ValueError):  # origins outside the declared split
        sm.predict(1, w, o, split_origins=o[: len(o) // 2])


def test_shuffle_keeps_labels_and_season(store, ctx, panel):
    """Shuffling replaces panel features only; season features and labels stay those of the true row."""
    sm = LogisticForecaster(store, shuffle_seed=3)
    w, o = ctx.train_index(1)
    fo = sm._feature_origins(panel, 1, o, o)
    X_true = sm._design((panel, ctx.static, ctx.cfg), 1, w, o)
    X_shuf = sm._design((panel, ctx.static, ctx.cfg), 1, w, o, fo)
    names = list(sm.feature_names)
    for nm in ("target_season_sin", "target_season_cos", "lat"):
        j = names.index(nm)
        np.testing.assert_array_equal(X_true[:, j], X_shuf[:, j])
    j = names.index("xhi_anom_lag0")
    assert not np.array_equal(X_true[:, j], X_shuf[:, j])
    assert targets.lead_label(panel, 1)[w, o].shape == w.shape


def test_class_weight_refused(store, ctx):
    from heatwave.forecast.models import logistic as lg

    class _M:
        def params(self, name):
            return {"C": 1.0, "class_weight": "balanced"}

    bad = replace(ctx.cfg, models=_M())
    with pytest.raises(ValueError):
        lg._lr_kwargs(bad)
