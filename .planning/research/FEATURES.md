# Feature Landscape

**Domain:** Sub-seasonal (1-6 week) ward-level heatwave probability forecast product feeding a health platform (CHAP)
**Milestone:** v2.0 Heat Forecasting (forecast layer on top of frozen `covariates-v1.0`)
**Researched:** 2026-10-02
**Overall confidence:** MEDIUM (CHAP format HIGH; West Africa skill evidence MEDIUM, mostly dynamical-model literature, none for a statistical ward-level model; predictor-skill claims for ENSO/Atlantic SST at 1-6 weeks are LOW)

## Key context shaping the feature list

1. **The skill literature is about dynamical models.** Published Sahel/West Africa sub-seasonal heatwave skill (ECMWF extended-range) is useful 1-2 weeks, near climatology by weeks 3-4 (anomaly correlation about 0.6 in week 1 falling to about 0.2 by weeks 3-4). A statistical model using only past ERA5-Land will mostly get skill from **persistence, seasonal cycle and trend**, and probably from soil moisture and humidity. Expect modest Brier skill score (BSS) over a *trend-aware* climatology at leads 3-6. A "no skill beyond climatology at lead N" result is a legitimate outcome and the go/no-go must be able to report it.
2. **Because the label is ERA5-Land percentile exceedance against a fixed 1991-2020 baseline, the trend is part of the signal.** Hot days/ward/yr rose from about 25 (1991-2000) to about 56 (2016-2025), so the base rate of a heatwave week is non-stationary. A full-history climatology will be badly biased low on the 2021-2026 test years. This is why the 10-year recent climatology baseline is not optional.
3. **CHAP wants deterministic covariate columns, not distributions.** The probability must be flattened into a table column.

## Table Stakes

Features a forecast product for a health platform must have. Missing any of these means the product is not trustworthy or not consumable.

