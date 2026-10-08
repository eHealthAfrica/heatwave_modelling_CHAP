---
phase: 08-forecast-foundation
plan: 04
subsystem: forecast
tags: [data, parquet, sha256, loader, fixtures]
requires: [08-02, 08-03]
provides:
  - heatwave/forecast/data.py hash-verified frozen loader and dense float32 Panel
  - heatwave/forecast/fixtures.py synthetic frozen dataset for CI
affects: [08-06, 08-07, 09]
tech-stack:
  added: []
  patterns: [hash-before-parse, double anchor (MANIFEST + forecast.yaml), position-array panel fill (never row order)]
key-files:
  created: [heatwave/forecast/data.py, heatwave/forecast/fixtures.py, tests/forecast/test_forecast_data.py]
  modified: []
key-decisions:
  - "Check order: MANIFEST version, parquet exists, source path allow-list, raw-byte sha256 vs MANIFEST then forecast.yaml, then metadata-only schema peek, then full read"
  - "Panel week axis is the contiguous global week index range from MANIFEST first/last week; wards sorted"
requirements-completed: []
requirements-progress: [DATA-01 (loader done; needs 08-06 verify_frozen.py and real-data tests), DATA-02 (week axis wired; needs 08-06 parity), DATA-05 (synthetic fixture done; needs 08-07)]
duration: ~20min
completed: 2026-10-05
---

# Phase 8 Plan 04: Frozen Loader Summary

Checksum-verified loader producing a dense (ward, week, 8) float32 Panel from the frozen `covariates-v1.0` parquet, plus a seeded synthetic frozen dataset (6 wards, 3 states, 1991-W02..1993-W05 including 1992-W53) so CI runs without the real data.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Constants, sha256_file, synthetic builder | ff848fe |
| 2 | Verify-then-load, assert_frozen_source, Panel | dce24ec |

## Public API (for Phase 9)

data.py:
- `FrozenDataError(RuntimeError)`
- `sha256_file(path, chunk_size=1<<20) -> str`
- `frozen_dataset_dir(data_cfg, data_root=None) -> Path`
- `read_manifest(dataset_dir) -> dict`
- `assert_frozen_source(path, data_cfg, data_root=None) -> Path`
- `verify_frozen_parquet(data_cfg, data_root=None) -> (Path, dict, str)`
- `Panel(values, wards, week_index, week_labels, week_start, variables, version, sha256)` with `ward_pos(code)`, `week_pos(label)`, `.shape`
- `load_panel(data_cfg, data_root=None) -> Panel`
- constants `PARQUET_NAME, MANIFEST_NAME, ID_COLUMNS, VARIABLES, EXPECTED_COLUMNS, INTEGER_VARIABLES, EXPECTED_ARROW_TYPES`

fixtures.py:
- `build_synthetic_frozen(data_root, *, version="covariates-v1.0", first_week="1991-W02", last_week="1993-W05", seed=0, with_inputs=True) -> SyntheticFrozen`
- `SyntheticFrozen(data_root, dataset_dir, parquet_path, manifest_path, sha256, wards, labels, frame)`; helper `arrow_schema()`

## Verification
- tests/forecast/test_forecast_data.py: 26 tests (acceptance, byte flip with read_parquet never called, tampered MANIFEST+parquet pair, missing files, version mismatch, schema/dtype, count mismatches, dropped week, duplicate cell, live CSV and foreign paths).
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q`: 207 passed.
- No write-mode `open(` and no chmod in data.py. Real frozen data was not touched.

## Requirements
DATA-01, DATA-02, DATA-05 left in progress: they need 08-06 (verify_frozen.py, real-data tests, parity check) and 08-07.

## Deviations from Plan
Task 1 was committed without the test file (it imports Task 2 symbols), so the tests arrived in the Task 2 commit and there is no separate RED commit. No behavioural deviations.

## Known Stubs
None.

## Threat Flags
None.

## Self-Check: PASSED
data.py, fixtures.py, test_forecast_data.py exist; commits ff848fe, dce24ec exist.
