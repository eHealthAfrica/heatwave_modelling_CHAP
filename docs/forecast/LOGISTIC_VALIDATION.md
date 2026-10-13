# Logistic regression: validation scores (2015-2020)

heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT; validation 2015-2020

Test years 2021-2026 are locked and unscored, as read from the evaluation log (hash chain verified): evaluation log test runs: 0; test-split scores recorded for this run: 0.

Run `20261013T104023Z_b82dc7bd`, generated 2026-10-13T11:04:26Z. Data `covariates-v1.0` (parquet sha256 `82583fbf5dee…`), config sha256 `b82dc7bdc424…`, seed 20261002, bootstrap B = 1000 (week blocks of 4 weeks, and whole years).

One L2-regularised logistic regression per lead, fitted on training targets only (before 2014-12-29), on a seeded subsample of at most 1,500,000 rows per lead, with 57 standardised features. Scored on the validation years only (4841 wards). Baselines are refitted in the same run.

**Reading the calls.** "Better" means the paired BSS interval excludes zero under both the 4-week block and the whole-year bootstrap. The go/no-go judgement uses leads 1, 2.

## 1. Skill against the baselines

| Lead | Brier logistic | Best baseline (Brier) | BSS vs best [week CI] [year CI] | Call vs best | BSS vs recent_climatology [week CI] [year CI] |
|---|---|---|---|---|---|
| 1 | 0.1271 | damped_persistence (0.1249) | -0.017 [-0.048, 0.008] [-0.033, 0.001] | not distinguishable | 0.069 [0.019, 0.115] [0.011, 0.126] |
| 2 | 0.1360 | damped_persistence (0.1322) | -0.029 [-0.057, -0.004] [-0.038, -0.017] | worse | 0.004 [-0.028, 0.030] [-0.028, 0.034] |
| 3 | 0.1383 | trend_season (0.1331) | -0.039 [-0.070, -0.013] [-0.055, -0.023] | worse | -0.013 [-0.051, 0.011] [-0.044, 0.013] |
| 4 | 0.1387 | trend_season (0.1331) | -0.042 [-0.066, -0.017] [-0.056, -0.030] | worse | -0.016 [-0.045, 0.008] [-0.046, 0.005] |
| 5 | 0.1372 | trend_season (0.1331) | -0.031 [-0.055, -0.006] [-0.044, -0.017] | worse | -0.005 [-0.035, 0.021] [-0.033, 0.015] |
| 6 | 0.1367 | trend_season (0.1332) | -0.027 [-0.049, -0.003] [-0.044, -0.014] | worse | -0.001 [-0.029, 0.024] [-0.026, 0.020] |

## 2. Ablation ladder (cumulative feature groups)

Each step adds a feature group to the previous one; the last step is the full model.

| Step | Features | Lead 1 Brier | Lead 1 BSS vs recent [week CI] | Lead 2 Brier | Lead 2 BSS vs recent [week CI] |
|---|---|---|---|---|---|
| season | 2 | 0.1350 | 0.011 [-0.007, 0.025] | 0.1351 | 0.011 [-0.006, 0.025] |
| +location | 8 | 0.1355 | 0.007 [-0.009, 0.020] | 0.1355 | 0.007 [-0.009, 0.021] |
| +trend | 12 | 0.1336 | 0.021 [-0.005, 0.039] | 0.1343 | 0.016 [-0.006, 0.031] |
| +persistence | 19 | 0.1301 | 0.047 [0.008, 0.078] | 0.1347 | 0.013 [-0.016, 0.037] |
| +heat | 51 | 0.1264 | 0.074 [0.026, 0.115] | 0.1349 | 0.012 [-0.021, 0.036] |
| +land | 57 | 0.1271 | 0.069 [0.019, 0.115] | 0.1360 | 0.004 [-0.028, 0.030] |

## 3. Negative control: year-shuffled features

Each origin's weather and trend features are taken from the same ISO week of a different random year in the same split; season, location and the labels are left true. A model that reads the current weather should lose its edge. The control passes when the shuffled model is not better than the best baseline (week-block lower bound of its BSS at or below zero).

