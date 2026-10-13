"""LightGBM per lead, CV tuning, OOF calibration and the extrapolation check (synthetic only)."""
from dataclasses import replace

import numpy as np
import pytest

from heatwave.forecast import splits
from heatwave.forecast.baselines import FitContext
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.evaluation.extrapolation import out_of_range_table
from heatwave.forecast.features import build_feature_store
from heatwave.forecast.fixtures import poison_future, synthetic_panel, synthetic_static_sources
from heatwave.forecast.models import lgbm
from heatwave.forecast.models.calibration import CLIP_HI, CLIP_LO, Calibrator, choose_calibrator, lofo_predictions
from heatwave.forecast.models.logistic import full_feature_set
from heatwave.forecast.static import build_static_table

LEADS = (1, 2)
SMALL_GRID = lgbm.GRID[:2]


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


def _params(cfg):
    p = lgbm.grid_params(cfg, "nl7_mcs200")
    p["min_child_samples"] = 20
    return {k: p for k in LEADS}


@pytest.fixture(scope="module")
def model(store, ctx, cfg):
    return lgbm.LightGBMForecaster(store, _params(cfg), {k: 30 for k in LEADS}).fit(ctx, LEADS)


# ----------------------------------------------------------------------------- calibration
def test_calibrators_fix_a_known_bias():
    rng = np.random.default_rng(0)
    true = rng.uniform(0.02, 0.6, 40000)
    y = (rng.uniform(size=true.size) < true).astype(float)
    raw = true * 0.6  # systematic under-prediction, like the prevalence shift
    for m in ("platt", "isotonic"):
        q = Calibrator(m).fit(raw, y).predict(raw)
        assert q.dtype == np.float32 and q.min() >= CLIP_LO and q.max() <= CLIP_HI
        assert abs(q.mean() - y.mean()) < 0.01
        assert np.mean((q - y) ** 2) < np.mean((raw - y) ** 2)


def test_lofo_never_uses_the_held_out_fold():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.05, 0.5, 6000)
    y = (rng.uniform(size=p.size) < p).astype(float)
    fold = np.repeat([0, 1, 2], 2000)
    a = lofo_predictions(p, y, fold, "isotonic")
    y2 = y.copy()
    y2[fold == 0] = 1 - y2[fold == 0]  # change only fold 0's labels
    b = lofo_predictions(p, y2, fold, "isotonic")
    np.testing.assert_array_equal(a[fold == 0], b[fold == 0])
    assert not np.array_equal(a[fold == 1], b[fold == 1])


def test_choose_calibrator_reports_cv_brier():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.05, 0.5, 9000)
    y = (rng.uniform(size=p.size) < np.clip(p * 1.4, 0, 1)).astype(float)
    cal, cv = choose_calibrator(p, y, np.repeat([0, 1, 2], 3000))
    assert set(cv) == {"raw", "platt", "isotonic"}
    assert cal.method == min(("platt", "isotonic"), key=lambda m: cv[m])
    assert cv[cal.method] < cv["raw"]


def test_calibrator_rejects_bad_input():
    with pytest.raises(ValueError):
        Calibrator("beta")
    with pytest.raises(ValueError):
        Calibrator("platt").fit([0.1, np.nan], [0, 1])
    with pytest.raises(RuntimeError):
        Calibrator("platt").predict([0.1])


# ----------------------------------------------------------------------------- lightgbm
def test_class_reweighting_refused(cfg):
    class _M:
        def params(self, name):
            return {"deterministic": True, "is_unbalance": True}

    with pytest.raises(ValueError):
        lgbm.base_params(replace(cfg, models=_M()))


def test_grid_params_keep_yaml_base(cfg):
    p = lgbm.grid_params(cfg, "nl15_mcs2000_l10")
    assert p["num_leaves"] == 15 and p["min_child_samples"] == 2000 and p["reg_lambda"] == 10.0
    assert p["deterministic"] is True and "n_estimators" not in p
    with pytest.raises(KeyError):
        lgbm.grid_params(cfg, "nope")


