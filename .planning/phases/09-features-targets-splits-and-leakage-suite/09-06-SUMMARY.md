---
phase: 09-features-targets-splits-and-leakage-suite
plan: 06
subsystem: forecast
tags: [leakage, truncation, poison, mutation-tests, splits]
requires: [09-05]
provides:
  - heatwave.forecast.leakage (reusable leakage checks)
affects: [09-07, 09-08]
key-files:
  created:
    - heatwave/forecast/leakage.py
    - tests/forecast/test_forecast_leakage.py
    - tests/forecast/test_forecast_leakage_frozen.py
key-decisions:
  - "Checks are bit-exact by default (atol=0.0, NaN-aware); atol is an optional documented fallback and the real-data and synthetic suites pass at atol=0"
  - "Synthetic suite uses 50 seeded random origins plus forced origins (1992-W53, 1998-W53, 1999-W01, last, positions 0-5); whole file runs in ~7 s"
requirements-completed: [FEAT-04]
duration: ~30 min
completed: 2026-10-07
---

# Phase 9 Plan 06: Leakage suite Summary

A reusable leakage module plus a synthetic suite (a)-(g) and a real-data @frozen variant; every deliberately injected leak is caught, and the real features, fitted climatology, splits and labels pass bit-exactly.

## Commits
- 88f14d7: leakage.py and synthetic suite
- c6167d2: @frozen real-data variant

## API (`heatwave.forecast.leakage`)
`LeakageError(AssertionError)`, `check_truncation_invariance(build, panel, origins, *, atol=0.0)`, `check_poison_invariance(build, panel, origins, *, modes, seed, atol=0.0)`, `check_row_truncation_invariance(build_rows, panel, origins, *, atol=0.0)`, `check_train_only_statistics(fit, panel, end, *, modes, seed)`, `check_registry(registry)`.

## Injected leaks and the check that catches each
| Injected leak | Caught by |
|---|---|
| `leak_hd_lead1` (heatwave_days at t+1, declared lookahead 0) | (a) truncation and (b) poison (both raise LeakageError naming the feature); also under atol=1e-6 |
| `leak_centered_roll3` (centred 3-week mean) | (a) and (b); also under atol=1e-6 |
| `leak_full_mean` (per-ward mean over all weeks) | (a) and (b); also under atol=1e-6 |
| Climatology fitted past the train end (whole panel; and +1 year) | (c) check_train_only_statistics |
| Nonzero `max_lookahead` (1), forbidden names (year_index, ward_id, wardcode, location, year) | (d) Registry.register ValueError; check_registry raises LeakageError for a spec that bypassed register() |

## Suite coverage
- (a)/(b): all 49 panel features, synthetic 6-ward panel, ~60 origins incl. warm-up positions 0-5 and both W53 weeks; garbage and NaN modes
- (c): main climatology at 1999-01-04, and CV-fold climatologies for 2005, 2014, 2020
- (d): registry guard; `lga_average_ward` accepted
- (f): train/validate/test target weeks disjoint per lead; train max target < i_train_end - 14; Mondays; 2020-W53 validate; per-fold embargo and disjointness
- (g): label equals heatwave_days >= 3 by an independent pandas join on (ward, target_week_start)
- Row level: issue-table feature and timing columns invariant under truncation (label columns excluded)
- @frozen (200 random wards, 10 origins incl. 1994-W04, 2004-W53, 2014-W52, 2015-W01, 2020-W53, 2021-W01, 2026-W38): truncation and poison (both modes) bit-exact; full-panel train-only statistics (garbage mode); real splits (lead 6 last train target 2014-W38, 2020-W53 validate, first test 2021-W01; lead 1 last origin in no split); 50 random label alignments

## Verification
- `pytest tests/forecast/test_forecast_leakage.py tests/forecast/test_forecast_isolation.py`: 20 passed (~9 s)
- `pytest tests/forecast/test_forecast_leakage_frozen.py -m frozen`: 6 passed locally (75 s)
- `pytest tests/forecast -q -m "not frozen"`: 380 passed, 18 deselected (104 s)

## Deviations from Plan
- Mutation tests are parametrized plus separate named tests (test_e_mutation_lead_shift_caught, centered, full_mean, climatology_fit_past_end), so each leak is individually named as the plan listed. Tests and implementation were committed together, not as separate RED/GREEN commits.

## Requirements
FEAT-04 complete (full suite (a)-(g) incl. frozen variant passes, fails on injected leaks). FEAT-01/02/03/05 left pending: 09-07/09-08 still list them (reporting and final verification).

## Self-Check: PASSED
