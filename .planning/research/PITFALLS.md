# Domain Pitfalls

**Domain:** Sub-seasonal (1-6 week) probabilistic heat forecasting, 4,841 wards, ERA5-Land-derived labels, added on top of a rule-based detection pipeline
**Researched:** 2026-10-02
**Scope:** Mistakes made when ADDING the v2.0 forecast layer to this system (frozen `covariates-v1.0`, 1991-W02..2026-W38, 9.0M rows).
**Overall confidence:** MEDIUM-HIGH. Project-specific findings (items marked [PROJECT]) were derived directly from `.planning/PROJECT.md` and `docs/METHODOLOGY.md` sections 4-6, 8, 9. General methodology comes from well-established forecast-verification and ML-evaluation practice. References are from training knowledge and were NOT re-fetched in this session; treat citations as MEDIUM confidence and check them before quoting in the report.

Phase vocabulary used below: **FS** = feature store, **BH** = baselines + harness, **MOD** = models, **CAL** = calibration, **FE** = final evaluation, **OPS** = operational.

---

## Critical Pitfalls

### C1. Target-week or future information in features (temporal leakage) [FS]
**What goes wrong:** Any column for week t+k (the target week) or later enters the feature row for origin t. In this table the dangerous columns are the ones concurrent with the label: `heatwave_days`, `hot_nights`, `heatwave_event_count`, `mean_heat_index`, `max_heat_index`. Common ways it happens: (a) a rolling window with `center=True` or a pandas `rolling()` that is not shifted so it includes the origin-plus-one week; (b) `groupby(ward).shift(-k)` for the label done on a frame that is not sorted by time, or after a merge that reorders; (c) shifting by row count when weeks are missing (the table starts 1991-W02, and ISO week 53 exists only in some years); (d) a "week-of-year mean" or "ward mean" feature computed over the full file; (e) forward-filling or interpolating across the origin.
**Why it happens:** the labels live in the same table as the features, so the label column is one typo away from being a feature.
**Consequences:** AUC 0.95+, BSS far above any literature value for week 3+ heat forecasts. The report is invalid and the go/no-go is meaningless.
**Prevention:**
- Make the feature store schema explicit: every feature has a declared `max_source_week_offset <= 0` relative to the origin week. Build features only from a time-sorted, gap-checked panel keyed by `week_start` date, never by row position.
- Never read the raw table in model code; models read only the feature-store output, whose columns are whitelisted.
- Label for lead k is built in one place: `label[t, k] = heatwave_days[t+k] >= 3`, using date-based join (week_start + 7k days), not `shift`.
**Automated tests:**
1. Truncation invariance: for 50 random origins, recompute features using only data with `week_start <= origin`; assert equality with the full-run features (allclose). This is the strongest single test.
2. Poison test: overwrite all data after the origin with NaN/random noise, rebuild features, assert unchanged.
3. Schema test: assert no feature column name in the target-concurrent list (`heatwave_days`, etc.) appears with offset > 0; assert feature set at lead k does not change when label horizon changes.
4. Univariate screen: fit a one-feature model for each feature; flag any single feature with AUC > 0.9 or BSS > 0.5 at lead >= 2.
**Detection:** skill that does not decay with lead; skill at lead 6 about equal to lead 1; one feature dominating SHAP with an implausible gain.

### C2. Data latency / issue-time misalignment: "lead 1" is not a forecast in operation [PROJECT] [BH, OPS]
**What goes wrong:** Lead is defined as "weeks from the last observed week". If week W ends Sunday S, its ERA5-Land data is available about S+8 days (stated latency ~8 days). Lead-1 target week W+1 spans S+1..S+7, so by the time the issue-time data exists the target week is already over. Lead 1 is then a hindcast/nowcast of a completed week, and lead 2 begins only about 6 days after issue. The go/no-go ("BSS>0 at leads 1-2") would be judged on leads that are operationally worthless or impossible.
**Why it happens:** the harness uses table index time, not wall-clock availability.
**Consequences:** headline skill is real in the harness and unusable by CHAP; users read "1-week-ahead" as 7 days of warning.
**Prevention:**
- Define and store for every forecast: `last_obs_week`, `issue_date` (= week end + latency, config value), `target_week`, `lead_weeks`, and `effective_days_ahead = target_week_start - issue_date`. Report skill against both the harness lead and effective days ahead.
- Decide explicitly, before seeing results, whether the go/no-go leads are "harness lead 1-2" or "effective lead >= 7 days". Recommended: keep the agreed definition but ALSO publish the effective-lead table, and state in the report that harness lead 1 is a nowcast under current latency. Consider shifting the go/no-go to leads 2-3.
- Verify the actual latency of `ECMWF/ERA5_LAND/DAILY_AGGR` empirically (last available date vs wall clock) and keep it in config; check how often the newest data is revised (ERA5-Land preliminary vs final).
**Automated tests:** assert `issue_date < target_week_start` for every row used in a claim labelled "forecast"; unit-test the effective-lead function across year-end and week-53 boundaries; operational dry-run test that builds features from a data snapshot truncated at `issue_date - latency` and reproduces the harness features.
**Detection:** target week start earlier than issue date in the forecast table; operational skill much worse than the harness.

