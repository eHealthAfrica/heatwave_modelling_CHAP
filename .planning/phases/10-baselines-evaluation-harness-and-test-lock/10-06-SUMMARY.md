---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 06
subsystem: forecast-evaluation
tags: [baselines, EVAL-01]
requires: [10-01 config, 10-04 slices.season_of]
provides: [heatwave.forecast.baselines]
affects: [10-07 harness, 10-08 script, 10-09 frozen checks, Phase 14 gate]
key-files:
  created:
    - heatwave/forecast/baselines.py
    - tests/forecast/test_forecast_baselines.py
key-decisions:
  - "Hyper-parameters are module constants (PERSISTENCE_PSEUDO=0.5, DAMPED_C=1.0, TREND_C=1e6); the models config block is never read"
  - "LogisticRegression uses its default l2 penalty (explicit penalty= is deprecated in the installed sklearn)"
requirements-completed: []
duration: ~25 min
completed: 2026-10-08
---

# Phase 10 Plan 06: Five baselines Summary

Five dense-array baselines that fit on training rows only (recent_climatology: as-of base rate), with poison tests, hand counts and an exact aggregated-vs-row-level trend fit.

## API (`heatwave.forecast.baselines`)

- `FitContext(panel, static, clim, cfg, train_index=None)`: frozen; static aligned to `panel.wards`; ValueError unless `clim.fit_end == cfg.splits.train_end`; default `train_index(lead) = dataset.lead_row_index(panel, cfg, lead, "train")`.
- Predictor shape (Protocol): `name: str`, `fit(ctx) -> self` (fits every lead in `cfg.leads`), `predict(lead, ward_pos, origin_pos) -> float32 array` (KeyError for an unfitted lead). Predictions are probabilities only.
- `ClimatologyBaseline`: pooled ISO-slot rate over the unique training target weeks (`rate[lead]` (n,53)).
- `RecentClimatologyBaseline`: `(pos + m p_state) / (cnt + m)` read at the TARGET column (`P` (n,T)); NaN only at early origins with counts < 15.
- `PersistenceBaseline`: `table[lead]` (2 y0 x 4 season x 3 geozone), `(pos+0.5)/(n+1)`, season via `slices.season_of` of the target week.
- `DampedPersistenceBaseline`: logistic on `INPUTS = (xhi_anom_lag0, y0, season_sin, season_cos)`; `coef_`/`intercept_` per lead.
- `TrendSeasonBaseline`: aggregated (target week x geozone) binomial logistic via `sample_weight`, year term centred at 2003.0 (local to this module); `coef_`/`intercept_` per lead.
- `BASELINE_REGISTRY`, `fit_baselines(ctx, names=None)` (config order), `train_base_rate(ctx, lead)`.

## Commit

- b1f54d6: baselines and tests (Tasks 1 and 2 share one file pair, committed together).

## Verification

- `pytest tests/forecast/test_forecast_baselines.py`: 12 passed in 9.5 s wall (about 4 s of module-scoped fixture fits, i.e. over the 3 s target; the whole quick loop still fits the budget).
- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 460 passed, 74 deselected, 47.8 s (50.5 s wall). Under 60 s; no tests marked slow.
- Greps: hw_base_rate_10y 0, cfg.models 0, `Climatology.fit` in tests 1, sample_weight 1, five baseline classes 5.
- Poisoned FitContexts reuse the clean Climatology (never refit on poison).

## Deviations from Plan

None in behaviour. Notes: persistence validation predictions legitimately differ under poison (y0 at validation origins is poisoned), so the poison test compares fitted tables/coefficients for it and predictions only for climatology.

## EVAL requirements

EVAL-01 not marked complete: harness scoring (10-07), report/script (10-08) and real-data magnitudes (10-09) remain.

## Known Stubs

None.

## Self-Check: PASSED
