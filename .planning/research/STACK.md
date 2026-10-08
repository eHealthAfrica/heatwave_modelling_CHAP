# Technology Stack: v2.0 Heat Forecasting Layer (additions only)

**Project:** Heatwave Modelling, v2.0 weekly forecast layer
**Researched:** 2026-10-02
**Scope:** Only NEW capabilities. The existing venv (Python 3.12.10, numpy 2.3.3, pandas 2.3.2, pyarrow 21, PyYAML 6.0.2, matplotlib 3.10.6, xarray 2026.9, requests 2.32.5, pytest) is kept as is.

Versions below are the latest on PyPI as of 2026-10-02 (checked via the PyPI JSON API). The venv is Python 3.12.10, which satisfies every requirement below (shap 0.52 needs >=3.12, scikit-learn 1.9 needs >=3.11).

## Recommended Stack

### ML core (NEW)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| scikit-learn | 1.9.1 | Regularised logistic regression, StandardScaler/Pipeline, isotonic calibration, metrics (brier_score_loss, roc_auc_score, calibration_curve, precision_recall_fscore_support, mean_pinball_loss) | Standard. Pure wheels for win_amd64/cp312. It already provides most verification metrics, so no extra scoring library is needed. |
| lightgbm | 4.7.0 | Binary classifier plus quantile regression (objective="quantile", alpha=0.1/0.5/0.9) | Fast on CPU, handles NaN natively (lag features at series starts), has native `pred_contrib=True` TreeSHAP. Windows win_amd64 wheels are on PyPI, so no compiler or cmake is needed. |
| scipy | 1.18.1 (pulled in by sklearn) | Sparse/solver backend, bootstrap helpers | Dependency only. Needs Python >=3.12, which the venv meets. |
| joblib | 1.6.0 (pulled in by sklearn) | Persist sklearn pipelines/calibrators | Ships with sklearn. |

### Explainability (NEW)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| shap | 0.52.0 | Summary/beeswarm/dependence plots on LightGBM models | Requires Python >=3.12 (OK). Use `shap.TreeExplainer(booster)` on a 20k-50k row sample from the test period. It pulls in numba/llvmlite, which have Windows wheels. Install after numpy 2.3 is pinned and check that `import shap` works (smoke test). Fallback with zero extra deps: `booster.predict(X, pred_contrib=True)` returns the same TreeSHAP values, and you can plot them with matplotlib. |

### Verification and calibration (mostly NO new library)
| Need | Use | Notes |
|------|-----|-------|
| Brier, BSS | `sklearn.metrics.brier_score_loss`; BSS = 1 - BS/BS_ref (ref = climatology baseline, computed on the same rows) | Write the BSS wrapper yourself (3 lines). |
| ROC AUC, PR, F1 | sklearn.metrics | |
| Reliability diagram | `sklearn.calibration.calibration_curve(strategy="quantile")` plus matplotlib; also plot a forecast-frequency histogram | Heatwave weeks are rare, so uniform bins leave most bins empty. Use quantile bins. |
| Quantile score / interval coverage / MAE | `sklearn.metrics.mean_pinball_loss` per alpha; coverage = mean(y between q10 and q90) | Average pinball loss over a dense quantile set approximates CRPS. With only 3 quantiles, report "mean pinball loss" and call it a CRPS-like score, not CRPS. |
| Isotonic calibration | `sklearn.isotonic.IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)` fitted directly on validation-period (2015-2020) raw probabilities | Simplest correct approach. Do NOT use `CalibratedClassifierCV(cv="prefit")`. It was deprecated in 1.6 and removed in later releases. The replacement is `CalibratedClassifierCV(FrozenEstimator(model))`. That adds nothing over direct IsotonicRegression for a time-split setup. |
| Bootstrap CIs | numpy: resample ISO-week indices (block bootstrap, 1000 draws) and recompute the metric | Custom code is needed anyway because the resampling unit is the week (the spatial dependence across wards is the whole point). No library does this. |

Optional (not required): `scores` 2.7.0 (maintained, xarray/pandas friendly, has CRPS, quantile scores, Murphy diagrams, Brier decompositions). Add it only if you later want ensemble CRPS or Murphy diagrams. MEDIUM confidence that it is wanted; skip for MVP.

