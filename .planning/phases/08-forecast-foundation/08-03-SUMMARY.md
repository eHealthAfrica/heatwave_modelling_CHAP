---
phase: 08-forecast-foundation
plan: 03
subsystem: forecast
tags: [config, yaml, dataclasses, validation, splits]
requires: [08-02]
provides:
  - forecast.yaml repo-root settings (data anchor, splits, leads, latency, baselines, gate, retrain policy, models, seed)
  - heatwave/forecast/config.py frozen validated ForecastConfig, load_forecast_config, config_to_dict, config_hash
affects: [08-04, 08-05, 08-06, 08-07]
tech-stack:
  added: []
  patterns: [frozen dataclasses with __post_init__ validation, yaml.safe_load only, canonical JSON hash for run folders]
key-files:
  created: [forecast.yaml, heatwave/forecast/config.py, tests/forecast/test_forecast_config.py]
  modified: []
key-decisions:
  - "Split cutoffs must equal Monday of ISO week 1 of the next split's first year; 2020-W53 is in validate"
  - "Cross-section rules (embargo >= max(leads), primary_leads subset of leads, refit years) live in ForecastConfig.__post_init__"
  - "data.version and frozen_subdir are regex-restricted to block path traversal"
requirements-completed: [DATA-03]
duration: ~20min
completed: 2026-10-05
---

# Phase 8 Plan 03: Forecast Config Summary

A validated repo-root `forecast.yaml` loaded by `yaml.safe_load` into a frozen, hashable `ForecastConfig`, with a canonical dict and sha256 hash for run folders.

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 | forecast.yaml and dataclasses, valid-load path | de7fcda (RED), 64191a7 (GREEN) |
| 2 | Validation rules and rejection matrix | 58ded00 (RED), 42ed230 (GREEN) |

## Verification
- tests/forecast/test_forecast_config.py: 72 tests (valid load, hash, snapshot round-trip, 50 parametrized rejections, safe_load tag refusal, untouched-config check).
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q`: 181 passed.
- `git diff --exit-code -- config.yaml heatwave/config.py tests/test_config.py` is clean; no `yaml.load(` in config.py.

## Requirements
DATA-03 complete: forecast.yaml holds splits, leads, latency, baselines, hyperparameters, gate, retrain policy, seed and the data anchor; invalid values raise ValueError.

## Deviations from Plan
None in behaviour. A first attempt at patching config.py via a shell script failed on quoting, so the file was rewritten in full with validation included; tests and commits were unaffected. Commit trailer is `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Known Stubs
None.

## Threat Flags
None.

## Self-Check: PASSED
forecast.yaml, heatwave/forecast/config.py, tests/forecast/test_forecast_config.py exist; commits de7fcda, 64191a7, 58ded00, 42ed230 exist.
