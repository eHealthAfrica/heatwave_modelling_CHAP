"""EVAL-03: paired week-block / year-block bootstrap on sufficient statistics."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from heatwave.forecast.evaluation import bootstrap as bs
from heatwave.forecast.evaluation import metrics

EDGES = np.array([0.0, 0.3, 0.6, 1.0])
AUC_EDGES = np.linspace(0.0, 1.0, 11)


def _stats(p, y, wk, W):
    return metrics.week_stats(p, y, wk, W, edges=EDGES, auc_edges=AUC_EDGES, threshold=0.5)


def _panel(W=60, sites=5, seed=0, shift=0.0):
    rng = np.random.default_rng(seed)
    wk = np.repeat(np.arange(W), sites)
    y = (rng.random(W * sites) < 0.3).astype(float)
    p = np.clip(0.3 + shift + 0.2 * (y - 0.3) + 0.1 * rng.standard_normal(W * sites), 0.01, 0.99)
    return p, y, wk


def test_week_block_validation_and_shape():
    rng = bs.lead_rng(1, 7)
    with pytest.raises(ValueError, match="EVAL-03"):
        bs.week_block_multiplicity(100, 3, 10, rng)
    with pytest.raises(ValueError):
        bs.week_block_multiplicity(3, 4, 10, rng)
    with pytest.raises(ValueError):
        bs.week_block_multiplicity(100, 4, 0, rng)
    m = bs.week_block_multiplicity(100, 4, 20, rng)
    assert m.shape == (20, 100)
    assert np.all(m.sum(axis=1) == 100)


def test_reproducible_from_seed_and_lead():
    a = bs.week_block_multiplicity(50, 4, 10, bs.lead_rng(3, 14))
    b = bs.week_block_multiplicity(50, 4, 10, bs.lead_rng(3, 14))
    c = bs.week_block_multiplicity(50, 4, 10, bs.lead_rng(3, 28))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    y1 = bs.year_block_multiplicity(np.repeat([2018, 2019, 2020], 10), 10, bs.lead_rng(3, 14, 1))
    y2 = bs.year_block_multiplicity(np.repeat([2018, 2019, 2020], 10), 10, bs.lead_rng(3, 14, 1))
    assert np.array_equal(y1, y2)


def test_year_block_whole_years():
    years = np.repeat([2018, 2019, 2020, 2021], 13)
    m = bs.year_block_multiplicity(years, 30, bs.lead_rng(0, 7, 1))
    assert m.shape == (30, 52)
    for y in np.unique(years):
        block = m[:, years == y]
        assert np.all(block == block[:, :1])
    assert np.all(m.sum(axis=1) == 52)


def test_matches_brute_force_expansion():
    W = 12
    p, y, wk = _panel(W=W, sites=3, seed=4)
    st = _stats(p, y, wk, W)
    c = bs.week_block_multiplicity(W, 4, 1, bs.lead_rng(0, 7))[0]
    rows = np.repeat(np.arange(len(p)), c[wk].astype(int))
    assert len(rows) < 1000
    expected = metrics.brier(p[rows], y[rows])
    assert metrics.stats_brier(st, c) == pytest.approx(expected, rel=1e-12)


def test_self_comparison_is_exactly_zero():
    p, y, wk = _panel()
    st = _stats(p, y, wk, 60)
    mw = bs.week_block_multiplicity(60, 4, 30, bs.lead_rng(0, 7))
    my = bs.year_block_multiplicity(np.repeat(np.arange(6), 10), 30, bs.lead_rng(0, 7, 1))
    out = bs.paired_comparison(st, st, mult_week=mw, mult_year=my, level=0.95)
    assert out["bss"] == 0.0 and out["dbs"] == 0.0
    for k in ("bss", "dbs"):
        for t in ("week", "year"):
            assert out[f"{k}_{t}_lo"] == 0.0 and out[f"{k}_{t}_hi"] == 0.0
    assert out["n_valid_week"] == 30


def test_perfect_spatial_correlation_equals_single_site():
    W = 40
    p1, y1, wk1 = _panel(W=W, sites=1, seed=1)
    q1, _, _ = _panel(W=W, sites=1, seed=2, shift=0.05)
    mw = bs.week_block_multiplicity(W, 4, 40, bs.lead_rng(5, 7))
    my = bs.year_block_multiplicity(np.repeat(np.arange(4), 10), 40, bs.lead_rng(5, 7, 1))

    def run(sites):
        wk = np.repeat(np.arange(W), sites)
        ref = _stats(np.repeat(p1, sites), np.repeat(y1, sites), wk, W)
        cand = _stats(np.repeat(q1, sites), np.repeat(y1, sites), wk, W)
        return bs.paired_comparison(ref, cand, mult_week=mw, mult_year=my, level=0.9)

    one, many = run(1), run(50)
    for k, v in one.items():
        assert many[k] == pytest.approx(v, rel=1e-12, abs=1e-15), k


def test_unpaired_rows_rejected():
    p, y, wk = _panel(W=20)
    a = _stats(p, y, wk, 20)
    b = _stats(p[:-1], y[:-1], wk[:-1], 20)
    m = bs.week_block_multiplicity(20, 4, 5, bs.lead_rng(0, 7))
    with pytest.raises(ValueError, match="paired"):
        bs.paired_comparison(a, b, mult_week=m, mult_year=m)


def test_no_row_or_ward_resampling_in_signatures():
    banned = {"rows", "ward", "wards", "ward_pos", "row_index"}
    for name, fn in inspect.getmembers(bs, inspect.isfunction):
        if name.startswith("_") or fn.__module__ != bs.__name__:
            continue
        assert not banned & set(inspect.signature(fn).parameters), name


def test_percentile_ci_nan_handling():
    lo, hi, n = bs.percentile_ci([1.0, 2.0, np.nan, 3.0], 0.5)
    assert n == 3 and 1.0 <= lo <= hi <= 3.0
    lo, hi, n = bs.percentile_ci([np.nan, np.nan], 0.95)
    assert np.isnan(lo) and np.isnan(hi) and n == 0


def test_metric_ci_all_metrics_and_unknown():
    p, y, wk = _panel(W=30)
    st = _stats(p, y, wk, 30)
    m = bs.week_block_multiplicity(30, 4, 20, bs.lead_rng(0, 7))
    for name in ("brier", "rel", "res", "auc", "precision", "recall", "f1", "base_rate"):
        lo, hi, n = bs.metric_ci(st, m, 0.9, name)
        assert n > 0 and lo <= hi
    with pytest.raises(ValueError):
        bs.metric_ci(st, m, 0.9, "accuracy")


# ------------------------------------------------------- review WR-09: non-circular blocks
def test_blocks_never_wrap_around():
    W, block = 30, 4
    idx = bs.week_block_indices(W, block, 500, bs.lead_rng(5, 7))
    assert idx.shape == (500, W) and idx.min() >= 0 and idx.max() <= W - 1
    n_full = W // block
    for b in range(n_full):
        seg = idx[:, b * block:(b + 1) * block]
        assert np.all(np.diff(seg, axis=1) == 1), "a block jumped (wrapped) instead of staying consecutive"


def test_multiplicity_from_non_circular_indices_sums_to_n_weeks():
    m = bs.week_block_multiplicity(26, 4, 50, bs.lead_rng(1, 2))
    assert np.all(m.sum(axis=1) == 26)
    # last block start <= W - block, so the final week needs a block ending exactly there
    idx = bs.week_block_indices(26, 4, 2000, bs.lead_rng(1, 2))
    assert idx.max() == 25 and idx.min() == 0
    assert bs.SENSITIVITY_BLOCK_WEEKS == (8, 13) and min(bs.SENSITIVITY_BLOCK_WEEKS) > bs.MIN_BLOCK_WEEKS


def test_week_block_bss_ci_matches_paired_comparison_shape():
    p, y, wk = _panel(W=60, sites=2, seed=2)
    ref = _stats(p, y, wk, 60)
    cand = _stats(np.clip(p + 0.05, 0.01, 0.99), y, wk, 60)
    m = bs.week_block_multiplicity(60, 8, 100, bs.lead_rng(0, 1, 2))
    bss, lo, hi, nv = bs.week_block_bss_ci(ref, cand, m)
    assert nv == 100 and lo <= hi
    full = bs.paired_comparison(ref, cand, mult_week=m, mult_year=m)
    assert (bss, lo, hi) == pytest.approx((full["bss"], full["bss_week_lo"], full["bss_week_hi"]))
