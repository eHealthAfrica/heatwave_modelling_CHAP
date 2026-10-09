"""Paired block bootstrap on per-target-week sufficient statistics (EVAL-03).

The resampling unit is target weeks (moving blocks that do not wrap around) or target years, never rows
or wards: wards in the same week are spatially correlated, so resampling them would
give overconfident intervals (PITFALLS C5). A replicate is a multiplicity vector
``c`` over weeks and every metric is a matrix product of ``c`` with the
``metrics.WeekStats`` arrays. Reference and candidate always share the same
multiplicity matrices (paired). The year-block bootstrap rests on about 6
validation clusters, so it is a coarse check only (Pitfall 10). Confidence
intervals on slices are exploratory.
"""

from __future__ import annotations

import numpy as np

from heatwave.forecast.evaluation import metrics

MIN_BLOCK_WEEKS = 4
# Longer week-block lengths reported next to the default for the skill-score intervals (WR-09).
SENSITIVITY_BLOCK_WEEKS = (8, 13)

_METRICS = ("brier", "rel", "res", "auc", "precision", "recall", "f1", "base_rate")


def lead_rng(seed: int, lead: int, stream: int = 0) -> np.random.Generator:
    """Reproducible generator from (seed, lead); stream 0 = week blocks, 1 = year blocks."""
    key = [int(seed), int(lead)] if stream == 0 else [int(seed), int(lead), int(stream)]
    return np.random.default_rng(np.random.SeedSequence(key))


def _int(name, v) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, np.integer)):
        raise ValueError(f"{name} must be an integer, got {v!r}")
    return int(v)


