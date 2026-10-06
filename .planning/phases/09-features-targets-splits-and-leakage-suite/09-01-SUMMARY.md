---
phase: 09-features-targets-splits-and-leakage-suite
plan: 01
subsystem: forecast
tags: [config, fixtures, testing, leakage]
requires: []
provides:
  - SplitsConfig.cv_first_year (2005) and embargo_weeks 14
  - heatwave.forecast.fixtures synthetic panel and manipulation helpers
  - tests/forecast/conftest.py session fixtures
affects: [09-02, 09-03, 09-04, 09-05, 09-06, 09-07, 09-08]
tech-stack:
  added: []
  patterns: [in-memory synthetic Panel, copy-on-write panel helpers, session-scoped real panel]
key-files:
  created:
    - tests/forecast/conftest.py
    - tests/forecast/test_forecast_fixtures.py
  modified:
    - heatwave/forecast/config.py
    - forecast.yaml
    - tests/forecast/test_forecast_config.py
    - heatwave/forecast/fixtures.py
key-decisions:
  - "cv_first_year validated in SplitsConfig: int (not bool), train_years[0] < y <= validate_years[1]"
  - "embargo_weeks 14 = max(leads) 6 + longest short feature window 8; validator rule (>= max(leads)) unchanged"
requirements-completed: []
duration: ~25 min
completed: 2026-10-06
---

# Phase 9 Plan 01: Config and test fixtures Summary

Added `splits.cv_first_year` (2005) with strict validation, set `embargo_weeks` to 14, and built the synthetic Panel, panel-manipulation helpers, a synthetic static-metadata fixture and session-scoped real-panel fixtures that the rest of Phase 9 tests against.

## Commits
- 5337ece: config (cv_first_year, embargo 14, tests)
- fb4e816: fixtures and conftest

## Public APIs for later plans
`heatwave.forecast.fixtures`:
- `synthetic_panel(*, first_week="1991-W02", last_week="2003-W20", seed=0, wards=SYNTHETIC_WARDS) -> Panel` (6 wards, float32, read-only, includes 1992-W53 and 1998-W53; event count independent of heatwave_days)
- `truncate_panel(panel, last_pos)` keeps positions 0..last_pos
- `poison_future(panel, last_pos, *, mode="garbage"|"nan", seed=0)` overwrites positions > last_pos
- `subset_panel(panel, ward_positions)` sorted unique wards
- `synthetic_static_sources(wards) -> (geojson_dict, lga_average_rows)`: Kano NWZ lat 12.0, Katsina NEZ lat 10.5, Sokoto NCZ lat 9.0 (lgacode "7023" unpadded); SOCCC002 has empty MultiPoint geometry and is the LGA-average ward
- `add_synthetic_static(sf)` writes `inputs/wards.geojson` and `wards_lga_average.csv` under the tmp dataset dir and registers both sha256 in MANIFEST
- all helpers return new Panels (sha256 derived), never mutate the input

`tests/forecast/conftest.py` session fixtures: `forecast_cfg`, `frozen_panel` (skips when frozen data absent).

Config: `cfg.splits.cv_first_year == 2005`, `cfg.splits.embargo_weeks == 14`.

## Deviations from Plan
None. `frozen_panel` checks frozen-data presence directly through `heatwave.config.settings` rather than importing `tests/conftest.py` (avoids a duplicate-conftest import clash).

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 268 passed, 8 deselected
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py`: 59 passed
- config.yaml, heatwave/config.py, tests/test_config.py untouched

## Requirements
FEAT-04 and FEAT-05 are foundation-only here; left pending (they span later plans).

## Self-Check: PASSED
