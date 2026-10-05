# Requirements: Heatwave Modelling (CHAP)

**Defined:** 2026-10-02 (milestone v2.0 Heat Forecasting; v1.0 requirements archived in `milestones/v1.0-REQUIREMENTS.md`)
**Core Value:** A correct, complete weekly covariate table for all 4,841 wards in 19 northern states and the FCT, handed off to CHAP, plus honest, calibrated forecasts of its heat indicators that demonstrably beat simple baselines.

**Conventions used below.**
- "Analyst" means whoever trains, evaluates or runs the forecast layer. "CHAP" means the downstream platform.
- **`heatwave_week`** = 1 when a ward-week has `heatwave_days >= 3`: three or more hot days, not necessarily consecutive. It is not the rule-based heatwave event (`heatwave_event_count`). Every report carries this definition.
- **Lead *k*** means the target week is *k* weeks after the last observed week. ERA5-Land runs about 8 days behind, so lead 1 is a nowcast.

## v2.0 Requirements

### Foundation (DATA)

- [ ] **DATA-01**: Analyst can load the frozen `covariates-v1.0` dataset for training, and the loader refuses any copy whose SHA-256 doesn't match its MANIFEST. The live `outputs/covariate_table.csv` can't be used for training.
- [ ] **DATA-02**: Analyst can convert between ISO week labels, an integer week index and `week_start` dates. All time arithmetic uses the index or dates, never label strings, and stays correct across 53-week ISO years (1992, 1998, 2004, 2009, 2015, 2020, 2026).
- [ ] **DATA-03**: Analyst can set all forecast settings (split years, leads, latency, baselines, model hyperparameters, gate thresholds, retrain policy) in a validated `forecast.yaml`, without changing `config.yaml` or the existing config tests.
- [ ] **DATA-04**: Each training or evaluation run writes a run folder outside the repo. It holds a config snapshot, the data hash, git commit, library versions and random seed, so any result can be reproduced.
- [ ] **DATA-05**: The forecast package installs alongside the existing code (scikit-learn, LightGBM, shap), never imports Earth Engine modules, and passes CI on Python 3.12 together with the existing 166 tests.

### Features, targets and splits (FEAT)

- [ ] **FEAT-01**: Analyst can build the `heatwave_week` target for each lead 1-6, aligned to the exact target week.
- [ ] **FEAT-02**: Every training and forecast row carries `last_obs_week`, `issue_date` (week end + measured ERA5-Land latency), `target_week`, `lead_weeks` and `effective_days_ahead`.
- [ ] **FEAT-03**: Analyst can build as-of features from data up to the last observed week only. They cover:
  - lags and rolling means of the Heat Index anomaly, hot days, hot nights, humidity, rainfall and soil moisture;
  - season;
  - trend and base-rate level features, such as trailing hot-day fraction and trailing 10-year base rate (no raw year index);
  - LGA/state context and static location.

  Every fitted statistic (climatology, standardisation) uses training years only and records its fit range.
- [ ] **FEAT-04**: An automated leakage suite proves features at week *t* don't change when the panel is truncated at *t* or future weeks are overwritten. It also proves fitted statistics don't change when validation/test data changes, and that every registered feature declares `max_lookahead = 0`. The suite fails when a leak is deliberately injected.
- [ ] **FEAT-05**: Analyst can split by target week with an embargo (train 1991-2014, validate 2015-2020, test 2021-2026) and generate expanding-window CV folds, with cutoffs defined by `week_start` dates.
- [ ] **FEAT-06**: Analyst can see `heatwave_week` prevalence by year, region and era, and the measured ERA5-Land latency, before any model is trained.

### Baselines and evaluation harness (EVAL)

- [ ] **EVAL-01**: Analyst can score five baselines per lead through the same harness as the models:
  - climatology;
  - recent 10-year climatology pooled across ±1-2 weeks;
  - probabilistic persistence;
  - damped persistence;
  - trend + season.
