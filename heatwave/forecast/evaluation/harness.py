"""Scoring harness: one path that scores stored predictions (EVAL-01..04).

The harness scores stored prediction files only. It never imports the baselines
or any model and never calls fit or predict: every predictor, baseline or model,
is scored by exactly this code from its Parquet file (``predictions.load_predictions``,
which is the only data entry point and is test-lock aware).

Per predictor and lead it reports Brier, the Murphy decomposition (with its
residual), quantile-bin reliability, precision/recall/F1 at the stated threshold,
calibration-in-the-large by year, and ROC AUC stratified by season, geozone and
latitude band only (there is no pooled AUC). Every skill score names its
reference and comes with paired week-block and year-block intervals from one
multiplicity matrix per lead shared by all predictors and slices. Slice
intervals are exploratory and are not adjusted for the number of slices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from heatwave.forecast import testlock
from heatwave.forecast.config import config_hash
from heatwave.forecast.evaluation import bootstrap, metrics, predictions, slices

__all__ = [
    "LeadResult",
    "ScoringContext",
    "best_baseline",
    "persistence_decay_check",
    "results_to_dict",
    "sanity_flags",
    "score_lead",
]

AUC_FAMILIES = ("season", "geozone", "lat_band")


@dataclass(frozen=True)
class ScoringContext:
    cfg: object
    lead: int
    threshold: float  # default rule = training base rate for the lead; always reported
    ward_attrs: pd.DataFrame  # slices.ward_attributes, indexed by ward code
    week_attrs: pd.DataFrame  # slices.week_attributes, indexed by target_week_index
    B: int | None = None
    block: int | None = None
    level: float | None = None
    k_bins: int | None = None
    h_bins: int | None = None
    run_id: str | None = None
    log_root: object = None

    def __post_init__(self):
        ev = self.cfg.evaluation
        for name, val in (
            ("B", ev.bootstrap_b),
            ("block", ev.block_weeks),
            ("level", self.cfg.gate.ci_level),
            ("k_bins", ev.reliability_bins),
            ("h_bins", ev.auc_hist_bins),
        ):
            if getattr(self, name) is None:
                object.__setattr__(self, name, val)


@dataclass
class LeadResult:
    lead: int
    split: str
    n_rows: int
    threshold: float
    predictors: tuple
    summary: pd.DataFrame
    comparisons: pd.DataFrame
    auc: pd.DataFrame
    reliability: pd.DataFrame
    prf: pd.DataFrame
    citl: pd.DataFrame
    slices: pd.DataFrame = field(default_factory=pd.DataFrame)
    p_valid: bool = True


# ------------------------------------------------------------------ stats helper
def _week_stats_from_bins(p, y, w, n_weeks, bk, bh, edges, auc_edges, threshold, mask=None):
    """WeekStats from precomputed week ids and bin ids (same result as metrics.week_stats)."""
    if mask is not None:
        p, y, w, bk, bh = p[mask], y[mask], w[mask], bk[mask], bh[mask]
    k, h = len(edges) - 1, len(auc_edges) - 1

    def per_week(wts):
        return np.bincount(w, weights=wts, minlength=n_weeks).astype(np.float64)

    def by_week(nb, bins, wts=None):
        flat = w * nb + bins
        return np.bincount(flat, weights=wts, minlength=n_weeks * nb).astype(np.float64).reshape(n_weeks, nb)

    pos = p >= threshold
    ones = y == 1.0
    return metrics.WeekStats(
        n=per_week(None), sum_y=per_week(y), sum_p=per_week(p), sse=per_week((p - y) ** 2),
        bin_n=by_week(k, bk), bin_sum_p=by_week(k, bk, p), bin_sum_y=by_week(k, bk, y),
        pos_hist=by_week(h, bh, y), neg_hist=by_week(h, bh, 1.0 - y),
        tp=per_week((pos & ones).astype(np.float64)),
        fp=per_week((pos & ~ones).astype(np.float64)),
        fn=per_week((~pos & ones).astype(np.float64)),
        edges=np.asarray(edges, dtype=np.float64), auc_edges=np.asarray(auc_edges, dtype=np.float64),
        threshold=float(threshold),
    )


# ------------------------------------------------------------------------ scoring
def _load_aligned(paths: Mapping[str, Path], ctx: ScoringContext):
    if not paths:
        raise ValueError("no prediction files given")
    names = list(paths)
    frames, metas = {}, {}
    for name in names:
        df, meta = predictions.load_predictions(paths[name], ctx.cfg, data_root=ctx.log_root)
        if meta.predictor != name:
            raise ValueError(f"file for {name!r} holds predictor {meta.predictor!r}")
        if meta.lead != ctx.lead:
            raise ValueError(f"{name!r} is lead {meta.lead}, expected lead {ctx.lead}")
        frames[name], metas[name] = df, meta
    splits_seen = {m.split for m in metas.values()}
    if len(splits_seen) != 1:
        raise ValueError(f"prediction files mix splits {sorted(splits_seen)}")
    first = frames[names[0]]
    order = {}
    for name in names:
        r_idx, c_idx = predictions.align(first, frames[name])
        order[name] = (r_idx, c_idx)
    ref_idx = order[names[0]][0]
    cols = {}
    for name in names:
        c_idx = order[name][1]
        cols[name] = (
            frames[name]["p"].to_numpy(dtype=np.float64)[c_idx],
            frames[name]["y"].to_numpy(dtype=np.float64)[c_idx],
        )
    key = first.iloc[ref_idx]
    return names, cols, key, splits_seen.pop()


def score_lead(paths: Mapping[str, Path], ctx: ScoringContext, *, references: Sequence[str]) -> LeadResult:
    names, cols, key, split = _load_aligned(paths, ctx)
    references = list(references)
    for r in references:
        if r not in names:
            raise ValueError(f"reference {r!r} is not among the loaded predictors {names}")

    cfg = ctx.cfg
    tw = key["target_week_index"].to_numpy(dtype=np.int64)
    uniq = np.unique(tw)
    n_weeks = len(uniq)
    week_id = np.searchsorted(uniq, tw)
    year_of_week = ctx.week_attrs.loc[uniq, "year"].to_numpy()
    mult_week = bootstrap.week_block_multiplicity(
        n_weeks, ctx.block, ctx.B, bootstrap.lead_rng(cfg.seed, ctx.lead)
    )
    mult_year = bootstrap.year_block_multiplicity(
        year_of_week, ctx.B, bootstrap.lead_rng(cfg.seed, ctx.lead, 1)
    )
    n = len(key)
    y = cols[names[0]][1]

    ward_idx = pd.Index(key["ward"].astype(object))
    wa = ctx.ward_attrs.loc[ward_idx]
    ks = ctx.week_attrs.loc[tw]
    auc_labels = {
        "season": ks["season"].to_numpy(),
        "geozone": wa["geozone"].to_numpy(),
        "lat_band": wa["lat_band"].to_numpy(),
    }
    masks = slices.row_slice_masks(ward_idx, tw, ctx.ward_attrs, ctx.week_attrs)
    year_row = ks["year"].to_numpy()

    summary, rel_rows, prf_rows, citl_rows, auc_rows = [], [], [], [], []
    stats, bins = {}, {}
    p_valid = True
    for name in names:
        p, yy = cols[name]
        p_valid &= bool(np.isfinite(p).all() and (n == 0 or (p.min() >= 0.0 and p.max() <= 1.0)))
        edges = metrics.quantile_edges(p, ctx.k_bins)
        auc_edges = metrics.quantile_edges(p, ctx.h_bins)
        bk, bh = metrics.assign_bins(p, edges), metrics.assign_bins(p, auc_edges)
        bins[name] = (edges, auc_edges, bk, bh)
        st = metrics.week_stats(p, yy, week_id, n_weeks, edges=edges, auc_edges=auc_edges, threshold=ctx.threshold)
        stats[name] = st
        mu = metrics.murphy(p, yy, ctx.k_bins, edges)
        row = {
            "predictor": name, "n": n, "brier": mu.bs, "rel": mu.rel, "res": mu.res, "unc": mu.unc,
            "residual": mu.residual, "n_bins": mu.n_bins, "mean_p": float(p.mean()) if n else float("nan"),
            "base_rate": mu.base_rate,
        }
        for tag, mult in (("week", mult_week), ("year", mult_year)):
            lo, hi, _ = bootstrap.metric_ci(st, mult, ctx.level, "brier")
            row[f"brier_{tag}_lo"], row[f"brier_{tag}_hi"] = lo, hi
        for m in ("rel", "res"):
            lo, hi, _ = bootstrap.metric_ci(st, mult_week, ctx.level, m)
            row[f"{m}_week_lo"], row[f"{m}_week_hi"] = lo, hi
        summary.append(row)

        rt = metrics.reliability_table(p, yy, ctx.k_bins, edges)
        rt.insert(0, "predictor", name)
        rel_rows.append(rt)

        prf = metrics.prf_at_threshold(p, yy, ctx.threshold)
        prf["predictor"] = name
        for m in ("precision", "recall", "f1"):
            lo, hi, _ = bootstrap.metric_ci(st, mult_week, ctx.level, m)
            prf[f"{m}_week_lo"], prf[f"{m}_week_hi"] = lo, hi
        prf_rows.append(prf)

        ct = metrics.calibration_in_the_large(p, yy, year_row)
        ct.insert(0, "predictor", name)
        citl_rows.append(ct)

        for fam in AUC_FAMILIES:
            sa = metrics.stratified_auc(p, yy, auc_labels[fam])
            for rec in sa.to_dict("records"):
                m = masks[(fam, rec["stratum"], "all_wards")]
                sst = _week_stats_from_bins(p, yy, week_id, n_weeks, bk, bh, edges, auc_edges, ctx.threshold, m)
                lo, hi, nv = bootstrap.metric_ci(sst, mult_week, ctx.level, "auc")
                auc_rows.append({
                    "predictor": name, "family": fam, "stratum": rec["stratum"], "n": rec["n"],
                    "n_pos": rec["n_pos"], "auc": rec["auc"], "auc_week_lo": lo, "auc_week_hi": hi,
                    "n_valid": nv,
                })

    comp_rows = []
    for ref in references:
        for cand in names:
            c = bootstrap.paired_comparison(
                stats[ref], stats[cand], mult_week=mult_week, mult_year=mult_year, level=ctx.level
            )
            comp_rows.append({"reference": ref, "candidate": cand, **c})

    slice_rows = _slice_table(names, cols, week_id, n_weeks, bins, masks, references, mult_week, mult_year, ctx)

    result = LeadResult(
        lead=ctx.lead, split=split, n_rows=n, threshold=float(ctx.threshold), predictors=tuple(names),
        summary=pd.DataFrame(summary), comparisons=pd.DataFrame(comp_rows),
        auc=pd.DataFrame(auc_rows), reliability=pd.concat(rel_rows, ignore_index=True),
        prf=pd.DataFrame(prf_rows), citl=pd.concat(citl_rows, ignore_index=True),
        slices=slice_rows, p_valid=p_valid,
    )
    chash = config_hash(cfg)
    for name in names:
        testlock.log_event(
            "score", outcome="scored", split=split, predictor=name, lead=ctx.lead, n_rows=n,
            run_id=ctx.run_id, config_sha256=chash, purpose="harness.score_lead", data_root=ctx.log_root,
        )
    return result


def _slice_table(names, cols, week_id, n_weeks, bins, masks, references, mult_week, mult_year, ctx):
    rows = []
    for (fam, stratum, ff), m in masks.items():
        cnt = int(m.sum())
        st = {}
        if cnt:
            for name in names:
                p, yy = cols[name]
                edges, auc_edges, bk, bh = bins[name]
                st[name] = _week_stats_from_bins(p, yy, week_id, n_weeks, bk, bh, edges, auc_edges, ctx.threshold, m)
        for name in names:
            row = {
                "predictor": name, "family": fam, "stratum": stratum, "flag_filter": ff, "n": cnt,
                "highlight": bool(fam == "season" and stratum == slices.HIGHLIGHT_SEASON),
                "brier": np.nan, "brier_week_lo": np.nan, "brier_week_hi": np.nan,
            }
            if cnt:
                one = np.ones(n_weeks)
                row["brier"] = float(metrics.stats_brier(st[name], one))
                row["brier_week_lo"], row["brier_week_hi"], _ = bootstrap.metric_ci(
                    st[name], mult_week, ctx.level, "brier"
                )
            for ref in references:
                b, lo, hi, nv = np.nan, np.nan, np.nan, 0
                if cnt:
                    c = bootstrap.paired_comparison(
                        st[ref], st[name], mult_week=mult_week, mult_year=mult_year, level=ctx.level
                    )
                    b, lo, hi, nv = c["bss"], c["bss_week_lo"], c["bss_week_hi"], c["n_valid_week"]
                row[f"bss_vs_{ref}"] = b
                row[f"bss_vs_{ref}_week_lo"] = lo
                row[f"bss_vs_{ref}_week_hi"] = hi
                row[f"bss_vs_{ref}_n_valid"] = nv
            rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------ checks and output
def best_baseline(brier_by_predictor: Mapping[str, float], order: Sequence[str]) -> str:
    """Lowest validation Brier; ties broken by configuration order."""
    if not brier_by_predictor:
        raise ValueError("no predictors to choose a best baseline from")
    order = list(order)
    for k in brier_by_predictor:
        if k not in order:
            raise ValueError(f"predictor {k!r} is not in the configured order {order}")
    return min(brier_by_predictor, key=lambda k: (brier_by_predictor[k], order.index(k)))


def persistence_decay_check(bss_by_lead: Mapping[int, float]) -> dict:
    """Persistence skill at the shortest lead must exceed that at the longest lead."""
    if len(bss_by_lead) < 2:
        raise ValueError("need at least two leads for the persistence decay check")
    leads = sorted(bss_by_lead)
    vals = [float(bss_by_lead[k]) for k in leads]
    return {
        "lead_first": leads[0], "lead_last": leads[-1], "bss_first": vals[0], "bss_last": vals[-1],
        "ok": bool(vals[0] > vals[-1]),
        "strictly_monotone": bool(all(a > b for a, b in zip(vals, vals[1:]))),
    }


def sanity_flags(result: LeadResult) -> dict:
    c = result.comparisons
    own = c[c["reference"] == c["candidate"]]
    self_zero = bool(len(own) > 0 and (own["bss"] == 0.0).all())
    return {"probabilities_valid": bool(result.p_valid), "self_bss_zero": self_zero}


def _clean(v):
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def _records(df: pd.DataFrame) -> list:
    return [{k: _clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]


def results_to_dict(result: LeadResult) -> dict:
    """JSON-serialisable form of a LeadResult (NaN mapped to None)."""
    out = {
        "lead": int(result.lead), "split": result.split, "n_rows": int(result.n_rows),
        "threshold": float(result.threshold), "predictors": list(result.predictors),
        "sanity": sanity_flags(result),
    }
    for name in ("summary", "comparisons", "auc", "reliability", "prf", "citl", "slices"):
        out[name] = _records(getattr(result, name))
    return out
