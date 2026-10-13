---
phase: 14
name: Explainability, One-Shot Test, Report and Go/No-Go
requirements: [DEC-01, DEC-02, DEC-03, DEC-04]
status: complete — decision NO-GO
completed: 2026-10-13
workflow: direct (no GSD agents)
runs:
  explain: 20261013T160212Z_b82dc7bd
  freeze: 20261013T160730Z_b82dc7bd
  test: 20261013T162219Z_b82dc7bd
---

# Phase 14 Summary: Explainability, One-Shot Test, Report and Go/No-Go

## What was built

| File | Purpose |
|---|---|
| `heatwave/forecast/evaluation/explain.py`, `scripts/forecast_explain.py` | DEC-01: grouped permutation importance, grouped SHAP (LightGBM TreeSHAP, exact linear SHAP for logistic) and the LightGBM ablation ladder, all on validation. Output: `docs/forecast/EXPLAINABILITY.md`. |
| `heatwave/forecast/models/frozen.py`, `scripts/forecast_freeze.py` | Pre-test freeze. Calibrators come from 2015-2020 expanding-window OOF predictions, fitted the same way for the model and for the best baseline. Final refit on 1991-2020 (targets up to the test start minus the embargo; climatology to 2021-01-04). The bundle is hash-checked and holds no data. Summary: `docs/forecast/MODEL_BUNDLE.json`. |
| `scripts/forecast_test.py`, `heatwave/forecast/evaluation/gate_report.py` | DEC-02/03/04. Requires the opened lock and the locked bundle, writes all test predictions before scoring, saves each lead at once, and writes `docs/forecast/GATE.json` and `docs/FORECAST_REPORT.md`. `--render-from` rebuilds them without scoring. |
| `heatwave/forecast/baselines.py` | `FitContext(fit_end=...)` takes an explicit climatology window, which needs an explicit `train_index`. |
| `docs/forecast/PREREGISTRATION.md` | Approved by the user and committed (blob `d7472e4c…`) before the lock opened. |
| Tests | `test_forecast_explain.py`, `test_forecast_gate.py` (decision rule, cautions, pre-test rows and embargo, bundle hash, closed-lock refusal, and the full synthetic freeze → single test → re-render → second run refused). The Phase 10 "no pre-registration yet" guard is replaced by a Phase 14 completeness check. |

## Explainability (validation, DEC-01)

- **Lead 1:** lagged heat dominates (74% of SHAP; shuffling it raises Brier by 118 × 10⁻⁴, about the whole gap between damped persistence and recent climatology).
- **Longer leads:** soil/humidity/rain and trend grow in share. For logistic at leads 5-6, persistence and soil/humidity/rain carry the permutation importance.
- **Trend features:** shuffling them *improves* validation Brier at every lead (−1.4 to −4.0 × 10⁻⁴). The trend group hurts under the post-2014 shift, which is consistent with the extrapolation finding.
- **Ablation with the tuned LightGBM:** lead 1 reaches BSS 0.085 vs recent climatology at +heat, equal to damped persistence (0.085). Land adds nothing.

## The single test (2021-2026)

Lock opened 2026-10-13T16:21:14Z by "Adedo Lukmon (approved 2026-10-13)". The evaluation log shows exactly 1 test run, and the hash chain is intact.

| Lead | BSS vs reference [week CI] | Year CI | Skill (rule) | vs recent climatology |
|---|---|---|---|---|
| 1 | -0.052 [-0.087, -0.014] vs damped_persistence_recal | [-0.087, -0.007] | no | 0.141 |
| 2 | -0.034 [-0.044, -0.021] | [-0.050, -0.018] | no | -0.000 |
| 3 | -0.016 [-0.031, -0.007] vs trend_season_recal | [-0.039, -0.003] | no | -0.061 |
| 4 | -0.015 [-0.030, -0.004] | [-0.043, -0.005] | no | -0.060 |
| 5 | 0.006 [-0.008, 0.014] | [-0.017, 0.021] | no | -0.038 |
| 6 | 0.021 [0.005, 0.030] | [-0.006, 0.039] | yes | -0.022 |

- **Decision: NO-GO** (leads 1 and 2 fail; both are significantly worse than the recalibrated damped persistence).
- **Lead 6 passes the rule, but the pass is fragile.** Its year CI includes 0, it is worse than recent climatology, and it is miscalibrated. The report carries a generated caution, which does not change the decision.
- **Calibration fails at every lead** (mean p 0.049-0.065 below observed). The test-period heatwave rate (about 21.5%) is above the 2015-2020 calibration years (15.4%); the regime shift continued.
- **Report:** ECMWF S2S benchmark recommended (DEC-04).

## Implications

- **Phase 15 (operational) is gated to the leads that passed.** Only lead 6 passed, and fragilely, so it is a user decision whether to operationalise lead 6 alone. My recommendation is not to.
- **Phase 16 (climate drivers) also depends on the gate.** It and the ECMWF S2S benchmark (FUT-01) are the natural next steps to look for skill the ward history lacks.
- **The heatwave covariate table for CHAP (v1.0, detection layer) is unaffected.** It remains the deliverable.
