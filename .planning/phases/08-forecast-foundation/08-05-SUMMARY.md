---
phase: 08-forecast-foundation
plan: 05
subsystem: forecast
tags: [provenance, run-folder, manifest, git, reproducibility]
requires: [08-01, 08-03]
provides:
  - heatwave/forecast/artifacts.py run folders with config snapshot and RUN_MANIFEST.json
affects: [08-06, 08-07, 10, 11, 12]
tech-stack:
  added: []
  patterns: [atomic manifest write (tmp + os.replace), in-repo base refusal, collision suffix _01.._99, fixed-argv git subprocess]
key-files:
  created: [heatwave/forecast/artifacts.py, tests/forecast/test_forecast_artifacts.py]
  modified: []
key-decisions:
  - "Manifest written at start (status running) and rewritten atomically at finish so crashes leave evidence"
  - "Seed is recorded only; later phases use numpy.random.default_rng(cfg.seed)"
requirements-completed: []
requirements-progress: [DATA-04 (run folders and manifest done; real-data run-folder test in 08-06)]
duration: ~15min
completed: 2026-10-05
---

# Phase 8 Plan 05: Run Folders Summary

Reproducible run folders under `<data_root>/forecast_runs/<run_id>/` holding a validated `config.yaml` snapshot and a `RUN_MANIFEST.json` with data version and parquet sha256, git commit and dirty flag, Python/platform and six library versions, seed, config sha256, UTC start/end and status.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | make_run_id, git_info, library_versions | 2ab16ae |
| 2 | start_run / finish_run / run_folder | 0c8489c |

## Public API
`RUNS_SUBDIR, TRACKED_PACKAGES, RunContext, make_run_id, git_info, library_versions, start_run, finish_run, run_folder` (also `REPO_ROOT, RUN_ID_PATTERN, MANIFEST_NAME`).

## Verification
- tests/forecast/test_forecast_artifacts.py: 22 passed (tmp_path data roots only).
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q`: 229 passed.
- No `forecast_runs` folder in the repo after tests; no `shell=True`; `os.replace` used.

## Requirements
DATA-04 left in progress: the real-data run-folder test belongs to plan 08-06.

## Deviations from Plan
Tasks were committed code-plus-tests together (no separate RED commits). Note: default `settings.local_data_dir` is `<repo>/data`, so calling `start_run` without `data_root` under the default setting is refused by design; callers must point `HEATWAVE_DATA_DIR` or `data_root` outside the repo.

## Known Stubs
None.

## Threat Flags
None.

## Self-Check: PASSED
artifacts.py and test_forecast_artifacts.py exist; commits exist.
