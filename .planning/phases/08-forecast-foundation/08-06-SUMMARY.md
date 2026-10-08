---
phase: 08-forecast-foundation
plan: 06
subsystem: forecast
tags: [verification, integrity, sha256, frozen-data, integration-tests]
requires: [08-04, 08-05]
provides:
  - scripts/verify_frozen.py CLI integrity check (outputs, forecast.yaml anchor, 361 MANIFEST inputs, copied inputs)
  - tests/forecast/test_forecast_verify_script.py CI-safe synthetic subprocess tests (12)
  - tests/forecast/test_forecast_frozen.py real-data tests (7, @pytest.mark.frozen)
affects: [08-07]
tech-stack:
  added: []
  patterns: [read-only "rb" hashing, MANIFEST key containment (BAD-KEY), exit codes 0/1/2]
key-files:
  created: [scripts/verify_frozen.py, tests/forecast/test_forecast_verify_script.py, tests/forecast/test_forecast_frozen.py]
  modified: []
key-decisions:
  - "Read-only file mode is reported as NOTE only, never a failure"
  - "Real-data tamper tests copy the parquet (and a parquet-only MANIFEST) to tmp_path; the 517 MB CSV is never copied"
requirements-completed: [DATA-01, DATA-02, DATA-04]
duration: ~25min
completed: 2026-10-05
---

# Phase 8 Plan 06: verify_frozen and Real-Data Tests Summary

`scripts/verify_frozen.py` re-hashes the frozen outputs, the forecast.yaml anchor, all MANIFEST inputs and the copied `inputs/`, and the real `covariates-v1.0` data is now proven through the loader, week axis, value round-trip, tamper rejection and run-folder provenance.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | verify_frozen.py + synthetic subprocess tests | 56cdb58 |
| 2 | Real-data integration tests | 440ab77 |

## Verification

- `verify_frozen.py --outputs-only` (real data), exit 0: `verify_frozen: 4 checked, 0 mismatches, 0 missing, 0 bad keys` (re-run at the end of the plan, after all tests: same result, exit 0).
- Full-mode run on real data (361 inputs plus copied inputs, about 20 s), exit 0: `verify_frozen: 376 checked, 0 mismatches, 0 missing, 0 bad keys`.
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q`: 248 passed.
- `pytest -m frozen -q`: 8 passed, 0 skipped. `test_forecast_frozen.py` alone: 7 passed; with `HEATWAVE_DATA_DIR=/nonexistent_dir`: 7 skipped.
- Real panel: shape (4841, 1863, 8), float32, no NaN, sha256 82583fbf..., labels equal `index_labels(1863)`, six in-data W53 weeks, 7-day steps.

## Deviations from Plan

None in behavior. Tasks were committed code-plus-tests together (no separate RED commits). The UNLISTED count is appended to the summary line only when non-zero.

## Known Stubs
None.

## Threat Flags
None. T-8-01, T-8-12 and T-8-17 mitigations are implemented and tested; no `forecast_runs` folder was left in the real data root (run-folder test uses tmp_path).

## Self-Check: PASSED
All three files exist; commits 56cdb58 and 440ab77 exist; real frozen folder unchanged.
