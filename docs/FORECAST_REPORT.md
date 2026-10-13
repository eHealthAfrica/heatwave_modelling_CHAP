# Heatwave forecast report: single test evaluation (2021-2026)

heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT; test 2021-2026, scored once

**Decision: NO-GO.** BSS of 'forecast' against the pre-registered reference > 0.0 with the paired week-block CI lower bound > 0.0, on every primary lead (primary leads 1, 2).

**No skill beyond the best baseline at leads 1, 2, 3, 4, 5.** The trained forecast does not beat the pre-registered reference on the primary leads, so it is not released as a skilful forecast. Recommended next step: benchmark against the ECMWF sub-seasonal (S2S) reforecasts, which carry large-scale drivers (e.g. the MJO) that ward-level reanalysis history alone cannot. Phase 15 runs only for leads that passed (6).

**Caution on the leads that passed the rule.** Lead 6: the whole-year bootstrap CI includes 0; it is worse than recent climatology (BSS -0.022); its probabilities are outside the calibration tolerance. A pass this fragile is not enough on its own to release an operational forecast; this is a reporting note and does not change the pre-registered decision.

## How to read this

- **Two layers.** The heatwave *detection* layer (which weeks are heatwave weeks) is rule-based: 3+ heatwave days in the week from ERA5-Land Heat Index thresholds. The *forecast* layer is the trained model scored here. Only the forecast layer is judged in this report.
- **Labels are reanalysis.** ERA5-Land, not station-confirmed observations.
- **Pre-registered.** The rule, reference and model were fixed in `docs/forecast/PREREGISTRATION.md` (git blob `d7472e4cabc6…`) before the test years were opened. The evaluation log shows 1 test run(s).
- **Model.** Per lead: lead 1 lightgbm, lead 2 lightgbm, lead 3 lightgbm, lead 4 lightgbm, lead 5 logistic, lead 6 logistic; refitted on 1991-2020 with frozen settings and calibrated on 2015-2020 out-of-fold predictions (bundle sha256 `f27f9bafc986…`).
- **Reference.** The best baseline per lead, recalibrated on 2015-2020 the same way as the model.

## 1. Skill by lead (all wards, 2021-2026)

| Lead | Days ahead | Brier forecast | Reference (Brier) | BSS vs reference [week CI] [year CI] | Skill | BSS vs raw best baseline | BSS vs recent climatology |
|---|---|---|---|---|---|---|---|
| 1 | +1 | 0.1437 | damped_persistence_recal (0.1365) | -0.052 [-0.087, -0.014] [-0.087, -0.007] | no | -0.057 | 0.141 |
| 2 | +8 | 0.1673 | damped_persistence_recal (0.1618) | -0.034 [-0.044, -0.021] [-0.050, -0.018] | no | -0.038 | -0.000 |
| 3 | +15 | 0.1775 | trend_season_recal (0.1747) | -0.016 [-0.031, -0.007] [-0.039, -0.003] | no | -0.022 | -0.061 |
| 4 | +22 | 0.1773 | trend_season_recal (0.1746) | -0.015 [-0.030, -0.004] [-0.043, -0.005] | no | -0.020 | -0.060 |
| 5 | +29 | 0.1736 | trend_season_recal (0.1746) | 0.006 [-0.008, 0.014] [-0.017, 0.021] | no | 0.001 | -0.038 |
| 6 | +36 | 0.1710 | trend_season_recal (0.1746) | 0.021 [0.005, 0.030] [-0.006, 0.039] | yes | 0.017 | -0.022 |

## 2. Effective lead and skill mask

A forecast is issued at the end of the last observed week ("now"); lead k targets the week starting 7k - 6 days later. The real ERA5-Land delay (about 9 days) is an operational note, not part of this test.

| Lead | Target week | Days ahead (to target Monday) | Skill mask |
|---|---|---|---|
| 1 | issue week + 1 | +1 | do not use |
| 2 | issue week + 2 | +8 | do not use |
| 3 | issue week + 3 | +15 | do not use |
| 4 | issue week + 4 | +22 | do not use |
| 5 | issue week + 5 | +29 | do not use |
| 6 | issue week + 6 | +36 | use |

## 3. Skill by season (exploratory)