| Feature | Why Expected | Complexity | Dependencies on existing pipeline / notes |
|---------|--------------|------------|-------------------------------------------|
| Binary target `heatwave_week` = (`heatwave_days` >= 3) per ward-week | Matches the agreed primary target and the WMO/ETCCDI style definition already used in detection (>=3 days above the daily 90th percentile; same definition as NHESS 2025 West African study). | Low | Derived directly from `covariates-v1.0` `heatwave_days`. Do NOT use `heatwave_event_count` as the label (events are counted only in the start week and a 3-day run split across the week boundary would label wrongly). Document the definition mismatch: label is "3 hot days in the week", not "event". |
| Forecast reference timing: `issue_week` (last observed week), `lead_weeks` (1-6), `target_week` (ISO `YYYY-Www`) | Every sub-seasonal product states issue date and valid period; users must know what a "week 3" forecast means. Without this, leakage and misuse follow. | Low | ISO-week handling already exists (METHODOLOGY section 6, Thursday trick). Define lead 1 = week after last observed week. Because ERA5-Land lags about 8 days, lead 1 is about 1.5-2 weeks after real time; record `data_cutoff_date` too. |
| Climatology baseline (day-of-year/week-of-year, per ward) | The reference for BSS in all sub-seasonal verification; the CPC/S2S community scores against climatology. | Low | Per-ward, per-ISO-week base rate from training years only (1991-2014). |
| 10-year recent (trend-aware) climatology baseline | The correct reference under strong warming. Literature handles trend by detrending anomalies or using recent-period climatology; fixed-baseline anomalies absorb the trend into "skill" otherwise. | Low | Rolling last-10-years base rate by ward x week-of-year, computed strictly from data before `issue_week`. Pool +-1-2 weeks and optionally neighbouring wards to reduce noise (about 10 samples per cell is very noisy). |
| Persistence baseline | Standard minimal skill benchmark at weeks 1-2. | Low | "Last observed week's `heatwave_days` >=3" and a smoothed variant (last 2-4 week mean). |
| Strictly causal lagged feature set from the frozen table with automated leakage test | Leakage is the dominant failure mode of weekly time-series ML. | Medium | Features: lags of `heatwave_days`, `max_heat_index`, `mean_heat_index`, `hot_nights`, rainfall, RH, soil moisture at 0..k weeks; rolling means; all computed as of `issue_week`. Test: truncate the table at `issue_week` and assert identical features. Handle null Heat Index weeks (no-data vs zero rule from METHODOLOGY section 6). |
| Seasonal cycle features (sin/cos of week-of-year, or week index) | Dominant source of skill in the Sahel; heatwave risk peaks pre-monsoon (Mar-May) and post-monsoon (Oct-Nov). Cheap and mandatory. | Low | Also include `target_week` seasonality (not just issue-week) because the model is per-lead. |
| Trend feature(s) (year index, and/or recent-10y ward base rate as a feature) | Without it, models trained on 1991-2014 under-predict 2021-2026. Highest-value single feature given the data. | Low-Med | Ablate: with/without year, with/without recent base rate. Tree models cannot extrapolate a year index, so prefer a trailing-N-year ward base rate or hot-day anomaly as a feature (LightGBM-friendly). Flag as the key extrapolation risk for the test period. |
| Spatial context features (ward lat/lon, state/zone, neighbour or state-mean lagged anomaly) | Heat anomalies are spatially coherent at weekly scale; neighbours' values reduce noise. Middle belt warms faster than far north so region matters. | Medium | Needs ward centroid and neighbour/state aggregation (ward boundary asset exists). Compute spatial means from the table only. |
| Soil moisture, rainfall, RH lagged features | Soil-moisture/evaporative-cooling coupling and moisture greenhouse effect are the documented physical drivers of Sahelian heatwaves and the main slow-memory source at weeks 3-4 in sub-seasonal ML literature. Already in the table. | Low | Already in covariates; add anomalies versus ward-week climatology (soil moisture and RH) so the seasonal cycle does not dominate. |
| Calibrated probabilities (isotonic, fitted on validation years) | The product's value for CHAP is a usable probability; uncalibrated LightGBM/logistic outputs are not. | Medium | Calibrate per lead on 2015-2020 only; check reliability on 2021-2026 once. Isotonic with a minimum-bin-count guard (heatwave weeks are rare in cool months; pool across wards). |
| Per-lead models (1-6), same feature contract | Agreed design; standard direct strategy for multi-horizon. | Medium | 6 models x (logistic, LightGBM) x calibration; keep a single training function parameterised by lead. |
| Headline metric BSS vs climatology AND vs recent climatology; ROC AUC; reliability diagram; stratified by lead, season, region | Standard probabilistic verification (Brier score/BSS used in S2S extreme-event studies; hit rate/FAR/Gilbert skill score for event detection). Health users need to know where it is trustworthy. | Medium | Week-block bootstrap CIs (already planned) because wards in a week are strongly correlated. Report both baselines; the recent-climatology BSS is the honest one. |
| Skill report that states "no skill" where true, per lead/season/region | Honest reporting; the literature says weeks 3-4 are near climatology. | Low | A skill mask in the output (see differentiators) or at minimum in the evaluation report. Go/no-go gate per lead. |
| Weekly forecast table in CHAP-consumable shape | The deliverable. See "CHAP integration" below. | Medium | Depends on a column-naming decision and on a historic-side counterpart column. |
| Versioned, documented output (model version, training data tag `covariates-v1.0`, code commit, issue date) | Reproducibility; consumers must be able to tell forecasts apart after retraining. | Low-Med | Manifest pattern already used for the frozen dataset. Write `forecast_manifest.json` next to each output. |
| No-NaN, gap-free output across all 4,841 wards and requested leads | CHAP rejects locations with missing covariates and requires consecutive periods and identical period sets per location. | Low | Validate with `chap validate` before release. Fallback for wards with null features: use recent climatology and flag it, never emit NaN. |

## Differentiators