### C3. Climatology, scaling and anomaly baselines computed with held-out years [FS, BH]
**What goes wrong:** Feature anomalies, standardisation, imputation, target encoding, "ward x week-of-year mean" or the baseline climatology forecasts use years outside the training window (e.g., full-file mean). Also the reverse trap: the labels' thresholds are on 1991-2020 (overlapping train AND validation), and the feature anomalies are on 1991-2014. Mixing these silently.
**Project-specific analysis of the label thresholds:** the 1991-2020 threshold is a fixed, published definition of the target, like a rule. It does not leak test years (2021-2026 are outside). It is NOT a model-fitting leak as long as (i) the threshold itself or "HI minus threshold" is never computed from years the model should not know, and (ii) everyone accepts it as part of the label definition. The real effects are different: (a) it makes labels on 1991-2020 "in-sample" by construction (~10% hot days) while 2021-2026 labels are out-of-baseline (strong exceedance, base rate far higher), so validation (2015-2020, inside baseline) is NOT representative of the test regime (see C6); (b) a feature such as `HI - threshold(ward, doy)` carries 2015-2020 information into training rows. Operationally this constant is known, so it is permissible, but document it as a design decision and run an ablation with and without it.
**Prevention:**
- A single `fit_transform` interface: every statistic (climatology, scaler, imputation value, quantile bins) is fit on the training fold only and stored in the model artifact; val/test only call `transform`.
- For expanding-window CV the climatology is refit per fold from that fold's training years.
- Recent (10-year) climatology baseline for target year Y uses years Y-10..Y-1 only (rolling), not a fixed window.
- Record in the manifest which year range every statistic was fit on.
**Automated tests:** perturb all val/test-year feature values (multiply by 2), refit climatology/scaler, assert the stored training statistics are bit-identical; hash the year-range of every fitted object and assert `max(year) <= train_end`.
**Detection:** validation scores unusually higher than CV scores; anomalies in training with mean exactly 0 for all years.

### C4. Purging/embargo failures at split and fold boundaries; overlapping rows across leads [BH, MOD]
**What goes wrong:** Row = (ward, origin t, lead k) with target at t+k. A training row with origin 2014-W50 and k=6 has its target in 2015 (validation). Lagged-feature windows overlap neighbouring rows, and weekly heat is strongly autocorrelated, so adjacent origins are near duplicates. Training rows whose targets fall in the validation window, or CV folds without a gap, leak label information across the boundary. Targets for different leads are different weeks (non-overlapping per lead), but the six per-lead datasets share features and the same origin; hyperparameters picked on one lead's validation do not transfer to the independence assumptions of another.
**Prevention:**
- Split by TARGET week: a row belongs to train only if `target_week_end <= train_end`; origin features may reach back into earlier splits (fine and operationally legitimate: val/test features may use pre-split observed data).
- Embargo of at least `k + max_feature_window` weeks between a training fold end and the next validation start in expanding-window CV; use at least 6 + longest lag weeks.
- Expanding-window CV folds should be whole years or whole seasons, never random rows, never random weeks. Never shuffle.
- Do not stack all six leads into one model unless lead is a feature and rows are grouped for CV.
**Automated tests:** for every fold assert `max(train.target_week) < min(val.target_week) - embargo` and `max(train.origin_week) + k < min(val.origin_week)`; assert no (ward, week) key appears as a label in both sets; assert test rows are never touched during fit via a guard (see C9).
**Detection:** CV score >> validation score; skill that rises when the embargo grows.

