# Phase 10: Baselines, Evaluation Harness and Test Lock - Context

**Gathered:** 2026-10-08
**Status:** Ready for research and planning
**Source:** These decisions were agreed with the user during v2.0 setup (PROJECT.md Key Decisions; research/SUMMARY.md adjustments 1, 7, 9 and 12 adopted 2026-10-02; the approved ROADMAP phase overview; the 2026-10-06 framing). Choices marked *(orchestrator)* were made within those decisions. The user said "proceed to the next" after PR #12 merged (2026-10-08).

<domain>
## Phase Boundary

Before any model is trained, the analyst can see exactly what a model must beat. Everything is scored through one honest path, and the 2021-2026 test years are mechanically locked. This phase delivers:
- five baselines;
- one scoring harness over stored predictions;
- bootstrap confidence intervals;
- results broken down by slice;
- the test lock with pre-registration;
- baseline scores on the validation years (2015-2020).

Requirements: EVAL-01 to EVAL-05. EVAL-06 (negative controls) needs a trained model and is in Phase 11. No trained ML model is built here.
</domain>

<decisions>
## Implementation Decisions

### Inputs (from Phase 9, merged in PR #12)
- Use `heatwave.forecast.dataset.lead_rows` / `lead_row_index`, splits, targets, the climatology and the static table exactly as built.
- Training rows exclude the warm-up and embargo rows.
- Validation is 2015-2020 by target week. Test rows (2021-2026) must not be scored in this phase.
- The labels and framing are `heatwave_week` = `heatwave_days >= 3`, latency 0, leads 1-6, and gate leads [1, 2].

### Baselines (EVAL-01)
All five are fitted on **training rows only** (targets before 2014-12-29, minus the embargo) and emit a probability per (ward, origin, lead):

1. **`climatology`:** the per-ward rate of `heatwave_week` for the target week's ISO week-of-year, over training years. It is pooled over ±2 weeks of the year (W53 pooled with W52 and W01), the same pooling as the Phase 9 climatology.
2. **`recent_climatology`:** the same as (1), but over the **10 years before the issue week** (trailing, as-of). It is pooled over ±2 weeks of the year. It shrinks toward the state-level pooled rate when the ward has few positives *(orchestrator: hierarchical ward→state shrinkage with a fixed pseudo-count; the planner chooses the count, and research may refine it)*. It uses past data only, so it is valid on validation and test rows without refitting.
3. **`persistence`:** probabilistic persistence, not a 0/1 copy. It is P(y at t+k = 1 | y at t = 0 or 1), estimated on training rows per lead. It is stratified by season (DJF/MAM/JJA/SON of the target week) and geozone *(orchestrator)*, so the Brier comparison is fair.
4. **`damped_persistence`:** a logistic regression per lead on the lag-0 Heat Index anomaly, lag-0 `heatwave_week`, and season (sin/cos of the target week), fitted on training rows.
5. **`trend_season`:** a logistic regression per lead on year (as a continuous value), season sin/cos and geozone, fitted on training rows.
   - A year term is allowed here, unlike in model features, because this baseline exists to represent the warming trend. A logistic regression extrapolates linearly, which is the intended behaviour.
   - Document that the trend is extrapolated into 2015-2020.

- **Best baseline per lead:** the baseline with the lowest Brier score on validation. It is recorded, and the Phase 14 gate uses it.
- **Sanity checks:**
  - BSS of a reference against itself is 0.
  - Persistence skill decays with lead.
  - Every baseline gives probabilities in [0, 1], with no NaN on scored rows.

### Stored predictions and harness (EVAL-02)
- **One prediction format for every predictor**, baselines now and models later. It is a Parquet file with columns:
  - `predictor`, `lead`, `ward`, `origin_week_index`, `target_week_index`, `target_week`, `split`, `p`, `y`, `fold` (nullable);
  - plus `run_id`, the config hash and the data sha in the file metadata.
