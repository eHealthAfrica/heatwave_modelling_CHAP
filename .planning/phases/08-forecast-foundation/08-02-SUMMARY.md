---
phase: 08-forecast-foundation
plan: 02
subsystem: forecast
tags: [iso-week, week-index, pytest, conftest, python-3.12]
requires: []
provides:
  - heatwave/forecast/weeks.py ISO label <-> integer index <-> week_start conversions (53-week safe)
  - tests/conftest.py frozen marker auto-skip and frozen_dir fixture
  - requires-python >=3.12 and registered frozen pytest marker
affects: [08-03, 08-04, 08-05, 08-06, 08-07]
tech-stack:
  added: []
  patterns: [all time arithmetic via integer index or week_start dates, frozen-data tests auto-skipped when absent]
key-files:
  created: [heatwave/forecast/__init__.py, heatwave/forecast/weeks.py, tests/forecast/test_forecast_weeks.py, tests/conftest.py]
  modified: [pyproject.toml]
key-decisions:
  - "Index 0 = 1991-W02 (1991-01-07); negative indices allowed for pre-epoch weeks"
  - "labels_to_indices parses each unique label once via a dict cache, for 9M-row columns"
requirements-completed: []
duration: ~10min
completed: 2026-10-05
---

# Phase 8 Plan 02: ISO Week Index and Test Infrastructure Summary

A 53-week-safe ISO week index (stdlib `fromisocalendar` plus numpy) with a frozen-data pytest marker that auto-skips when `covariates-v1.0` is absent, and Python 3.12 declared.

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 | Week index module, test-first | 8a35ccf (RED), a1210d3 (GREEN) |
| 2 | Frozen marker, conftest, Python 3.12 | dcf7fbb |

## Verification
- tests/forecast/test_forecast_weeks.py: 35 tests (34 plus 1 frozen); round trip over all 1,863 indices, all seven 53-week years, invalid labels rejected.
- Frozen test passes locally (`-m frozen`); with `HEATWAVE_DATA_DIR=/nonexistent_dir` it skips with "frozen covariates-v1.0 data not found".
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q`: 109 passed. tests/test_config.py: 35 passed.
- config.yaml, heatwave/config.py and tests/test_config.py untouched.

## Requirements
DATA-02 and DATA-05 remain open. DATA-02 needs the frozen-data parity check (plan 08-06); DATA-05 needs CI 3.12 and isolation (plan 08-07). This plan delivers the week index module and the 3.12 / frozen marker pieces only.

## Deviations from Plan
- The RED commit contained the unit tests only. The `frozen` fixture test was added in Task 2 together with conftest, because it cannot run before the fixture exists. No behavioural change.
- Commit trailer used is `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (the attribution given by the harness system context) rather than the "Opus 5.5" line in the orchestrator prompt; agent messages cannot override that.

## Known Stubs
None.

## Self-Check: PASSED
All listed files exist; commits 8a35ccf, a1210d3, dcf7fbb exist.