| Lead | BSS logistic vs recent | BSS shuffled vs recent [week CI] | BSS shuffled vs best [week CI] [year CI] | Control |
|---|---|---|---|---|
| 1 | 0.069 | 0.010 [-0.008, 0.025] | -0.083 [-0.138, -0.032] [-0.140, -0.021] | pass |
| 2 | 0.004 | -0.008 [-0.026, 0.007] | -0.041 [-0.061, -0.018] [-0.058, -0.024] | pass |
| 3 | -0.013 | -0.012 [-0.032, 0.008] | -0.038 [-0.050, -0.019] [-0.053, -0.017] | pass |
| 4 | -0.016 | 0.011 [-0.008, 0.027] | -0.014 [-0.025, -0.002] [-0.029, 0.001] | pass |
| 5 | -0.005 | -0.005 [-0.022, 0.010] | -0.031 [-0.043, -0.015] [-0.044, -0.012] | pass |
| 6 | -0.001 | -0.002 [-0.022, 0.017] | -0.027 [-0.039, -0.011] [-0.037, -0.016] | pass |

## 4. Skill decay with lead

BSS of logistic vs recent_climatology: lead 1 0.069, lead 6 -0.001. Decay check passes.

## 5. Calibration (Murphy decomposition)

| Lead | Predictor | Brier | Reliability | Resolution | Mean p | Observed rate |
|---|---|---|---|---|---|---|
| 1 | logistic | 0.1271 | 0.00362 | 0.00682 | 0.117 | 0.154 |
| 1 | logistic_shuffled | 0.1352 | 0.00493 | 0.00010 | 0.096 | 0.154 |
| 2 | logistic | 0.1360 | 0.00558 | 0.00061 | 0.107 | 0.154 |
| 2 | logistic_shuffled | 0.1376 | 0.00780 | 0.00049 | 0.092 | 0.154 |
| 3 | logistic | 0.1383 | 0.00719 | 0.00005 | 0.107 | 0.154 |
| 3 | logistic_shuffled | 0.1381 | 0.00766 | 0.00010 | 0.081 | 0.154 |
| 4 | logistic | 0.1387 | 0.00788 | 0.00019 | 0.107 | 0.154 |
| 4 | logistic_shuffled | 0.1350 | 0.00500 | 0.00014 | 0.100 | 0.154 |
| 5 | logistic | 0.1372 | 0.00677 | 0.00020 | 0.105 | 0.154 |
| 5 | logistic_shuffled | 0.1372 | 0.00694 | 0.00013 | 0.085 | 0.154 |
| 6 | logistic | 0.1367 | 0.00606 | 0.00009 | 0.104 | 0.154 |
| 6 | logistic_shuffled | 0.1367 | 0.00644 | 0.00006 | 0.090 | 0.154 |

## 6. Largest standardised coefficients

Coefficients are per one standard deviation of the training sample. They describe the fitted model, not causes: correlated features share weight.

| Rank | Lead 1 feature | coef | Lead 2 feature | coef |
|---|---|---|---|---|
| 1 | `xhi_anom_roll8` | +0.408 | `hn_roll8` | -0.360 |
| 2 | `rh_anom_roll4` | -0.307 | `target_season_cos` | +0.289 |
| 3 | `mhi_anom_lag0` | +0.297 | `hd_roll8` | +0.277 |
| 4 | `target_season_cos` | +0.295 | `rh_anom_roll4` | -0.275 |
| 5 | `lga_mean_mhi_anom_lag0` | +0.232 | `mhi_anom_lag3` | -0.198 |
| 6 | `hd_roll8` | +0.200 | `hn_lag3` | +0.185 |
| 7 | `state_mean_mhi_anom_lag0` | +0.196 | `xhi_anom_roll8` | +0.183 |
| 8 | `xhi_anom_lag0` | +0.192 | `mhi_anom_roll8` | +0.182 |
| 9 | `hn_roll8` | -0.173 | `pr_anom_sum8` | -0.175 |
| 10 | `lat` | +0.163 | `xhi_anom_lag3` | +0.140 |

## Notes

- Labels are ERA5-Land reanalysis heatwave weeks (3+ heatwave days), not station-confirmed.
- The heatwave detection layer is rule-based and separate from this trained forecast layer.

<!-- generated by scripts/forecast_logistic.py -->
