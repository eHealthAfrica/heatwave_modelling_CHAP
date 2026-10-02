# Project Research Summary

**Project:** Heatwave Modelling (CHAP), milestone v2.0 Heat Forecasting
**Domain:** Sub-seasonal (1-6 week) probabilistic heat forecasting, ward-level panel ML, feeding a health platform (CHAP)
**Researched:** 2026-10-02
**Confidence:** MEDIUM. Stack, architecture and the CHAP format are solid. Achievable skill at leads 3-6 is unknown, and the literature covers dynamical models, not statistical ones.

Sources: `STACK.md`, `FEATURES.md`, `ARCHITECTURE.md` and `PITFALLS.md` in this folder. The agreed design is in `.planning/PROJECT.md` (Key Decisions, 2026-10-02). The research synthesizer returned this file's content as text because it couldn't write files, and the orchestrator saved it unchanged.

## Executive Summary

v2.0 is a pooled panel-ML forecast layer on the frozen `covariates-v1.0` table (4,841 wards x 1,863 ISO weeks, 9.02M rows). It lives in a new sibling package `heatwave/forecast/` with its own `forecast.yaml`. It has no Earth Engine dependency and does not touch the rule-based detection code. The agreed design stands:
- primary target: heatwave-week probability;
- one model per lead (1-6);
- order: baselines, then logistic regression, then LightGBM, then isotonic calibration, then a one-shot test on 2021-2026.

The stack is small and standard: scikit-learn 1.9.1, LightGBM 4.7.0 and shap 0.52.0, on top of the existing pandas, pyarrow and PyYAML. Run folders hold YAML configs, JSON metrics and Parquet predictions.

**The main risk is evaluation honesty, not modelling.**
- **Warming makes weak baselines easy to beat.** Hot days per ward rose from about 25 a year (1991-2000) to about 56 (2016-2025). Against a stale 1991-2014 climatology, any model that knows the climate has warmed will "win".
- **Pooled AUC flatters trivial models.** A model that learns only season, geography and trend still looks good on it.
- **Expected skill is modest.** Literature on ECMWF extended-range forecasts shows useful skill to about 2 weeks and near-climatology by weeks 3-4. A statistical model on past ERA5-Land alone should expect modest gains over a trend-aware baseline at leads 1-2, and probably none at leads 4-6.
- **What the go/no-go needs:**
  - comparison against the best of several trend-aware baselines;
  - week-block bootstrap confidence intervals;
  - "no skill at lead N" as an outcome it can report.
- **The no-go branch should be planned**, with the ECMWF S2S benchmark as the fallback, not treated as an exception.

**The second class of risk is leakage and timing.**
- **Leakage sources:**
  - target-week information in features;
  - climatology fitted on held-out years;
  - labels bleeding across split boundaries;
  - reuse of the test set.
- **Latency:** ERA5-Land arrives about 8 days after week end, so harness "lead 1" is a nowcast of a week that has already finished.
- **Controls must be mechanical, not left to discipline:**
  - an as-of feature function with truncation-invariance and poison tests;
  - train-only fitted objects that record their fit range;
  - splits by target week with an embargo;
  - a test lock file;
  - an explicit issue date and effective lead on every output.

**Climate drivers go last.** Their expected gain is small, and they carry publication-lag and revision leakage. By then the test years are spent, so they can only be judged by cross-validation or ablation evidence.

## Recommended Adjustments for User Decision

None of these is applied without a user decision. Type (A) adds to the agreed design without contradicting it. Type (C) changes something agreed, or makes an undecided point concrete.

