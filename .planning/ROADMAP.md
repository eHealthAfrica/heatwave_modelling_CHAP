# Roadmap: Heatwave Modelling (CHAP)

## Shipped

<details>
<summary>Shipped: v1.0 (Phases 1-7), archived in <code>.planning/milestones/v1.0-ROADMAP.md</code></summary>

Rule-based detection pipeline, local covariate table build, Streamlit viewer, methodology docs and CI. All 28 v1 requirements complete. Frozen dataset `covariates-v1.0` produced.

</details>

## Milestone v2.0: Heat Forecasting

**Goal:** Forecast each ward's weekly heat indicators 1-6 weeks ahead, with calibrated probabilities that are proven to beat simple baselines on held-out years and can be passed to CHAP.

**Granularity:** fine (9 phases, 8-16). Numbering continues from v1.0, which ended at Phase 7.

**Conventions.** `heatwave_week` = 1 when `heatwave_days >= 3` (not necessarily consecutive; not the rule-based event). Lead *k* = target week is *k* weeks after the last observed week; lead 1 is a nowcast under the ~8-day ERA5-Land latency. The go/no-go judges leads 2-3.

## Phases

- [ ] **Phase 8: Forecast Foundation** - Frozen-data access with checksum, week index, `forecast.yaml`, run folders, dependencies and CI on Python 3.12
- [ ] **Phase 9: Features, Targets, Splits and Leakage Suite** - Leakage-safe as-of features, lead targets with timing fields, embargoed splits, prevalence/latency report
- [ ] **Phase 10: Baselines, Evaluation Harness and Test Lock** - Five baselines, one scoring path, bootstrap CIs, slices, locked 2021-2026 test years
- [ ] **Phase 11: Logistic Regression per Lead** - First trained model, validation BSS with CIs, negative controls
- [ ] **Phase 12: LightGBM, Calibration and Selection** - Tuned deterministic LightGBM, out-of-fold calibration, extrapolation check
- [ ] **Phase 13: Secondary Targets** - Heat Index anomaly quantiles and hot-night probability (deferred if Phase 12 shows no skill)
- [ ] **Phase 14: Explainability, One-Shot Test, Report and Go/No-Go** - Ablations, single locked test, `GATE.json`, `FORECAST_REPORT.md` (gates Phases 15-16)
- [ ] **Phase 15: Operational Weekly Forecast for CHAP** - Release bundle, CHAP-valid forecast table, archive, manifest, docs (runs only for leads that passed)
- [ ] **Phase 16: Climate Drivers** - ENSO, tropical Atlantic SST, MJO as frozen inputs, judged by added skill under a fresh protocol

## Phase Overview (approved by the user 2026-10-02)

Every phase runs through the same GSD cycle: discuss, then plan (checked), then execute (one commit per task), then verify and review.

