---
phase: 03-climatology-heatwave-detection
plan: 04
subsystem: testing
tags: [earth-engine, integration-test, zonal-statistics, climatology, heatwave-detection, tdd, pytest]

# Dependency graph
requires:
  - phase: 03-climatology-heatwave-detection (plan 01)
    provides: "heatwave/zonal.py's reduce_to_ward_daily() row schema (ward_id, value, doy, system:time_start)"
  - phase: 03-climatology-heatwave-detection (plan 02)
    provides: "heatwave/science/climatology.py's compute_climatology_thresholds() row schema (ward_id, doy, threshold)"
  - phase: 03-climatology-heatwave-detection (plan 03)
    provides: "heatwave/science/heatwave.py's flag_heatwave_days()/detect_heatwave_events() combined row schema"
provides:
  - "tests/test_heatwave_detection.py: composed end-to-end pipeline test (CLIM-06) plus a real ERA5-Land + real ward asset zonal smoke test, closing Phase 3's own test coverage"
affects: [phase-4-batch-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single ward-daily table filtered into two views (baseline years vs. detection year) rather than two separate zonal reductions -- the exact shape Phase 4's scripts/run_batch_export.py inherits"
    - "Two-graph runtime fallback for a chained live-EE test: materialise an intermediate FeatureCollection once with .getInfo(), then rebuild an equivalent table from the live-computed values via a synthetic-data helper, to avoid a lazy graph being fully re-evaluated on every downstream .getInfo() call"
    - "Pitfall-4-proof real-ward selection: feature.set('area_m2', geometry().area(maxError=1000)).sort('area_m2', False).limit(3) instead of a bare .limit(3) on unsorted asset order"

key-files:
  created: []
  modified:
    - tests/test_heatwave_detection.py

key-decisions:
  - "Task 1's initial single-computation-graph composed test measured 65.81s against 03-VALIDATION.md's 30s budget; applied the plan's documented two-graph fallback (materialise reduce_to_ward_daily's output once, rebuild via the existing _make_ward_daily_fc helper) and re-measured at 16.09s"
  - "Task 2's real ERA5-Land smoke test measured 27-43s across repeated runs (network-latency variance), over the 30s aspirational budget on at least one run; no fallback applies here because the cost is the mandated full-asset area-sort itself (Pitfall-4-proof ward selection), not a re-evaluated lazy graph -- documented as an accepted D-03 cost in a code comment rather than a correctness issue"
  - "Reworded two docstring literal-'4,841' mentions and one comment's '4,841' mention in the new real-data test to 'nationwide ward asset' to satisfy the task's own D-03 no-full-scale-literal acceptance grep -- same class of self-inflicted near-miss fix as plans 03-01/03-02/03-03's docstring rewording, zero behavior change"

patterns-established: []

requirements-completed: [CLIM-01, CLIM-02, CLIM-03, CLIM-04, CLIM-05, CLIM-06]

# Metrics
duration: 35min
completed: 2026-09-13
---

# Phase 3 Plan 4: Composition and Real-Data Integration Summary

**One live test chains `reduce_to_ward_daily` -> `compute_climatology_thresholds` -> `flag_heatwave_days` -> `detect_heatwave_events` in the exact order Phase 4's batch export will call them, and a second live test exercises that same zonal-reduction stage against the real ERA5-Land collection and the real ward asset, closing CLIM-06.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-13 (session start)
- **Completed:** 2026-09-13
- **Tasks:** 2 (both `type="auto"`, no TDD RED/GREEN split -- this plan adds tests only, no production module changes)
- **Files modified:** 1 (`tests/test_heatwave_detection.py`)

## Accomplishments

- `test_end_to_end_climatology_and_event_pipeline` added: a synthetic two-ward, 30-image fixture (constant 20.0 baseline across 2001/2002, mixed 15.0/25.0 detection window in 2003) drives all four Phase 3 stages in one chain. Threshold, `is_hot`, `run_id`, and `event_id` sequences are asserted for both W-A and W-B independently, proving per-ward partitioning holds under composition, not just under one ward's coincidental correctness.
- New helper `_make_constant_heat_index_collection(date_values)` added (spatially constant images, as opposed to plan 03-01's longitude-valued helper), with a docstring explaining why a constant image is required to make the whole downstream chain hand-computable.
- `test_real_era5_land_zonal_reduction_smoke` added: the three largest real ward polygons (selected by `area_m2` sort, never a bare `.limit(3)`, per 03-RESEARCH.md Pitfall 4) over five real ERA5-Land days (2020-06-01..05), mapped through `compute_relative_humidity` -> `compute_heat_index` -> `reduce_to_ward_daily`. Pins exactly 15 non-null rows, a 50-200 degF Heat Index sanity band, the leap-year `doy` set `{153..157}`, 3 distinct real `wardcode` values, and a re-verified `calendarRange` timestamp guard against real data.
- Runtime discipline honored: Task 1's composed test initially measured 65.81s (over 03-VALIDATION.md's 30s budget) as a single lazy computation graph re-evaluated on every downstream `.getInfo()` call; applied the plan's documented two-graph fallback (materialise the zonal output once, rebuild an equivalent table via `_make_ward_daily_fc`) and re-measured at 16.09s. Task 2's real-data test measured 27-43s across repeated runs (real-network latency variance) with no available fallback (the cost is the mandated full-asset area-sort itself); documented as an accepted D-03 cost rather than weakened.
- Credential-skip path verified explicitly: temporarily relocated the local `keys/service_account.json`, ran the full file with `-rs`, confirmed 3 module-export tests pass and all 21 credentialed tests skip cleanly with `Live GCP credentials not available`, zero failures, then restored the key file.
- Full Phase 1-3 suite (39 tests across `tests/test_heat_index.py`, `tests/test_heatwave_detection.py`, `tests/test_integration.py`, `tests/test_requirements.py`) green with credentials present; no single test exceeded 30s in that combined run.
- Every `-k` selector published in 03-VALIDATION.md and 03-RESEARCH.md (`zonal`, `climatology`, `pooling`, `flag`, `event`, plus this plan's own `end_to_end`, `real_era5`, `export`) resolves to a non-empty, fully-passing set.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the end-to-end synthetic pipeline composition test** - `f639ddf` (test)
2. **Task 2: Add the real ERA5-Land zonal smoke test and run the phase-gate regression** - `d8169d1` (test)

**Plan metadata:** (this commit, docs: complete plan)

_Note: This plan has no RED/GREEN TDD split -- both tasks add pure test coverage against already-implemented, already-tested (in plans 03-01/03-02/03-03) production modules. No production module was modified._

## Files Created/Modified

- `tests/test_heatwave_detection.py` - added `_make_constant_heat_index_collection` helper, `test_end_to_end_climatology_and_event_pipeline` (CLIM-06 composition test), and `test_real_era5_land_zonal_reduction_smoke` (real-data CLIM-05 test); file grew from 671 to 900 lines, 23 to 24 tests total.

## Decisions Made

- Applied the plan's documented runtime fallback for Task 1 exactly as specified: materialise `reduce_to_ward_daily`'s output once via `.getInfo()`, assert the 60-row expectation on that live payload, then rebuild an equivalent table with `_make_ward_daily_fc` from the live-computed `(ward_id, date_string, value)` triples (date strings derived from `system:time_start` millis via Python's stdlib `datetime`, not a parallel science-math reimplementation -- D-02 is unaffected). Re-measured duration dropped from 65.81s to 16.09s.
- Reworded three literal "4,841" mentions in the new real-data test's docstring/comments to "nationwide ward asset" -- see key-decisions above; no code behavior changed, same self-inflicted-acceptance-grep-fix pattern established in plans 03-01/03-02/03-03.
- Left Task 2's real-data test without a fallback for its 27-43s measured runtime: the plan documents a fallback only for Task 1's composed test; Task 2's cost is the mandated Pitfall-4-proof area-sort over the real, full ward asset, which cannot be split into two graphs the way a downstream-recomputed lazy chain can. Documented as an accepted D-03 cost in a code comment rather than silently ignored.

## Deviations from Plan

None that changed behavior or scope. Two self-inflicted acceptance-criteria near-misses were caught and fixed before committing (see Decisions Made): the initial composed-test runtime exceeding the 30s budget (fixed via the plan's own documented fallback) and three literal "4,841" mentions tripping the D-03 no-full-scale-literal grep (fixed via docstring/comment rewording only).

## Issues Encountered

- Task 1's first draft of `test_end_to_end_climatology_and_event_pipeline`, run as a single lazy Earth Engine computation graph, measured 65.81s with `--durations=5` -- over 03-VALIDATION.md's 30s budget, because every downstream `.getInfo()` call (threshold check, per-ward `is_hot`/`run_id`/`event_id` assertions) re-evaluated the entire chain including the 366-day-sequence climatology reducer from scratch. Applied the plan's documented two-graph fallback and re-measured at 16.09s.
- Task 2's real-data test measured inconsistently across runs (43.07s on first run, 27.01s on a second run, both against the same live `heatwave-508110` project) -- attributed to real GCP network/compute latency variance rather than a code issue. No fallback was available or specified for this task, so the variance is documented rather than engineered away.
- Both tasks' initial drafts included literal "4,841" ward-count mentions in test docstrings/comments (for narrative clarity describing the real asset), which tripped Task 2's own `grep -c "4841\|4,841"` acceptance criterion (must return 0). Reworded to "nationwide ward asset" in all three locations -- no functional change, re-ran the affected tests and the full grep suite to confirm.

## User Setup Required

None -- no external service configuration required. Live GCP credentials (`keys/service_account.json`) were already present in the environment and used to run all 21 credentialed live-EE tests to completion; the file was temporarily relocated and restored solely to verify the credential-absent skip path, with no lasting change.

## Next Phase Readiness

- CLIM-06 is closed: `tests/test_heatwave_detection.py` now validates climatology computation and day/event detection at every level -- per stage (plans 03-01/03-02/03-03), composed (this plan's Task 1), and against real data (this plan's Task 2).
- The exact call order and default-parameter shape Phase 4's `scripts/run_batch_export.py` will use is now proven end-to-end: `reduce_to_ward_daily` -> `compute_climatology_thresholds` -> filter to detection years -> `flag_heatwave_days` -> `detect_heatwave_events`, with one ward-daily table filtered into two views rather than two separate zonal reductions.
- CLIM-05 is now proven against the real ERA5-Land collection and the real nationwide ward asset, not only synthetic constructions; the 50-200 degF sanity band, null-freedom, and leap-year `doy` set are all real-data regression guards ready for Phase 4 to inherit.
- Two open items carried forward from plan 03-03 remain unresolved by design (D-03 scope): the null-`value` policy for sub-pixel wards reaching `flag_heatwave_days`, and the `.iterate()` state-machine's untested behavior at Phase 4's full ~10,950-element (30-year) scale. Phase 4 planning must address both before reusing these modules at full scale.
- No blockers. The full Phase 1-3 suite (39 tests) is green, the credential-skip path is confirmed clean, and every published `-k` selector resolves correctly.

---
*Phase: 03-climatology-heatwave-detection*
*Completed: 2026-09-13*

## Self-Check: PASSED

- FOUND: tests/test_heatwave_detection.py
- FOUND: .planning/phases/03-climatology-heatwave-detection/03-04-SUMMARY.md
- FOUND: f639ddf (test commit, Task 1)
- FOUND: d8169d1 (test commit, Task 2)
