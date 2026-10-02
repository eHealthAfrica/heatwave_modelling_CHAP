---
phase: 03-climatology-heatwave-detection
plan: 02
subsystem: science
tags: [earth-engine, percentile, climatology, day-of-year, tdd, pytest]

# Dependency graph
requires:
  - phase: 03-climatology-heatwave-detection (plan 01)
    provides: "heatwave/zonal.py's reduce_to_ward_daily() row schema (ward_id, value, doy, system:time_start) consumed as the input contract"
provides:
  - "heatwave/science/climatology.py: floor_mod/wrapped_day wraparound helpers, pooling_window_filter, compute_climatology_thresholds (CLIM-01, CLIM-02)"
  - "tests/test_heatwave_detection.py: 9 new CLIM-01/CLIM-02 tests plus the _make_ward_daily_fc synthetic-data helper, extending plan 03-01's scaffold"
affects: [03-03-heatwave-detection, 03-04-integration, phase-4-batch-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Floor-mod wraparound arithmetic (ee.Number.mod() correction via ee.Algorithms.If) feeding ee.Filter.calendarRange's native start>end wrap, no ee.Filter.Or needed"
    - "ee.List.sequence(1, 366).map(...) + Reducer.percentile().group() for one grouped percentile reducer call per calendar day covering all wards at once (ward-count-agnostic, D-04)"
    - "Config-driven tuning parameters: None-defaulting signature params resolved from settings.climatology, with is-not-None (not truthy-or) used for window_days so an explicit 0 survives"

key-files:
  created:
    - heatwave/science/climatology.py
  modified:
    - tests/test_heatwave_detection.py

key-decisions:
  - "Reworded three climatology.py docstring/comment lines (mentioning literal '90, 5, 1991 and 2020', 'ee.Filter.Or', and a duplicated 'groupField=1') to avoid tripping their own no-hardcoded-literal / no-Filter.Or / exact-count acceptance greps, without changing any behavior -- same class of fix as plan 03-01's '4,841' docstring rework"

patterns-established:
  - "compute_climatology_thresholds: filter to baseline years via calendarRange('year') before pooling, then one calendarRange('day_of_year')-filtered grouped-percentile reduceColumns call per doy in ee.List.sequence(1,366).map(...); output rows carry ward_id/doy/threshold with no system:time_start (joined on (ward_id, doy) downstream, never calendarRange-filtered again)"

requirements-completed: [CLIM-01, CLIM-02, CLIM-06]

# Metrics
duration: 10min
completed: 2026-09-13
---

# Phase 3 Plan 2: Climatology Baseline (CLIM-01/CLIM-02) Summary

**`heatwave/science/climatology.py`'s `compute_climatology_thresholds()` computes a per-ward, per-calendar-day 90th-percentile baseline with a wraparound-safe ±5-day pooling window, using one grouped `ee.Reducer.percentile()` call per calendar day rather than a per-ward Python loop.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-13T15:35:00+01:00
- **Completed:** 2026-09-13T15:45:16+01:00
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `tests/test_heatwave_detection.py` extended with a `_make_ward_daily_fc` synthetic-data helper (reproduces `heatwave/zonal.py`'s exact row schema by computing `doy` server-side from the date string) and 9 new tests: 6 CLIM-01 (module exports, live-verified p90=9.5 percentile oracle, baseline-year exclusion, per-ward grouping, Feb-29 own calendar-day slot, config-driven defaults) and 3 CLIM-02 (floor-mod negative-input correction, bidirectional new-year/day-366 pooling wraparound)
- `heatwave/science/climatology.py` created, implementing `floor_mod`, `wrapped_day`, `pooling_window_filter`, and `compute_climatology_thresholds` exactly per the interface contract
- D-05 (Feb 29 gets its own real threshold, never merged with Feb 28's) and D-06 (bidirectional pooling-window wraparound via floor-mod, not `ee.Filter.Or`) both live and passing against real Earth Engine
- D-02 honored: the `[1..10]` p90=9.5 test oracle is EE's own live-computed value; no numpy/pandas/scipy/statistics import anywhere in module or test file
- All four tuning parameters (`percentile`, `window_days`, `baseline_start_year`, `baseline_end_year`) default to `None` and resolve from `settings.climatology` (security V5) — zero hardcoded `90`/`1991`/`2020` literals in the module
- Full test suite (29 tests across Phases 1-3) green with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing CLIM-01/CLIM-02 climatology and pooling-window tests (RED)** - `a0932c9` (test)
2. **Task 2: Implement heatwave/science/climatology.py wraparound pooling and grouped percentile thresholds (GREEN)** - `fc47cd0` (feat)

**Plan metadata:** (this commit, docs: complete plan)

_Note: This was a plan-level TDD task pair (RED then GREEN), not a per-behavior TDD subtask — 9 tests written first, all failing with `ModuleNotFoundError`, then `heatwave/science/climatology.py` written to turn all 9 (14 total) green._

## Files Created/Modified
- `tests/test_heatwave_detection.py` - `_make_ward_daily_fc` helper, 6 CLIM-01 tests, 3 CLIM-02 tests (14 tests total in file now)
- `heatwave/science/climatology.py` - `DAYS_IN_LEAP_YEAR` constant, `floor_mod`, `wrapped_day`, `pooling_window_filter`, `compute_climatology_thresholds`

## Decisions Made
- Reworded three docstring/comment lines in `heatwave/science/climatology.py` (see key-decisions above) purely to satisfy the plan's own literal-grep acceptance criteria (no hardcoded `90`/`1991`/`2020`, no `ee.Filter.Or`, exactly one `groupField=1` occurrence) — no behavior change, same category of fix as plan 03-01's ward-count docstring rework.

## Deviations from Plan

None — plan executed exactly as written. Three self-inflicted acceptance-criteria near-misses were caught and fixed during Task 2 verification (see Decisions Made) before committing; no code logic was altered, only prose in docstrings/comments.

## Issues Encountered
- Initial `climatology.py` draft included explanatory docstring/comment text that quoted the plan's own forbidden literals (`90, 5, 1991 and 2020`, `` `ee.Filter.Or` ``) and a duplicated mention of `groupField=1` in both a comment and the code line beneath it — this tripped 3 of Task 2's automated acceptance greps (`\b90\b\|\b1991\b\|\b2020\b` != 0, `ee.Filter.Or` != 0, `groupField=1` count != 1). Reworded all three to describe the same facts without repeating the exact forbidden substrings; re-ran the full grep suite and all 14 tests to confirm no functional change.

## User Setup Required

None — no external service configuration required. Live GCP credentials (`keys/service_account.json`) were already present in the environment and used to run all 13 credentialed live-EE tests to completion (`test_climatology_module_exports` and `test_climatology_defaults_read_from_settings`'s signature assertion run without credentials; the rest call `init_ee()`).

## Next Phase Readiness
- `compute_climatology_thresholds()`'s output row schema (`ward_id`, `doy`, `threshold`, no `system:time_start`) is now the fixed contract plan 03-03 (heatwave day/event detection) joins against via `ee.Join.saveFirst` on `(ward_id, doy)`.
- `floor_mod`/`wrapped_day`/`pooling_window_filter` are general-purpose and reusable if plan 03-03 or Phase 4 needs day-of-year wraparound arithmetic again.
- No blockers. The live-verified EE percentile oracle (9.5 for `[1..10]` p90) and the Feb-29-own-slot guarantee are both regression-tested and ready for 03-03 to build the exceedance-flagging and consecutive-run-detection stage on top.

---
*Phase: 03-climatology-heatwave-detection*
*Completed: 2026-09-13*

## Self-Check: PASSED

- FOUND: heatwave/science/climatology.py
- FOUND: tests/test_heatwave_detection.py
- FOUND: .planning/phases/03-climatology-heatwave-detection/03-02-SUMMARY.md
- FOUND: a0932c9 (test commit)
- FOUND: fc47cd0 (feat commit)
