---
phase: 11
name: Logistic Regression per Lead
requirements: [MODEL-01, EVAL-06]
status: complete
completed: 2026-10-13
workflow: direct (no GSD agents, per user instruction 2026-10-13)
official_run: 20261013T104023Z_b82dc7bd
---

# Phase 11 Summary: Logistic Regression per Lead

## What was built

| File | Purpose |
|---|---|
| `heatwave/forecast/models/logistic.py` | `LogisticForecaster` (Predictor protocol): one L2 logistic regression per lead, fitted on `ctx.train_index(lead)` rows only, seeded subsample of at most 1.5M rows, train-fitted standardisation, no class weighting (refused if configured), non-finite features refused. `ablation_ladder()`, `year_shuffle_map()`. |
| `heatwave/forecast/evaluation/logistic_report.py` | Renders `docs/forecast/LOGISTIC_VALIDATION.md` (headline skill, ablation, negative control, decay, Murphy, coefficients, lock note). |
| `scripts/forecast_logistic.py` | Refits the baselines, fits logistic, the shuffled control and the ablation steps, stores validation predictions, scores them through the Phase 10 harness against recent_climatology, damped_persistence and trend_season. |
| `tests/forecast/test_forecast_logistic.py` | Synthetic: ladder, valid probabilities, train-only fit (poisoned future leaves coefficients unchanged), determinism, seeded subsample, shuffle map (same slot, other year, same split), shuffle keeps season and labels, class weighting refused. |
| `tests/forecast/test_forecast_logistic_script.py` | Source checks (no EE, no test split), bad arguments exit 2, slow synthetic end-to-end. |

The full model uses 57 features (all 58 registered features minus `lead_weeks`, which is constant within a per-lead model).

## Results (validation 2015-2020, B = 1000)

| Lead | Brier logistic | Best baseline | BSS vs best [week CI] | Call | BSS vs recent_climatology [week CI] |
|---|---|---|---|---|---|
| 1 | 0.1271 | damped_persistence 0.1249 | -0.017 [-0.048, 0.008] | not distinguishable | 0.069 [0.019, 0.115] |
| 2 | 0.1360 | damped_persistence 0.1322 | -0.029 [-0.057, -0.004] | worse | 0.004 [-0.028, 0.030] |
| 3-6 | 0.137-0.139 | trend_season 0.133 | -0.027 to -0.042 | worse | about 0 |

- **The logistic model does not beat the best baseline at any lead.** At lead 1 it has real skill over recent climatology, but damped persistence (4 inputs) is as good or better.
- **Calibration-in-the-large is the main defect.** Mean predicted probability is 0.105-0.117 against an observed validation rate of 0.154. Training prevalence was 8.4%, so the regime shift (Phase 9) pulls the model low. Reliability is about half the lead-1 resolution.
- **Ablation (lead 1):** season 0.011, +location 0.007, +trend 0.021, +persistence 0.047, +heat 0.074, +land 0.069. Recent heat and persistence carry the skill; the land/humidity group adds nothing at validation.
- **Negative control passes at every lead.** With year-shuffled features, lead-1 BSS vs recent drops from 0.069 to 0.010 (CI spans 0), so the lead-1 skill comes from the current weather state, not from season, place or trend alone.
- **Decay check passes:** BSS vs recent 0.069 at lead 1, -0.001 at lead 6.

## Implications for Phase 12

- Calibration on out-of-fold predictions (MODEL-03) has to handle the prevalence shift; recalibration alone may close much of the gap to damped persistence.
- Nonlinear interactions (LightGBM) must beat damped persistence at leads 1-2, not just climatology.
- Consider a recent-years training weight or a recency feature only through CV, never tuned on validation.

## Guardrails confirmed

- Test lock: 0 test runs, 0 test scores in the run, hash chain verified (real log).
- No change to `config.yaml`, `heatwave/config.py`, `forecast.yaml` or the frozen data.
- Quick test loop: 548 passed (about 64 s while a real-data run was competing for CPU).
