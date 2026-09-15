---
phase: 03-climatology-heatwave-detection
plan: 03
subsystem: science
tags: [earth-engine, join, state-machine, iterate, heatwave-detection, tdd, pytest]

# Dependency graph
requires:
  - phase: 03-climatology-heatwave-detection (plan 01)
    provides: "heatwave/zonal.py's reduce_to_ward_daily() row schema (ward_id, value, doy, system:time_start) consumed as the flagging input contract"
  - phase: 03-climatology-heatwave-detection (plan 02)
    provides: "heatwave/science/climatology.py's compute_climatology_thresholds() row schema (ward_id, doy, threshold) consumed as the join's right-hand side"
provides:
  - "heatwave/science/heatwave.py: flag_heatwave_days (threshold join + exceedance flagging, CLIM-03), tag_consecutive_runs + detect_heatwave_events (consecutive-run event detection, CLIM-04)"
  - "tests/test_heatwave_detection.py: 8 new CLIM-03/CLIM-04 tests plus the _make_climatology_fc synthetic-data helper, extending plans 03-01/03-02's scaffold"
affects: [03-04-integration, phase-4-batch-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ee.Join.saveFirst equi-join on two ee.Filter.equals clauses (ward_id AND doy) inside an ee.Filter.And, keeping a calendar-day-specific threshold match instead of one ward-wide value"
    - "ee.List.iterate() state machine ([prev_flag, group_id, tags_so_far]) for consecutive-run tagging, verified against the exact live literal from 03-RESEARCH.md Pattern 6"
    - "Per-ward event detection via aggregate_array(...).distinct().map(...) server-side partitioning (no Python ward loop), each partition sorted by system:time_start before the state machine runs, run length checked with ee.List.frequency()"

key-files:
  created:
    - heatwave/science/heatwave.py
  modified:
    - tests/test_heatwave_detection.py

key-decisions:
  - "Reworded one docstring line (referring to settings.climatology.min_consecutive_days) and joined a wrapped .sort(\"system:time_start\") call onto one line, both purely to satisfy this plan's own literal-grep acceptance criteria (exact count of 1 for each pattern) -- same class of self-inflicted near-miss as plans 03-01/03-02's docstring rewording, no behavior change"

patterns-established:
  - "detect_heatwave_events: aggregate_array(ward_id).distinct().map(process_one_ward) where each ward's rows are filtered, sorted by system:time_start, converted to a flags list, run through tag_consecutive_runs, then re-zipped with the original feature list by index via ee.List.sequence -- the reusable per-ward stateful-computation shape for any future EE run-length feature"

requirements-completed: [CLIM-03, CLIM-04, CLIM-06]

# Metrics
duration: 18min
completed: 2026-09-13
---

# Phase 3 Plan 3: Heatwave Detection (CLIM-03/CLIM-04) Summary

**`heatwave/science/heatwave.py`'s `flag_heatwave_days()` joins each ward-day to its own calendar-day climatological threshold via `ee.Join.saveFirst` and flags strict exceedance, while `detect_heatwave_events()` runs a per-ward, date-sorted `ee.List.iterate()` state machine to group consecutive hot days into events subject to the configured minimum run length.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-09-13T15:50:00+01:00
- **Completed:** 2026-09-13T16:08:00+01:00
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `tests/test_heatwave_detection.py` extended with a `_make_climatology_fc` synthetic-data helper (reproduces `heatwave/science/climatology.py`'s exact `ward_id`/`doy`/`threshold` row schema) and 8 new tests: 1 no-credentials export smoke test, 3 CLIM-03 threshold-join/exceedance tests, and 4 CLIM-04 consecutive-run/event-detection tests
- `heatwave/science/heatwave.py` created, implementing `flag_heatwave_days`, `tag_consecutive_runs`, and `detect_heatwave_events` exactly per the interface contract, with `NO_RUN = -1` as the single sentinel constant used everywhere
- CLIM-03's strict-greater-than exceedance boundary and calendar-day-specific (not ward-wide) threshold matching both live and passing against real Earth Engine
- CLIM-04's live-verified run-tag sequence (`[0,1,1,1,0,1,1,0,0,1,1,1,1,0]` -> `[-1,1,1,1,-1,2,2,-1,-1,3,3,3,3,-1]`) reproduced exactly, the >=3-day event qualification filter, and per-ward run isolation (D-04) all live and passing
- Security V5 upheld: `min_consecutive_days` defaults to `None` and resolves from `settings.climatology.min_consecutive_days`; no hardcoded `3` anywhere in the module
- D-03 honored and visible: the `.iterate()` Phase 4 scale limitation (untested beyond ~3,650 elements vs. the real ~10,950-element series) is recorded as a code comment naming the documented array forward-difference fallback, not silently assumed away
- Full test suite (37 tests across Phases 1-3) green with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing CLIM-03/CLIM-04 flagging and event-detection tests (RED)** - `538e37d` (test)
2. **Task 2: Implement heatwave/science/heatwave.py threshold join, day flagging, and run-based event detection (GREEN)** - `7a341ba` (feat)

**Plan metadata:** (this commit, docs: complete plan)

_Note: This was a plan-level TDD task pair (RED then GREEN), not a per-behavior TDD subtask — 8 tests written first, all failing with `ModuleNotFoundError`, then `heatwave/science/heatwave.py` written to turn all 8 (22 total) green._

## Files Created/Modified
- `tests/test_heatwave_detection.py` - `_make_climatology_fc` helper, `_VERIFIED_FLAG_SEQUENCE`/`_VERIFIED_RUN_TAGS`/`_VERIFIED_EVENT_IDS` constants, 1 export smoke test, 3 CLIM-03 tests, 4 CLIM-04 tests (22 tests total in file now)
- `heatwave/science/heatwave.py` - `NO_RUN` constant, `flag_heatwave_days`, `_run_group_step`, `tag_consecutive_runs`, `detect_heatwave_events`

## Decisions Made
- Reworded the `settings.climatology.min_consecutive_days` docstring mention and collapsed a wrapped `.sort("system:time_start")` call onto a single line (see key-decisions above), purely to satisfy this plan's own literal-grep acceptance criteria (exact count 1 for each), with zero behavior change — verified by re-running the full test suite after the edit.

## Deviations from Plan

None — plan executed exactly as written. Two self-inflicted acceptance-criteria near-misses were caught and fixed during Task 2 verification (see Decisions Made) before committing; no code logic was altered, only docstring prose and line-wrapping.

## Issues Encountered
- Initial `heatwave/science/heatwave.py` draft split `.sort("system:time_start")` across two lines for readability and mentioned `settings.climatology.min_consecutive_days` twice (once in a docstring, once in code) — this tripped 2 of Task 2's automated acceptance greps requiring an exact count of 1 for each literal pattern. Reworded the docstring line and joined the `.sort(...)` call onto one line; re-ran all 22 tests plus the full suite to confirm no functional change.
- Verified `ee.List.frequency()` live with a one-line probe (`ee.List([1,1,1,-1,2,2]).frequency(1).getInfo()` -> `3`) before relying on it in `detect_heatwave_events`, per the plan's explicit instruction — confirmed available and correct on the installed `earthengine-api` version, so the `Reducer.frequencyHistogram()` fallback was not needed.

## User Setup Required

None - no external service configuration required. Live GCP credentials (`keys/service_account.json`) were already present in the environment and used to run all 21 credentialed live-EE tests to completion (`test_heatwave_module_exports` and the other export/signature smoke tests run without credentials).

## Next Phase Readiness
- `flag_heatwave_days`/`tag_consecutive_runs`/`detect_heatwave_events`'s combined output row schema (`ward_id`, `value`, `doy`, `system:time_start`, `threshold`, `is_hot`, `run_id`, `event_id`) is now the fixed contract plan 03-04 (integration) and Phase 4's batch export aggregate into the CHAP covariate table's `heatwave_days` and `heatwave_event_count` columns.
- The null-`value` policy for sub-pixel wards reaching `flag_heatwave_days` remains an explicit, documented open decision for Phase 4 (T-03-17, D-03) — this module forbids null-coalescing rather than silently resolving it.
- The `.iterate()` scale limitation at Phase 4's ~10,950-element full series is flagged in code comments as an open benchmarking task, not resolved here (D-03).
- No blockers. All three exported functions are ward-count-agnostic (D-04) and config-driven (security V5), ready for 03-04 to wire into an end-to-end pipeline call.

---
*Phase: 03-climatology-heatwave-detection*
*Completed: 2026-09-13*

## Self-Check: PASSED

- FOUND: heatwave/science/heatwave.py
- FOUND: tests/test_heatwave_detection.py
- FOUND: .planning/phases/03-climatology-heatwave-detection/03-03-SUMMARY.md
- FOUND: 538e37d (test commit)
- FOUND: 7a341ba (feat commit)
