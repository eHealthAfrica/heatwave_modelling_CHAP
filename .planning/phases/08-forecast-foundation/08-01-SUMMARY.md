---
phase: 08-forecast-foundation
plan: 01
subsystem: infra
tags: [scikit-learn, lightgbm, shap, numba, requirements]
requires: []
provides:
  - ML stack (scikit-learn 1.9.1, lightgbm 4.7.0, shap 0.52.0) installed in .venv and exactly pinned
  - tests/forecast/test_forecast_deps.py smoke tests
affects: [phase 11, phase 12, phase 14]
tech-stack:
  added: [scikit-learn 1.9.1, lightgbm 4.7.0, shap 0.52.0, scipy 1.18.1, joblib 1.6.0, numba 0.68.0, llvmlite 0.50.0, cloudpickle 3.1.2, slicer 0.0.8, threadpoolctl 3.7.0, tqdm 4.70.1]
  patterns: [requirements.txt as full exact-pin freeze; tests/forecast has no __init__.py]
key-files:
  created: [tests/forecast/test_forecast_deps.py]
  modified: [requirements.txt]
key-decisions:
  - "Shap fallback not needed: shap 0.52.0 imports and TreeExplainer runs against numpy 2.3.3"
requirements-completed: [DATA-05]
duration: ~10min
completed: 2026-10-05
---

# Phase 8 Plan 01: ML Stack Install and Pins Summary

scikit-learn 1.9.1, lightgbm 4.7.0 and shap 0.52.0 installed in .venv with 8 transitive packages, all exact-pinned in requirements.txt, with 15 smoke tests passing.

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Approve dependency dry-run | Completed by user ("approved", 2026-10-05) before install; orchestrator ran the dry-run | n/a |
| 2 | Install, pin, smoke test | Done | af6759b |

## Packages added (11)
cloudpickle 3.1.2, joblib 1.6.0, lightgbm 4.7.0, llvmlite 0.50.0, numba 0.68.0, scikit-learn 1.9.1, scipy 1.18.1, shap 0.52.0, slicer 0.0.8, threadpoolctl 3.7.0, tqdm 4.70.1. This matches the approved dry-run list exactly. The pip freeze diff before and after shows only these additions; numpy 2.3.3, pandas 2.3.2 and pyarrow 21.0.0 are unchanged.

## Verification
- `pytest tests/forecast/test_forecast_deps.py tests/test_requirements.py -q`: 16 passed
- `pip check`: no broken requirements
- Every requirements.txt line is an exact `==` pin; tests/forecast/__init__.py does not exist.
- Shap fallback was NOT triggered (no import error), so plan 08-07 has nothing extra to document in the README.

## Deviations from Plan
None to the plan's behavior. Note: requirements.txt had 107 lines and the .venv freeze had 109. The difference is iniconfig and pluggy (pytest deps), which were already missing from the file, plus a PyYAML/shapely ordering difference. Existing lines were left untouched per the plan, and only the 11 new lines were inserted.

## Known Stubs
None.

## Self-Check: PASSED
requirements.txt and tests/forecast/test_forecast_deps.py exist; commit af6759b exists.
