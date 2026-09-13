---
phase: 03-climatology-heatwave-detection
plan: 01
subsystem: testing
tags: [earth-engine, reduceRegions, zonal-statistics, tdd, pytest]

# Dependency graph
requires:
  - phase: 02-heat-index-relocation
    provides: heatwave/science/heat_index.py's 'heat_index' band name and system:time_start propagation precedent
provides:
  - "heatwave/zonal.py: reduce_to_ward_daily(), the gridded-to-per-ward-daily zonal reduction stage (CLIM-05)"
  - "tests/test_heatwave_detection.py: CLIM-06 test file scaffold with credential gate and 3 reusable synthetic-data helpers (_make_ward_fc, _make_heat_index_collection, _props)"
affects: [03-02-climatology-baseline, 03-03-heatwave-detection, 03-04-integration, phase-4-batch-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ee.Image.reduceRegions + .map() + .flatten() for gridded-to-tabular zonal reduction"
    - "Longitude-valued synthetic ee.Image (ee.Image.pixelLonLat()) so spatially separated synthetic wards reduce to distinguishable, hand-predictable values"
    - "Absent reducer output property (reduceRegions' 'mean') normalised to an explicit None rather than dropped or coalesced to 0"

key-files:
  created:
    - heatwave/zonal.py
    - tests/test_heatwave_detection.py
  modified: []

key-decisions:
  - "Reworded a docstring sentence in heatwave/zonal.py to avoid a literal '4,841' ward-count mention (originally written for narrative context) after it tripped the D-04 no-hardcoded-ward-count acceptance grep; replaced with 'full nationwide ward scale'"

patterns-established:
  - "Zonal reduction pipeline stage: ee.Image.select(band).reduceRegions(collection=wards, reducer=ee.Reducer.mean(), scale=scale).map(set_row_properties), wrapped per-image and flattened across the ImageCollection"
  - "CLIM-06 test scaffold: per-test @_REQUIRES_CREDENTIALS gate (never module-level pytestmark), local synthetic-data helpers shared across the whole test_heatwave_detection.py file for plans 03-02/03-03 to extend"

requirements-completed: [CLIM-05, CLIM-06]

# Metrics
duration: 12min
completed: 2026-09-13
---

# Phase 3 Plan 1: Zonal Reduction (CLIM-05) Summary

**`heatwave/zonal.py`'s `reduce_to_ward_daily()` reduces a gridded ERA5-Land Heat Index `ee.ImageCollection` to a long-format per-ward-daily `ee.FeatureCollection` via `reduceRegions`, with `system:time_start` on every row so downstream `calendarRange` filters work and null (not dropped) values for sub-pixel-weight ward polygons.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-09-13T15:18:00+01:00
- **Completed:** 2026-09-13T15:31:00+01:00
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 2 (both created)

## Accomplishments
- `tests/test_heatwave_detection.py` created as the CLIM-06 scaffold: per-test credential gate copied from `tests/test_heat_index.py`, three reusable synthetic-data helpers (`_make_ward_fc`, `_make_heat_index_collection`, `_props`), and 5 CLIM-05 tests
- `heatwave/zonal.py` created, implementing `reduce_to_ward_daily()` exactly per the interface contract: `ward_id`, `value`, `doy`, `system:time_start` row schema
- Regression guard for 03-RESEARCH.md Pitfall 1 (`calendarRange` needs `system:time_start`) and Pitfall 4 (sub-pixel wards yield a null row, not a dropped one) both live and passing against real Earth Engine
- Full test suite (20 tests across Phases 1-3) green with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tests/test_heatwave_detection.py with credential gate, synthetic helpers, and failing CLIM-05 zonal tests (RED)** - `05c10b8` (test)
2. **Task 2: Implement heatwave/zonal.py gridded-to-per-ward-daily reduction (GREEN)** - `80d5018` (feat)

**Plan metadata:** (this commit, docs: complete plan)

_Note: This was a plan-level TDD task pair (RED then GREEN), not a per-behavior TDD subtask — 5 tests written first, all failing with `ModuleNotFoundError`, then heatwave/zonal.py written to turn all 5 green._

## Files Created/Modified
- `tests/test_heatwave_detection.py` - CLIM-06 test scaffold: credential gate, 3 synthetic-data helpers, 5 CLIM-05 tests (row count, per-ward value, calendarRange compatibility, tiny-ward null-not-dropped)
- `heatwave/zonal.py` - `reduce_to_ward_daily()`: gridded Heat Index ImageCollection -> per-ward-daily FeatureCollection, `ERA5_LAND_NOMINAL_SCALE_M` constant

## Decisions Made
- Reworded one docstring sentence in `heatwave/zonal.py` (see key-decisions above) to satisfy the D-04 acceptance criterion literally, without changing any code behavior — the constraint (no hardcoded ward count) was already honored in the function body; only a narrative docstring mention of "4,841" needed to be genericized.

## Deviations from Plan

None - plan executed exactly as written. One minor plan-artifact inconsistency was discovered and does not represent a code deviation:

- **Acceptance criterion vs. copied pattern mismatch (non-blocking, no code change needed):** Task 1's acceptance criteria state `grep -v '^#' tests/test_heatwave_detection.py | grep -F -c "EE_SA_JSON"` should return `1`, but the credential-gate block the task explicitly instructs copying "structurally" from `tests/test_heat_index.py` (and the identical block reproduced in `03-PATTERNS.md`) itself contains 2 occurrences of `EE_SA_JSON` (the `os.getenv("EE_SA_JSON")` call and the skip `reason=` string). Verified `tests/test_heat_index.py` also returns `2` for the same grep. Treated the literal copy of the established, working pattern as authoritative over the acceptance-criterion count; no functional issue.

## Issues Encountered
- Initial `heatwave/zonal.py` docstring included the phrase "Phase 4's 4,841-ward scale" for narrative clarity; this tripped the automated D-04 acceptance check (`grep -c "4841\|4,841"` must return 0). Reworded to "Phase 4's full nationwide ward scale" — no functional change, re-verified all 5 tests plus the full suite still green after the edit.

## User Setup Required

None - no external service configuration required. Live GCP credentials (`keys/service_account.json`) were already present in the environment and used to run all 5 live-EE tests to completion.

## Next Phase Readiness
- `reduce_to_ward_daily()`'s row schema (`ward_id`, `value`, `doy`, `system:time_start`) is now the fixed contract that 03-02 (climatology baseline) and 03-03 (heatwave detection) build against.
- `tests/test_heatwave_detection.py`'s three synthetic-data helpers (`_make_ward_fc`, `_make_heat_index_collection`, `_props`) and the per-test credential-gate convention are ready for 03-02/03-03 to extend in the same file.
- No blockers. The `system:time_start` and tiny-ward-null guarantees this plan established are exactly the two guarantees 03-RESEARCH.md flags as prerequisites for 03-02's `calendarRange`-based pooling-window filter.

---
*Phase: 03-climatology-heatwave-detection*
*Completed: 2026-09-13*

## Self-Check: PASSED

- FOUND: heatwave/zonal.py
- FOUND: tests/test_heatwave_detection.py
- FOUND: .planning/phases/03-climatology-heatwave-detection/03-01-SUMMARY.md
- FOUND: 05c10b8 (test commit)
- FOUND: 80d5018 (feat commit)
