---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 02
subsystem: forecast-evaluation
tags: [metrics, brier, murphy, auc, bootstrap-stats, EVAL-02]
requires: []
provides: [heatwave.forecast.evaluation.metrics, WeekStats sufficient statistics]
affects: [10-04 bootstrap, 10-07 harness]
tech-stack:
  added: []
  patterns: [per-target-week sufficient statistics, tie-safe quantile bins]
key-files:
  created:
    - heatwave/forecast/evaluation/__init__.py
    - heatwave/forecast/evaluation/metrics.py
    - tests/forecast/test_forecast_metrics.py
  modified: []
key-decisions:
  - "quantile_edges keeps duplicate edges, and when p has <= k distinct values it returns edges separating every distinct value (needed for the 90/5/5 three-valued case to be exact with n_bins == 3; the plain recipe merges 0.2 and 0.6)"
  - "No pooled AUC function; stratified_auc only. No accuracy word or symbol in the module"
requirements-completed: []
duration: ~15 min
completed: 2026-10-08
---

# Phase 10 Plan 02: Metrics layer Summary

Pure numpy/pandas metrics (EVAL-02 building blocks) plus per-target-week sufficient statistics so bootstrap replicates are matrix products over weeks.

## Metrics API (`heatwave.forecast.evaluation.metrics`)

Point metrics (inputs validated: ValueError on NaN, p outside [0,1], y outside {0,1}, length mismatch):
- `brier(p, y)`, `brier_skill_score(bs_cand, bs_ref)` (nan when ref == 0; array-capable)
- `quantile_edges(p, k)`, `assign_bins(p, edges)` (single `searchsorted(edges[1:-1], p, side="left")`)
- `murphy(p, y, k=10, edges=None) -> MurphyDecomposition(bs, rel, res, unc, residual, n_bins, base_rate, n)`
- `reliability_table(p, y, k, edges)` -> bin, n, mean_p, obs_freq, p_lo, p_hi
- `auc(p, y)` (rank-based, nan if one class), `stratified_auc(p, y, strata)` -> stratum, n, n_pos, auc (no pooled row or function)
- `prf_at_threshold(p, y, threshold)` -> threshold, n, tp, fp, fn, precision, recall, f1, predicted_positive_rate, prevalence (rule p >= t)
- `calibration_in_the_large(p, y, year)` -> year, n, mean_p, obs, citl

Sufficient statistics:
- `WeekStats` (frozen): n, sum_y, sum_p, sse, bin_n, bin_sum_p, bin_sum_y, pos_hist, neg_hist, tp, fp, fn, edges, auc_edges, threshold
- `week_stats(p, y, week_id, n_weeks, *, edges, auc_edges, threshold)` (ValueError if week_id out of range)
- Aggregators taking `c` of shape (W,) or (B, W): `stats_brier`, `stats_base_rate`, `stats_mean_p`, `stats_murphy` (rel, res, unc), `stats_auc`, `stats_prf` (precision, recall, f1); `auc_from_hist(pos, neg)`. Empty replicates give nan. Replicate REL/RES are conditional on the full-sample bin edges.

## Commit

- de84283: both tasks (single module and test file, committed together)

## Verification

- `tests/forecast/test_forecast_metrics.py`: 18 passed (calls ~0.2 s; ~4.5 s wall including scipy/sklearn import).
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 416 passed, 68 deselected in 53.4 s.
- Greps: accuracy 0, np.unique 0, searchsorted present, no pooled AUC def.

## Deviations from Plan

**1. [Rule 1 - Bug] Tie-safe edges for few-valued predictors.** The research recipe puts 0.2 and 0.6 in one bin for the 90/5/5 case (residual 3e-3), contradicting the required exact residual and n_bins == 3. `quantile_edges` now returns value-separating edges when p has <= k distinct values; otherwise it is the plain duplicate-keeping quantile edges. Commit de84283.

**2. Test distribution.** The continuous Murphy test uses Beta(2, 14) (residual < 1e-3 holds); Beta(0.5, 5) was too skewed for 10 bins.

**3.** Tasks 1 and 2 share one file and were committed as a single commit.

## EVAL-02 status

Not marked complete: bootstrap CIs (10-04) and harness reporting (10-07) remain.

## Known Stubs

None.

## Self-Check: PASSED