| # | Phase | Work done in the phase | What it delivers | Requirements | Depends on |
|---|---|---|---|---|---|
| 8 | Forecast foundation | 1. Install scikit-learn, LightGBM and shap; check them on Windows and with numpy, with a fallback if shap fails<br>2. Create the `heatwave/forecast/` package and `forecast.yaml` (splits, leads, latency, model settings, gate thresholds, refit policy), validated when loaded<br>3. Write the frozen-data loader (checksum check against MANIFEST, column check, compact ward × week array)<br>4. Build the week index (label ↔ integer ↔ start date, including 53-week years)<br>5. Build run folders that record config, data hash, commit, library versions and seed<br>6. Create a small synthetic dataset so CI doesn't need the real data<br>7. Move CI to Python 3.12; add a test that the code never imports Earth Engine | Checksum-verified frozen-data loader, week index, `forecast.yaml`, reproducible run folders, new libraries, CI on 3.12 | DATA-01–05 | – |
| 9 | Features, targets, splits and leakage tests | 1. Measure the real ERA5-Land delay, and heatwave-week frequency by year and region<br>2. Build `heatwave_week` targets for leads 1–6 with timing fields<br>3. Fit a climatology on 1991–2014 only, for anomalies<br>4. Build past-only features: recent heat, hot days and hot nights (1, 2, 4 weeks); humidity, rainfall and soil-moisture anomalies; season; trend and base-rate; LGA and state averages; location<br>5. Write the splits (train 1991–2014, validate 2015–2020, test 2021–2026) by target week with a boundary gap, plus expanding-window folds<br>6. Write the leakage tests (cutting the data, overwriting the future, deliberately injecting a leak) | Past-only features, lead 1–6 targets with timing fields, embargoed splits, prevalence and data-delay report | FEAT-01–06 | 8 |
| 10 | Baselines, evaluation harness and test lock | 1. Build 5 baselines: climatology, recent 10-year climatology, persistence, damped persistence, trend + season<br>2. Build the scoring harness: Brier and Brier skill score, AUC by season and region, reliability, precision/recall/F1, calibration by year<br>3. Build confidence intervals by resampling whole weeks and whole years<br>4. Slice by lead, season, region and year; flag the LGA-average wards<br>5. Build the test lock (2021–2026 unreadable until pre-registration is committed)<br>6. Score all baselines on 2015–2020 | Five baselines, one scoring path, bootstrap CIs, slices, 2021–2026 locked | EVAL-01–05 | 9 |
| 11 | Logistic regression | 1. Train one regularised model per lead on 1991–2014 and score it on 2015–2020 against the best baseline, with CIs<br>2. Negative controls (year-shuffled features should show no skill; skill should fall as the lead grows)<br>3. Ablation steps (season → location → trend → persistence → heat → land) | First trained model per lead, validation skill vs the best baseline, negative controls | MODEL-01, EVAL-06 | 10 |
| 12 | LightGBM and calibration | 1. Tune LightGBM per lead with expanding-window CV (strongly regularised, deterministic)<br>2. Calibrate on out-of-fold predictions, choosing Platt or isotonic per lead<br>3. Reliability plots; compare LightGBM with logistic regression<br>4. Extrapolation check: count recent rows outside the training range<br>5. **Decision point:** if there's no skill, skip Phase 13 | Tuned LightGBM, out-of-fold calibration, extrapolation check | MODEL-02–04 | 11 |
| 13 | Secondary targets | 1. Heat Index anomaly as p10/p50/p90 (fix crossed quantiles; check the 80% range holds about 80%)<br>2. Hot-night probability, reusing the Phase 12 setup | HI anomaly quantiles, hot-night probability (deferred if Phase 12 shows no skill) | SEC-01–02 | 12 |
| 14 | Explainability, one-shot test, report and go/no-go | 1. SHAP explanations and the full ablation ladder<br>2. Write and commit the pre-registration (score, leads 2–3, baselines, CI method, pass threshold) before touching the test data<br>3. Refit the chosen model on 1991–2020 with its settings frozen<br>4. Open the lock and score 2021–2026 **once**<br>5. Record go/no-go in `GATE.json`; write `FORECAST_REPORT.md` with the reanalysis caption, and detection kept separate from forecasting<br>6. **User review** of the decision and report | SHAP and ablations, single locked test, `GATE.json`, `FORECAST_REPORT.md` | DEC-01–04 | 12 |
| 15 | Operational forecast for CHAP | 0. **Before starting:** confirm column names with the CHAP team<br>1. Retrain the release model on all years, with a model card marked "not independently tested"<br>2. Weekly forecast script: latest pipeline output, same feature code as training, check of live data against the frozen version<br>3. CHAP table (no missing values, unbroken weeks, `heatwave_prob` + `heatwave_week`), then `chap validate`<br>4. Archive and manifest; update METHODOLOGY and README | Release model, CHAP-valid weekly table, archive, manifest, docs (only for leads that pass) | OPS-01–04 | 14 (go) |
| 16 | Climate drivers | 1. Download and freeze the ENSO, Atlantic SST and MJO indices, lagged by their publication delay<br>2. Pre-register a fresh test (the 2021–2026 test is already used)<br>3. Measure the skill they add; release a new model version only if the gain is clearly above zero, otherwise document no gain | Frozen climate-driver inputs, judged by the skill they add | DRV-01–02 | 14 (go) |

## Phase Details

### Phase 8: Forecast Foundation

**Goal**: An analyst can load the frozen `covariates-v1.0` data safely, do correct week arithmetic, configure forecast runs, and reproduce any run, without disturbing the existing 166 tests.
**Depends on**: Nothing (first v2.0 phase)
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05
**Success Criteria** (what must be TRUE):

  1. Loading the real frozen Parquet succeeds locally; a corrupted or modified copy is rejected on SHA-256 mismatch, and the live `outputs/covariate_table.csv` is refused for training.
  2. Converting ISO labels to an integer index and `week_start` dates round-trips correctly across the 53-week years (1992, 1998, 2004, 2009, 2015, 2020, 2026), including 2020-W53 into 2021-01-03.
  3. A validated `forecast.yaml` holds all forecast settings, and bad values (e.g. misordered split years) are rejected, while `config.yaml` and `tests/test_config.py` are unchanged.
  4. A run writes a folder outside the repo with config snapshot, data hash, git commit, library versions and seed.
  5. CI is green on Python 3.12 with scikit-learn, LightGBM and shap installed, the 166 existing tests still pass, and an import test shows the forecast package never imports `ee` or `geemap`.

