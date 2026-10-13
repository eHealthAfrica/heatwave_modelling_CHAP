---
phase: 12
name: LightGBM, Calibration and Selection
requirements: [MODEL-02, MODEL-03, MODEL-04]
status: complete with one criterion not met (reliability tolerance)
completed: 2026-10-13
workflow: direct (no GSD agents, per user instruction 2026-10-13)
official_run: 20261013T124205Z_b82dc7bd
---

# Phase 12 Summary: LightGBM, Calibration and Selection

## What was built

| File | Purpose |
|---|---|
| `heatwave/forecast/models/lgbm.py` | `LightGBMForecaster` (deterministic, 8 fixed threads, class reweighting refused). Six regularised grid configs. `run_cv` does expanding-window CV on training-era folds 2010-2014: each fold refits climatology and features on its own past, early stopping uses the fold's last 52 training target weeks behind a 14-week embargo, and the fold year is predicted out of fold. `select_config` picks by mean fold Brier with trees = median early-stopping iteration. |
| `heatwave/forecast/models/calibration.py` | Platt or isotonic chosen by leave-one-fold-out Brier on OOF rows, refitted on all OOF rows, clipped to [0.001, 0.999]. |
| `heatwave/forecast/evaluation/extrapolation.py` | Share of evaluation feature values outside the training range (MODEL-04). |
| `heatwave/forecast/evaluation/lightgbm_report.py` | Report, the stated reliability tolerance, and the reliability figure. |
| `scripts/forecast_lightgbm.py` | CV, calibration, selection by CV Brier, final fits, validation scoring against the baselines and logistic; writes `docs/forecast/LIGHTGBM_VALIDATION.md`, `docs/forecast/MODEL_SELECTION.json` and `docs/forecast/figures/phase12_reliability.png`. |
| Tests | `test_forecast_lgbm.py` (calibration, LOFO isolation, determinism, train-only fit, fold row ordering, CV and selection, extrapolation) and `test_forecast_lightgbm_script.py`. |

Candidates per lead: logistic, logistic_cal, lightgbm, lightgbm_cal. Selection uses CV Brier only, before validation is seen.

## Results (validation 2015-2020, B = 1000)

| Lead | Selected (CV) | Trees | BSS vs best baseline [week CI] | Call | BSS vs recent climatology [week CI] |
|---|---|---|---|---|---|
| 1 | lightgbm | 30 | -0.002 [-0.040, 0.028] vs damped_persistence | not distinguishable | 0.083 [0.050, 0.110] |
| 2 | lightgbm | 12 | -0.005 [-0.030, 0.015] vs damped_persistence | not distinguishable | 0.026 [0.005, 0.042] |
| 3 | lightgbm | 20 | -0.015 [-0.035, 0.005] vs trend_season | not distinguishable | 0.010 |
| 4 | lightgbm | 27 | -0.010 [-0.028, 0.009] | not distinguishable | 0.015 |
| 5 | logistic | - | -0.031 [-0.055, -0.006] | worse | -0.005 |
| 6 | logistic | - | -0.027 [-0.049, -0.003] | worse | -0.001 |

- **No model beats the best baseline at any lead.** At leads 1-2 LightGBM ties damped persistence. That is the best of the trained models, but not a pass of the gate.
- **LightGBM beats logistic** at leads 2-6 (paired BSS 0.023-0.031, both CIs above 0); at lead 1 the difference is not distinguishable.
- **Early stopping is very early** (10-30 trees at learning rate 0.05): the learnable signal beyond season, trend and persistence is small.
- **At leads 5-6 the CV selection picked logistic**, though LightGBM is better on validation. The rule was applied as fixed in advance; the report shows all candidates.
- **Reliability tolerance (criterion 3) is NOT met.** Every candidate under-predicts by 0.04-0.07 (mean p minus observed rate). Calibration makes it worse, because the calibration folds (2010-2014) have a much lower heatwave rate than 2015-2020, so OOF calibrators learn to push probabilities down. This is the train-to-validation prevalence shift (8.4% to 15.4%) seen since Phase 9.
- **Extrapolation (MODEL-04):** 22 of 55 features have some validation values outside the training range. The 3-year mean Heat Index anomaly (`mhi_anom_mean156`) has 7.7% of validation values above the training maximum, which is the warming signal. All other features are at or below 0.24%.

## Requirement status

- MODEL-02: complete.
- MODEL-04: complete.
- MODEL-03: implemented as specified (OOF, chosen by CV Brier, clipped, no row overlap), but criterion 3 (reliability within tolerance on validation) fails. Needs a user decision; options below.

## Options for the calibration gap (user decision)

1. **Calibrate on recent folds for the test.** `retrain_policy.pre_test_refit_years` is 1991-2020, and the CV folds already run to 2020. Before the single test, refit with calibrators from OOF folds 2015-2020. This needs no new data, but its validation evidence would be leave-one-year-out within 2015-2020 rather than a clean held-out split.
2. **Add an explicit recency signal** (e.g. a recent base-rate feature with a short window, or year-weighted fitting), chosen by CV only.
3. **Accept and document.** Report the miscalibration and judge by Brier and BSS only. Phase 13 is deferred anyway, because Phase 12 shows no skill over the best baseline.

## Guardrails confirmed

- Test lock: 0 test runs, 0 test scores in the run, hash chain verified (real log).
- No change to `config.yaml`, `heatwave/config.py`, `forecast.yaml` or the frozen data. Tuned settings live in `docs/forecast/MODEL_SELECTION.json` (generated).
- Quick test loop: 561 passed in 52 s. The script argument tests now run in-process.
