---
phase: 09-features-targets-splits-and-leakage-suite
plan: 02
subsystem: forecast
tags: [static-metadata, climatology, anomalies, leakage]
requires: [09-01]
provides:
  - heatwave.forecast.static (StaticTable, build_static_table, load_static, GEOZONES)
  - heatwave.forecast.climatology (Climatology, pooling_matrix, iso_week_slots)
  - session fixtures frozen_static, frozen_clim
affects: [09-03, 09-04, 09-05, 09-06, 09-07, 09-08]
key-files:
  created:
    - heatwave/forecast/static.py
    - heatwave/forecast/climatology.py
    - tests/forecast/test_forecast_static.py
    - tests/forecast/test_forecast_climatology.py
  modified:
    - tests/forecast/conftest.py
key-decisions:
  - "lga_id is a dense code of (statename, lgacode with leading zeros stripped); lgacode kept as raw strings"
  - "Climatology variance is mean-centred about the pooled slot mean (after a per-ward shift), ddof 0; std floor = max(0.1 x median std, 1e-6) per variable"
requirements-completed: []
duration: ~40 min
completed: 2026-10-06
---

# Phase 9 Plan 02: Static ward table and train-only climatology Summary

Static ward metadata (centroid lat/lon, geozone, LGA/state group ids, LGA-average flag) loads from the hash-verified frozen files, and a train-only per-ward ISO-week climatology (+-2 week pooling, W53 pooled with W52/W01, std floor) records its fit range and is bit-identical under poisoned held-out weeks.

## Commits
- 64c28f6: static ward table
- dbcccfd: climatology and session fixtures

## Public APIs for later plans
`heatwave.forecast.static`
- `GEOZONES = ("NWZ","NEZ","NCZ")`
- `StaticTable` (frozen, eq=False, arrays read-only): `wards, lat, lon (float32), geozone, statename, lgacode (tuple of str), lga_id, state_id (int32), lga_average_ward, empty_geometry (bool)`; `.align(wards)` subsets/reorders (ids not renumbered; unknown ward -> KeyError)
- `build_static_table(geojson, lga_rows, wards)` pure; `load_static(data_cfg, wards, data_root=None)` hashes raw bytes vs MANIFEST (`inputs_sha256["wards.geojson"]`, `outputs_sha256["wards_lga_average.csv"]`) then parses the same bytes; FrozenDataError on any failure

`heatwave.forecast.climatology`
- constants `N_SLOTS=53, POOL_WEEKS=2, STD_FLOOR_FRAC=0.1, MIN_ABS_STD_FLOOR=1e-6, CLIMATOLOGY_VARIABLES`
- `iso_week_slots(week_start) -> int16 (1..53)`; `pooling_matrix(pool=2) -> (53,53) bool`
- `Climatology.fit(panel, end: date)` (Monday, date not datetime; trains on `week_start < end`); fields `mean/std (n,53,V) float32`, `std_floor (V,)`, `pooled_counts (53,)`, `fit_end, first/last_week_index, first/last_week_start, n_fit_weeks, data_sha256, pool_weeks`
- `.anomaly(panel, variable) -> (n,T) float32` (aligns wards by code, never refits); `.fit_range() -> dict` (JSON-safe provenance)

Fixtures in `tests/forecast/conftest.py`: `frozen_static`, `frozen_clim` (fit at `splits.train_end`).

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 293 passed (run under concurrent load, 220 s; the plan's 60 s target was not met in that run, individual new modules run in 2-5 s)
- @frozen run locally: static (4841 wards, 6 flagged == 6 empty geometries, geozones 2004/1518/1319) passed; climatology (1991-W02..2014-W52, 1251 weeks, sha matches, pooled min >= 95) passed
- isolation test passes; no write-mode opens in the new modules

## Deviations from Plan
None. Note: the poison test compares `fit_range()` with `data_sha256` excluded, because the poisoned Panel carries a derived sha by design; mean, std and std_floor are compared bit-exactly.

## Requirements
FEAT-03 and FEAT-04 span later plans (features, registry, leakage suite); left pending.

## Self-Check: PASSED