**Plans**: 7 plans

Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Install scikit-learn/LightGBM/shap after dry-run approval; pin in requirements.txt; import smoke test
- [x] 08-02-PLAN.md — `heatwave/forecast` package, 53-week-safe week index, frozen marker + conftest, requires-python >=3.12

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 08-03-PLAN.md — Validated `forecast.yaml` + config dataclasses (splits/cutoffs, leads, latency, baselines, gate, retrain policy, models, seed)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 08-04-PLAN.md — Hash-verified frozen loader (dense float32 Panel), live-CSV refusal, synthetic frozen dataset for CI
- [ ] 08-05-PLAN.md — Reproducible run folders with RUN_MANIFEST provenance outside the repo

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 08-06-PLAN.md — `scripts/verify_frozen.py` + real-data `@frozen` integration tests

**Wave 5** *(blocked on Wave 4 completion)*

- [ ] 08-07-PLAN.md — Earth Engine import-isolation tests, CI on Python 3.12, README note, full regression, push + CI-green checkpoint

### Phase 9: Features, Targets, Splits and Leakage Suite

**Goal**: Leakage-safe features, lead-aligned targets and time-honest splits exist and are proven leak-free before any model is trained.
**Depends on**: Phase 8
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05, FEAT-06
**Success Criteria** (what must be TRUE):

  1. For each lead 1-6, the `heatwave_week` target aligns to the exact target week, and every row carries `last_obs_week`, `issue_date`, `target_week`, `lead_weeks` and `effective_days_ahead`.
  2. As-of features (lags, rolling means, season, trend/base-rate level, LGA/state context, static location) are built from data up to the last observed week only, and fitted statistics record their train-only fit range. No raw year index is used.
  3. The leakage suite passes on real features, and fails when a leak is deliberately injected (truncation, future-overwrite, changed validation/test data, nonzero `max_lookahead`).
  4. Splits by target week with an embargo (train 1991-2014, validate 2015-2020, test 2021-2026) and expanding-window CV folds use `week_start` cutoffs.
  5. A pre-model report shows `heatwave_week` prevalence by year, region and era, and the measured ERA5-Land latency.

**Plans**: TBD

### Phase 10: Baselines, Evaluation Harness and Test Lock

**Goal**: The analyst can see exactly what a model must beat, scored through one honest path, with the test years mechanically locked.
**Depends on**: Phase 9
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05
**Success Criteria** (what must be TRUE):

  1. Five baselines (climatology, recent pooled climatology, probabilistic persistence, damped persistence, trend+season) have validation scores per lead through the same harness; BSS of a reference against itself is 0 and persistence skill decays with lead.
  2. Reports include Brier/BSS with a named reference and Brier decomposition, stratified ROC AUC, quantile-bin reliability, P/R/F1 at a stated threshold and calibration-in-the-large by year, with no accuracy metric.
  3. Confidence intervals come from paired week-block (>= 4 weeks) and year-block bootstraps, never row or ward resampling.
  4. Results break down by lead, season (March-May highlighted), region and year, with the 6 LGA-average and small wards flagged.
  5. Loaders refuse 2021-2026 test rows until a pre-registration file is committed and the lock is opened; the evaluation log shows no test run yet.

**Plans**: TBD

### Phase 11: Logistic Regression per Lead

**Goal**: A regularised, interpretable per-lead model exists with honest validation evidence against the best baseline.
**Depends on**: Phase 10
**Requirements**: MODEL-01, EVAL-06
**Success Criteria** (what must be TRUE):

  1. Per-lead logistic models train deterministically (same seed gives same output) with train-only standardisation and no class reweighting.
  2. Validation BSS against the best baseline per lead is reported with paired CIs.
  3. The year-shuffled-features negative control shows no skill, and the skill-vs-lead decay check is reported.

**Plans**: TBD

### Phase 12: LightGBM, Calibration and Selection

**Goal**: A strongly regularised, deterministic LightGBM per lead produces calibrated probabilities, with extrapolation risk visible.
**Depends on**: Phase 11
**Requirements**: MODEL-02, MODEL-03, MODEL-04
**Success Criteria** (what must be TRUE):

  1. LightGBM per lead is tuned with expanding-window CV, deterministic, regularised, with no class reweighting; logistic vs LightGBM comparison with CIs is available.
  2. Per-lead calibration (Platt or isotonic chosen by CV Brier, outputs clipped) uses out-of-fold predictions, and calibration rows never overlap fitting or early-stopping rows.
  3. Reliability plots on held-out validation rows are within the stated tolerance.
  4. A report shows how many evaluation rows fall outside each feature's training range.