- [ ] **EVAL-02**: The harness scores stored predictions identically for every predictor. It reports:
  - Brier score and Brier skill score against a named reference, with Brier decomposition;
  - ROC AUC, stratified by season and region;
  - a reliability diagram with quantile bins;
  - precision/recall/F1 at a stated threshold;
  - calibration-in-the-large by year.

  There is no accuracy metric.
- [ ] **EVAL-03**: Analyst gets confidence intervals from a paired week-block bootstrap (blocks of at least 4 weeks) and a year-block bootstrap, never resampling individual rows or wards.
- [ ] **EVAL-04**: Analyst can break results down by lead, season (with March-May highlighted), region (far north vs middle belt) and year, with the 6 LGA-average wards and the small wards flagged.
- [ ] **EVAL-05**: The 2021-2026 test years are locked. Loaders refuse test rows until a pre-registration file is committed and the lock is opened, and the evaluation log shows exactly one test run.
- [ ] **EVAL-06**: Analyst can run negative controls (year-shuffled features, skill-vs-lead decay) that show whether apparent skill is real.

### Models and calibration (MODEL)

- [ ] **MODEL-01**: Analyst can train and validate a regularised logistic regression per lead, with validation BSS against the best baseline and CIs.
- [ ] **MODEL-02**: Analyst can train and tune LightGBM per lead with expanding-window CV. It is strongly regularised and deterministic, with no class reweighting.
- [ ] **MODEL-03**: Probabilities are calibrated per lead using out-of-fold CV predictions. Platt or isotonic is chosen by CV Brier score, outputs are clipped, and calibration rows never overlap fitting or early-stopping rows.
- [ ] **MODEL-04**: Analyst can see how many evaluation rows fall outside the training range of each feature, which signals extrapolation risk under warming.

### Secondary targets (SEC)

- [ ] **SEC-01**: Analyst can forecast the weekly max Heat Index anomaly as non-crossing p10/p50/p90 quantiles per lead, with pinball loss and 80% interval coverage by year and region.
- [ ] **SEC-02**: Analyst can forecast hot-night probability per lead with the same harness and calibration.

### Decision and report (DEC)

- [ ] **DEC-01**: Analyst can explain models with grouped SHAP and grouped permutation importance, and run the ablation ladder: season → +location → +trend → +persistence → +lagged heat → +soil/humidity/rain.
- [ ] **DEC-02**: The confirmatory test runs once. The model is refit on 1991-2020 with frozen hyperparameters and scored on 2021-2026 against the pre-registered go/no-go: at leads 2-3, BSS > 0 against the best baseline, with a CI that excludes 0. The decision is recorded in `GATE.json`.
- [ ] **DEC-03**: Stakeholders can read a forecast report (`docs/FORECAST_REPORT.md`). It includes:
  - skill by lead, season and region, with CIs;
  - an effective-lead table;
  - a skill mask;
  - the mandatory caption "skill against ERA5-Land-defined heatwave weeks (reanalysis labels), 4,841 wards in 19 northern states and the FCT";
  - a clear separation between the rule-based detection layer and the trained forecast layer.
- [ ] **DEC-04**: On a no-go, the report says plainly which leads have no skill beyond the baselines and recommends the next step (ECMWF S2S benchmark). The operational phase then runs only for leads that passed.

### Operational forecast for CHAP (OPS)

- [ ] **OPS-01**: Analyst can produce the weekly forecast from the latest `run_local_pipeline.py` output, using the same feature code as training, plus a release bundle retrained on all years. The bundle comes with a model card that marks it "not independently tested".
- [ ] **OPS-02**: CHAP can read a weekly forecast table that has:
  - `time_period` (YYYY-Www) and `location` (wardcode);
  - `heatwave_prob` with the observed counterpart `heatwave_week` (provisional names, to be confirmed with the CHAP team);
  - `lead_weeks` and `skill_flag`;
  - no missing values, and an unbroken run of weeks for every ward.

  The table passes `chap validate`.
