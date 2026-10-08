"""Point metrics and per-target-week sufficient statistics (EVAL-02).

Pure numpy and pandas. Every score is defined once here. The bootstrap and
the harness reuse the per-target-week sufficient statistics (``WeekStats``)
so that a replicate is a weighted sum over weeks, not a pass over rows.

ROC AUC is only available stratified; there is deliberately no pooled AUC.
Precision, recall and F1 always carry their threshold, the predicted-positive
rate and the prevalence.

Caveat: replicate reliability and resolution computed from ``WeekStats`` are
conditional on the full-sample quantile bin edges (the edges are not
re-estimated inside each replicate).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import rankdata

__all__ = [
    "MurphyDecomposition",
    "WeekStats",
    "assign_bins",
    "auc",
    "auc_from_hist",
    "brier",
    "brier_skill_score",
    "calibration_in_the_large",
    "murphy",
    "prf_at_threshold",
    "quantile_edges",
    "reliability_table",
    "stats_auc",
    "stats_base_rate",
    "stats_brier",
    "stats_mean_p",
    "stats_murphy",
    "stats_prf",
    "stratified_auc",
    "week_stats",
]


# ----------------------------------------------------------------- validation
def _prep(p, y):
    p = np.asarray(p, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    if p.shape != y.shape:
        raise ValueError(f"length mismatch: p has {p.size} rows, y has {y.size}")
    if np.isnan(p).any():
        raise ValueError("NaN in p")
    if np.isnan(y).any():
        raise ValueError("NaN in y")
    if p.size and (p.min() < 0.0 or p.max() > 1.0):
        raise ValueError("p outside [0, 1]")
    if p.size and not np.all((y == 0.0) | (y == 1.0)):
        raise ValueError("y outside {0, 1}")
    return p, y


# --------------------------------------------------------------------- Brier
def brier(p, y) -> float:
    """Mean squared error between probability and 0/1 outcome."""
    p, y = _prep(p, y)
    return float(np.mean((p - y) ** 2))


def brier_skill_score(bs_cand, bs_ref):
    """1 - bs_cand / bs_ref; nan where bs_ref == 0. Works on arrays too."""
    bs_cand = np.asarray(bs_cand, dtype=np.float64)
    bs_ref = np.asarray(bs_ref, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(bs_ref == 0.0, np.nan, 1.0 - bs_cand / bs_ref)
    return float(out) if out.ndim == 0 else out


# ---------------------------------------------------------------------- bins
def quantile_edges(p, k: int) -> np.ndarray:
    """Quantile edges of p, KEEPING duplicates (ties must stay in one bin).

    If p takes at most k distinct values, the edges separate every distinct
    value so that p is constant within each bin (the decomposition is then
    exact even when most rows tie at one value).
    """
    p = np.asarray(p, dtype=np.float64).ravel()
    k = int(k)
    if p.size:
        s = np.sort(p)
        distinct = s[np.concatenate(([True], s[1:] != s[:-1]))]
        if 1 < len(distinct) <= k:
            return np.concatenate(([distinct[0]], distinct[:-1], [distinct[-1]]))
    return np.quantile(p, np.linspace(0.0, 1.0, k + 1))


def assign_bins(p, edges) -> np.ndarray:
    """Bin index per value; equal values always share a bin."""
    edges = np.asarray(edges, dtype=np.float64)
    return np.searchsorted(edges[1:-1], np.asarray(p, dtype=np.float64), side="left").astype(np.int64)


def _bin_sums(p, y, edges):
    k = len(edges) - 1
    b = assign_bins(p, edges)
    n = np.bincount(b, minlength=k).astype(np.float64)
    sp = np.bincount(b, weights=p, minlength=k)
    sy = np.bincount(b, weights=y, minlength=k)
    return n, sp, sy


@dataclass(frozen=True)
class MurphyDecomposition:
    bs: float
    rel: float
    res: float
    unc: float
    residual: float
    n_bins: int
    base_rate: float
    n: int


def murphy(p, y, k: int = 10, edges=None) -> MurphyDecomposition:
    """Murphy decomposition BS ~ REL - RES + UNC with quantile bins."""
    p, y = _prep(p, y)
    if edges is None:
        edges = quantile_edges(p, k)
    n_k, sp, sy = _bin_sums(p, y, edges)
    m = n_k > 0
    n = float(p.size)
    obar = float(y.mean())
    pb = sp[m] / n_k[m]
    ob = sy[m] / n_k[m]
    rel = float(np.sum(n_k[m] * (pb - ob) ** 2) / n)
    res = float(np.sum(n_k[m] * (ob - obar) ** 2) / n)
    unc = obar * (1.0 - obar)
    bs = float(np.mean((p - y) ** 2))
    return MurphyDecomposition(
        bs=bs, rel=rel, res=res, unc=unc, residual=bs - (rel - res + unc),
        n_bins=int(m.sum()), base_rate=obar, n=int(p.size),
    )


def reliability_table(p, y, k: int = 10, edges=None) -> pd.DataFrame:
    """Per-bin n, mean forecast, observed frequency (non-empty bins only)."""
    p, y = _prep(p, y)
    if edges is None:
        edges = quantile_edges(p, k)
    edges = np.asarray(edges, dtype=np.float64)
    n_k, sp, sy = _bin_sums(p, y, edges)
    idx = np.flatnonzero(n_k > 0)
    return pd.DataFrame({
        "bin": idx,
        "n": n_k[idx].astype(np.int64),
        "mean_p": sp[idx] / n_k[idx],
        "obs_freq": sy[idx] / n_k[idx],
        "p_lo": edges[idx],
        "p_hi": edges[idx + 1],
    })


# ----------------------------------------------------------------------- AUC
def auc(p, y) -> float:
    """Exact ROC AUC by rank (average ties); nan if one class only."""
    p, y = _prep(p, y)
    n_pos = float(y.sum())
    n_neg = float(y.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    r = rankdata(p)
    return float((r[y == 1.0].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def stratified_auc(p, y, strata) -> pd.DataFrame:
    """One AUC row per stratum label. There is deliberately no pooled row."""
    p, y = _prep(p, y)
    s = np.asarray(strata).ravel()
    if s.shape != p.shape:
        raise ValueError("strata length mismatch")
    rows = []
    for lab in sorted(pd.unique(s).tolist()):
        m = s == lab
        rows.append({
            "stratum": lab, "n": int(m.sum()), "n_pos": int(y[m].sum()),
            "auc": auc(p[m], y[m]),
        })
    return pd.DataFrame(rows, columns=["stratum", "n", "n_pos", "auc"])


# ----------------------------------------------------------------- P / R / F1
def _prf(tp, fp, fn):
    with np.errstate(divide="ignore", invalid="ignore"):
        prec = tp / (tp + fp)
        rec = tp / (tp + fn)
        f1 = 2.0 * prec * rec / (prec + rec)
    return prec, rec, f1


def prf_at_threshold(p, y, threshold: float) -> dict:
    """Precision, recall, F1 at p >= threshold, with context fields."""
    p, y = _prep(p, y)
    pos = p >= threshold
    tp = float(np.sum(pos & (y == 1.0)))
    fp = float(np.sum(pos & (y == 0.0)))
    fn = float(np.sum(~pos & (y == 1.0)))
    prec, rec, f1 = (float(v) for v in _prf(np.float64(tp), np.float64(fp), np.float64(fn)))
    n = int(p.size)
    return {
        "threshold": float(threshold), "n": n,
        "tp": int(tp), "fp": int(fp), "fn": int(fn),
        "precision": prec, "recall": rec, "f1": f1,
        "predicted_positive_rate": float(pos.mean()) if n else float("nan"),
        "prevalence": float(y.mean()) if n else float("nan"),
    }


# -------------------------------------------------------------- calibration
def calibration_in_the_large(p, y, year) -> pd.DataFrame:
    """Mean forecast minus observed frequency per target year."""
    p, y = _prep(p, y)
    yr = np.asarray(year).ravel()
    if yr.shape != p.shape:
        raise ValueError("year length mismatch")
    df = pd.DataFrame({"year": yr, "p": p, "y": y})
    g = df.groupby("year", sort=True)
    out = pd.DataFrame({"n": g.size(), "mean_p": g["p"].mean(), "obs": g["y"].mean()}).reset_index()
    out["citl"] = out["mean_p"] - out["obs"]
    return out[["year", "n", "mean_p", "obs", "citl"]]


# ------------------------------------------------- per-target-week statistics
@dataclass(frozen=True)
class WeekStats:
    n: np.ndarray
    sum_y: np.ndarray
    sum_p: np.ndarray
    sse: np.ndarray
    bin_n: np.ndarray
    bin_sum_p: np.ndarray
    bin_sum_y: np.ndarray
    pos_hist: np.ndarray
    neg_hist: np.ndarray
    tp: np.ndarray
    fp: np.ndarray
    fn: np.ndarray
    edges: np.ndarray
    auc_edges: np.ndarray
    threshold: float


def _by_week(week_id, n_weeks, nb, bins, weights=None):
    flat = week_id * nb + bins
    return np.bincount(flat, weights=weights, minlength=n_weeks * nb).astype(np.float64).reshape(n_weeks, nb)


def week_stats(p, y, week_id, n_weeks: int, *, edges, auc_edges, threshold: float) -> WeekStats:
    """Sufficient statistics per target week (rows with week_id in [0, n_weeks))."""
    p, y = _prep(p, y)
    w = np.asarray(week_id).ravel().astype(np.int64)
    if w.shape != p.shape:
        raise ValueError("week_id length mismatch")
    if w.size and (w.min() < 0 or w.max() >= n_weeks):
        raise ValueError("week_id outside [0, n_weeks)")
    edges = np.asarray(edges, dtype=np.float64)
    auc_edges = np.asarray(auc_edges, dtype=np.float64)
    k = len(edges) - 1
    h = len(auc_edges) - 1
    bk = assign_bins(p, edges)
    bh = assign_bins(p, auc_edges)
    pos = p >= threshold
    ones = y == 1.0

    def per_week(wts):
        return np.bincount(w, weights=wts, minlength=n_weeks).astype(np.float64)

    return WeekStats(
        n=per_week(None), sum_y=per_week(y), sum_p=per_week(p), sse=per_week((p - y) ** 2),
        bin_n=_by_week(w, n_weeks, k, bk),
        bin_sum_p=_by_week(w, n_weeks, k, bk, p),
        bin_sum_y=_by_week(w, n_weeks, k, bk, y),
        pos_hist=_by_week(w, n_weeks, h, bh, y),
        neg_hist=_by_week(w, n_weeks, h, bh, 1.0 - y),
        tp=per_week((pos & ones).astype(np.float64)),
        fp=per_week((pos & ~ones).astype(np.float64)),
        fn=per_week((~pos & ones).astype(np.float64)),
        edges=edges, auc_edges=auc_edges, threshold=float(threshold),
    )


def _c2(c):
    c = np.asarray(c, dtype=np.float64)
    return np.atleast_2d(c), c.ndim == 1


def _out(a, single):
    return float(a[0]) if single else a


def _ratio(num, den):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def stats_brier(st: WeekStats, c):
    c, s = _c2(c)
    return _out(_ratio(c @ st.sse, c @ st.n), s)


def stats_base_rate(st: WeekStats, c):
    c, s = _c2(c)
    return _out(_ratio(c @ st.sum_y, c @ st.n), s)


def stats_mean_p(st: WeekStats, c):
    c, s = _c2(c)
    return _out(_ratio(c @ st.sum_p, c @ st.n), s)


def stats_murphy(st: WeekStats, c) -> dict:
    """rel, res, unc per replicate; bins with zero weighted count are dropped."""
    c, s = _c2(c)
    n = c @ st.n
    nk = c @ st.bin_n
    m = nk > 0
    safe = np.where(m, nk, 1.0)
    pb = (c @ st.bin_sum_p) / safe
    ob = (c @ st.bin_sum_y) / safe
    obar = _ratio(c @ st.sum_y, n)
    rel = _ratio(np.sum(np.where(m, nk * (pb - ob) ** 2, 0.0), axis=1), n)
    res = _ratio(np.sum(np.where(m, nk * (ob - obar[:, None]) ** 2, 0.0), axis=1), n)
    unc = obar * (1.0 - obar)
    return {"rel": _out(rel, s), "res": _out(res, s), "unc": _out(unc, s)}


def auc_from_hist(pos, neg):
    """AUC from score histograms along the last axis (ties within a bin count 1/2)."""
    pos = np.asarray(pos, dtype=np.float64)
    neg = np.asarray(neg, dtype=np.float64)
    cn = np.cumsum(neg, axis=-1) - neg
    num = np.sum(pos * (cn + neg / 2.0), axis=-1)
    den = pos.sum(axis=-1) * neg.sum(axis=-1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def stats_auc(st: WeekStats, c):
    c, s = _c2(c)
    return _out(auc_from_hist(c @ st.pos_hist, c @ st.neg_hist), s)


def stats_prf(st: WeekStats, c) -> dict:
    c, s = _c2(c)
    tp, fp, fn = c @ st.tp, c @ st.fp, c @ st.fn
    prec, rec, f1 = _prf(tp, fp, fn)
    return {"precision": _out(prec, s), "recall": _out(rec, s), "f1": _out(f1, s)}
