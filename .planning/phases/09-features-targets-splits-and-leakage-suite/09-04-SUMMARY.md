---
phase: 09-features-targets-splits-and-leakage-suite
plan: 04
subsystem: forecast
tags: [features, registry, leakage, base-rate]
requires: [09-01, 09-02, 09-03]
provides:
  - heatwave.forecast.registry (FeatureSpec, Registry, FORBIDDEN_NAME_PATTERN)
  - heatwave.forecast.features (REGISTRY, build_feature_store, FeatureStore, helpers)
affects: [09-05, 09-06, 09-07, 09-08]
key-files:
  created:
    - heatwave/forecast/registry.py
    - heatwave/forecast/features.py
    - tests/forecast/test_forecast_registry.py
    - tests/forecast/test_forecast_features.py
key-decisions:
  - "FORBIDDEN_NAME_PATTERN exactly as planned; lga_average_ward accepted, ward/ward_id/wardcode/location/year tokens rejected"
  - "base_rate: anchors from ISO (year-j, min(week, weeks_in_year)) with +-2 offsets, vectorised over t with a running float64 accumulator across the 5 offsets (inner loop over the 10 years bounds memory)"
requirements-completed: []
duration: ~25 min
completed: 2026-10-06
---

# Phase 9 Plan 04: Feature registry and as-of feature families Summary

A registry that rejects any feature without an int-0 `max_lookahead` (or with a ward/year/label name), plus 49 as-of panel features, 6 static and 3 calendar specs, built float32 family by family; the real full build (4841 x 1863, 49 arrays) has no NaN from position 159 on.

## Commits
- 6d356ec: registry with max_lookahead guard
- f7c7228: features, base rate, store, tests

## Feature registry (58 specs, all max_lookahead 0)
- recent_heat (35): `mhi_anom_lag0-3`, `xhi_anom_lag0-3`, `mhi_anom_roll2/4/8`, `xhi_anom_roll2/4/8`, `hd_lag0-3`, `hn_lag0-3`, `hw_lag0-3`, `hd_roll2/4/8`, `hn_roll2/4/8`, `hw_roll2/4/8`
- land_humidity (6): `sm_anom_lag0`, `sm_anom_roll4`, `pr_anom_sum4`, `pr_anom_sum8`, `rh_anom_lag0`, `rh_anom_roll4`
- trend (4): `hw_frac26`, `hw_frac52`, `hw_base_rate_10y`, `mhi_anom_mean156`
- spatial (4): `lga_mean_mhi_anom_lag0`, `state_mean_mhi_anom_lag0`, `lga_mean_hd_lag0`, `state_mean_hd_lag0`
- static (6, kind static): `lat`, `lon`, `geozone_NWZ`, `geozone_NEZ`, `geozone_NCZ`, `lga_average_ward`
- season (3, kind calendar): `target_season_sin`, `target_season_cos`, `lead_weeks`

## Public APIs
- `registry`: `FeatureSpec(name, family, kind, max_lookahead, window_weeks, description, fn)`, `Registry` (`register, get, specs, names(kind, family), copy, len/iter/contains`), `FAMILIES`, `KINDS`, `FORBIDDEN_NAME_PATTERN`, `FORBIDDEN_EXACT_NAMES`
- `features`: `REGISTRY`, `default_registry()`, `FeatureContext(panel, clim, static)`, `build_feature_store(panel, clim, static, *, registry, names=None) -> FeatureStore` (`store[name]`, `.names`, `.arrays`, `.clim_fit_range`, `.data_sha256`; read-only float32 (n,T)), `static_feature_matrix(static, names=None)`, `season_features(target_week_start) -> (sin, cos)`, `base_rate(hw, week_start) -> (values, counts)`, `lag`, `trail_mean`, `trail_sum`, `group_mean`, constants `HW_DAYS_THRESHOLD=3, LONGEST_FIXED_WINDOW_WEEKS=156, BASE_RATE_MIN_OBS=15`

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 353 passed (100 s; the 60 s target is not met because of Phase 8 subprocess tests, new modules run in under 1 s)
- @frozen full build: passed locally (41 s), 49 float32 arrays (4841, 1863), no NaN at positions >= 159, base rate first valid at 159 (1994-W04)
- Synthetic warm-ups: lags 3, roll8 7, frac26 25, frac52 51, mean156 155, base rate 159; base rate matches an independent per-t reference, ignores current-year weeks, handles the 1998-W53 origin
- Grep gates: no center/shift/ffill/interpolate/fillna, no `.fit(` in features.py

## Deviations from Plan
None. Tests and implementation were written together rather than as separate RED/GREEN commits (commits are per feature module, not per TDD phase).

## Requirements
FEAT-03 and FEAT-04 need the dataset assembly (09-05) and leakage suite (09-06); left pending.

## Self-Check: PASSED