- Predictions are written to the run folder (Phase 8 artifacts), outside the repo.
- **The harness scores stored predictions only.** It never calls a model, so every predictor is scored identically.
- **Metrics:**
  - Brier score;
  - **Brier skill score against a named reference** (the reference predictor's stored predictions on the same rows);
  - the Brier decomposition (reliability, resolution, uncertainty; Murphy) with quantile bins;
  - ROC AUC, reported only **stratified** by season and by region, never pooled alone;
  - a reliability diagram with **quantile bins** (default 10);
  - precision/recall/F1 at a **stated threshold**. The default threshold is the training-set base rate for that lead *(orchestrator)*, and the threshold is always written next to the numbers;
  - **calibration-in-the-large by year** (mean p minus mean y per target year);
  - **no accuracy metric anywhere**.

### Confidence intervals (EVAL-03)
- A **paired week-block bootstrap.** It resamples contiguous blocks of target weeks (default block length 4 weeks, at least 4), keeping all wards of a sampled week together. Paired means the reference and the candidate are scored on the same resampled rows.
- A **year-block bootstrap** as the second CI: whole target years resampled.
- It never resamples individual rows or wards.
- Defaults are B = 1000 with a fixed seed from `forecast.yaml` and a 95% CI. *(orchestrator: B is configurable; tests use a small B.)*
- The output is a CI for each metric and for the BSS **difference** (candidate minus reference).

### Slices (EVAL-04)
- **Lead:** 1-6.
- **Season of the target week:** DJF, MAM, JJA, SON. **MAM (March-May) is highlighted** in reports.
- **Region:** geozone (NWZ, NCZ, NEZ), plus latitude bands (far north > 11.5°N, middle belt < 9.5°N, central otherwise), as in DATA_REPORT.
- **Target year.**
- **Flags:**
  - the 6 LGA-average wards (`lga_average_ward`);
  - **small wards**: a ward whose area is smaller than one ERA5-Land grid cell (0.1° × 0.1° at its latitude), so its value effectively comes from one cell *(orchestrator: computed from the frozen ward geometries)*.
  - Flagged wards can be excluded or reported separately in each slice.

### Test lock and pre-registration (EVAL-05)
- Loaders (`lead_rows` and any prediction or evaluation loader) **refuse test-split rows** unless both of these hold:
  - (a) a pre-registration file `docs/forecast/PREREGISTRATION.md` exists **and is committed in git**, with an unchanged working-tree copy;
  - (b) a lock file `TEST_LOCK.json` under `<local_data_dir>/forecast_runs/` has been **explicitly opened** by a dedicated function or CLI that records the pre-registration's git blob sha, the config hash and the model-bundle hash.
- **The evaluation log** is append-only JSONL under `<local_data_dir>/forecast_runs/evaluation_log.jsonl`, outside the repo. Every scoring run records predictor, split, rows, run_id and timestamp, and every attempt to touch test rows is logged. After this phase the log must show **no test run**.
- **Phase 10 creates the mechanism and a pre-registration *template*,** but does not open the lock. The real pre-registration is written and committed in Phase 14.
- Tests use a tmp git repo and tmp data root to exercise lock-closed, lock-open and tampered-pre-registration cases.
- **Decision (review WR-08, 2026-10-09): descriptive prevalence of the test years is published by design.** The Phase 9 data report (`docs/forecast/DATA_REPORT.md`, `report.prevalence_tables`) shows label prevalence per year and per era including 2021-2026. That is a description of the labels, not model scoring, and it uses no prediction. The test lock governs model scoring and the loaders that return test rows or labels for modelling (`lead_rows`, `build_issue_table`, `load_predictions`, `build_frame`); it does not blank the data report. The report states this in its Caveats (`report.PREVALENCE_DECISION`). Revisit in Phase 14 if the pre-registration wants the test-period prevalence withheld until the lock is opened.

### Validation results
- A script `scripts/forecast_baselines.py`:
  - fits all five baselines on train;
  - writes stored predictions for validation (and train, for diagnostics) to a run folder;
  - scores them through the harness with CIs and slices;
  - writes a committed summary `docs/forecast/BASELINES_VALIDATION.md`.
- The summary contains:
  - per-lead Brier and BSS against climatology and against recent climatology, with week-block and year-block CIs;
  - the best baseline per lead;
  - the MAM-highlighted season table;
  - the region table;
  - calibration by year;
  - the caption "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT; validation 2015-2020";
  - a note that test years are locked and unscored.

### Claude's Discretion
- Module names. Suggested: `heatwave/forecast/baselines.py`, `evaluation/metrics.py`, `evaluation/bootstrap.py`, `evaluation/slices.py`, `evaluation/predictions.py`, `testlock.py` and `scripts/forecast_baselines.py`.
- The `Predictor` protocol shape, the shrinkage pseudo-count, the bootstrap implementation details, and the number of reliability bins.
</decisions>

<canonical_refs>
## Canonical References
- `.planning/research/PITFALLS.md`:
  - C5 (spatial autocorrelation and CIs)
  - C6 (stale climatology and trend strawman)
  - C7 (trivial skill)
  - C8 (persistence)
  - C9 (test reuse)
  - M3 (metrics and multiple comparisons)
  - M5 (pre-registration)
- `.planning/research/ARCHITECTURE.md`: Predictor interface, harness, test lock, artifacts
- `.planning/research/SUMMARY.md`: adjustments 1, 7, 9 and 12
- Phase 9 code and summaries: `.planning/phases/09-features-targets-splits-and-leakage-suite/09-0*-SUMMARY.md`, `09-REVIEW-FIX.md`
- `docs/forecast/DATA_REPORT.md`: prevalence (train 8.4%, validate 15.4%, test 21.5%), regions, eras
- `forecast.yaml`: baselines section, gate, seed
</canonical_refs>

<specifics>
## Specific Ideas
- **Prevalence shift:** prevalence rises from 8.4% (train) to 15.4% (validate). Expect the static `climatology` baseline to be badly calibrated on validation, so `recent_climatology` or `trend_season` will probably be the best baseline. That is the honest bar.
- **Row counts:** lead 1 has about 1.52M validation rows. Keep stored predictions compact (float32 `p`, int8 `y`, categorical strings).
- **Test speed:** keep the quick test loop under ~60 s (`-m "not frozen and not slow"`). Mark real-data and large-bootstrap tests `frozen` or `slow`.
</specifics>

<deferred>
## Deferred Ideas
- Negative controls (EVAL-06): Phase 11.
- The real pre-registration content and opening the lock: Phase 14.
- Single-feature AUC leakage screen (deferred from Phase 9): include it here only if trivial on top of the harness; otherwise Phase 11.
</deferred>

---
*Phase: 10-baselines-evaluation-harness-and-test-lock*

## Resolved after phase research (2026-10-08)
- **Baseline results measured by research.** On validation (Brier), the best baseline is `damped_persistence` at leads 1-2 and `trend_season` at leads 3-6. Static `climatology` predicts a mean of 0.089 against 0.154 observed, which is worse than a constant base rate. These are expectations only; the harness produces the official numbers.
- **`recent_climatology`:**
  - It reads the 10-year base rate at the **target** column (origin + lead), not the origin-week feature.
  - It shrinks toward the state rate with a fixed pseudo-count **m = 50**, which goes into `forecast.yaml` `baselines.shrinkage_pseudo_count`.
  - Early-year NaN rows are dropped from stored train predictions.
- **`damped_persistence` inputs:** `xhi_anom_lag0` (lag-0 max Heat Index anomaly), lag-0 `heatwave_week`, and season sin/cos.
- **`trend_season`:** an exact binomial logistic fit on (week × geozone) counts with sample weights.
- **Persistence sanity:** skill at lead 1 must beat lead 6. Strict monotonicity is not required: research found lead 4 slightly worse than lead 5.
- **BSS reporting:** report both the BSS against the named reference and the Brier difference (reference − candidate). Both come from the same paired bootstrap replicates, with week-block and year-block CIs. The year-block CI rests on only 6 clusters and is labelled a coarse check.
- **Bootstrap:**
  - Precompute per-target-week sufficient statistics, so one replicate is a weighted sum over weeks.
  - Use a circular week-block multiplicity matrix per lead, seeded with `SeedSequence([seed, lead])`.
  - Defaults are B = 1000, block 4 weeks, 95% CI from `gate.ci_level`.
  - Compute the AUC CI from a histogram (1000 bins).
- **Murphy decomposition:** keep duplicate quantile edges, using `searchsorted(edges[1:-1], p)` as sklearn does, and never `np.unique` the edges.
- **Small wards:** a ward is small when its geometry area is under 0.01 deg² (one 0.1° cell). That's 3,086 of 4,835 non-empty wards (64%). Headline numbers use **all wards**, and every slice table adds a "large wards only" row. The 6 LGA-average wards are flagged separately.
- **Test lock:**
  - The template is `docs/forecast/PREREGISTRATION.template.md`. The real file `PREREGISTRATION.md` is created only in Phase 14.
  - "Committed and unmodified" means `git ls-files --error-unmatch` plus `git hash-object` equal to `git rev-parse HEAD:<path>`, which is CRLF-safe.
  - `TEST_LOCK.json` records the `HEAD:` blob sha, the config hash and the bundle hash. These are recomputed on every access, so tampering re-closes the lock.
  - The pre-registration must contain the current config hash and no placeholder token.
  - There is no `allow_test` bypass parameter.
- **Guard placement:**
  - `lead_rows(split="test", fold=None)` and the stored-prediction loader for test rows raise while the lock is closed.
  - `build_issue_table` **blanks** its test-split label columns (NaN, `has_label` False) while the lock is closed, so operational and report paths keep working.
  - Descriptive prevalence in `report.py` (`heatwave_week_matrix`) is unaffected: it was already published in DATA_REPORT and is not model scoring.
  - Existing Phase 9 tests that request test rows use an explicit test fixture that opens a tmp lock.
- **Evaluation log hygiene:** an autouse fixture in `tests/forecast/conftest.py` points every test's data root at tmp, so no test writes to the real `evaluation_log.jsonl`. After this phase, the real log must show no test-split entries.
- **Config:**
  - Add `baselines.shrinkage_pseudo_count: 50`.
  - Add a new `evaluation:` section: `bootstrap_b` 1000, `block_weeks` 4 (validated ≥ 4), `reliability_bins` 10, `auc_hist_bins` 1000.
  - Update config tests and rejection cases.
  - Reuse `gate.ci_level` and `seed`.
  - Baselines do not use `models.logistic_regression`.
- **Stored train predictions:** diagnostics for leads 1 and 6 only by default. Train rows for all leads total 156M rows.
- **Test fixtures:** use `synthetic_panel(last_week="2027-W10")` so all splits exist. Tests that spawn git are marked `@slow`; the quick loop uses a stubbed git callable.
