---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 03
subsystem: forecast-evaluation
tags: [test-lock, dataset-guards, EVAL-05]
requires: [10-01 testlock and fixtures]
provides: [guarded lead_rows, label-blanking build_issue_table]
affects: [10-05, 10-07, Phase 14]
key-files:
  modified:
    - heatwave/forecast/dataset.py
    - tests/forecast/test_forecast_dataset.py
    - tests/forecast/test_forecast_leakage.py
key-decisions:
  - "dataset.py imports the testlock module and calls testlock.require_open / testlock.labels_unlocked so fixtures can patch them; no bypass parameter"
  - "lead_row_index stays unguarded (report row counts)"
requirements-completed: []
duration: ~15 min
completed: 2026-10-08
---

# Phase 10 Plan 03: Dataset test-lock guards Summary

lead_rows(split="test", no fold) now raises TestLockError and logs the refusal while the lock is closed; build_issue_table blanks test-split labels (heatwave_week_l{k} NaN, has_label_l{k} False) and logs one "blanked" record, leaving features and timing unchanged. No log record is written when no test targets are present or for train/validate/fold selections.

## Commits
- fba54bd: guards in dataset.py plus new/updated dataset tests (refused, open, blanked, kept-when-open, no-log cases; module-scoped 2027-W10 panel fixture)
- a39a6f8: test_f_split_integrity opts in via allow_test_rows (the only leakage-suite change; other issue-table helpers compare truncated vs full panels, unaffected)

## Verification
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 421 passed, 68 deselected in about 55 s.
- Frozen tests (test_forecast_leakage_frozen.py, test_forecast_frozen.py): 13 passed locally in 105 s.
- Dataset, leakage and report modules (not slow): 47 passed.
- Greps: require_open 1, labels_unlocked 1, `allow_test` in heatwave/ 0, `from heatwave.forecast.testlock import` 0.

## Deviations from Plan
None. Test-split detection in build_issue_table uses the literal "test" split name.

## EVAL-05 status
Not marked complete: prediction loader (10-05) and phase-gate real-log check (10-09) remain.

## Known Stubs
None.

## Self-Check: PASSED