Valuable, not expected for a first release.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Secondary target: weekly max Heat Index anomaly quantiles (LightGBM quantile) | Gives intensity and uncertainty, not just occurrence; interval coverage is verifiable. | Medium | Anomaly relative to ward-week climatology, preferably recent/detrended. Report pinball loss and 80% interval coverage. Planned; do after the primary target. |
| Secondary target: hot nights probability or count | Separate health risk (night-time heat, sleep, mortality). | Medium | Same pipeline, different label; `hot_nights` is in the table. |
| Expected `heatwave_days` or categorical (0 / 1-2 / >=3 / >=5 days) forecast | Richer than binary; matches tercile/quintile category style of S2S products. | Medium | Ordinal or multi-class variant; defer. |
| Climate drivers (ENSO/Nino3.4, tropical Atlantic SST/Atlantic Nino, MJO RMM phase/amplitude) | Literature: MJO and equatorial waves significantly modulate Sahelian heatwave probability (Dynamics paper below); Atlantic SST/ENSO affect monsoon onset and spring heat. **Expected lift at 1-6 weeks is small and uncertain; MJO is the one with sub-seasonal timescale.** | Medium (data ingestion) | Already scheduled for a later phase; measured by ablation skill gain. External data: NOAA ONI/Nino3.4 monthly, NOAA OISST indices, BoM or NOAA RMM index (daily, publicly available). Keep lag/availability discipline (monthly indices are published with delay). Confidence LOW on skill gain. |
| Skill mask / confidence flag per (lead, region, season) in the output | Lets CHAP or users ignore leads where the model does not beat recent climatology; prevents over-trust at lead 4-6. | Low-Med | Derive from validation BSS; ship as `skill_flag` column or sidecar file. |
| Reliability by region/season, bundled with each release | Evidence that probabilities mean the same thing in the middle belt and the far north. | Medium | Reuse evaluation code; publish as a static report per model version. |
| SHAP and ablation tables | Explains which predictors drive skill (persistence vs soil moisture vs trend). Supports scientific credibility. | Medium | Planned. Beware correlated lags; report grouped SHAP. |
| ECMWF S2S benchmark | A credible upper-bound reference if accessible. | High | Explicitly out of scope except as fallback/benchmark. Do not build now. |
| Hierarchical pooling (ward -> state -> zone) in climatology baselines | Stabilises rare-event base rates. | Low-Med | Improves the recent-climatology baseline itself; strong value for cheap. |
| Forecast archive (every issue's output kept) and rolling live verification | Allows ongoing skill monitoring after deployment as new ERA5-Land weeks arrive. | Medium | Needs a stable issue-week scheduler and storage layout. |

## Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Fitting on all 1991-2026 data and quoting skill | Leakage and optimism; breaks the one-shot test | Time split as agreed; touch 2021-2026 once; for the operational model retrain on all data after the evaluation freeze, and say so |
| Full-history climatology as the sole skill reference | Trend makes it a straw man; inflates BSS | Report BSS versus recent climatology as the headline |
| Random or ward-wise K-fold CV | Spatial and temporal autocorrelation inflate scores | Blocked/time-ordered splits; week-block bootstrap |
| Using ENSO/SST/MJO before baselines and lagged-feature models are proven | Adds ingestion and leakage surface; unclear value | Keep for a later phase and judge by ablation |
| Reporting skill with ROC AUC/accuracy only | Heatwave weeks are seasonal and imbalanced; AUC is dominated by seasonal cycle | BSS versus climatology baselines plus reliability |
| Treating ERA5-Land labels as station truth in communication | Station check shows heatwave-week overlap only about 37-50%, weekly Tmax anomaly r about 0.8 | State label provenance in every report and manifest; refer to METHODOLOGY section 9 |
| Disease-impact features or health-warning thresholds inside this repo | Out of scope; CHAP does disease modelling | Provide a clean heat covariate; leave impact to CHAP |
| Per-ward bespoke models (4,841 models) | Overfits, huge ops burden | One pooled model per lead with ward/region features |
| Deep learning/foundation weather emulators | Excess complexity for a 35-year weekly table, no evidence of gain here | Logistic then LightGBM, as agreed |
| Streamlit polish for forecasts | App is QA tooling only (PROJECT.md) | At most a map layer reading the forecast table |
| Hard yes/no heatwave alerts without a documented threshold | Decision thresholds are a user/policy choice | Ship probabilities; optionally document suggested thresholds from validation precision/recall |

## Target definitions seen in practice (and the choice for this project)

| Practice | Used by | Fit here |
|----------|---------|----------|
| Exceedance probability of daily percentile (binary event) with Brier score/BSS | NHESS 2025 West African heat waves (>=3 days above climatological 90th percentile; Brier, CRPS, hit rate, FAR, Gilbert skill score); NOAA subseasonal extreme-warm-day work (BSS on semidecile exceedance) | Direct match; chosen primary target |
| Tercile/quintile categories, RPSS | ECMWF/WMO S2S weekly products, CPC week 3-4 outlooks | Differentiator variant (ordinal days) |
| Weekly mean anomaly (deterministic, ACC, RMSE) | ECMWF extended range verification | Used for the Heat Index anomaly secondary target |
| Trend handling: detrend observed anomalies, or use recent-period climatology, or "persistence++" blends of lagged obs with climatology | S2S ML literature (Persistence++ and anomalies detrended to remove anthropogenic forcing) | Recent climatology baseline + trend/base-rate features |

## CHAP integration (what the platform expects)

Verified by reading `dhis2-chap/chap-core` docs on GitHub (`docs/external_models/data_formats.md`, `describe_model.md`, `generated_features.md`).

- Dataset CSV columns: `time_period`, `location`, `disease_cases` (target, NaN allowed), model-declared covariates (e.g. `rainfall`, `mean_temperature`), optional `population`. Covariates must be fully observed: **no NaN**.
- `time_period`: `YYYY-Wnn` for weekly (e.g. `2023-W01`), `YYYY-MM` monthly; do not mix. Our `YYYY-Www` ISO-week format matches.
- Every location must have exactly the same set of consecutive time periods, no gaps; `chap validate --dataset-csv ...` checks this.
- Models are called as `predict.py {model} {historic_data} {future_data} {out_file}`. `future_data` holds the future time periods **with their covariates** and `disease_cases` missing. A model's predictions are `time_period, location, sample_0..sample_N`.
- CHAP does **not** impute covariates and has no ensemble dimension for covariates; future covariates are one value per (location, period). Forecast heat indicators therefore have to be delivered as ordinary covariate columns for the future periods (for example `heatwave_prob`, plus optional anomaly quantile columns and `lead_weeks`).
- Implications: (a) the historic side needs a *comparable* column, e.g. observed `heatwave_week` (0/1) beside forecast `heatwave_prob`, because a CHAP model reads one column across both historic and future rows; (b) the table must span the whole CHAP prediction horizon for all 4,841 wards (the chapkit EWARS example supports 0-100 periods with default 3), so deliver leads up to 6 and let CHAP trim; (c) `location` must equal `wardcode` used by the DHIS2 org-unit mapping (CHAP supports a data-source column mapping via `--data-source-mapping`, so column renaming is cheap); (d) the one-forecast-per-(ward, target week) rule means pick the forecast issued most recently for each target week, and keep full issue-week metadata in a separate long-format archive file.
- Confidence: HIGH on format rules (official docs). MEDIUM on how DHIS2-side CHAP would ingest a *pre-computed forecast* covariate (docs describe climate data imports through DHIS2 Climate Tools; I did not find a documented "forecast covariate" path distinct from historic covariates). Check with the CHAP team or `climate-tools.dhis2.org` before finalising column names.

## Evidence on predictors and skill (West Africa/Sahel)

| Claim | Evidence | Confidence |
|-------|----------|------------|
| ECMWF extended-range forecasts have significant skill for Sahelian heatwaves to about 2 weeks; wet heatwaves more predictable than dry ones at longer leads | Sahel dynamics/prediction paper, Climate Dynamics 2021 (link below) | MEDIUM (abstract-level via search; paywalled) |
| ACC of thermal indices above 0.6 in week 1, falling to about 0.2 by weeks 3-4 | NHESS 2025 and related summaries | MEDIUM |
| Skill depends on regime: Atlantic coastal region highest skill (low variability), continental Sahel highest variability and strongest heatwaves, Guinean coast humidity-driven | NHESS 2025 | MEDIUM |
| Dominant physical drivers: heat advection and moisture (greenhouse) effect; heatwave peaks pre- and post-monsoon | Barbier et al. 2018 (MWR), Guigma et al. 2020 (Climate Dynamics), Bouniol et al. 2021 | MEDIUM |
| MJO and equatorial waves modulate probability/intensity of Sahelian heatwaves | Climate Dynamics 2021 | MEDIUM |
| Soil moisture deficit reduces evaporative cooling, reinforcing heat; antecedent root-zone soil moisture contributes to week 3-4 skill in hybrid statistical-dynamical models | Domeisen et al. 2022 (Nat Rev Earth Env); sub-seasonal ML literature | MEDIUM |
| ENSO and Atlantic SST skill at 1-6 weeks over northern Nigeria | No direct source found; known influence is mostly seasonal | LOW |
| Expected statistical skill by lead (this project) | My expectation, not sourced: some BSS vs recent climatology at leads 1-2 (persistence, soil moisture), approaching zero by 4-6 except seasonal-cycle effects already in climatology | LOW |

## Feature Dependencies

```
covariates-v1.0 (frozen)
  -> heatwave_week label (>=3 hot days)
  -> causal lagged features + leakage test
       -> baselines (climatology, recent climatology, persistence)
       -> logistic regression per lead
            -> LightGBM per lead
                 -> isotonic calibration (validation years)
                      -> evaluation (BSS, reliability, by lead/season/region, bootstrap)
                           -> go/no-go + skill mask
                                -> CHAP forecast table + manifest/versioning
  -> anomaly target -> LightGBM quantile models (after primary)
  -> climate drivers (later) -> ablation
Ward geometry/centroids + state -> spatial context features
Historic-side heatwave_week column -> CHAP model compatibility with forecast column
```

## MVP Recommendation

Prioritise:
1. Label, causal feature store, leakage test (foundation for everything).
2. Three baselines including the recent (trend-aware) climatology, with the evaluation harness (BSS, reliability, by lead/season/region, week-block bootstrap). This tells you what a model must beat.
3. Regularised logistic regression per lead with seasonal, trend/base-rate, lagged heat, soil moisture/RH and simple spatial features; then LightGBM; isotonic calibration; go/no-go.
4. CHAP forecast table with no NaN, ISO-week `time_period`, `location`=wardcode, manifest and version, validated with `chap validate`.
5. One differentiator early: skill mask per lead/region.

Defer: quantile anomaly and hot-night targets until the primary target passes go/no-go; climate drivers (ENSO/Atlantic SST/MJO) until baselines and lagged models are done; ECMWF S2S benchmark; categorical/ordinal targets.

## Open questions for the roadmap

- Final CHAP column names and whether CHAP needs a historic counterpart column (`heatwave_week`) in the covariate table (small change to the existing table, or a derived file).
- Whether the recent-climatology baseline should use ward-only, state-pooled, or neighbour-pooled cells (affects both baseline strength and BSS headline).
- Lead 1 timing relative to real time, given the 8-day ERA5-Land delay (document explicitly).
- Whether the operational model retrains after the one-shot test and how that is communicated.

## Sources

- CHAP data format (official, HIGH): https://github.com/dhis2-chap/chap-core/blob/master/docs/external_models/data_formats.md
- CHAP train/predict contract (official, HIGH): https://github.com/dhis2-chap/chap-core/blob/master/docs/external_models/describe_model.md
- CHAP generated features (official, HIGH): https://github.com/dhis2-chap/chap-core/blob/master/docs/external_models/generated_features.md
- CHAP own-data guide (official, HIGH): https://github.com/dhis2-chap/chap-core/blob/master/docs/external_models/prepare_data/own-data.md
- chapkit EWARS example (output samples, horizon, MEDIUM): https://github.com/chap-models/chapkit_ewars_model
- Subseasonal forecasts of heat waves in West African cities, NHESS 2025 (MEDIUM): https://nhess.copernicus.org/articles/25/147/2025/
- Forecasting West African Heat Waves at Subseasonal and Seasonal Time Scales, MWR 2018 (MEDIUM): https://journals.ametsoc.org/mwr/article/146/3/889/103156/Forecasting-West-African-Heat-Waves-at-Subseasonal
- Prediction skill of Sahelian heatwaves out to subseasonal lead times and importance of atmospheric tropical modes of variability, Climate Dynamics 2021 (MEDIUM, abstract only): https://link.springer.com/article/10.1007/s00382-021-05726-8
- Characteristics and thermodynamics of Sahelian heatwaves (MEDIUM): https://link.springer.com/article/10.1007/s00382-020-05438-5
- Characterization of Heat Waves in the Sahel and Associated Physical Mechanisms, J. Climate 2017 (MEDIUM): https://journals.ametsoc.org/view/journals/clim/30/9/jcli-d-16-0432.1.xml
- Domeisen et al. 2022, Prediction and projection of heatwaves, Nat Rev Earth Environ (MEDIUM): https://bpb-us-e1.wpmucdn.com/sites.mit.edu/dist/f/680/files/2024/07/Domeisen_et_al_2022_Nature_Reviews.pdf
- Subseasonal ML: Persistence++, BSS on exceedance, detrended anomalies (LOW-MEDIUM, from search summaries): https://arxiv.org/html/2604.16238 ; https://repository.library.noaa.gov/view/noaa/54095
- WHO/WMO Heatwaves and Health: Guidance on Warning-System Development (MEDIUM): https://reliefweb.int/report/world/heatwaves-and-health-guidance-warning-system-development