| Lead | Season | n | BSS vs reference [week CI] |
|---|---|---|---|
| 1 | DJF | 353,393 | -0.039 [-0.118, 0.034] |
| 1 | MAM | 377,598 | -0.040 [-0.083, -0.002] |
| 1 | JJA | 382,439 | -0.072 [-0.143, -0.010] |
| 1 | SON | 329,188 | -0.046 [-0.132, 0.029] |
| 2 | DJF | 353,393 | -0.008 [-0.035, 0.031] |
| 2 | MAM | 377,598 | -0.029 [-0.048, -0.008] |
| 2 | JJA | 382,439 | -0.037 [-0.056, -0.021] |
| 2 | SON | 329,188 | -0.052 [-0.073, -0.012] |
| 3 | DJF | 353,393 | -0.038 [-0.204, 0.014] |
| 3 | MAM | 377,598 | -0.000 [-0.023, 0.018] |
| 3 | JJA | 382,439 | -0.017 [-0.028, -0.009] |
| 3 | SON | 329,188 | -0.023 [-0.049, -0.008] |
| 4 | DJF | 353,393 | -0.028 [-0.192, 0.024] |
| 4 | MAM | 377,598 | 0.003 [-0.022, 0.022] |
| 4 | JJA | 382,439 | -0.020 [-0.032, -0.012] |
| 4 | SON | 329,188 | -0.022 [-0.051, -0.008] |
| 5 | DJF | 353,393 | -0.017 [-0.205, 0.031] |
| 5 | MAM | 377,598 | 0.015 [-0.003, 0.029] |
| 5 | JJA | 382,439 | 0.007 [-0.004, 0.014] |
| 5 | SON | 329,188 | 0.006 [-0.025, 0.018] |
| 6 | DJF | 353,393 | -0.018 [-0.225, 0.034] |
| 6 | MAM | 377,598 | 0.026 [0.004, 0.040] |
| 6 | JJA | 382,439 | 0.026 [0.013, 0.036] |
| 6 | SON | 329,188 | 0.028 [-0.004, 0.040] |

## 4. Skill by region (geopolitical zone, exploratory)

| Lead | Geozone | n | BSS vs reference [week CI] |
|---|---|---|---|
| 1 | NWZ | 597,192 | -0.035 [-0.076, 0.010] |
| 1 | NEZ | 393,062 | -0.049 [-0.102, 0.005] |
| 1 | NCZ | 452,364 | -0.068 [-0.114, -0.024] |
| 2 | NWZ | 597,192 | -0.024 [-0.037, -0.006] |
| 2 | NEZ | 393,062 | -0.024 [-0.039, -0.005] |
| 2 | NCZ | 452,364 | -0.046 [-0.060, -0.031] |
| 3 | NWZ | 597,192 | -0.020 [-0.045, -0.003] |
| 3 | NEZ | 393,062 | -0.024 [-0.051, -0.009] |
| 3 | NCZ | 452,364 | -0.011 [-0.018, -0.004] |
| 4 | NWZ | 597,192 | -0.017 [-0.043, -0.000] |
| 4 | NEZ | 393,062 | -0.022 [-0.049, -0.004] |
| 4 | NCZ | 452,364 | -0.011 [-0.019, -0.003] |
| 5 | NWZ | 597,192 | 0.001 [-0.023, 0.014] |
| 5 | NEZ | 393,062 | 0.000 [-0.023, 0.014] |
| 5 | NCZ | 452,364 | 0.011 [0.004, 0.017] |
| 6 | NWZ | 597,192 | 0.010 [-0.015, 0.023] |
| 6 | NEZ | 393,062 | 0.011 [-0.013, 0.026] |
| 6 | NCZ | 452,364 | 0.033 [0.023, 0.039] |

Slices are exploratory: only the per-lead result on all wards is confirmatory.

## 5. Calibration on the test years

Tolerance as in Phase 12: |mean p - observed| <= 0.02; bins with at least 1% of rows within 0.05 of the diagonal.

| Lead | Mean p - observed | Max bin deviation | Within tolerance |
|---|---|---|---|
| 1 | -0.049 | 0.293 | no |
| 2 | -0.057 | 0.376 | no |
| 3 | -0.065 | 0.418 | no |
| 4 | -0.064 | 0.455 | no |
| 5 | -0.062 | 0.418 | no |
| 6 | -0.059 | 0.336 | no |

## Provenance

- Test run `20261013T162219Z_b82dc7bd`, generated 2026-10-13T16:24:18Z; bootstrap B = 1000, week blocks of 4 weeks, seed 20261002.
- Data `covariates-v1.0` (parquet sha256 `82583fbf5dee…`); config sha256 `b82dc7bdc424…`.
- Validation evidence: `docs/forecast/LOGISTIC_VALIDATION.md`, `LIGHTGBM_VALIDATION.md`, `RECALIBRATION_VALIDATION.md`, `EXPLAINABILITY.md`.

<!-- generated by scripts/forecast_test.py -->