### C5. Spatial autocorrelation inflates effective sample size and shrinks CIs wrongly [PROJECT] [BH, FE]
**What goes wrong:** 4,841 wards but only ~24k ward-cell pairs from a 0.1 degree grid, and heat anomalies are synoptic-scale (hundreds of km). The effective independent spatial sample at weekly scale is perhaps tens to a few hundred, not 4,841. Pooled metrics over 9M rows look statistically tight; bootstrapping rows or wards gives absurdly narrow CIs. In addition, the test period is only ~5.7 seasons, so the real inferential unit is the season/year.
**Prevention:**
- Resample whole weeks (all wards together) in blocks. Use moving/stationary block bootstrap with block length covering the autocorrelation (>= 4 weeks), and report a second CI with whole-year blocks as sensitivity. Never resample wards or rows independently.
- Report the effective sample estimate (e.g., number of distinct ERA5-Land cells; leading EOF count) and state that CIs reflect temporal, not spatial, uncertainty.
- Compute the per-ward-score variance of BSS differences; evaluate the model-vs-baseline difference in BSS (paired), not two separate CIs.
- Weight or de-duplicate wards by cell for headline metrics, or report cell-level metrics as a robustness check.
- Wards sharing a cell have nearly identical series: this duplicates rows (harmless across time split but inflates early-stopping stability and SHAP importances). The 6 LGA-average wards (NASAKW04, PLSBSA20, PLSBKK06, PLSTNK08, PLSQAP14, BNSVDY02) must be flagged, not treated as independent ward-level data.
**Automated tests:** bootstrap unit test: on a synthetic panel with perfect spatial correlation, assert the CI width equals the single-site CI width within tolerance; assert the bootstrap function takes `week` as the resampling unit (signature test); regression test that the number of resampling units equals the number of weeks (or blocks), not rows.
**Detection:** CI half-width below ~0.002 BSS on test; every regional slice "significant".

### C6. Nonstationarity makes climatology a strawman, and causes calibration drift in the test period [PROJECT] [BH, CAL, FE]
**What goes wrong:** ~25 hot days/ward/yr in 1991-2000 vs ~56 in 2016-2025; test is 2021-2026 and outside the fixed baseline. Consequences:
1. A 1991-2014 climatology forecast is badly biased on the test years (too low), so ANY model with a trend or recent-state predictor beats it. BSS vs this baseline measures "knows the climate has warmed", not forecasting skill (cf. Hamill and Juras 2006, "Measuring forecast skill: is it real skill or is it the varying climatology?").
2. The 10-year recent climatology is better but still lags the trend and misses ward-specific warming (middle belt warms ~1.7x faster in ERA5-Land than TerraClimate suggests, i.e., regional differences in base-rate trend exist).
3. Base rates differ across eras: validation (2015-2020) sits inside the 1991-2020 baseline, test (2021-2026) outside. Calibration fitted on validation will be systematically under-confident (too-low probabilities) in test. Tree models cannot extrapolate beyond training feature ranges (HI anomalies above training maximum saturate), so they under-predict in test; logistic regression extrapolates linearly but can over-predict.
4. The class balance moves (~4-6% heatwave weeks early, much higher later): thresholds for F1, calibration maps and class weights decay.
**Prevention:**
- Add a "trend + season" baseline (logistic on `year`, sin/cos DOY, ward static/region, fit on training years) and an "adaptive" baseline (trailing 52-week or 5-year hot-day fraction for that ward-DOY). The go/no-go compares against the BEST baseline chosen on validation, not the weakest. Report BSS against all baselines.
- Give the model a way to learn the level: slowly varying features (trailing 26/52-week hot-day fraction, trailing anomaly vs a trailing climatology) rather than only anomaly vs fixed 1991-2014 climatology.
- Final model is refit on train+val (1991-2020) with all hyperparameters frozen BEFORE test; calibrator refit on the most recent OOF window. Document it as part of the protocol.
- Always report reliability diagram AND calibration-in-the-large (mean forecast vs observed rate) by test year, and the Brier decomposition (reliability, resolution, uncertainty). Use a per-fold, per-year reference climatology rather than a pooled single base rate.
- Treat as expected, not a bug: test BSS vs the stale 1991-2014 climatology will be inflated; do not headline it.
**Automated tests:** in the harness, assert that every reported BSS has a named reference, and that the baseline set includes the trend baseline; test that calibration-in-the-large by year is computed and written to the report; synthetic test with a linearly rising base rate verifying that the stationary climatology baseline has worse Brier than the trend baseline.
**Detection:** mean predicted probability under mean observed rate in each test year; skill concentrated in the last years; year (or a proxy) is the top SHAP feature.

