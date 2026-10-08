---
phase: 09-features-targets-splits-and-leakage-suite
plan: 03
subsystem: forecast
tags: [targets, splits, embargo, cv, leakage]
requires: [09-01]
provides:
  - heatwave.forecast.targets (labels and timing fields)
  - heatwave.forecast.splits (target-week splits, embargo, CV folds)
affects: [09-04, 09-05, 09-06, 09-07, 09-08]
key-files:
  created:
    - heatwave/forecast/targets.py
    - heatwave/forecast/splits.py
    - tests/forecast/test_forecast_targets.py
    - tests/forecast/test_forecast_splits.py
key-decisions:
  - "Label is heatwave_days >= 3 built only by integer gather at position t+k; tail NaN, never filled"
  - "Split membership takes only indices and config; splits.py never imports data"
requirements-completed: []
duration: ~30 min
completed: 2026-10-06
---

# Phase 9 Plan 03: Targets, timing fields and splits Summary

Per-lead labels (`heatwave_week = heatwave_days >= 3`) with full timing fields (effective_days_ahead +1,+8,+15,+22,+29,+36 at latency 0; -8,-1,6,13,20,27 at latency 9), plus target-week train/validate/test assignment, a 14-week training embargo and 16 expanding-window CV folds (2005..2020).

## Commits
- 49383bc: targets.py and tests
- e1bc24b: splits.py and tests

## Public APIs
`heatwave.forecast.targets`
- `HEATWAVE_DAYS_THRESHOLD=3`, `TARGET_NAME`, `LABEL_DEFINITION`
- `heatwave_week_matrix(panel) -> (n,T) float32`
- `lead_label(panel, k) -> (n,T) float32` (NaN where t+k > T-1); `has_label(panel, k) -> (T,) bool`
- `effective_days_ahead(k, latency_days=0) -> int` = 7k - 6 - latency
- `TimingFields` (frozen): `last_obs_week_index, last_obs_week, issue_date (Sunday+latency), target_week_index, target_week, target_week_start, lead_weeks, effective_days_ahead, latency_days`
- `timing_fields(panel, k, latency_days) -> TimingFields` (target labels also for origins past the data end)

`heatwave.forecast.splits`
- `SPLIT_NAMES`, `FEATURE_SHORT_WINDOW_WEEKS=8`
- `cutoff_indices(splits_cfg) -> (i_train_end, i_validate_end)`
- `assign_split(target_week_index, splits_cfg) -> "<U8" array` (ValueError outside 1991-W01..2026 end)
- `embargo_keep(target_idx, cutoff_index, embargo_weeks)`
- `split_masks(target_idx, splits_cfg) -> {train, embargoed, validate, test}` (last train target 2014-W38; embargoed 2014-W39..W52)
- `refit_train_mask(target_idx, splits_cfg)` (target < validate cutoff - 14; Phase 14 refit)
- `CVFold` (year, validate_start_index, validate_end_index, train_max_target_exclusive, climatology_end, validate_start, validate_end); `cv_folds(splits_cfg)` -> 16 folds; `fold_masks(fold, target_idx) -> (train, validate)`

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 314 passed, 11 deselected (193 s under load; new modules run in under 1 s)
- Frozen targets test (2026-W38 -> 2026-W39 start 2026-09-21, no label) passed locally
- grep acceptance checks: no shift/rolling or quoted heatwave_event_count in targets.py; no data imports in splits.py

## Deviations from Plan
None.

## Requirements
FEAT-01, FEAT-02 and FEAT-05 each have parts in later plans (features, leakage suite, reporting); left pending.

## Self-Check: PASSED
