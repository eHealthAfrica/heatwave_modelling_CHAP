"""Unit tests for heatwave.forecast.evaluation.metrics (EVAL-02)."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from sklearn.calibration import calibration_curve
from sklearn.metrics import brier_score_loss, roc_auc_score

from heatwave.forecast.evaluation import metrics as M


def _rng(seed=0):
    return np.random.default_rng(seed)


def test_brier_hand_and_sklearn():
    assert M.brier([0.2, 0.8], [0, 1]) == pytest.approx(0.04)
    r = _rng()
    p = r.random(5000)
    y = (r.random(5000) < p).astype(float)
    assert M.brier(p, y) == pytest.approx(brier_score_loss(y, y_proba=p), rel=1e-12)


def test_bss():
    assert M.brier_skill_score(0.09, 0.12) == pytest.approx(0.25)
    assert M.brier_skill_score(0.1, 0.1) == 0.0
    assert np.isnan(M.brier_skill_score(0.1, 0.0))


@pytest.mark.parametrize("bad", ["nan", "range", "y", "len"])
def test_input_validation(bad):
    p, y = np.array([0.1, 0.5]), np.array([0, 1])
    if bad == "nan":
        p = np.array([np.nan, 0.5])
    elif bad == "range":
        p = np.array([1.2, 0.5])
    elif bad == "y":
        y = np.array([0, 2])
    else:
        y = np.array([0, 1, 1])
    with pytest.raises(ValueError):
        M.brier(p, y)


def test_murphy_two_valued_exact():
    r = _rng(1)
    p = r.choice([0.1, 0.3], size=1000)
    y = (r.random(1000) < p).astype(float)
    d = M.murphy(p, y, k=10)
    assert abs(d.residual) < 1e-12 and d.n_bins == 2


def test_murphy_continuous():
    r = _rng(2)
    p = r.beta(2, 14, size=200_000)
    y = (r.random(p.size) < p).astype(float)
    assert abs(M.murphy(p, y, k=10).residual) < 1e-3


def test_murphy_tied_three_valued():
    r = _rng(3)
    p = r.choice([0.05, 0.2, 0.6], size=20_000, p=[0.9, 0.05, 0.05])
    y = (r.random(p.size) < p).astype(float)
    d = M.murphy(p, y, k=10)
    assert abs(d.residual) < 1e-12 and d.n_bins == 3


def test_reliability_matches_sklearn():
    r = _rng(4)
    p = r.random(20_000)
    y = (r.random(p.size) < p).astype(float)
    t = M.reliability_table(p, y, k=10)
    frac, mean_p = calibration_curve(y, p, n_bins=10, strategy="quantile")
    assert len(t) == len(frac)
    np.testing.assert_allclose(t["obs_freq"], frac, atol=1e-12)
    np.testing.assert_allclose(t["mean_p"], mean_p, atol=1e-12)
    assert t["n"].sum() == p.size


def test_stratified_auc():
    r = _rng(5)
    p = r.random(600)
    y = (r.random(600) < p).astype(float)
    s = np.array(["a"] * 300 + ["b"] * 299 + ["c"])
    out = M.stratified_auc(p, y, s)
    assert list(out["stratum"]) == ["a", "b", "c"]
    assert out["auc"].iloc[0] == pytest.approx(roc_auc_score(y[:300], p[:300]))
    assert np.isnan(out["auc"].iloc[2])  # single-row stratum has one class
    assert not out["stratum"].astype(str).str.lower().isin(["pooled", "all"]).any()


def test_prf():
    p = np.array([0.9, 0.8, 0.4, 0.1, 0.6])
    y = np.array([1, 0, 1, 0, 1])
    d = M.prf_at_threshold(p, y, threshold=0.5)
    assert d["threshold"] == 0.5 and (d["tp"], d["fp"], d["fn"]) == (2, 1, 1)
    assert d["precision"] == pytest.approx(2 / 3) and d["recall"] == pytest.approx(2 / 3)
    assert d["predicted_positive_rate"] == pytest.approx(0.6)
    assert d["prevalence"] == pytest.approx(0.6) and d["n"] == 5
    assert d["f1"] == pytest.approx(2 / 3)


def test_citl():
    p = np.array([0.2, 0.4, 0.6, 0.8])
    y = np.array([0, 0, 1, 1])
    yr = np.array([2020, 2020, 2021, 2021])
    out = M.calibration_in_the_large(p, y, yr)
    np.testing.assert_allclose(out["citl"], [0.3, -0.3])
    assert list(out.columns) == ["year", "n", "mean_p", "obs", "citl"]


def test_no_accuracy_no_pooled_auc():
    src = inspect.getsource(M).lower()
    assert "accuracy" not in src
    assert not [n for n in dir(M) if "accuracy" in n.lower() or "pooled" in n.lower()]


# ---------------------------------------------------------- sufficient stats
def _setup(n=20_000, w=40, k=10, h=1000, seed=7, thr=0.3):
    r = _rng(seed)
    p = r.beta(0.7, 3, size=n)
    y = (r.random(n) < p).astype(float)
    wk = r.integers(0, w, size=n)
    edges = M.quantile_edges(p, k)
    ae = np.linspace(0, 1, h + 1)
    st = M.week_stats(p, y, wk, w, edges=edges, auc_edges=ae, threshold=thr)
    return p, y, wk, edges, st, thr


def test_unit_weights_reproduce_point_metrics():
    p, y, wk, edges, st, thr = _setup()
    c = np.ones(40)
    assert M.stats_brier(st, c) == pytest.approx(M.brier(p, y), rel=1e-12)
    assert M.stats_base_rate(st, c) == pytest.approx(y.mean(), rel=1e-12)
    assert M.stats_mean_p(st, c) == pytest.approx(p.mean(), rel=1e-12)
    m = M.murphy(p, y, edges=edges)
    d = M.stats_murphy(st, c)
    assert d["rel"] == pytest.approx(m.rel, abs=1e-12)
    assert d["res"] == pytest.approx(m.res, abs=1e-12)
    assert d["unc"] == pytest.approx(m.unc, abs=1e-12)
    pr = M.prf_at_threshold(p, y, thr)
    s = M.stats_prf(st, c)
    for key in ("precision", "recall", "f1"):
        assert s[key] == pytest.approx(pr[key], abs=1e-12)
    assert abs(M.stats_auc(st, c) - M.auc(p, y)) < 1e-3


def test_replicate_shapes_and_empty():
    _, _, _, _, st, _ = _setup()
    r = _rng(9)
    c = r.integers(0, 3, size=(5, 40)).astype(float)
    c[2] = 0.0
    for out in (M.stats_brier(st, c), M.stats_auc(st, c), M.stats_base_rate(st, c)):
        assert out.shape == (5,) and np.isnan(out[2]) and not np.isnan(out[0])
    assert np.isnan(M.stats_murphy(st, c)["rel"][2])
    assert np.isnan(M.stats_prf(st, c)["f1"][2])


def test_week_id_out_of_range():
    p = np.array([0.1, 0.2])
    y = np.array([0, 1])
    e = np.linspace(0, 1, 3)
    with pytest.raises(ValueError):
        M.week_stats(p, y, np.array([0, 5]), 3, edges=e, auc_edges=e, threshold=0.5)
    with pytest.raises(ValueError):
        M.week_stats(p, y, np.array([-1, 0]), 3, edges=e, auc_edges=e, threshold=0.5)


def test_zero_weight_week_excluded():
    p, y, wk, edges, st, thr = _setup()
    c = np.ones(40)
    c[3] = 0.0
    keep = wk != 3
    st2 = M.week_stats(p[keep], y[keep], wk[keep], 40, edges=edges, auc_edges=st.auc_edges, threshold=thr)
    ones = np.ones(40)
    assert M.stats_brier(st, c) == pytest.approx(M.stats_brier(st2, ones), rel=1e-12)
    assert M.stats_auc(st, c) == pytest.approx(M.stats_auc(st2, ones), rel=1e-12)
    assert M.stats_murphy(st, c)["rel"] == pytest.approx(M.stats_murphy(st2, ones)["rel"], abs=1e-12)
