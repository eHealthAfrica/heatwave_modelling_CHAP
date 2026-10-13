---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 05
subsystem: forecast-evaluation
tags: [predictions, parquet, test-lock, EVAL-02, EVAL-05]
requires: [10-01 testlock, 10-02 metrics]
provides: [stored prediction format, lock-aware loader, key alignment]
affects: [10-06 baselines, 10-07 harness, 10-08 script, Phase 14]
key-files:
  created:
    - heatwave/forecast/evaluation/predictions.py
    - tests/forecast/test_forecast_predictions.py
key-decisions:
  - "predictions.py references testlock as a module (testlock.require_open) so fixtures can patch it"
  - "Loader checks the lock on metadata split before reading rows, and again on row split values (tampered metadata)"
requirements-completed: []
duration: ~15 min
completed: 2026-10-08
---

# Phase 10 Plan 05: Stored predictions Summary

One Parquet format (zstd, JSON provenance metadata, no pickle) for every predictor, written only inside run folders, with a test-lock-guarded loader and strict key alignment.

## Predictions API (`heatwave.forecast.evaluation.predictions`)

- Schema: `SCHEMA_VERSION = 1`, `METADATA_KEY = b"heatwave_forecast"`, `PREDICTIONS_SUBDIR`, `COLUMNS` = predictor, lead, ward, origin_week_index, target_week_index, target_week, split, p, y, fold; `DTYPES` = category, int8, category, int16, int16, category, category, float32, int8, Int8.
- `PredictionMeta(run_id, config_sha256, data_sha256, predictor, lead, split, schema_version=1, threshold=None)`: frozen, validated (run-id pattern, 64 lowercase hex, name regex, lead >= 1, split whitelist).
- `build_frame(panel, cfg, predictor, lead, split, ward_pos, origin_pos, p, *, fold=None)`: validates p (finite, in [0,1], same length), calls `testlock.require_open` for split "test" before reading labels, y from `targets.lead_label`, row splits verified against `assign_split`.
- `prediction_path(run_dir, predictor, lead, split)` -> `<run_dir>/predictions/<predictor>_L<lead>_<split>.parquet`; refuses bad names, unknown split, non-run-id folder, parent not `forecast_runs`, repo or `frozen` paths, escaping resolved parent.
- `write_predictions(df, meta, run_dir)`: column/dtype/meta consistency checks, `.tmp` then `os.replace`.
- `read_metadata(path)`: JSON only, exact field set, validated.
- `load_predictions(path, cfg, *, data_root=None) -> (df, meta)`: lock check on test metadata or test rows; validates p, y, predictor/lead/split vs metadata; no log record for validate/train files.
- `align(ref, cand) -> (r_idx, c_idx)`: lexsort on (ward code, origin_week_index); ValueError on length, ward categories, duplicate or differing keys, differing y. No `pd.merge`.

## Commits

- 33f7ad9: predictions module and tests (both plan tasks, one file pair, committed together)
- 1ce59b9: docstring reword so the "no pickle" grep acceptance returns 0

## Verification

- `pytest tests/forecast/test_forecast_predictions.py`: 9 passed in 0.72 s.
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 453 passed, 69 deselected, 59.07 s (62 s wall incl. startup). Very tight against the 60 s budget; no tests marked slow.
- Greps: pickle/eval 0, `testlock.require_open` 3, `pd.merge` 0.
- Tests use tmp roots only; the real evaluation log and forecast_runs untouched.

## Deviations from Plan

None. Tasks 1 and 2 touch the same two files and were committed together.

## EVAL requirements

EVAL-02 and EVAL-05 not marked complete: harness scoring (10-07), baselines (10-06), script and phase-gate real-log check (10-08/10-09) remain.

## Known Stubs

None.

## Self-Check: PASSED