- [ ] **OPS-03**: Each forecast run writes a long-format archive (`issue_week, target_week, lead, location, p_heatwave_week, hi_anomaly_p10/p50/p90, model_version, data_version`) and a FORECAST_MANIFEST. It flags drift between the live table's history and the frozen values.
- [ ] **OPS-04**: METHODOLOGY and README describe the forecast layer, how to run it, and its caveats.

### Climate drivers (DRV)

- [ ] **DRV-01**: Analyst can build a frozen, versioned dataset of climate indices (Niño3.4/ONI, tropical Atlantic SST (TNA, plus ATL3 if a source is found), MJO RMM), with features lagged by each index's publication delay and using as-published values.
- [ ] **DRV-02**: Analyst can measure the skill the drivers add, using a fresh pre-registered protocol (expanding-window CV on 2015-2026, paired ablation). A new model version is released only if the gain's CI is above 0. Otherwise the no-gain result is documented.

## Future Requirements

Deferred. Tracked, but not in the current roadmap.

- **FUT-01**: ECMWF extended-range (S2S) forecasts as a benchmark or fallback (triggered by a no-go at DEC-02).
- **FUT-02**: Ordinal or categorical heatwave-days target (0, 1-2, 3-4, 5-7 days).
- **FUT-03**: Forecast page in the Streamlit viewer.
- **FUT-04**: Station-based re-validation if NiMet data is obtained.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Deep learning (LSTM, ConvLSTM, transformers) | Too little independent history (35 correlated years); overfits and is hard to explain |
| Per-ward models | 4,841 separate models can't share information; pooled per-lead models instead |
| Class reweighting / SMOTE / `scale_pos_weight` | They distort probabilities and break the Brier score and calibration |
| Random K-fold CV or random row splits | They leak across time and between neighbouring wards and inflate skill |
| Disease-impact logic | CHAP's job downstream |
| Hard yes/no heat alerts | Need an agreed operational threshold with health partners; probabilities only for now |
| Station-confirmed labels | NiMet data isn't open, and NOAA GSOD is too sparse (METHODOLOGY section 9) |
| MLflow / W&B / DVC / Hydra / Optuna | Run folders with YAML, JSON and Parquet are enough at this scale |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 8 | Pending |
| DATA-02 | Phase 8 | Pending |
| DATA-03 | Phase 8 | Pending |
| DATA-04 | Phase 8 | Pending |
| DATA-05 | Phase 8 | In progress (deps done in 08-01; CI 3.12 + isolation in 08-07) |
| FEAT-01 | Phase 9 | Pending |
| FEAT-02 | Phase 9 | Pending |
| FEAT-03 | Phase 9 | Pending |
| FEAT-04 | Phase 9 | Pending |
| FEAT-05 | Phase 9 | Pending |
| FEAT-06 | Phase 9 | Pending |
| EVAL-01 | Phase 10 | Pending |
| EVAL-02 | Phase 10 | Pending |
| EVAL-03 | Phase 10 | Pending |
| EVAL-04 | Phase 10 | Pending |
| EVAL-05 | Phase 10 | Pending |
| EVAL-06 | Phase 11 | Pending |
| MODEL-01 | Phase 11 | Pending |
| MODEL-02 | Phase 12 | Pending |
| MODEL-03 | Phase 12 | Pending |
| MODEL-04 | Phase 12 | Pending |
| SEC-01 | Phase 13 | Pending |
| SEC-02 | Phase 13 | Pending |
| DEC-01 | Phase 14 | Pending |
| OPS-01 | Phase 15 | Pending |
| DEC-02 | Phase 14 | Pending |
| OPS-02 | Phase 15 | Pending |
| DEC-03 | Phase 14 | Pending |
| OPS-03 | Phase 15 | Pending |
| DEC-04 | Phase 14 | Pending |
| OPS-04 | Phase 15 | Pending |
| DRV-01 | Phase 16 | Pending |
| DRV-02 | Phase 16 | Pending |
