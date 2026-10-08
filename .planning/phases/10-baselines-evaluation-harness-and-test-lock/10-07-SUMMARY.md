---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 07
subsystem: forecast-evaluation
tags: [harness, scoring, EVAL-01, EVAL-02, EVAL-03, EVAL-04]
requires: [10-02 metrics, 10-04 bootstrap+slices, 10-05 predictions, 10-01 testlock]
provides: [heatwave.forecast.evaluation.harness]
affects: [10-08 report/script, 10-09 frozen checks, Phase 14 gate]
key-files:
  created:
    - heatwave/forecast/evaluation/harness.py
    - tests/forecast/test_forecast_harness.py
key-decisions:
  - "The harness reads only stored prediction files (predictions.load_predictions) and never imports baselines or models; enforced by grep and a static isolation test"
  - "One week-block and one year-block multiplicity matrix per lead (seed streams 0 and 1), shared by all predictors, comparisons and slices"
requirements-completed: []
duration: ~25 min
completed: 2026-10-08
---

# Phase 10 Plan 07: Scoring harness Summary

One scoring path over stored predictions: point metrics, paired week-block and year-block intervals, stratified AUC, slice tables, best-baseline and persistence-decay checks, and one evaluation-log record per predictor.

## Harness API (`heatwave.forecast.evaluation.harness`)

- `ScoringContext(cfg, lead, threshold, ward_attrs, week_attrs, B=None, block=None, level=None, k_bins=None, h_bins=None, run_id=None, log_root=None)`: frozen; None fields default from `cfg.evaluation` and `cfg.gate.ci_level`.
- `score_lead(paths: {name: Path}, ctx, *, references) -> LeadResult`. ValueError on lead or split mix, file/predictor name mismatch, or unknown reference. Output tables (DataFrames on `LeadResult`):
  - `summary`: predictor, n, brier, rel, res, unc, residual, n_bins, mean_p, base_rate, brier_{week,year}_{lo,hi}, {rel,res}_week_{lo,hi}
  - `comparisons`: reference, candidate, bs_ref, bs_cand, bss, dbs, bss/dbs_{week,year}_{lo,hi}, n_valid_{week,year}; includes ref-vs-itself (bss 0, all CI bounds 0)
  - `auc`: predictor, family (season, geozone, lat_band only), stratum, n, n_pos, auc, auc_week_lo/hi, n_valid; no pooled row
  - `reliability`: predictor, bin, n, mean_p, obs_freq, p_lo, p_hi (quantile bins)
  - `prf`: predictor, threshold, n, tp, fp, fn, precision, recall, f1, predicted_positive_rate, prevalence, {precision,recall,f1}_week_{lo,hi}
  - `citl`: predictor, year, n, mean_p, obs, citl (point values, no CI)
  - `slices`: predictor, family (all, season, geozone, lat_band, year), stratum, flag_filter (all_wards, large_wards_only, exclude_lga_average, lga_average_only), n, highlight (True only for season MAM), brier + week CI, and per reference bss_vs_<ref> with `_week_lo`, `_week_hi`, `_n_valid`. Empty slices give n 0 and NaN. Slice CIs are exploratory.
  - plus `lead, split, n_rows, threshold, predictors, p_valid`.
- `best_baseline(brier_by_predictor, order)`: argmin Brier, ties by config order, ValueError if empty or unknown name.
- `persistence_decay_check({lead: bss})` -> lead_first, lead_last, bss_first, bss_last, ok (first lead skill > last lead skill), strictly_monotone (warning only).
- `sanity_flags(result)` -> probabilities_valid, self_bss_zero.
- `results_to_dict(result)`: JSON-safe dict of record lists (NaN to None) with a `sanity` entry.
- Log record: per predictor `testlock.log_event("score", outcome="scored", split, predictor, lead, n_rows, run_id, config_sha256=config_hash(cfg), purpose="harness.score_lead", data_root=ctx.log_root)`, written after scoring succeeds.
- Private `_week_stats_from_bins` builds `WeekStats` from precomputed week ids and the full-sample bin ids (reused for every slice and AUC stratum); a test shows it equals `metrics.week_stats`.

## Commit

- 77a77c1: harness and tests (Tasks 1 and 2 share one file pair, committed together).

## Verification

- `pytest tests/forecast/test_forecast_harness.py -q -m "not frozen and not slow"`: 15 passed in about 6 s wall (about 3 s of calls; tests use h_bins=50 and B=40 for speed).
- Greps: baselines import 0, `.fit(`/`.predict(` 0, accuracy/significance/p-value 0, `load_predictions` present, 4 helper defs present, harness.py 354 lines.
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 475 passed, 74 deselected, 51.2 s (56 s wall including startup). Under 60 s.

## Deviations from Plan

**1. Moved step (orchestrator note N1).** The Wave 3 quick-loop timing and slow-marking step of Task 2 was not performed here; it moves to the start of 10-08. The measured quick-loop time is reported above (51.2 s, no slow-marking needed).

**2. Tasks 1 and 2** share one file pair and were committed together.

No other deviations. Tests only use tmp roots; the real evaluation log and forecast_runs were not touched.

## EVAL requirements

EVAL-01..04 not marked complete: the report and script (10-08) and the real-data checks (10-09) remain.

## Known Stubs

None.

## Self-Check: PASSED