| # | Topic | Agreed design | Research recommendation | Type | Source |
|---|-------|---------------|-------------------------|------|--------|
| 1 | Extra baselines | climatology, recent (10-yr) climatology, persistence | Add (a) a trend + season baseline (logistic on year, sin/cos of day-of-year and region, fit on training years) and (b) damped persistence (logistic on last week's label or anomaly + season). Make persistence probabilistic (conditional frequency given last week's state) so Brier is fair. Go/no-go compares against the best baseline per lead, chosen on validation. | A | PITFALLS C6, C8 |
| 2 | Trend handling | recent-climatology baseline only | Also give models slowly varying level features: trailing 26/52-week hot-day fraction, trailing 10-yr ward base rate, anomaly vs trailing climatology. Don't rely on a `year` index, because trees can't extrapolate into 2021-2026. Ablate with and without. The headline BSS is against the recent or best baseline, never the 1991-2014 climatology. Pool the recent climatology across ±1-2 weeks (optionally state or neighbours), because 10 samples per cell is noisy. | C | FEATURES; PITFALLS C6, M7 |
| 3 | Lead and latency definition | lead k = k weeks after the last observed week | Keep the definition. Store `last_obs_week`, `issue_date` (= week end + latency, from config), `target_week`, `lead_weeks` and `effective_days_ahead`. State that harness lead 1 is a nowcast under the ~8-day ERA5-Land latency, and measure the real latency empirically. Decide before seeing results which leads the go/no-go judges: harness leads 1-2, or effective lead ≥ 7 days (leads 2-3). Publish an effective-lead table. | C | PITFALLS C2; FEATURES |
| 4 | Label naming | "heatwave week" | The label is `heatwave_days >= 3`: three hot days in the week, not necessarily consecutive. It is not the rule-based event (3 consecutive days, `heatwave_event_count`). Name it `hot_week_ge3` in code and reports, or keep `heatwave_week` with a mandatory definition footnote. Never use `heatwave_event_count` as the label. State that the 1991-2020 threshold overlaps the validation years as part of the label definition. | C | PITFALLS M1, C3 |
| 5 | Calibration fit set | isotonic, fitted on the validation years | STACK and ARCHITECTURE say fit directly on validation (2015-2020). PITFALLS M4 warns this overfits when validation also drives early stopping and hyperparameters, and when there are few effective events. Fit on out-of-fold predictions from expanding-window CV, or on a validation slice not used for early stopping. Compare Platt scaling (2 parameters, robust under shift) with isotonic by paired CV Brier, and use the simpler one unless isotonic clearly wins. Clip to [eps, 1-eps]. Use `IsotonicRegression` directly, never `CalibratedClassifierCV(cv="prefit")`. | C | STACK; PITFALLS M4 |
| 6 | Refit on train+val before test | train-only model scored on test | The files disagree. ARCHITECTURE: score the train-only model on test, then refit on all data as a separate operational `model_version`. PITFALLS C6: refit on train+val (1991-2020) with frozen hyperparameters before the test, because validation sits inside the label baseline and test is a warmer regime. FEATURES: retrain after the freeze. Whichever is chosen goes into `forecast.yaml` before the test run, and the operational refit is documented as not independently tested. | C | ARCHITECTURE; PITFALLS C6 |
| 7 | Test lock and pre-registration | test 2021-2026 once | Enforce it mechanically: `TEST_LOCK.json` (config hash + model bundle hash), an append-only evaluation log, and loaders that refuse test rows until the lock is opened. Commit a pre-registration file before the test run covering the primary metric, primary leads, baselines, CI method, go/no-go thresholds, and which slices are confirmatory vs exploratory. | A | ARCHITECTURE; PITFALLS C9, M5 |
| 8 | Split rule | time split by year | Split by target week: a training row needs `target_week_end <= train_end`. Use a CV embargo of at least 6 + longest-lag weeks. Define cutoffs by `week_start` date, not ISO year (2020-W53 runs into 2021-01-03). Do all time arithmetic on dates or an integer week index, never on label strings. | A | PITFALLS C4, M2 |
| 9 | Reporting | BSS headline | Agreed, plus: Brier decomposition, calibration-in-the-large by test year, no accuracy metric, and AUC only stratified by season or region. Every report carries a mandatory caption: "skill against ERA5-Land-defined heatwave weeks (reanalysis labels), 4,841 wards in 19 northern states and the FCT". Add negative controls (year-shuffle, skill-vs-lead decay). Report two bootstrap CIs: week-block (≥ 4 weeks) and whole-year blocks. | A | PITFALLS C5, C7, C10, M3 |
| 10 | CHAP output shape | forecast table for CHAP | CHAP needs ordinary covariate columns: `time_period` (`YYYY-Www`), `location` (= wardcode), no NaN, and the same consecutive set of periods for every ward. It also needs a historic counterpart column (observed `heatwave_week` 0/1 beside forecast `heatwave_prob`), because a CHAP model reads one column across historic and future rows. Emit one forecast per (ward, target week), the latest issued, and keep the full issue/lead metadata in a separate long-format archive. The ARCHITECTURE schema (`issue_week, target_week, lead, location, p_heatwave_week, ..., model_version, data_version`) can be that archive. Validate with `chap validate`. Column names aren't final, because the forecast-covariate ingestion path is undocumented; confirm with the CHAP team. Flag observed vs forecast rows (train/serve mismatch). | C | FEATURES (CHAP); PITFALLS M10 |
| 11 | CI Python version | CI on 3.11, `pyproject` ≥ 3.11 | `shap 0.52` and `scipy 1.18` need Python ≥ 3.12. The local venv is 3.12.10, but `.github/workflows/tests.yml` runs 3.11. Either bump CI to 3.12 (recommended), or keep 3.11 and make shap optional (`requirements-forecast.txt`) with older scipy. | C | STACK; ARCHITECTURE |
| 12 | Spatial handling | pooled ward-level models | Keep one pooled model per lead. Use coordinates and region as static features, not ward id. Flag the 6 LGA-average wards and the 73 small-ward fallback wards in slices. Add a spatial-block holdout as a robustness check. Use strong regularisation (`min_data_in_leaf` ~500-2000) and week-level bagging, because wards sharing a grid cell are near-duplicates. | A | PITFALLS C5, M8 |
| 13 | Evaluating drivers after the test is spent | drivers later, judged by added skill | The test years can't be reused for drivers. Pre-register a fresh protocol (expanding-window CV on 2015-2026, or a validation-only paired ablation), or report driver value as CV evidence and flag the driver model as not independently tested. Lag drivers by their publication delay, use as-published values, and avoid centred ONI means. | C | ARCHITECTURE; PITFALLS m6 |