### C7. Trivial-skill trap: model learns seasonality + spatial climate + trend only [BH, MOD, FE]
**What goes wrong:** Pooled AUC/BSS over all wards and weeks is dominated by predictable structure: heatwave weeks occur mainly Feb-May, and more in the middle belt, more in later years. A model that knows only DOY, ward, and year gets high pooled AUC and positive BSS against a single pooled base rate, with zero predictive information from the state of the atmosphere/land.
**Prevention:**
- Reference forecast = ward x week-of-year climatology (and the trend baseline of C6), never a pooled base rate.
- Report anomaly-conditional skill: AUC and BSS within season and within region strata; and the incremental skill over "season + trend + ward" model (a LightGBM/logistic with ONLY those features) at every lead.
- Negative controls (automatable, mandatory): (a) year-shuffle control: for each (ward, DOY) replace the lagged weather features with those from a randomly chosen different year, keeping label and static/season features; skill must collapse to the seasonal-baseline level; (b) lead-decay check: skill should decrease with lead; if lead 6 is about equal to lead 1, flag.
- Ablation ladder: season-only, +ward, +trend, +persistence, +lagged HI, +soil moisture/humidity/rain, +drivers (later). Each rung gets a paired CI.
**Detection:** "skill" vanishes under the shuffle test; ablation without any weather feature keeps most of the BSS.

### C8. Persistence and autocorrelated targets inflate apparent skill at short leads [BH, MOD]
**What goes wrong:** Heat weeks cluster (seasonal onset, multi-week spells, soil dryness). Lag-1 persistence of the label or HI anomaly gives strong skill at lead 1-2 that decays quickly. Any model that includes last week's `heatwave_days` will "beat" climatology there; the interesting question is whether it beats persistence and damped persistence. Also, on a rare-event label persistence has a very poor Brier (it forecasts 0/1) yet strong hit rate; comparing persistence only by Brier or only by F1 misleads. Further, an AR-type model (logistic on lag label + season) is the real "easy" benchmark.
**Prevention:**
- Baselines at each lead: climatology, recent climatology, trend, persistence (raw), damped persistence = logistic on last-week label/anomaly + season (this is the critical one), all computed on the same rows.
- Probabilistic persistence must be given a non-0/1 form (e.g., conditional frequency from training data given last-week state) to be scored fairly with Brier.
- Go/no-go is on paired difference vs the BEST of these, with CI excluding 0 (already agreed), computed from the week-block bootstrap.
**Detection:** model SHAP dominated by lag-1 label; model ~ damped persistence.

### C9. Model selection and decisions on the test set (test used more than once) [BH, FE]
**What goes wrong:** Test years viewed for debugging, threshold choice, calibrator choice, feature choice, or "just one more run". With 5.7 test seasons even a few looks overfit the choices. Also using validation for early stopping, hyperparameter search, calibrator fitting AND reporting makes validation scores optimistic.
**Prevention:**
- A test-lock in the harness: `evaluate_test()` refuses to run unless a frozen config hash and model artifacts exist, writes an append-only log entry (timestamp, config hash, code commit), and fails on the second call with a different hash. Test rows excluded from every data loader by default (`split='test'` needs the explicit lock-open call).
- Pre-register (a file committed before the test run): primary metric, primary leads, baselines, reference forecast, CI method, thresholds for go/no-go, and the list of slices considered confirmatory.
- Use nested protocol: expanding-window CV for model/hyperparameter selection; validation for early stopping and calibrator; test only for final report.
**Automated tests:** loader unit test that a test-year slice cannot be returned without the lock-open flag; CI check that grep finds no reference to test years in training/selection modules.
**Detection:** test log with more than one entry; metrics differ from the pre-registered config.