def week_block_indices(n_weeks: int, block: int, B: int, rng) -> np.ndarray:
    """(B, n_weeks) week indices of a moving-block bootstrap; blocks never wrap around.

    Each block is ``block`` consecutive weeks starting uniformly in [0, n_weeks - block], so the
    last week is never joined to the first (they are years apart, in a different season). The
    price is that the first and last weeks are drawn slightly less often than the middle ones.
    The concatenated blocks are trimmed to ``n_weeks``.
    """
    W, block, B = _int("n_weeks", n_weeks), _int("block", block), _int("B", B)
    if block < MIN_BLOCK_WEEKS:
        raise ValueError(f"EVAL-03: block length must be >= {MIN_BLOCK_WEEKS} weeks, got {block}")
    if block > W:
        raise ValueError(f"block length {block} exceeds the number of weeks {W}")
    if B < 1:
        raise ValueError("B must be >= 1")
    n_blocks = -(-W // block)
    starts = rng.integers(0, W - block + 1, size=(B, n_blocks))
    idx = starts[:, :, None] + np.arange(block)[None, None, :]
    return idx.reshape(B, n_blocks * block)[:, :W]


def week_block_multiplicity(n_weeks: int, block: int, B: int, rng) -> np.ndarray:
    """(B, n_weeks) moving-block (non-circular) bootstrap multiplicities; each row sums to n_weeks."""
    W, B = _int("n_weeks", n_weeks), _int("B", B)
    idx = week_block_indices(W, block, B, rng)
    flat = (idx + (np.arange(B) * W)[:, None]).ravel()
    return np.bincount(flat, minlength=B * W).astype(np.float64).reshape(B, W)


def year_block_multiplicity(year_of_week, B: int, rng) -> np.ndarray:
    """(B, W) multiplicities; each replicate is a union of whole target years."""
    B = _int("B", B)
    if B < 1:
        raise ValueError("B must be >= 1")
    yw = np.asarray(year_of_week)
    if yw.ndim != 1 or yw.size == 0:
        raise ValueError("year_of_week must be a non-empty 1-d array")
    years, inv = np.unique(yw, return_inverse=True)
    Y = len(years)
    draws = rng.integers(0, Y, size=(B, Y))
    counts = np.zeros((B, Y), dtype=np.float64)
    np.add.at(counts, (np.repeat(np.arange(B), Y), draws.ravel()), 1.0)
    return counts[:, inv]


def percentile_ci(reps, level: float = 0.95):
    """(lo, hi, n_valid) percentile interval ignoring nan replicates."""
    if not 0.0 < level < 1.0:
        raise ValueError("level must be in (0, 1)")
    r = np.asarray(reps, dtype=np.float64).ravel()
    n_valid = int(np.isfinite(r).sum())
    if n_valid == 0:
        return float("nan"), float("nan"), 0
    lo = np.nanpercentile(r, 100.0 * (1.0 - level) / 2.0)
    hi = np.nanpercentile(r, 100.0 * (1.0 + level) / 2.0)
    return float(lo), float(hi), n_valid


def metric_ci(st, mult, level: float, metric: str):
    """(lo, hi, n_valid) interval of one metric over the replicate matrix ``mult``."""
    if metric not in _METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {_METRICS}")
    if metric == "brier":
        reps = metrics.stats_brier(st, mult)
    elif metric == "base_rate":
        reps = metrics.stats_base_rate(st, mult)
    elif metric in ("rel", "res"):
        reps = metrics.stats_murphy(st, mult)[metric]
    elif metric == "auc":
        reps = metrics.stats_auc(st, mult)
    else:
        reps = metrics.stats_prf(st, mult)[metric]
    return percentile_ci(reps, level)


def _bss_dbs(bs_ref, bs_cand):
    return metrics.brier_skill_score(bs_cand, bs_ref), np.asarray(bs_ref) - np.asarray(bs_cand)


def week_block_bss_ci(ref, cand, mult, level: float = 0.95):
    """(bss, lo, hi, n_valid) of cand vs ref over the replicate matrix ``mult`` (week blocks)."""
    W = len(ref.n)
    mult = np.asarray(mult, dtype=np.float64)
    if mult.ndim != 2 or mult.shape[1] != W:
        raise ValueError(f"multiplicity must have shape (B, {W}), got {mult.shape}")
    ones = np.ones(W)
    bss = float(metrics.brier_skill_score(float(metrics.stats_brier(cand, ones)), float(metrics.stats_brier(ref, ones))))
    rb, _ = _bss_dbs(metrics.stats_brier(ref, mult), metrics.stats_brier(cand, mult))
    lo, hi, nv = percentile_ci(rb, level)
    return bss, lo, hi, nv


def paired_comparison(ref, cand, *, mult_week, mult_year, level: float = 0.95) -> dict:
    """Point BSS/dBS of cand vs ref plus paired week-block and year-block intervals.

    dbs = bs_ref - bs_cand (positive means the candidate is better).
    """
    if not (np.array_equal(ref.n, cand.n) and np.array_equal(ref.sum_y, cand.sum_y)):
        raise ValueError("ref and cand are not paired: per-week n or sum_y differ")
    W = len(ref.n)
    ones = np.ones(W)
    bs_ref = float(metrics.stats_brier(ref, ones))
    bs_cand = float(metrics.stats_brier(cand, ones))
    bss, dbs = _bss_dbs(bs_ref, bs_cand)
    out = {"bs_ref": bs_ref, "bs_cand": bs_cand, "bss": float(bss), "dbs": float(dbs)}
    for tag, mult in (("week", mult_week), ("year", mult_year)):
        mult = np.asarray(mult, dtype=np.float64)
        if mult.ndim != 2 or mult.shape[1] != W:
            raise ValueError(f"{tag} multiplicity must have shape (B, {W}), got {mult.shape}")
        r_ref = metrics.stats_brier(ref, mult)
        r_cand = metrics.stats_brier(cand, mult)
        rb, rd = _bss_dbs(r_ref, r_cand)
        lo, hi, nv = percentile_ci(rb, level)
        out[f"bss_{tag}_lo"], out[f"bss_{tag}_hi"] = lo, hi
        lo, hi, _ = percentile_ci(rd, level)
        out[f"dbs_{tag}_lo"], out[f"dbs_{tag}_hi"] = lo, hi
        out[f"n_valid_{tag}"] = nv
    return out