**Plans**: TBD
**Note**: Short design spike on real validation predictions is advised (calibration fit set, regime shift). If this phase shows no skill over the best baseline, Phase 13 is deferred.

### Phase 13: Secondary Targets

**Goal**: Where the primary target shows skill, analysts can also forecast Heat Index anomaly quantiles and hot-night probability.
**Depends on**: Phase 12 (deferred if Phase 12 shows no skill)
**Requirements**: SEC-01, SEC-02
**Success Criteria** (what must be TRUE):

  1. Per-lead non-crossing p10/p50/p90 Heat Index anomaly forecasts exist, with pinball loss reported.
  2. 80% interval coverage is near nominal by year and region on validation.
  3. Hot-night probability per lead is scored and calibrated through the same harness and calibration as the primary target.

**Plans**: TBD

### Phase 14: Explainability, One-Shot Test, Report and Go/No-Go

**Goal**: The project reaches an honest, pre-registered decision on whether the trained model has skill, and stakeholders can read it.
**Depends on**: Phase 12 (Phase 13 optional)
**Requirements**: DEC-01, DEC-02, DEC-03, DEC-04
**Success Criteria** (what must be TRUE):

  1. Grouped SHAP, grouped permutation importance and the ablation ladder (season, location, trend, persistence, lagged heat, soil/humidity/rain) are produced.
  2. With the pre-registration committed, the model is refit on 1991-2020 with frozen hyperparameters and scored once on 2021-2026; the evaluation log shows exactly one test run and `GATE.json` records the go/no-go (leads 2-3, BSS > 0 vs the best baseline with CI excluding 0).
  3. `docs/FORECAST_REPORT.md` gives skill by lead, season and region with CIs, an effective-lead table, a skill mask, the mandatory reanalysis-label caption, and separates the rule-based detection layer from the trained forecast layer.
  4. On a no-go, the report names the leads without skill and recommends the ECMWF S2S benchmark; Phases 15-16 then proceed only for leads that passed (or not at all).

**Plans**: TBD
**Gate**: Go/no-go here controls Phases 15 and 16.

### Phase 15: Operational Weekly Forecast for CHAP

**Goal**: CHAP can read a validated weekly forecast table for the leads that passed the gate.
**Depends on**: Phase 14 (go, for passing leads only)
**Requirements**: OPS-01, OPS-02, OPS-03, OPS-04
**Success Criteria** (what must be TRUE):

  1. A weekly forecast is produced from the latest `run_local_pipeline.py` output using the same feature code as training, plus a release bundle retrained on all years with a model card marked "not independently tested".
  2. The CHAP table (`time_period`, `location`, `heatwave_prob`, observed `heatwave_week`, `lead_weeks`, `skill_flag`) has no missing values and an unbroken week run per ward, and passes `chap validate`. Column names are confirmed with the CHAP team.
  3. Each run writes the long-format archive (including `hi_anomaly_p10/p50/p90` where Phase 13 ran) and a FORECAST_MANIFEST, and flags drift between live history and frozen values.
  4. METHODOLOGY and README describe the forecast layer, how to run it and its caveats.

**Plans**: TBD

### Phase 16: Climate Drivers

**Goal**: The value of ENSO, tropical Atlantic SST and MJO drivers is measured, and a new model version is released only if they demonstrably help.
**Depends on**: Phase 14 (go); sequenced after Phase 15
**Requirements**: DRV-01, DRV-02
**Success Criteria** (what must be TRUE):

  1. A frozen, versioned dataset of Nino3.4/ONI, TNA (plus ATL3 if a source is found) and MJO RMM exists with checksum, as-published values, and features lagged by each index's publication delay.
  2. A paired ablation under a fresh pre-registered protocol (expanding-window CV on 2015-2026) reports the gain with a CI.
  3. A new model version is released only if the gain's CI is above 0; otherwise a no-gain result is documented.

**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 8. Forecast Foundation | 0/0 | Not started | - |
| 9. Features, Targets, Splits and Leakage Suite | 0/0 | Not started | - |
| 10. Baselines, Evaluation Harness and Test Lock | 0/0 | Not started | - |
| 11. Logistic Regression per Lead | 0/0 | Not started | - |
| 12. LightGBM, Calibration and Selection | 0/0 | Not started | - |
| 13. Secondary Targets | 0/0 | Not started | - |
| 14. Explainability, One-Shot Test, Report and Go/No-Go | 0/0 | Not started | - |
| 15. Operational Weekly Forecast for CHAP | 0/0 | Not started | - |
| 16. Climate Drivers | 0/0 | Not started | - |