## Key Findings

### Recommended Stack

**Packages:**
- **Add only:** `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `shap==0.52.0`. Transitive dependencies are joblib, scipy, numba and llvmlite.
- **Keep pinned:** numpy 2.3.3, pandas 2.3.2, pyarrow 21, PyYAML and matplotlib 3.10.6.
- **Before installing:** verify the Windows wheels with `pip install --dry-run`, and add an import smoke test.
- **SHAP fallback:** native `booster.predict(pred_contrib=True)` needs no extra dependency.

**Core technologies:**
- **scikit-learn:** regularised logistic regression, isotonic regression, and all verification metrics (Brier, AUC, calibration_curve, pinball). No extra scoring library is needed.
- **LightGBM:** binary classifier plus quantile regression (alpha 0.1, 0.5, 0.9). It handles NaN natively, supports TreeSHAP via `pred_contrib`, and runs on CPU with Windows wheels.
- **shap:** summary and dependence plots on a 20-50k-row sample, grouped by feature family.
- **pandas + pyarrow + numpy:** unchanged. 9M rows x ~40 float32 columns is about 1.5 GB. Build lags on a dense (ward x week x variable) float32 array, not with 9M-row groupby shifts.
- **Run folders** (YAML, JSON, Parquet, MANIFEST) instead of MLflow, W&B, DVC, Hydra, Optuna, Polars, DuckDB, properscoring or xskillscore.
- **Climate indices (later phase):** plain `requests` + pandas. Sources: NOAA PSL Niño3.4 and TNA, CPC ONI, and BoM RMM daily (needs a browser User-Agent, so cache the file). The ATL3 source isn't located yet: the guessed URLs returned 404.

**Do not use:**
- SMOTE, class weights or `scale_pos_weight`. They break the Brier score and calibration.
- `CalibratedClassifierCV(cv="prefit")`.
- `outputs/covariate_table.csv` for training.

### Expected Features

**Must have (table stakes):**
- **Label and timing fields:** a binary label (`heatwave_days >= 3`), plus `issue_week`, `lead_weeks`, `target_week` and `data_cutoff_date`.
- **Baselines:** the three agreed baselines plus the extras in Adjustments 1-2, all scored by the same harness.
- **Strictly causal lagged features**, guarded by an automated leakage test:
  - lags and rolling means of heat, humidity, rain and soil moisture;
  - seasonal sin/cos and trend/base-rate level features;
  - spatial context: coordinates, state, and the neighbour or state-mean lagged anomaly;
  - soil-moisture and humidity anomalies against the ward-week climatology.
- **Models:** per-lead logistic regression, then LightGBM, with calibrated probabilities.
- **Evaluation:**
  - BSS against climatology and against the recent or best baseline;
  - ROC AUC;
  - reliability with quantile bins;
  - slices by lead, season and region;
  - week-block bootstrap CIs;
  - a per-lead go/no-go that can say "no skill".
- **CHAP-ready weekly table:** no NaN, ISO `time_period`, `location` = wardcode, with a manifest and versioning. Wards with null features fall back to recent climatology and are flagged.

**Should have (differentiators):**
- A quantile Heat Index anomaly (p10/p50/p90, pinball loss, 80% coverage) and a hot-night probability, once the primary target passes.
- A skill mask (`skill_flag`) per lead, region and season.
- Grouped SHAP plus an ablation ladder: season only → +ward → +trend → +persistence → +lagged heat → +soil/humidity/rain → +drivers.
- Hierarchical pooling (ward → state → zone) in the recent-climatology baseline.
- Reliability by region and season in every release, plus a forecast archive.

**Defer:**
- The ECMWF S2S benchmark (only on a no-go).
- An ordinal or categorical heatwave-days target.
- A Streamlit forecast page.
- Deep learning, per-ward models, and hard yes/no alerts without a documented threshold.
- Disease-impact features (CHAP's job).

### Architecture Approach

- **Package and config:** a new package `heatwave/forecast/` plus thin CLI scripts, and a separate `forecast.yaml`, so the 35 `test_config.py` tests stay untouched.
- **Tests:** `tests/forecast/` runs on synthetic panels, so CI needs no real data.
- **Artifacts:** they live outside the repo under `<local_data_dir>/forecast_runs/<run_id>/`. Only small decision documents are committed.
- **One scoring path:** baselines and models share one `Predictor` interface and one harness that scores stored predictions identically.
- **Features:** a pure as-of function `build(panel, issue_week)`, used unchanged for training and serving.
- **Data access:**
  - `data.py` accepts only the frozen path, with a SHA-256 check.
  - The live loader is used only in `operational.py`, which also checks the live table against the frozen values for definition drift.

**Major components:**
1. `data.py`, `weeks.py`, `config.py`, `artifacts.py`: frozen load with checksum, an integer week index (safe for 53-week ISO years), typed config, and the run and MANIFEST layout.
2. `climatology.py`, `features.py`, `targets.py`, `dataset.py`, `splits.py`: train-only fitted statistics that record their fit range, as-of features, targets (the only forward-looking module), and splits by target week with an embargo.
3. `baselines.py`, `models/{logistic,lgbm,quantile}.py`, `calibration.py`: all behind the `Predictor` interface.
4. `evaluation/*`, `gate.py`, `report.py`, `explain.py`: the harness, week-block bootstrap, a structured go/no-go, a report built purely from artifacts, and the test lock.
5. `operational.py`, `drivers.py` (later): the CHAP-shaped weekly table with a FORECAST_MANIFEST, and driver loaders with a declared availability lag.

### Critical Pitfalls

1. **Target-week leakage in features (C1).**
   - Build features as as-of functions.
   - Guard them with truncation-invariance and poison-the-future tests.
   - Keep a feature registry with `max_lookahead = 0`.
   - Run a single-feature AUC screen.
   - Use date-keyed joins, not row shifts.
2. **Stale climatology and trend make skill look real (C6, C7, C8).**
   - Compare against the best of the trend-aware and damped-persistence baselines.
   - Use ward x week-of-year references, never a pooled base rate.
   - Run the ablation ladder, a year-shuffle negative control and a skill-vs-lead decay check.
   - Report calibration-in-the-large by test year.
3. **Latency makes lead 1 a nowcast (C2).**
   - Store `issue_date` and `effective_days_ahead`.
   - Fix the go/no-go lead definition before seeing results.
   - Verify the real ERA5-Land latency.
4. **Split-boundary leakage, spatial autocorrelation and test reuse (C4, C5, C9).**
   - Split by target week with an embargo.
   - Bootstrap whole weeks in blocks (never rows or wards) and use paired BSS differences.
   - Add a test lock and pre-registration.
5. **Calibration on the wrong rows, and regime shift (M4, C6).**
   - Calibrate on out-of-fold or untouched rows.
   - Compare Platt with isotonic.
   - Clip outputs, calibrate per lead, and refit on a recent window.
   - The reanalysis-label caveat (C10) appears in every report, because only 24-50% of ERA5-Land heatwave weeks match station heatwave weeks.

## Implications for Roadmap

Phase numbering continues from Phase 8. The order follows the ARCHITECTURE build order: Phases 8-9 come first, and Phase 14's gate controls Phase 15. Phases 11 and 12 could be merged if fewer phases are wanted.

### Phase 8: Forecast Foundation (data access, week index, config, artifacts, dependencies)

**Rationale:** everything reads through it, and it settles Python/CI compatibility early.

**Delivers:**
- `forecast.yaml` and `config.py` (frozen dataclasses, validated split years).
- `data.py`: frozen load, SHA-256 check against the MANIFEST, schema check, dense float32 panel.
- `weeks.py`: ISO label ↔ integer index, `week_start` dates, 52/53-week handling.
- `artifacts.py`: run_id, RUN_MANIFEST, config snapshot.
- Supporting pieces:
  - a synthetic-panel fixture;
  - an import-isolation test (no `ee` or `geemap`);
  - requirements and `.gitignore` updates;
  - the pytest marker `frozen`;
  - `verify_frozen.py`.

**Avoids:** M2 (week 53), m1 (live vs frozen data), CI breakage (Adjustment 11).

**Exit:** it loads the real frozen Parquet locally and rejects a corrupted copy. CI is green on the chosen Python version, and the existing 166 tests still pass.

### Phase 9: Feature Store, Targets, Splits and Leakage Test Suite

**Rationale:** leakage is the dominant failure mode and must be caught before any model exists.

**Delivers:**
- train-only `climatology.py`;
- as-of `features.py`: lags, rolling means, anomalies, season, trend/base-rate level features, spatial context, static ward features;
- `targets.py` (the label plus issue_date and effective-lead fields) and `dataset.py`;
- `splits.py`: by target week, with an embargo and `week_start` cutoffs;
- a feature registry with `max_lookahead`;
- an optional feature cache keyed by data hash + config hash;
- leakage tests T1-T8.

**Addresses:** the label, causal features, seasonal/trend/spatial features, timing fields.

**Avoids:** C1, C3, C4, M1, M2.

**Decides:** the latency definition (Adjustment 3) and the label name (Adjustment 4).

**Exit:** the leakage tests pass, and they fail when a leak is deliberately injected (mutation check). Prevalence by year is about 10% in the baseline period and higher after it.

### Phase 10: Baselines, Evaluation Harness and Test Lock

**Rationale:** it shows what a model must beat, and how much skill is even available, before effort goes into models.

**Delivers:**
- `baselines.py`: climatology, pooled recent climatology and persistence, plus trend+season and damped persistence (Adjustment 1).
- `evaluation/*`:
  - BSS with a named reference, Brier decomposition, AUC and P/R/F1;
  - reliability with quantile bins;
  - week-block and year-block bootstrap;
  - lead x season x region slices;
  - calibration-in-the-large by year.
- One prediction-Parquet format for all predictors.
- The test lock plus a pre-registration file.
- The first validation table.

**Avoids:** C5, C6, C7, C8, C9, M3, M5.

**Exit:** BSS of the reference against itself is 0, and persistence skill decays with lead. Baseline scores per lead are in on validation, and the harness refuses test rows without the lock.

### Phase 11: Logistic Regression per Lead

**Rationale:** it's the first trained model, and it's interpretable. It extrapolates linearly, which hedges against trees failing to extrapolate.

**Delivers:**
- `models/logistic.py`: standardisation fitted on train, regularised, unweighted.
- Validation BSS vs the best baseline, with CIs.
- The ablation scaffold, the year-shuffle negative control and the skill-vs-lead decay check.

**Avoids:** C7, M3.

**Exit:** validation results with paired CIs against the best baseline per lead, plus determinism tests.

### Phase 12: LightGBM, Calibration and Hyperparameter Selection

**Rationale:** this is the main model, and the calibration design is tied to model selection and early stopping.

**Delivers:**
- `models/lgbm.py`: `min_data_in_leaf` 500-2000, week-level bagging, `deterministic=True`, `max_bin` 63.
- `calibration.py` per Adjustment 5: out-of-fold or untouched slice, Platt vs isotonic, clipping.
- Expanding-window CV with an embargo.
- Reliability plots and a logistic vs LightGBM comparison.
- A feature-range coverage check: how many rows fall outside the training range.

**Avoids:** M4, M7, M8, C6.

**Exit:** calibrated probabilities with reliability within tolerance on held-out rows. The calibration rows don't overlap the fitting or early-stopping rows.

### Phase 13: Secondary Targets (Heat Index anomaly quantiles, hot nights)

**Rationale:** these are differentiators, worth doing only once the primary target beats the baselines. Defer them if Phase 12 shows no skill.

**Delivers:**
- `models/quantile.py`: p10/p50/p90 against a train-only or trailing climatology, with a non-crossing fix and coverage correction.
- Pinball loss and 80% coverage by year and region. Called "CRPS-like", not CRPS.
- A hot-night classifier reusing Phase 12.

**Avoids:** M9.

**Exit:** coverage near nominal on validation, by year and region.

### Phase 14: Explainability, Ablations, One-Shot Test, Report and Go/No-Go

**Rationale:** this is the decision point, and it spends the test set, so the protocol must be frozen first.

**Delivers:**
- `explain.py`: grouped SHAP, grouped permutation importance, the ablation ladder.
- `gate.py`: the pre-registered go/no-go.
- The retrain policy (Adjustment 6) and a single locked test evaluation.
- `report.py`, `docs/FORECAST_REPORT.md` and `GATE.json`.
- An effective-lead table and the mandatory reanalysis-label caption.
- An optional station sanity check (Kano, Abuja, Minna, Ilorin), clearly labelled.
- A skill mask by lead, region and season.

**Avoids:** C9, M5, M6, C10, C2.

**Exit:** the decision is recorded in `GATE.json`, and the test-lock log has exactly one entry. On a no-go: stop and re-scope, with the ECMWF S2S benchmark as the fallback, and don't proceed to Phases 15-16.

### Phase 15: Operational Weekly Forecast Table for CHAP

**Rationale:** it delivers the validated model to CHAP. It is gated on Phase 14, or released only for the leads that passed.

**Delivers:**
- `operational.py`, `scripts/forecast_run.py`, and the release bundle `forecast_releases/<model_version>` (retrained on all data, per the policy).
- MODEL_CARD, FORECAST_MANIFEST, and a drift check of the live table against the frozen values.
- The CHAP table plus the long-format archive. Columns:
  - ISO `time_period` and `location` = wardcode;
  - `heatwave_prob`, with the historic counterpart `heatwave_week`;
  - `lead_weeks` and `skill_flag`;
  - no NaN.
- A `chap validate` pass, a schema doc, and METHODOLOGY and README updates.

**Avoids:** M10, m1, m2, C2.

**Exit:** a forecast produced end to end from `run_local_pipeline.py` output. The train/serve parity test passes, and `chap validate` passes.

### Phase 16: Climate Drivers (ENSO, tropical Atlantic SST, MJO)

**Rationale:** it has the most ingestion and leakage surface and the smallest, least certain expected gain at 1-6 weeks. MJO is the only one of these indices that varies on a sub-seasonal timescale. It goes last by design.

**Delivers:**
- `drivers.py` and a versioned, frozen input dataset of indices with a checksum.
- Features that respect availability lag (the registry requires a declared `availability_lag_weeks`).
- A paired ablation against the Phase 14 model, under a fresh pre-registered protocol (Adjustment 13).
- A new `model_version` only if the gain's CI lies above 0.

**Avoids:** m6, C9.

**Exit:** a documented skill gain with a CI, or a documented no-gain result.

### Phase Ordering Rationale

- **Strict dependency order:**
  1. data and the week index;
  2. leakage-safe features;
  3. baselines and the harness;
  4. models;
  5. calibration;
  6. the test;
  7. operational;
  8. drivers.
- **Baselines and the harness (Phase 10) come before any model.** That sizes the effort by the skill actually available, and makes the harness the only place metrics are computed.
- **The test lock is built in Phase 10 and used in Phase 14.** The retrain policy must be in config before Phase 14.
- **Operational comes before drivers.** Operational ships the validated model, and drivers produce a new `model_version`.

### Research Flags

**Phases likely to need deeper research during planning:**
- **Phase 15:** the CHAP forecast-covariate ingestion path is undocumented. Confirm column names and the historic counterpart column with the CHAP team or the climate-tools docs.
- **Phase 16:**
  - the ATL3 source isn't located;
  - the PSL missing-value flags and footers aren't checked;
  - BoM may block non-browser user agents;
  - each index needs its publication lag and revision rules;
  - the skill gain is LOW confidence.
- **Phase 12:** the calibration fit set, regime shift, and the Platt vs isotonic choice are contested across the research files. A short design spike on real validation predictions is worthwhile.
- **Phase 10:** recent-climatology pooling (ward vs state vs neighbour) and the effective spatial sample size need sizing from the data.

**Phases with standard patterns (skip research-phase):** 8, 9 (the test catalogue T1-T8 is specified), 11, 13, 14.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH (versions) / MEDIUM (wheels, shap-numpy compatibility) | Versions come from the PyPI JSON API on 2026-10-02. Windows wheels and shap/lightgbm/numpy 2.3 compatibility are untested, but a fallback exists. Index URLs were fetched live (HIGH). ATL3 is LOW. |
| Features | MEDIUM | The CHAP format is HIGH (official docs). Skill evidence comes from dynamical-model literature at abstract level. Expected statistical skill by lead has no source (LOW). ENSO/SST skill at 1-6 weeks is LOW. |
| Architecture | HIGH for integration, MEDIUM for patterns | Integration points were read from repo code and the MANIFEST. The patterns are standard practice and weren't re-checked externally. |
| Pitfalls | MEDIUM-HIGH | Project-specific items are HIGH (from PROJECT.md and METHODOLOGY). Citations come from training knowledge and weren't re-fetched; check them before quoting. |

**Overall confidence:** MEDIUM. The build plan is well grounded. The main unknown is the outcome itself, skill beyond a trend-aware baseline at leads 3-6, which is what the project is designed to answer.

### Gaps to Address

- **ERA5-Land latency (Phase 9):** measure the actual `DAILY_AGGR` latency and revision behaviour, and store it in config. It decides how lead 1 is presented.
- **Heatwave-week prevalence (Phases 9-10):** it hasn't been computed by year, region and era in the frozen table. Doing so sizes the base-rate shift and the baselines.
- **Effective spatial sample size (Phase 10):** count the distinct grid cells and the correlation length of weekly anomalies, to set expectations for CI width.
- **Skill at leads 3-6:** whether persistence plus land state gives any skill at 3-6 weeks is unknown. Plan the no-go branch up front.
- **CHAP column names:** the forecast-covariate path and final names must be resolved with the CHAP team before Phase 15.
- **Phase 16 data details:** the ATL3 source, and PSL file parsing (missing-value flag, footer).
- **shap compatibility:** smoke-test shap 0.52 + lightgbm 4.7 + numpy 2.3 on Windows in Phase 8. The fallback is native `pred_contrib`.
- **User decisions:** the 13 adjustments above, especially 3 (go/no-go leads), 5 (calibration fit set), 6 (refit policy), 10 (CHAP shape) and 11 (CI Python version).

## Sources

### Primary (HIGH confidence)
- CHAP docs (`dhis2-chap/chap-core` on GitHub): data format, the train/predict contract, generated features, and the own-data guide.
- PyPI JSON API (queried 2026-10-02): versions and Python requirements for scikit-learn, lightgbm, shap, scipy and joblib.
- Live fetches (2026-10-02): NOAA PSL Niño3.4 and TNA, CPC ONI, BoM RMM, and PSL OMI.
- Repo code and the `covariates-v1.0` MANIFEST:
  - `heatwave/local/pipeline.py`, `heatwave/config.py`, `config.yaml`;
  - `.github/workflows/tests.yml`, `requirements.txt`;
  - `.planning/PROJECT.md`, and `docs/METHODOLOGY.md` sections 4-6, 8 and 9.

### Secondary (MEDIUM confidence)
- West African heatwave forecasting literature: NHESS 2025; Barbier et al. 2018 (MWR); Guigma et al. 2020; the Climate Dynamics 2021 Sahelian prediction-skill paper; Domeisen et al. 2022; WHO/WMO heatwave warning guidance.
- The chapkit EWARS example.
- Verification and ML methodology, from training knowledge and not re-fetched: Hamill and Juras 2006; Niculescu-Mizil and Caruana 2005; Roberts et al. 2017; Kapoor and Narayanan 2023; Wilks; Murphy 1973; Bröcker and Smith 2007; Davis and Goadrich 2006; Lundberg and Lee 2017; Ploton et al. 2020.

### Tertiary (LOW confidence)
- Persistence++, detrended anomalies and BSS on exceedance in S2S ML (arXiv 2604.16238, NOAA repository 54095): search summaries only.
- The `CalibratedClassifierCV` prefit deprecation and `FrozenEstimator` (scikit-learn 1.6 notes, not re-checked against 1.9).
- Expected statistical skill by lead, and ENSO/Atlantic SST skill at 1-6 weeks over northern Nigeria: no direct source.

---
*Research completed: 2026-10-02. Ready for roadmap after user decisions on the Recommended Adjustments.*