### C10. Reanalysis-label skill presented as real-world skill [PROJECT] [FE, OPS]
**What goes wrong:** Labels are ERA5-Land derived; the model forecasts an ERA5-Land-defined event. Station check (METHODOLOGY section 9): only 24-50% of ERA5-Land heatwave weeks are heatwave weeks at the station (vs ~10% by chance), weekly hot-day-count correlation 0.39-0.68. ERA5-Land warming in the middle belt is high-end (TerraClimate shows ~60% of it), so regional label base rates are partly a data-product artefact. The label is a relative-threshold (ward's own 90th percentile) exceedance, not a health-impact or absolute threshold. A model can look better against ERA5-Land because the same reanalysis model produced features and labels (shared biases, shared smoothness and persistence).
**Prevention:**
- Every figure, table and report headline carries the label "skill against ERA5-Land-defined heatwave weeks (reanalysis labels), 4,841 wards in 19 northern states and the FCT". Include the station agreement numbers as a ceiling on real-world meaning.
- Add the available independent check where possible (Kano, Abuja, Minna, Ilorin station-derived weekly hot-week labels for 2011-2025 as a small, clearly labelled sanity evaluation, not a headline).
- The decisive test of the table's value stays "does it improve CHAP's disease forecasts" (METHODOLOGY section 9): state that this is not evaluated in v2.0.
- Do not compare with ECMWF S2S unless scored against the same labels and on the same issue-time definition.
**Detection:** reviewers asking "does this predict heatwaves" and the answer relying on unqualified wording.

---

## Moderate Pitfalls

### M1. Label construction subtleties [PROJECT] [FS]
**What goes wrong:** (a) The agreed label (`heatwave_days >= 3`) is NOT the rule-based "event" (3 CONSECUTIVE hot days; `heatwave_event_count`). A week with three non-consecutive hot days is labelled positive; an event that starts the previous week and continues is not counted in the continuing week. Naming the target "heatwave" invites misinterpretation. (b) The threshold pools +-5 days over 1991-2020 (about 330 values per DOY) so each baseline-year hot day helped define its own threshold (in-sample); neighbouring DOYs are strongly dependent, so labels in baseline years have smoothly ~10% base rate while later years do not (C6). (c) Feb 29 has its own threshold; (d) the weekly table keeps only complete 7-day ISO weeks.
**Prevention:** name the target `hot_week_ge3` in code and reports; document the difference to events; keep a derived secondary target `event_start_week` only if needed. Test: recompute labels from `heatwave_days` and check against the table; assert baseline-period (1991-2020) hot-day rate is ~10% +/- tolerance and the rate for 2021+ is higher.
**Detection:** label prevalence by year not matching expectations.

### M2. ISO week-53 and calendar handling [PROJECT] [FS]
**What goes wrong:** ISO years with 53 weeks in range: 1992, 1998, 2004, 2009, 2015, 2020, 2026 (verify with `date.isocalendar()` in a test; 2026-W38 is last row). Problems: lag/lead by subtracting week numbers (W01 - 1 = W00 or W52 vs W53); `week_of_year` feature with value 53 appearing in only 7 years and treated as unseen category by trees; sin/cos with period 52 vs 53; "same week last year" joins; sorting strings like `2020-W9` vs `2020-W10` (table uses zero-padded so safe, but any int conversion is not); the first row is 1991-W02 so 52-week lags are NaN for the first year; calendar-year vs ISO-year grouping in train/val/test cutoffs (2014-W53 doesn't exist, 2015-W01 starts 2014-12-29, 2020-W53 ends 2021-01-03 and falls in the "val" year by ISO year but days belong to 2021).
**Prevention:** one canonical key `week_start` (Monday date) and `week_mid` date; all arithmetic with date offsets of 7 days; seasonal features from day-of-year of `week_mid` (sin/cos with period 365.25); define splits by `week_start` date with explicit cutoffs (e.g., test starts at the Monday of 2021-W01, train ends at the week ending 2014-12-28), documented, and assert the 2020-W53 handling; labels and thresholds are keyed by DOY (1-366) so week-of-year is only used for display.
**Automated tests:** property test over all weeks 1991-2026 that `week_start + 7` equals the next key; round-trip ISO string to date to ISO string; assert weeks in each split are contiguous with no gap/overlap; assert no feature has `week_of_year == 53` as a raw category.

### M3. Class imbalance and misuse of accuracy/F1 [BH, MOD, CAL, FE]
**What goes wrong:** Accuracy is >90% by predicting never; F1 depends on threshold and base rate and the base rate shifts over time; PR-AUC, F1, precision/recall can look different if the validation-chosen threshold is used on test with a different prevalence. Re-balancing (class weights, SMOTE, undersampling) distorts probabilities and breaks BSS/reliability unless recalibrated (and recalibration then needs data that wasn't resampled). Pooled ROC AUC mixes between-season/between-region discrimination with real skill (C7).
**Prevention:** headline = BSS (proper score) vs best baseline; also log-loss (clipped), CRPS-like threshold-weighted if needed. No accuracy. F1/P/R only at declared thresholds (e.g., probability thresholds set on validation, and a second operating point at fixed alert rate); always show prevalence next to PR-AUC; AUC reported stratified by season/region and as anomaly AUC. Avoid class weights for the probabilistic model; if used for LightGBM stability, recalibrate on unweighted OOF data and check reliability.
**Automated tests:** assert the report generator contains no "accuracy" metric; metric function tests against hand-computed Brier, BSS with known synthetic cases; test that BSS of the reference forecast against itself is exactly 0.

### M4. Calibration fitted on the wrong split [CAL]
**What goes wrong:** Isotonic fitted on the training predictions (overfit, nearly perfect-looking) or on the same validation rows used for early stopping and hyperparameters; fitted on 9M autocorrelated rows so the step function overfits a few effective events (isotonic is known to overfit with little effective data, Niculescu-Mizil and Caruana 2005); produces exact 0 or 1 outputs (infinite log-loss) and flat regions that destroy resolution; fitted pooled across leads or regions with different reliabilities; mismatched era (see C6). Calibrating the quantile models separately (conformal/coverage) is often forgotten: quantile intervals under-cover in the warming test period.
**Prevention:** calibrator fit on out-of-fold predictions from the expanding-window CV (last folds weighted/most recent), one per lead; compare Platt/logistic recalibration (2 parameters, robust under shift) with isotonic via paired CV Brier, pick the simpler unless isotonic clearly wins; enforce minimum leaf size/monotone clip to [eps, 1-eps]; evaluate calibration only on rows the calibrator never saw; final production calibrator refit on the most recent window. For quantiles use conformalised quantile regression or empirical coverage correction fit on recent OOF, and sort quantiles to prevent crossing.
**Automated tests:** assert calibrator input row ids are disjoint from the rows used for model fitting and early stopping; assert predictions in [eps, 1-eps]; assert no quantile crossing; assert reliability slope/intercept computed on held-out rows.

### M5. Multiple comparisons across slices [FE]
**What goes wrong:** 6 leads x 3+ targets x models x seasons x regions x metrics gives hundreds of comparisons; some will "win". Slicing after seeing the test results is a forking path.
**Prevention:** one pre-registered confirmatory test (BSS vs best baseline at leads 1-2, pooled, week-block CI). Everything else labelled exploratory; for any slice table use CIs from the same block bootstrap with Holm or Benjamini-Hochberg adjustment over the table; do not claim a regional or seasonal win that is not paired-CI-clear. Do not tune on test slices.
**Automated tests:** report builder requires a `confirmatory: bool` flag per table and refuses to print p-values or "significant" in exploratory tables.

### M6. SHAP misinterpretation with correlated features [MOD, FE]
**What goes wrong:** Lag-1..lag-8 HI, rolling means, humidity, soil moisture and rainfall are highly correlated, so TreeSHAP splits credit arbitrarily and rankings change across seeds/folds; importance for lags may be understated individually. SHAP values are in log-odds for LightGBM binary (not probability) unless explained. SHAP describes the model, not causal drivers, and with ward static features (lat/lon) or `year` it mostly explains trend/geography. Ward duplicates inflate effective sample. Computing on 9M rows is slow so subsample can be biased towards seasons.
**Prevention:** group features by family (persistence, recent HI, humidity/rain, soil moisture, season, geography, trend) and report group-level SHAP and grouped permutation importance plus the ablation ladder as the primary evidence; check ranking stability across seeds and CV folds; stratified subsample by season/region/year; use the test period only after lock for reporting; avoid causal language ("drives") in the report; interventional vs path-dependent TreeSHAP stated.
**Detection:** top feature flips between folds; `year`/lat/lon dominate.

### M7. Tree models cannot extrapolate; features drifting outside the training range [MOD]
See C6(3). Prevention: ranks/trailing-climatology anomalies instead of absolute HI; monotone constraints where physically justified; logistic baseline kept in the final comparison; check feature range coverage (fraction of test rows outside train min/max) in the harness.

### M8. Hyperparameter search and early stopping on autocorrelated, duplicated data [MOD]
Row-wise early stopping and random CV give inflated stability. Use time-ordered folds, early stopping on the last CV fold's validation, strong regularisation (min_data_in_leaf in the thousands given 4,841 near-duplicate wards), subsample by week (bagging at the week level) and fixed seeds with seed-repeat variance. Stop searching when improvements are below the block-bootstrap noise.

### M9. Quantile LightGBM (HI anomaly) specific errors [MOD, CAL]
Anomaly defined with a climatology that includes test years; crossing quantiles; coverage measured pooled hides regional/seasonal miscoverage; pinball loss vs interval coverage drift in the warming test period. Anomaly vs training-only (or trailing) climatology and report the mean anomaly shift per test year; sort/rearrange quantiles; report coverage by year and region with week-block CIs; hot nights target uses the same rate-shift caveat as heatwave weeks.

### M10. Train/serve mismatch for CHAP [OPS]
CHAP's disease models are trained on OBSERVED (reanalysis) covariates, but at deployment they'll receive FORECAST covariates with different error structure, calibration and smoothness. Deliver forecasts with probabilities and uncertainty, flag the type (`observed` vs `forecast`, lead), keep the observed table unchanged, and document that CHAP should train on hindcast forecasts or use probabilities explicitly.

---

## Minor Pitfalls

### m1. Frozen dataset vs live table
Training must read only `covariates-v1.0` (manifest hash check at load); `outputs/covariate_table.csv` is overwritten each run. Test: loader verifies MANIFEST checksum and refuses otherwise. Operationally, near-real-time ERA5-Land data used for features can differ from the final reprocessed data the frozen table contains; build a consistency check (overlap period) before shipping operational forecasts.

### m2. Static baseline period vs operational labels
Thresholds are fixed on 1991-2020; an operational forecast must score against the same thresholds. If the baseline is ever updated, versions of model, thresholds and labels must change together (version stamp in every forecast row).

### m3. Wards with LGA-average values and shared cells
Flag six LGA-average wards; avoid ward-level claims for them; exclude or flag in slices.

### m4. Partial final season in test
Test ends 2026-W38 (September), so it contains only ~one full hot season for 2026 (Feb-May included) but not post-season weeks; yearly and seasonal slices have unequal sizes. Report counts of positives per slice and suppress slices with < N events.

### m5. Compute/memory
9M rows x 6 leads x many lags; use float32, per-lead datasets, parquet, week-level sampling for SHAP and CV; fix seeds and record library versions (scikit-learn, LightGBM) for reproducibility.

### m6. Climate-driver phase (later) leakage
ENSO (ONI/Nino3.4), tropical Atlantic SST and MJO indices are published with delays and revised; ONI is a 3-month centred mean (uses future months), RMM index may be revised. Use the value available at issue date, lag by publication delay, and avoid centred means. Judge added skill only through paired ablation vs the same model without drivers and identical seeds; expect small effects at this latitude.

### m7. Reporting precision
Report BSS to 3 decimals with CI; do not round away small positive values; present Brier decomposition; give event counts in each panel.

---

## Phase-Specific Warnings

| Phase topic | Likely pitfall | Mitigation |
|-------------|---------------|------------|
| FS: feature store | C1 target-week leakage, M2 week-53 handling, C3 climatology fit, M1 label naming | Truncation-invariance + poison tests, date-keyed panel, fit-on-train statistics, label recomputation test |
| FS: issue-time design | C2 latency makes lead 1 a nowcast | Store issue_date and effective lead; empirical latency check; decide go/no-go lead definition before results |
| BH: baselines + harness | C6 strawman climatology, C8 persistence, C7 trivial skill, C4 purging | Trend, damped persistence, season-only baselines; ward x week reference; purged splits; negative-control (year-shuffle) test |
| BH: bootstrap/CI | C5 spatial autocorrelation | Week-block (and year-block) paired bootstrap; unit-tested resampling unit |
| BH: test guard | C9 test reuse | Test lock, pre-registration file, append-only evaluation log |
| MOD: LR + LightGBM + quantile | M7 extrapolation, M8 early stopping on duplicates, C7 ablation ladder, M9 quantile issues | Trailing-climatology anomalies, week-level bagging, strong regularisation, paired ablations |
| CAL: calibration | M4 wrong split / isotonic overfit, C6 drift, M3 reweighting | OOF-fit per-lead calibrators, Platt vs isotonic compared, recent-window refit, calibration-in-the-large by year |
| FE: final evaluation | C9 test once, M5 multiple comparisons, M6 SHAP, C10 reanalysis caveat, C6 baseline choice | Pre-registered primary test, exploratory flag, grouped SHAP, labelled-as-reanalysis wording, best-baseline comparison |
| FE: go/no-go | C2 + C8: leads 1-2 judged against weak baselines or nowcasts | Paired CI vs best baseline; also publish effective-lead table; define "no-go" fallback (ECMWF S2S benchmark, per scope) |
| OPS: weekly table to CHAP | M10 train/serve mismatch, m1/m2 versioning, C2 latency | Versioned forecast rows (model, thresholds, issue_date, lead), observed-vs-forecast flag, dry-run reproduction test |
| Later: climate drivers | m6 index revision/centred means | Issue-date-available values only; paired ablation |

## Automated Test Catalogue (for the harness)

| # | Test | Guards against | Phase |
|---|------|----------------|-------|
| T1 | Truncation invariance of features | C1 | FS |
| T2 | Poison-the-future test | C1 | FS |
| T3 | Feature schema whitelist, no target-concurrent columns, offset <= 0 | C1 | FS |
| T4 | Single-feature AUC/BSS screen (>0.9 AUC at lead >= 2 flags) | C1 | FS |
| T5 | Date-based key property tests across 1991-2026 incl. W53 years | M2 | FS |
| T6 | Label recomputation from `heatwave_days` and prevalence-by-year check (~10% in baseline, higher after) | M1, C6 | FS |
| T7 | Fitted-statistics provenance: max year used <= train_end | C3 | FS/BH |
| T8 | Split/embargo assertions for all folds and leads | C4 | BH |
| T9 | Bootstrap resampling unit is week/blocks (synthetic perfect-correlation test) | C5 | BH |
| T10 | BSS(reference, reference) == 0; hand-computed Brier cases; baselines include trend and damped persistence | C6, C8, M3 | BH |
| T11 | Year-shuffle negative control: skill collapses to seasonal baseline | C7 | BH/MOD |
| T12 | Skill-vs-lead monotone decay check (warning) | C7, C1 | MOD |
| T13 | Test lock: loaders refuse test rows; one evaluation per config hash | C9 | BH/FE |
| T14 | Calibrator rows disjoint from fit/early-stopping rows; outputs within [eps, 1-eps]; no quantile crossing | M4, M9 | CAL |
| T15 | Calibration-in-the-large by year written to the report | C6 | CAL/FE |
| T16 | Report builder: no accuracy metric, confirmatory flag, mandatory "reanalysis labels" caption | M3, M5, C10 | FE |
| T17 | Frozen manifest checksum on load | m1 | all |
| T18 | Operational dry-run reproduces harness features from a latency-truncated snapshot | C2, OPS | OPS |

## Gaps / Items Needing Phase-Specific Verification

- Actual current ERA5-Land DAILY_AGGR latency and revision behaviour in Earth Engine (stated as ~8 days; verify empirically). It decides how the lead definition is presented (C2).
- True effective spatial sample size (count distinct cells, EOF/correlation length of weekly anomalies) to calibrate the expected CI widths (C5).
- Heatwave-week prevalence by year, region and era in the frozen table (not computed here); needed to quantify the C6 base-rate shift and to size baselines.
- Whether the literature supports any 3-6 week skill for temperature extremes in West Africa from persistence + land state only; expect skill to be marginal beyond lead 2, so the "no-go with ECMWF S2S fallback" branch should be planned, not treated as an exception.

## Sources

- Project documents (HIGH confidence for project facts): `.planning/PROJECT.md`; `docs/METHODOLOGY.md` sections 4-6, 8, 9.
- Hamill, T. M. and Juras, J. (2006). Measuring forecast skill: is it real skill or is it the varying climatology? Q. J. R. Meteorol. Soc. 132, 2905-2923. (MEDIUM, from training knowledge, not re-fetched)
- Niculescu-Mizil, A. and Caruana, R. (2005). Predicting good probabilities with supervised learning. ICML. (MEDIUM)
- Roberts, D. R. et al. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. Ecography 40, 913-929. (MEDIUM)
- Kapoor, S. and Narayanan, A. (2023). Leakage and the reproducibility crisis in machine-learning-based science. Patterns 4(9). (MEDIUM)
- Wilks, D. S. Statistical Methods in the Atmospheric Sciences (chapters on forecast verification, effective sample size and block bootstrap). (MEDIUM)
- Brier decomposition and reliability diagrams: Murphy (1973); Brocker and Smith (2007) on consistency bars for reliability diagrams. (MEDIUM)
- Davis, J. and Goadrich, M. (2006). The relationship between precision-recall and ROC curves. ICML. (MEDIUM)
- Lundberg, S. M. and Lee, S.-I. (2017). A unified approach to interpreting model predictions (SHAP) and subsequent literature on correlated-feature attribution. (MEDIUM)
- Ploton, P. et al. (2020). Spatial validation reveals poor predictive performance of large-scale ecological mapping models. Nat. Commun. 11, 4540. (MEDIUM; spatial-autocorrelation inflation analogue)