def test_valid_and_deterministic(model, store, ctx, cfg, panel):
    w, o = lead_row_index(panel, cfg, 1, "validate")
    p = model.predict(1, w, o)
    assert p.dtype == np.float32 and np.isfinite(p).all() and (p > 0).all() and (p < 1).all()
    again = lgbm.LightGBMForecaster(store, _params(cfg), {k: 30 for k in LEADS}).fit(ctx, LEADS)
    np.testing.assert_array_equal(again.predict(1, w, o), p)
    imp = model.gain_importance(1)
    assert {n for n, _ in imp} == set(full_feature_set())


def test_train_only_fit(panel, static, clim, cfg, model, ctx):
    last = max(int(ctx.train_index(k)[1].max()) + k for k in LEADS)
    poisoned = poison_future(panel, last)
    pstore = build_feature_store(poisoned, clim, static)
    pm = lgbm.LightGBMForecaster(pstore, _params(cfg), {k: 30 for k in LEADS}).fit(
        FitContext(poisoned, static, clim, cfg), LEADS)
    w, o = ctx.train_index(1)
    np.testing.assert_array_equal(pm.predict(1, w[:5000], o[:5000]), model.predict(1, w[:5000], o[:5000]))


def test_tune_folds_stay_in_training_era(cfg):
    folds = lgbm.tune_folds(cfg)
    assert [f.year for f in folds] == list(lgbm.TUNE_FOLD_YEARS)
    assert all(f.validate_end <= cfg.splits.train_end for f in folds)
    with pytest.raises(ValueError):
        lgbm.tune_folds(cfg, years=(2016,))


def test_fold_rows_are_disjoint_and_ordered(panel, cfg):
    fold = lgbm.tune_folds(cfg)[0]
    (wf, of), (we, oe), (wv, ov), _ = lgbm._fold_rows(panel, cfg, 1, fold)
    wi = np.asarray(panel.week_index)
    t_fit, t_es, t_oof = wi[of] + 1, wi[oe] + 1, wi[ov] + 1
    assert t_fit.max() + cfg.splits.embargo_weeks < t_es.min()  # embargo between fitting and early stopping
    assert t_es.max() < t_oof.min()  # early stopping ends before the out-of-fold year
    assert (t_oof >= fold.validate_start_index).all() and (t_oof < fold.validate_end_index).all()


@pytest.mark.slow
def test_run_cv_and_select(panel, static, cfg):
    folds = lgbm.tune_folds(cfg, years=(2013, 2014))
    cv = lgbm.run_cv(panel, static, cfg, (1,), grid=SMALL_GRID, folds=folds, max_train_rows=20000, log=lambda m: None)
    d = cv[1]
    assert d["y"].shape == d["fold"].shape == d["logistic"].shape
    assert set(np.unique(d["fold"])) == {2013, 2014}
    for g in SMALL_GRID:
        rec = d["lgb"][g["id"]]
        assert rec["oof"].shape == d["y"].shape and set(rec["fold_brier"]) == {2013, 2014}
    cid, n_est, mean_bs = lgbm.select_config(d)
    assert cid == min(mean_bs, key=mean_bs.get) and n_est >= lgbm.MIN_TREES


# ----------------------------------------------------------------------------- extrapolation
def test_out_of_range_table(store, static, panel, cfg, ctx):
    tr = ctx.train_index(1)[1]
    va = lead_row_index(panel, cfg, 1, "validate")[1]
    names = [n for n in full_feature_set() if n not in ("target_season_sin", "target_season_cos")]
    df = out_of_range_table(store, static, panel, names, tr, va)
    assert set(df["feature"]) == set(names)
    assert (df["frac_out"].between(0, 1)).all()
    assert (df.loc[df["family"] == "static", "frac_out"] == 0).all()
    same = out_of_range_table(store, static, panel, ["xhi_anom_lag0"], tr, tr)
    assert same["frac_out"].iloc[0] == 0
