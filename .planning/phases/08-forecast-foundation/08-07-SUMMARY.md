---
phase: 08-forecast-foundation
plan: 07
subsystem: forecast
tags: [isolation, ci, python-3.12, readme, regression]
requires: [08-01, 08-02, 08-03, 08-04, 08-05, 08-06]
provides:
  - tests/forecast/test_forecast_isolation.py (subprocess sys.modules check, AST scan, scanner self-test)
  - CI on Python 3.12 with pip cache
  - README Python >=3.12 and forecast dependency note
affects: []
tech-stack:
  added: []
  patterns: [subprocess import-isolation, AST import scan incl. function-local and importlib calls]
key-files:
  created: [tests/forecast/test_forecast_isolation.py]
  modified: [.github/workflows/tests.yml, README.md]
key-decisions:
  - "README names shap 0.52.0 (08-01 shap fallback was not used)"
requirements-completed: []
status: complete
duration: ~30min
completed: 2026-10-05
---

# Phase 8 Plan 07: Isolation, CI 3.12, Regression Summary

The forecast package is proven free of Earth Engine imports at runtime and statically, CI is moved to Python 3.12, and all local suites are green. CI on GitHub is green on Python 3.12 (Task 3, confirmed 2026-10-06).

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Isolation tests, CI 3.12, README | done | 6513b55 |
| 2 | Full local regression | done (verification only) | none |
| 3 | Push and confirm CI green | Done: user approved push and PR #11 (2026-10-06) | n/a |

## Local results

- Full suite `pytest -q`: `358 passed, 2 skipped, 3 warnings in 299.04s` (166 pre-existing passed + 2 skipped, plus 192 forecast tests).
- Frozen suite `pytest -m frozen -q`: `8 passed, 352 deselected` (0 skipped).
- CI simulation `HEATWAVE_DATA_DIR=/nonexistent_dir pytest tests/forecast -q -rs`: `184 passed, 8 skipped` (all 8 are frozen-data skips).
- `verify_frozen.py --outputs-only`: exit 0, `4 checked, 0 mismatches, 0 missing, 0 bad keys`.
- `git status`: only local-only `outputs/` files untracked; no forecast_runs, no changes to config.yaml, heatwave/config.py or tests/test_config.py.
- Isolation tests: 3 passed. tests.yml parses as YAML, has no "3.11".

## Deviations from Plan

None - plan executed as written.

## Task 3 (checkpoint:human-verify): done 2026-10-06

The user asked to push the branch and open a PR. The branch `milestone/v2.0-heat-forecasting` was pushed, and PR #11 was opened: https://github.com/eHealthAfrica/heatwave_modelling_CHAP/pull/11

CI "Tests" ran green twice, for the push and for the PR:
- https://github.com/eHealthAfrica/heatwave_modelling_CHAP/actions/runs/37394258768
- https://github.com/eHealthAfrica/heatwave_modelling_CHAP/actions/runs/37394228123

The runs used Python 3.12.14 with scikit-learn 1.9.1, lightgbm 4.7.0 and shap 0.52.0 installed, and no libgomp step was needed. Result: **288 passed, 72 skipped**. The skips are the 8 `frozen` tests (no real data on the runner) plus the credential-gated live Earth Engine tests (no `EE_SA_JSON` secret), the same pattern as before Phase 8.

DATA-05 is complete.