### Data handling / performance (NO new library by default)
| Approach | Detail |
|----------|--------|
| Stay on pandas 2.3 + pyarrow 21 | 9.0M rows x ~40 float32 features is about 1.5 GB. This fits a laptop. Polars (1.44.2) and DuckDB (1.5.6) are not needed. |
| Cast to float32 at load | `pd.read_parquet(..., columns=[...])`, then downcast. Keep location as category/int16 code and time_period as an int week index. |
| Build lags with a (ward x week x variable) numpy array, not groupby.shift | Reshape the panel to a dense 3D float32 array (4841 x 1863 x V). Lags and rolling means are then slice shifts and cumulative-sum differences, which is much faster and uses less memory than 9M-row groupby shifts. Check the panel is complete and sorted first (it should be, 4841 x 1863 = 9,018,783). |
| Leakage control | Features for lead k use only information up to the origin week t. Targets are shifted by k. Drop rows where the target is NaN. Apply the split on origin week, not target week. |
| LightGBM memory | Build `lgb.Dataset(X, y, free_raw_data=True, params={"max_bin": 63})` once per lead, validation as `reference=train_ds`. Use `train_ds.save_binary()` to cache. Use `num_threads` = physical cores, `min_data_in_leaf` ~ 500-2000 given ~6M rows, early stopping on the validation period. Optionally subsample negative weeks or wards for hyperparameter search only, then train the final model on all rows. |
| Climatology baselines | Compute from the training period per (ward, ISO week-of-year) with a +/-1 week smoothing window. This is just a pandas groupby and needs no library. |

### Config, tracking, persistence (NO MLflow)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| PyYAML | 6.0.2 (already installed) | Experiment config files (`configs/lead3_lgbm.yaml`) | Already in the venv. Combine with a frozen `dataclass` for typing. Pydantic (2.13.5) is optional only if you want validation, and is not needed. |
| JSON + Parquet | stdlib / pyarrow | Per-run `runs/<run_id>/{config.yaml, metrics.json, preds.parquet, MANIFEST}` | Fully reproducible, git-friendly, and no server. Record the covariates-v1.0 MANIFEST hash, git commit, library versions and seed in each run. |
| LightGBM `Booster.save_model(".txt")` | n/a | Persist GBM models | Text format is version-stable and readable. |
| joblib `dump` | 1.6.0 | Persist sklearn logistic pipelines and the isotonic calibrator | Pin the sklearn version in the run record because pickles are not portable across versions. |

### Climate indices (LATER phase) - clients and formats
No new client library. Use `requests` (already installed) plus `pandas`/`numpy` parsing. All sources are plain text, small (KB to a few hundred KB), and need no authentication. Cache raw downloads under the data directory with a retrieval date, as with the frozen data.

| Index | URL (HTTP status checked 2026-10-02) | Format | Notes |
|-------|--------------------------------------|--------|-------|
| Niño3.4 anomaly (monthly) | https://psl.noaa.gov/data/correlation/nina34.anom.data (reachable) | PSL "correlation" fixed-width text. First line = first_year last_year. Then one row per year: year + 12 monthly values. A footer carries the missing-value flag (typically -99.99). Check the footer when parsing. | Updates monthly, with a lag of about 1 month. Use `np.loadtxt`/`pd.read_csv(sep=r"\s+")` for rows with 13 fields. |
| ONI (3-month running, seasonal) | https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt (reachable) | Whitespace table with columns SEAS YR TOTAL ANOM (e.g. DJF 1950 25.01 -1.32) | Official ENSO definition. Seasonal labels must be mapped to the centre month. Prefer the monthly Niño3.4 for weekly features, with ONI as a cross-check. |
| Tropical Northern Atlantic (TNA) | https://psl.noaa.gov/data/correlation/tna.data (reachable) | Same PSL year x 12 format | Good for "tropical Atlantic SST". |
| Other PSL indices (AMO etc.) | https://psl.noaa.gov/data/correlation/amon.us.data (reachable, ends 2023, so stale) | Same format | Avoid indices that stop early. Check the last year in the header line before use. |
| ATL3 (Atlantic Niño) | NOT confirmed. The guessed URLs `atl3.data` and `tna.anom.data` returned 404. | n/a | LOW confidence. Locate via https://psl.noaa.gov/data/climateindices/list/ in the phase research, or derive from NOAA OISST/ERSST gridded SST (region 20W-0, 3S-3N) with xarray, which needs a heavier download. |
| MJO RMM (daily) | http://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt (reachable) | 2 header lines, then whitespace columns: year month day RMM1 RMM2 phase amplitude, then a trailing method string. Missing = 1.E36 or 999. | Daily from 1974-06-01, updated near real time. Parse with `pd.read_csv(sep=r"\s+", skiprows=2, usecols=range(7), names=[...])`. Convert missing to NaN. Aggregate to ISO weeks with the mean of RMM1/RMM2/amplitude and the modal phase. Beware that the BoM site sometimes blocks non-browser user agents. Send a normal User-Agent header and cache the file. |
| MJO OMI (alternative) | https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt (reachable) | Text | Alternative if the BoM link breaks. Do not use both as features. |

Leakage note for later phase: for forecast origin week t, a monthly index value may only be used once that month has been published. Lag monthly indices by at least 1 month (and use the as-published value) to avoid look-ahead. RMM is available with about 1-day latency, but only use values up to the end of the origin week.

## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| GBM | LightGBM | XGBoost / CatBoost | The user agreed on LightGBM. LightGBM's native quantile objective and low CPU memory are enough. |
| Calibration | Direct IsotonicRegression | CalibratedClassifierCV(FrozenEstimator) / Platt | Same result with more machinery. Platt is a fallback if the isotonic fit looks step-like on rare events. |
| Verification | sklearn + numpy | properscoring 0.1, xskillscore 0.0.29 | properscoring has had no release since 2015 (unmaintained) and is ensemble-oriented. xskillscore is xarray-centred and brings in extra dependencies for functions that are one-liners here. |
| Dataframes | pandas + numpy | polars 1.44.2, DuckDB 1.5.6 | Data fits in memory. The existing pipeline is pandas. Adding another dataframe API creates two idioms for no gain. |
| Tracking | YAML + JSON run folders | MLflow / Weights & Biases / DVC | Single user, laptop, a few dozen runs. A server, DB or SaaS is unjustified. |
| Hyperparameter search | Manual small grid / `lgb` early stopping | Optuna | Not needed for MVP. Add later only if the ablation phase needs it. |
| Explainability | shap (plus native pred_contrib) | LIME, permutation-only | TreeSHAP is exact and fast for GBMs. Add permutation importance from sklearn for the logistic baseline. |

## What NOT to Add
- **MLflow, W&B, DVC, Hydra, Kedro, Prefect/Airflow**: too heavy for a single-user project. Plain run folders suffice.
- **Deep learning (PyTorch, TensorFlow), Prophet, statsmodels time-series stacks**: outside the agreed design. Panel GBM with lag features is the plan.
- **Polars / DuckDB / Dask / Spark / Ray / Vaex**: no memory problem at 6M x 40 float32.
- **properscoring, xskillscore**: see above.
- **GPU builds of LightGBM**: no benefit on a laptop, and the setup is fragile on Windows.
- **Optuna, scikit-optimize** (until ablations demand it).
- **cdsapi / ERA5 downloaders, Copernicus clients, cfgrib**: not needed for the later indices. They are plain-text files.
- **imbalanced-learn / SMOTE**: resampling distorts probabilities, which breaks Brier skill and calibration. Do not use `scale_pos_weight` either. Train unweighted on natural frequency, then calibrate.
- **Re-pinning existing packages**: do not upgrade numpy/pandas/pyarrow/xarray. Newer matplotlib (3.11) and scipy 1.18 exist, but leave matplotlib 3.10.6 pinned unless a plot feature requires the upgrade.

## Installation

```bash
# From repo root, venv active (.venv, Python 3.12.10)
pip install "scikit-learn==1.9.1" "lightgbm==4.7.0" "shap==0.52.0"
# pulls in: scipy, joblib, threadpoolctl, numba, llvmlite, tqdm, cloudpickle, slicer

pip install --dry-run "scikit-learn==1.9.1" "lightgbm==4.7.0" "shap==0.52.0"   # first check that numpy 2.3.3 stays pinned

# Afterwards, refresh requirements.txt (pip freeze) and add a smoke test:
#   python -c "import sklearn, lightgbm, shap; print(sklearn.__version__, lightgbm.__version__, shap.__version__)"
```

Optional later: `pip install scores==2.7.0`.

Windows notes: all three packages ship win_amd64 cp312 wheels, so no compiler is needed. If `lightgbm` import fails with a missing DLL, install the Microsoft Visual C++ Redistributable (the wheel bundles its own OpenMP runtime, so this is rare). If `pip install shap` tries to build numba/llvmlite from source, the cp312 wheels were not found. In that case check the pip version and the platform tag.

## Confidence
| Item | Level | Basis |
|------|-------|-------|
| Package versions and Python requirements | HIGH | PyPI JSON API, 2026-10-02 |
| Windows wheels exist for sklearn/lightgbm/shap | MEDIUM | Long-standing PyPI practice; wheel files were not enumerated. Verify with `pip install --dry-run` / `pip download --only-binary=:all:` |
| shap 0.52 compatibility with lightgbm 4.7 / numpy 2.3 | MEDIUM | Not tested here. The smoke test above and the native `pred_contrib` fallback cover the risk |
| CalibratedClassifierCV cv="prefit" deprecation / FrozenEstimator | MEDIUM | From scikit-learn 1.6 release notes (training knowledge, not re-checked against 1.9 docs) |
| properscoring unmaintained | HIGH | PyPI latest = 0.1 |
| Climate index URLs and formats (Niño3.4, TNA, ONI, RMM) | HIGH | Fetched live 2026-10-02 (HTTP 200 and sample rows seen) |
| PSL missing value flag and footer format | MEDIUM | Not displayed in the head-only fetch. Check the file tail when writing the parser |
| ATL3 source | LOW | Not located |

## Sources
- PyPI JSON API for scikit-learn, lightgbm, shap, scores, xskillscore, properscoring, polars, duckdb, joblib, scipy (queried 2026-10-02)
- https://psl.noaa.gov/data/correlation/nina34.anom.data
- https://psl.noaa.gov/data/correlation/tna.data
- https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt
- http://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt
- https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt
- https://psl.noaa.gov/data/climateindices/list/ (index catalogue)
