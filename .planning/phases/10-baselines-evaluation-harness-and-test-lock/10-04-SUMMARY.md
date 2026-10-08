---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 04
subsystem: forecast-evaluation
tags: [bootstrap, slices, EVAL-03, EVAL-04]
requires: [10-02 metrics]
provides: [heatwave.forecast.evaluation.bootstrap, heatwave.forecast.evaluation.slices]
affects: [10-06 baselines, 10-07 harness, report]
key-files:
  created:
    - heatwave/forecast/evaluation/bootstrap.py
    - heatwave/forecast/evaluation/slices.py
    - tests/forecast/test_forecast_bootstrap.py
    - tests/forecast/test_forecast_slices.py
key-decisions:
  - "Resampling unit is weeks or years only; no public bootstrap function accepts rows or wards (signature test)"
  - "Slice masks are keyed (family, stratum, flag_filter); small ward = area < 0.01 deg^2"
requirements-completed: []
duration: ~20 min
completed: 2026-10-08
---

# Phase 10 Plan 04: Bootstrap and slices Summary

Paired circular week-block and year-block bootstrap on `WeekStats`, plus one shared definition of seasons, latitude bands, years and ward flags.

## Bootstrap API (`heatwave.forecast.evaluation.bootstrap`)
- `MIN_BLOCK_WEEKS = 4`
- `lead_rng(seed, lead, stream=0)`: SeedSequence([seed, lead]) for stream 0 (week blocks), [seed, lead, stream] otherwise (year blocks use 1)
- `week_block_multiplicity(n_weeks, block, B, rng)` -> (B, W); ValueError (naming EVAL-03) for block < 4, block > W, B < 1
- `year_block_multiplicity(year_of_week, B, rng)` -> (B, W), whole years
- `percentile_ci(reps, level)` -> (lo, hi, n_valid), nan-aware
- `metric_ci(st, mult, level, metric)` -> (lo, hi, n_valid) for brier, rel, res, auc, precision, recall, f1, base_rate
- `paired_comparison(ref, cand, *, mult_week, mult_year, level)` -> dict: bs_ref, bs_cand, bss, dbs (ref - cand, positive = candidate better), bss/dbs_{week,year}_{lo,hi}, n_valid_week, n_valid_year; ValueError if per-week n or sum_y differ

## Slices API (`heatwave.forecast.evaluation.slices`)
- Constants: SEASONS, HIGHLIGHT_SEASON = "MAM", SMALL_WARD_AREA_DEG2 = 0.01, LAT_BANDS, FLAG_FILTERS, FAMILIES
- `season_of(week_start)` (mid-week day), `lat_band(lat)` (report constants imported)
- `ward_areas_deg2(geojson, wards)`, `load_ward_areas(data_cfg, wards, data_root=None)` (hash-verified read), `small_ward_flags(areas)`
- `ward_attributes(static, areas)`, `week_attributes(target_week_index, target_week_start, target_week_label)`
- `row_slice_masks(ward_codes, target_week_index, ward_attrs, week_attrs, *, families, flag_filters)` -> {(family, stratum, flag_filter): bool mask}

## Commits
- a304551: bootstrap + tests (10 tests, 2.8 s)
- a8f0b74: slices + tests (14 tests; frozen test confirms 4,835 finite areas and 3,086 small wards, run locally)

## Verification
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 444 passed, 69 deselected in 56.18 s (under 60 s).
- Slices module incl. @frozen: 14 passed.

## Deviations from Plan
None. The latitude-band count test compares against the report's inequalities directly rather than calling `prevalence_tables` (which needs a full panel and config).

## Requirement status
EVAL-03 and EVAL-04 not marked complete: harness reporting of CIs and slices (10-07) remains.

## Known Stubs
None.

## Self-Check: PASSED
