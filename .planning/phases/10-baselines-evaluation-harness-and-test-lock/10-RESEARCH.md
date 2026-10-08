# Phase 10: Baselines, Evaluation Harness and Test Lock - Research

**Researched:** 2026-10-08
**Domain:** probabilistic forecast verification (Brier / Murphy decomposition / block bootstrap) on a ward x week panel, plus a git-backed test-set lock
**Confidence:** HIGH (all numbers below were measured on the real frozen data with the repo's own Phase 9 code; library behaviour was checked in the installed environment)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Inputs (from Phase 9, merged in PR #12)**
- Use `heatwave.forecast.dataset.lead_rows` / `lead_row_index`, splits, targets, the climatology and the static table exactly as built.
- Training rows exclude the warm-up and embargo rows.
- Validation is 2015-2020 by target week. Test rows (2021-2026) must not be scored in this phase.
- The labels and framing are `heatwave_week` = `heatwave_days >= 3`, latency 0, leads 1-6, and gate leads [1, 2].

**Baselines (EVAL-01).** All five are fitted on **training rows only** (targets before 2014-12-29, minus the embargo) and emit a probability per (ward, origin, lead):
1. `climatology`: the per-ward rate of `heatwave_week` for the target week's ISO week-of-year, over training years. Pooled over +-2 weeks of the year (W53 pooled with W52 and W01), the same pooling as the Phase 9 climatology.
2. `recent_climatology`: the same as (1), but over the **10 years before the issue week** (trailing, as-of). Pooled over +-2 weeks. It shrinks toward the state-level pooled rate when the ward has few positives *(orchestrator: hierarchical ward->state shrinkage with a fixed pseudo-count; the planner chooses the count, and research may refine it)*. Uses past data only, so it is valid on validation and test rows without refitting.
3. `persistence`: probabilistic persistence, not a 0/1 copy. P(y at t+k = 1 | y at t = 0 or 1), estimated on training rows per lead. Stratified by season (DJF/MAM/JJA/SON of the target week) and geozone *(orchestrator)*.
4. `damped_persistence`: a logistic regression per lead on the lag-0 Heat Index anomaly, lag-0 `heatwave_week`, and season (sin/cos of the target week), fitted on training rows.
5. `trend_season`: a logistic regression per lead on year (continuous), season sin/cos and geozone, fitted on training rows. A year term is allowed here (this baseline exists to represent the warming trend); logistic extrapolates linearly, which is intended. Document that the trend is extrapolated into 2015-2020.
- **Best baseline per lead:** lowest Brier on validation. Recorded; the Phase 14 gate uses it.
- **Sanity checks:** BSS of a reference against itself is 0; persistence skill decays with lead; every baseline gives probabilities in [0, 1], no NaN on scored rows.

**Stored predictions and harness (EVAL-02)**
- One prediction format for every predictor. Parquet columns: `predictor`, `lead`, `ward`, `origin_week_index`, `target_week_index`, `target_week`, `split`, `p`, `y`, `fold` (nullable); plus `run_id`, the config hash and the data sha in the file metadata.
- Predictions are written to the run folder (Phase 8 artifacts), outside the repo.
- The harness scores stored predictions only. It never calls a model.
- Metrics: Brier; Brier skill score against a named reference (the reference predictor's stored predictions on the same rows); Brier decomposition (reliability, resolution, uncertainty; Murphy) with quantile bins; ROC AUC only **stratified** by season and by region, never pooled alone; reliability diagram with **quantile bins** (default 10); precision/recall/F1 at a **stated threshold** (default = training-set base rate for that lead *(orchestrator)*, threshold always written next to the numbers); calibration-in-the-large by year (mean p minus mean y per target year); **no accuracy metric anywhere**.

**Confidence intervals (EVAL-03)**
- Paired week-block bootstrap: resample contiguous blocks of target weeks (default block length 4 weeks, at least 4), all wards of a sampled week together; reference and candidate scored on the same resampled rows.
- Year-block bootstrap as the second CI: whole target years resampled.
- Never resample individual rows or wards.
- Defaults B = 1000, fixed seed from `forecast.yaml`, 95% CI. *(orchestrator: B configurable; tests use a small B.)*
- Output: a CI for each metric and for the BSS **difference** (candidate minus reference).

**Slices (EVAL-04)**
- Lead 1-6; season of the target week DJF/MAM/JJA/SON with **MAM highlighted**; region = geozone (NWZ, NCZ, NEZ) plus latitude bands (far north > 11.5 N, middle belt < 9.5 N, central otherwise); target year.
- Flags: the 6 LGA-average wards (`lga_average_ward`); **small wards** = ward area smaller than one ERA5-Land cell (0.1 x 0.1 deg at its latitude) *(orchestrator: computed from the frozen ward geometries)*. Flagged wards can be excluded or reported separately in each slice.

**Test lock and pre-registration (EVAL-05)**
- Loaders (`lead_rows` and any prediction or evaluation loader) **refuse test-split rows** unless (a) `docs/forecast/PREREGISTRATION.md` exists **and is committed in git** with an unchanged working-tree copy, and (b) a lock file `TEST_LOCK.json` under `<local_data_dir>/forecast_runs/` has been **explicitly opened** by a dedicated function or CLI that records the pre-registration's git blob sha, the config hash and the model-bundle hash.
- The evaluation log is append-only JSONL under `<local_data_dir>/forecast_runs/evaluation_log.jsonl`, outside the repo. Every scoring run records predictor, split, rows, run_id and timestamp; every attempt to touch test rows is logged. After this phase the log must show **no test run**.
- Phase 10 creates the mechanism and a pre-registration *template*, but does not open the lock. The real pre-registration is written and committed in Phase 14.
- Tests use a tmp git repo and tmp data root to exercise lock-closed, lock-open and tampered-pre-registration cases.

**Validation results**
- `scripts/forecast_baselines.py` fits all five baselines on train; writes stored predictions for validation (and train, for diagnostics) to a run folder; scores them through the harness with CIs and slices; writes a committed summary `docs/forecast/BASELINES_VALIDATION.md` containing: per-lead Brier and BSS against climatology and against recent climatology with week-block and year-block CIs; best baseline per lead; MAM-highlighted season table; region table; calibration by year; the caption "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT; validation 2015-2020"; a note that test years are locked and unscored.

### Claude's Discretion
- Module names. Suggested: `heatwave/forecast/baselines.py`, `evaluation/metrics.py`, `evaluation/bootstrap.py`, `evaluation/slices.py`, `evaluation/predictions.py`, `testlock.py`, `scripts/forecast_baselines.py`.
- The `Predictor` protocol shape, the shrinkage pseudo-count, the bootstrap implementation details, and the number of reliability bins.

### Deferred Ideas (OUT OF SCOPE)
- Negative controls (EVAL-06): Phase 11.
- The real pre-registration content and opening the lock: Phase 14.
- Single-feature AUC leakage screen: include only if trivial on top of the harness; otherwise Phase 11.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Five baselines per lead through the same harness as models | Dense-array implementations measured (sec. "Baselines: measured behaviour"); validation Brier per baseline and lead; best-baseline per lead is `damped_persistence` at leads 1-2 and `trend_season` at 3-6 on real data |
| EVAL-02 | Harness scores stored predictions identically for every predictor (Brier, BSS vs reference, Murphy decomposition, stratified AUC, quantile reliability, P/R/F1 at stated threshold, calibration-in-the-large by year, no accuracy) | Parquet format sized/timed; Murphy quantile-bin pitfalls verified numerically; sklearn API facts |
| EVAL-03 | Paired week-block (>=4) and year-block bootstrap; never rows or wards | Sufficient-statistics-per-week design, O(B x n_weeks); measured CIs and ACF; year-block caveat (6 clusters) |
| EVAL-04 | Slices by lead, season (MAM highlighted), region, year; LGA-average and small wards flagged | Small-ward count measured: 3,086 of 4,835 non-empty wards (64%) |
| EVAL-05 | Test years locked; loaders refuse test rows until committed pre-registration + opened lock; log shows (here: no) test run | Windows/CRLF git mechanics verified; guard placement; existing tests that must change |
</phase_requirements>

## Summary

All five baselines can be computed on the dense (ward x week) arrays in seconds, then emitted as standard stored-prediction rows by gathering at the exact `(ward_pos, origin_pos)` pairs that `dataset.lead_row_index` returns. No DataFrame is needed to fit or predict. Loading the real panel takes about 9 s, `features.base_rate` about 5 s, each lead's logistic regression on about 5.2M training rows about 3 s (lbfgs converges in about 11 iterations), and `trend_season` is exact on aggregated (week x geozone) binomial counts in about 0.02 s. Materialising `lead_rows` itself is cheap (0.3 s for 1.52M validation rows, 1.0 s for 5.2M train rows with one feature), so memory is not the constraint. Validation has **1,520,074 rows for every lead** (314 target weeks x 4,841 wards; 2020-W53 included); train has 5,213,757 rows at lead 1 falling to 5,189,552 at lead 6.

Measured on the real data, the "bar" is low and the baselines are close to one another. Validation Brier (lead 1 / lead 6): climatology 0.1376 / 0.1376, recent_climatology (shrunk) 0.1365 / 0.1365, persistence 0.1306 / 0.1370, damped_persistence 0.1249 / 0.1356, trend_season 0.1330 / 0.1332; the validation "uncertainty" term is 0.1302. So **the best baseline is damped_persistence at leads 1-2 and trend_season at leads 3-6**. The prevalence shift (train 8.4-8.9% to validation 15.4%) makes static climatology predict a mean of 0.089 against an observed 0.154, and it is worse than a constant training base rate (0.1344). The static ward x ISO-week climatology therefore has no useful local information in validation and is a strawman reference. This is exactly what CONTEXT warned about, and the report must show it.

Confidence intervals are cheap if the bootstrap is expressed on per-week sufficient statistics. A replicate is a multiplicity vector over weeks times per-week sums, so B = 1000 takes about 5-10 ms for Brier/BSS and about 0.16 s for a 1000-bin AUC histogram. The paired lead-1 BSS (damped vs recent) is 0.085 with a week-block 95% CI of about [0.040, 0.130] and a year-block CI of about [0.028, 0.143]. The weekly loss-difference autocorrelation is only 0.15 at lag 1, so CI width is nearly independent of block length (L=1: [0.041, 0.125], L=4: [0.040, 0.130], L=26: [0.035, 0.130]). The test lock is straightforward with git: `git hash-object <file>` (clean filter applied) equals `git rev-parse HEAD:<file>` even under `core.autocrlf=true` with CRLF working-tree files.

**Primary recommendation:** Implement baselines as dense-array functions that return `(P_val[n, T])`-style matrices, emit rows by gathering at `lead_row_index` pairs, store one Parquet per (predictor, lead, split) with schema-level metadata, score everything through a sufficient-statistics-per-target-week engine that also drives both bootstraps, and put the test guard in `lead_rows` (split == "test"), `build_issue_table` (test-target labels) and the prediction loader, all through one `testlock.require_open()` that logs every attempt.

## Architectural Responsibility Map

This is a single-process offline Python pipeline (no browser/SSR/CDN tiers). Mapped to the repo's own layers:

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Baseline fitting and prediction | `heatwave/forecast/baselines.py` (pure numpy, dense arrays) | `dataset.lead_row_index` for the row set | Only module that fits; reads panel/clim/static; emits arrays, not files |
| Stored-prediction I/O + schema/metadata | `evaluation/predictions.py` | `artifacts.py` (run folder, manifest) | One place that knows the Parquet contract; writes under the run folder |
| Metrics (Brier, BSS, Murphy, AUC, P/R/F1, CITL) | `evaluation/metrics.py` (pure functions on arrays) | sklearn for cross-checks only | Deterministic, unit-testable on hand-computed cases |
| Bootstrap | `evaluation/bootstrap.py` (weights over target weeks) | `metrics.py` sufficient-stats | Resampling unit is the week/year; signature takes week ids, never rows |
| Slices and flags | `evaluation/slices.py` | `static.py` + new small-ward helper | Slice = boolean mask over rows keyed by ward/week attributes |
| Test lock + evaluation log | `heatwave/forecast/testlock.py` | `artifacts._git`, `config.config_hash` | Single gate; every loader calls it |
| Report rendering | `scripts/forecast_baselines.py` | `report.py` helpers (`_table`, `_pct`, `CAPTION`, lat constants) | Reads stored artifacts; writes `docs/forecast/BASELINES_VALIDATION.md` |

## Standard Stack

### Core (all already pinned in `requirements.txt`; nothing new to install)
| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.3.3 / 2.3.x | dense arrays, bincount-based bins, bootstrap weights | all Phase 9 code is numpy-dense |
| pandas | 2.3.2 | prediction frames, report tables | already used for lead_rows; categoricals keep memory ~18 B/row |
| pyarrow | 21.0.0 | Parquet with schema-level metadata | `replace_schema_metadata` for run_id / config hash / data sha |
| scikit-learn | 1.9.1 | `LogisticRegression`; `roc_auc_score`, `brier_score_loss` as cross-checks | pinned; lbfgs on 5.2M x 4 converges in ~3 s |
| shapely | 2.1.2 | ward polygon area for small-ward flag | already used by `static.py` |
| matplotlib | 3.10.6 | optional reliability PNG in the run folder | pinned; not needed for committed markdown |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| own numpy Brier/AUC | sklearn `brier_score_loss` / `roc_auc_score` | Use sklearn only in tests as cross-check: `brier_score_loss(y, p)` has `scale_by_half='auto'` (no halving for binary y; verified 0.3333 on uniform p) but the signature changed (`y_proba`, not `y_prob`); own numpy is 10x faster on grouped stats and is needed for sufficient statistics |
| `calibration_curve(strategy='quantile')` | own `searchsorted` binning | sklearn returns only fraction_of_positives and mean_predicted_value, not bin counts (needed for REL/RES weights); use own, cross-check bin means against sklearn in a test |
| scipy `stats.bootstrap` | own weights bootstrap | scipy resamples iid or by `axis`; no paired block with ratio statistics; own is ~30 lines |
| per-row LR for trend_season | binomial aggregated to (week x geozone) with `sample_weight` | Exact same MLE, 0.02 s instead of seconds |

**Installation:** none. (`pip list` confirms scikit-learn 1.9.1, scipy 1.18.1, pyarrow 21.0.0, shapely 2.1.2, matplotlib 3.10.6; `psutil` is not installed, do not use it.)

## Package Legitimacy Audit

No new external packages are recommended; every library above is already pinned in `requirements.txt` and in use. slopcheck was not run because there is nothing new to install.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| (none new) | - | - | - | - | n/a | Approved (already pinned) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 frozen panel (parquet, sha-verified) --load_panel--> Panel(values n x T x V)
 wards.geojson (hash-verified) --load_static--> StaticTable (geozone, lat, state_id, lga_average_ward)
                                           \
 Climatology.fit(panel, train_end)  ---------+--> xhi_anom (n x T)
                                             |
        +------------------------------------+------------------------------+
        |                                                                   |
  baselines.py (dense arrays)                              dataset.lead_row_index(panel,cfg,k,split)
  fit on TRAIN rows only:                                   -> (ward_pos, origin_pos), origin-major
   climatology / persistence / damped / trend                         |
  as-of (no fit): recent_climatology (features.base_rate)             |
        |   P[n x T_target] per (predictor, lead)                     |
        +----------- gather at (ward_pos, target_pos) ----------------+
                                  |
                      predictions.write(df) -> <run>/predictions/<predictor>_L<k>_<split>.parquet
                                  |      (testlock.require_open if any split == "test")
                                  v
                      predictions.load(...)  [only entry to the harness]
                                  |
                       align(reference, candidate): identical (ward, origin, lead) keys, else error
                                  |
          sufficient statistics per TARGET WEEK (and per slice):
            n, sum y, sum p, SSE, per-bin (n_k, sum p_k, sum y_k), AUC hist pos/neg, TP/FP/FN
                                  |
        +-------------------------+----------------------------+
   point metrics              week-block bootstrap          year-block bootstrap
   (Brier, BSS, REL/RES/UNC,   c[b, w] = multiplicity of     c[b, year]
    AUC by slice, P/R/F1,      week w in replicate b          (6 clusters)
    CITL by year)              metric_b = (c @ stats) ratio   percentile CI
                                  |
              best-baseline per lead  -->  scripts/forecast_baselines.py
                                  |
        docs/forecast/BASELINES_VALIDATION.md (committed)  +  run folder artifacts
                                  |
   every load/score  -->  testlock.log (evaluation_log.jsonl, append-only)
   split == "test"  -->  testlock.require_open()  [PREREGISTRATION.md committed+clean AND TEST_LOCK.json open]
```

### Recommended Project Structure
```
heatwave/forecast/
├── baselines.py            # 5 baselines, dense arrays; BASELINE_REGISTRY keyed by cfg.baselines.names
├── testlock.py             # require_open / open_lock / log_event / count_test_runs
└── evaluation/
    ├── __init__.py
    ├── predictions.py      # schema, write, load (lock-aware), align
    ├── metrics.py          # brier, bss, murphy, auc, prf, citl; WeekStats sufficient statistics
    ├── bootstrap.py        # block_weights(), year_weights(), ci(); signature takes week ids
    └── slices.py           # season/region/year masks, flags (lga_average, small ward)
scripts/forecast_baselines.py
docs/forecast/PREREGISTRATION.template.md   # template ONLY (see Pitfall 8)
docs/forecast/BASELINES_VALIDATION.md       # generated, committed
tests/forecast/test_forecast_{baselines,metrics,bootstrap,slices,predictions,testlock}.py
```

### Pattern 1: Baselines on dense arrays, rows by gather
**What:** every baseline returns a float32 `(n, T)` matrix indexed `[ward_pos, origin_pos]` for a given lead; rows come from `lead_row_index` so the row set is identical to `lead_rows` by construction.
**When:** always for the five baselines. Phase 11 models use `lead_rows` frames, but rows are in the same origin-major order, so they write the same format.
**Example (verified numbers in this doc come from this logic):**
```python
# Source: measured in this research session against heatwave.forecast.* (scratch scripts)
ward_pos, origin_pos = dataset.lead_row_index(panel, cfg, lead, "validate")  # origin-major, ward fastest
tgt_pos = origin_pos + lead                                   # target position in the panel
p = P_lead[ward_pos, origin_pos].astype(np.float32)           # P_lead built for (n, T) origins
y = targets.lead_label(panel, lead)[ward_pos, origin_pos].astype(np.int8)
```

### Pattern 2: Per-target-week sufficient statistics drive every CI
**What:** for each (predictor, lead, slice) compute arrays indexed by target week: `n_w`, `sum_y_w`, `sum_p_w`, `sse_w`, `n_wk`, `sum_p_wk`, `sum_y_wk` (K fixed quantile bins), `pos_wh`, `neg_wh` (H = 1000 fixed-edge score bins for AUC), `tp_w, fp_w, fn_w` at the stated threshold. A bootstrap replicate with multiplicity vector `c` (length W) is `c @ stat` then a ratio.
**Why:** O(B x W) not O(B x n_rows). Measured: Brier+BSS B=1000 about 5-10 ms; AUC histogram CI 0.16 s; binned AUC 0.7019278 vs exact sklearn 0.7019276.
**Caveat:** reliability/resolution CIs are conditional on the full-sample quantile bin edges (state it in the report).

### Pattern 3: Circular block weights
```python
# Source: measured; circular block bootstrap (Politis & Romano 1992) as multiplicity counts
def block_weights(n_weeks, block, B, rng):
    nb = -(-n_weeks // block)                                    # ceil
    start = rng.integers(0, n_weeks, size=(B, nb))
    idx = ((start[:, :, None] + np.arange(block)) % n_weeks).reshape(B, -1)
    c = np.zeros((B, n_weeks))
    rows = np.repeat(np.arange(B), idx.shape[1])
    np.add.at(c, (rows, idx.ravel()), 1.0)                       # or loop of bincount, 1000 iterations is fast
    return c
```
Use circular (wrap) so every week has equal inclusion probability; moving-block (no wrap) under-weights the first and last `L-1` weeks. Both gave the same CIs here. Generate `c` **once per lead** from `np.random.SeedSequence([cfg.seed, lead])` and reuse it for every predictor and slice so pairing is exact and results do not depend on call order.

### Pattern 4: One `Predictor` protocol, harness never imports it
```python
class Predictor(Protocol):
    name: str
    def fit(self, ctx: "FitContext") -> "Predictor": ...          # ctx: panel, static, clim, cfg, train_target_end
    def predict(self, lead: int, ward_pos: np.ndarray, origin_pos: np.ndarray) -> np.ndarray: ...  # float32 in [0,1]
```
Keep `train_target_end` a parameter (default derived from `splits`) so Phase 14 can refit baselines on 1991-2020 with `splits.refit_train_mask` without rewriting them.

### Anti-Patterns to Avoid
- **Resampling rows or wards:** forbidden (PITFALLS C5). Make `bootstrap` functions take `week_id` / `year_id` arrays and test the signature.
- **Fitting inside the harness** or calling `.predict` from scoring code.
- **Pooled AUC as a headline.** Only stratified (season, region) AUC; there is no pooled-AUC output field.
- **Any accuracy metric.** Add a test that the metrics module exposes no `accuracy` symbol and report text has no "accuracy".
- **Merging prediction frames with `pd.merge` on 1.5M string keys.** Compare aligned integer arrays instead (see Code Examples).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Logistic regression | custom Newton/IRLS | `sklearn.linear_model.LogisticRegression(solver='lbfgs')` | 5.2M x 4 fits in about 3 s; handles `sample_weight` for exact aggregated binomial |
| Same-season trailing base rate | new rolling code | `features.base_rate(hw, week_start, years=cfg.baselines.recent_climatology_years)` | already Phase 9-tested and leak-free; read it at the **target** column (see Pitfall 2) |
| Ward group means (state pooling) | loops | `features.group_mean(x, static.state_id)` | vectorised |
| ISO-week pooling matrix | new | `climatology.iso_week_slots` + `pooling_matrix()` (W53 pooled with W52/W01) | exactly the Phase 9 pooling CONTEXT asks to reuse |
| Run folders, manifests, git info | new | `artifacts.run_folder`, `artifacts._git`, `git_info`, `REPO_ROOT` | refuses in-repo data roots; atomic manifest |
| Report markdown tables | new | `report._table`, `report._pct`, `report.CAPTION`, `LAT_FAR_NORTH`/`LAT_MIDDLE_BELT` | consistent with DATA_REPORT.md |
| Config hash | new | `config.config_hash(cfg)` | already the provenance key in run ids |
| AUC point estimate | own rank code | `sklearn.metrics.roc_auc_score` (0.45 s on 1.5M rows) | handles ties; only the CI path uses the histogram approximation |

**Key insight:** every expensive thing in this phase is a sum over rows that factorises over target weeks. Compute those sums once per (predictor, lead, slice) and everything else (bootstrap CIs, year tables, bin tables) is a small matrix product.

## Baselines: measured behaviour (real data, validation 2015-2020)

Fit/prediction recipes and the numbers behind the recommendations. All validated by running against the frozen panel with the repo's own Phase 9 modules.

### Row sets
| lead | train rows | validate rows | train origins | validate origins |
|------|-----------:|--------------:|-------------:|-----------------:|
| 1 | 5,213,757 | 1,520,074 | 1,077 | 314 |
| 2 | 5,208,916 | 1,520,074 | 1,076 | 314 |
| 3 | 5,204,075 | 1,520,074 | 1,075 | 314 |
| 4 | 5,199,234 | 1,520,074 | 1,074 | 314 |
| 5 | 5,194,393 | 1,520,074 | 1,073 | 314 |
| 6 | 5,189,552 | 1,520,074 | 1,072 | 314 |

Warm-up first position = 159. Train cutoff index 1251, validate end 1565, T = 1863. [VERIFIED: ran `dataset.lead_row_index`]

### Brier on validation (identical rows for all predictors)
| lead | climatology | recent_clim (m=50) | persistence | damped_persistence | trend_season | best |
|-----:|------:|------:|------:|------:|------:|------|
| 1 | 0.13756 | 0.13652 | 0.13058 | **0.12488** | 0.13304 | damped |
| 2 | 0.13756 | 0.13652 | 0.13549 | **0.13224** | 0.13307 | damped |
| 3 | 0.13756 | 0.13652 | 0.13638 | 0.13448 | **0.13310** | trend |
| 4 | 0.13757 | 0.13652 | 0.13828 | 0.13690 | **0.13312** | trend |
| 5 | 0.13756 | 0.13652 | 0.13761 | 0.13646 | **0.13314** | trend |
| 6 | 0.13756 | 0.13652 | 0.13704 | 0.13558 | **0.13316** | trend |

At lead 3 trend_season (0.13310) already beats damped (0.13448). So the best baseline is **damped_persistence at leads 1-2 and trend_season at leads 3-6** [VERIFIED: scratch run, all six leads]. The gate leads [1, 2] therefore compare against damped_persistence, an AR-type benchmark (PITFALLS C8), which is a far harder bar than climatology.

Reference quantities: observed validation base rate 0.15385; "uncertainty" (Brier of the constant validation rate) 0.13018; constant training rate (0.0885) scores 0.1344; the ward x ISO-week climatology scores 0.1376 (worse than the constant). Mean predicted probability: climatology 0.0888 (lead 1), recent_clim (unshrunk) 0.1118, trend 0.1165 (lead 1), against 0.1539 observed. Hard 0/1 persistence scores 0.2146 at lead 1 and 0.2559 at lead 6, which is why probabilistic persistence is mandatory.

### Calibration-in-the-large by year (lead 1; mean p vs observed)
| year | observed | climatology | recent (m=50) | trend | damped |
|-----:|---:|---:|---:|---:|---:|
| 2015 | 0.140 | 0.089 | 0.109 | 0.111 | 0.098 |
| 2016 | 0.223 | 0.088 | 0.102 | 0.113 | 0.144 |
| 2017 | 0.158 | 0.088 | 0.106 | 0.115 | 0.128 |
| 2018 | 0.105 | 0.088 | 0.115 | 0.117 | 0.106 |
| 2019 | 0.170 | 0.088 | 0.121 | 0.120 | 0.126 |
| 2020 | 0.128 | 0.089 | 0.118 | 0.123 | 0.103 |

All static or trend baselines under-predict every validation year except 2018 (by construction), so any model with recent-state information will show large BSS against climatology. Reporting BSS against recent climatology as well as climatology (already in CONTEXT) is essential, and the gate uses the best baseline.

### Recent-climatology details
- Compute `br, cnt = features.base_rate(hw, panel.week_start, years=cfg.baselines.recent_climatology_years)` once (5 s). For origin t and lead k, the value is `br[:, t + k]` (the base rate **at the target column**). The anchors used at column s are ISO weeks (year(s) - j, week(s)) +-2 for j = 1..10, i.e. positions <= s - 50, so for k <= 6 they are all <= t. No label from after the issue week is used. [VERIFIED: reading `base_rate`: `valid = idx <= arange_t`; anchors at least 52-2 weeks back]
- Observations per ward-week window: 10 years x 5 weeks = 50 (min 50, median 50 on validation; `min_obs=15` NaNs only the first ~3 years of the series).
- Do NOT read `store["hw_base_rate_10y"]`: that feature is evaluated at the origin week, not the target week.
- **State shrinkage:** `p = (pos + m * p_state) / (n_obs + m)` with `pos = br * cnt` and `p_state = group_mean(br, static.state_id)` (20 states, 62-484 wards each). Validation Brier by pseudo-count m (lead-independent): m=0: 0.13713, 5: 0.13699, 10: 0.13689, 20: 0.13674, 50: 0.13652, 100: 0.13638, 200: 0.13629, 500: 0.13624 (state only: 0.13621; domain-wide: 0.13509). The same monotone pattern holds in a **training-period backtest** (targets 2005-2014: 0.10121 at m=0 to 0.10061 at m=500). Ward-level detail in a 50-observation window is noise relative to state-level signal; the ERA5-Land weekly labels are spatially very coherent.
- **Recommendation:** fix the pseudo-count at **m = 50** (equal weight to the ward's own window and the state rate), set in config (hash-tracked), and state in the report that larger m scores marginally better on both backtest and validation (differences are far below the CI half-width, about 0.002 in Brier). This avoids choosing m on validation.

### Persistence
- Estimate `P(y_{t+k}=1 | y_t, season(target), geozone)` from the training rows with a light additive smoothing (`(pos + 0.5) / (n + 1)`), 2 x 4 x 3 = 24 cells per lead. Season = month of target week mid-week (Monday + 3 days): DJF = Dec/Jan/Feb, MAM = Mar-May, JJA, SON. Geozone from `static.geozone`.
- Lead 1: P(y=1|y0=1) mean 0.299, P(y=1|y0=0) mean 0.067; lead 6: 0.170 / 0.081. Skill decays with lead overall (Brier 0.1306 -> 0.1370) but **not strictly monotonically** (lead 4: 0.1383 is worse than lead 5: 0.1376). So the sanity check must be "lead-1 persistence skill > lead-6 persistence skill" (and a warning, not an assertion, on strict monotonicity).

### damped_persistence
- Features: `xhi_anom_lag0` (max-heat-index anomaly, the quantity most tied to the heatwave definition) or `mhi_anom_lag0`; both give nearly identical Brier (lead 1: 0.12488 xhi vs 0.12446 mhi; lead 6: 0.13558 vs 0.13552). Recommend `xhi_anom_lag0` on conceptual grounds (it is closest to the label's Tmax-HI definition); do not pick on validation score. Obtain it as `Climatology.anomaly(panel, "max_heat_index")[:, origin]` (clim fitted at `splits.train_end`; the same object Phase 9 uses). Plus lag-0 `heatwave_week`, `sin`, `cos` of the **target** week (use `features.season_features(target_week_start)`).
- `LogisticRegression(C=1.0, penalty='l2', solver='lbfgs', max_iter=2000)`, 4 columns, float64; 2.4-2.9 s per lead; coefficients (lead 1): xhi +0.99, y0 +0.53, sin +0.05, cos +0.33; lead 6: 0.37, 0.34, 0.04, 0.34. Fixed constants, not `cfg.models.logistic_regression` (Phase 12 tunes that block and would silently change the baseline).
- Fitting on the dense arrays: build `X` only for `lead_row_index(..., "train")` pairs; 5.2M x 4 float64 = 167 MB.

### trend_season
- Features: continuous year (fractional year of the target week, centered at the training midpoint e.g. 2003 to avoid intercept collinearity), `sin`/`cos` of the target week, geozone one-hot (two dummies). Exact fit via aggregation: for each (target week, geozone) cell create two rows (y=1 weight = positives, y=0 weight = negatives) and fit `LogisticRegression(C=1e6)`. 0.02 s. Coefficients (lead 1): year +0.0228 logit/yr, sin 0.043, cos 0.332.
- It extrapolates the linear logit trend into 2015-2020 and still under-predicts (mean p 0.1165 vs 0.1539 observed). Document explicitly (CONTEXT requires it). The trend is a Brier-best baseline at leads 3-6 only because the other baselines have no recent-state information at long lead.
- The registry bans "year" in **feature names** (`registry.FORBIDDEN_NAME_PATTERN`), but this baseline never goes through the feature registry; keep the year term local to `baselines.py` and add a test that no registry feature contains it.

### climatology (fit)
- Pooled per-ward rate over training target weeks (those of the lead's training rows: origin >= warm-up, target < train_end - 14 weeks): `rate[:, slot] = (hw[:, S] @ onehot @ M.T) / (M @ counts)` where `M = pooling_matrix()`, `onehot` maps weeks to `iso_week_slots - 1`. Using all weeks before `train_end` instead changes Brier only in the 4th digit (0.13787 vs 0.13756); use the lead's training rows for consistency with "fitted on training rows only".

### Murphy decomposition: correctness pitfalls (measured)
- Identity `BS = REL - RES + UNC` is exact only if p is constant within bins. With 10 quantile bins on a continuous predictor (damped), the residual is 7.5e-5 (K=10) and -1.5e-5 (K=20), versus REL = 0.0030, RES = 0.0083, UNC = 0.1302. Report the **residual** (or "within-bin variance term") explicitly, and test the exact identity only on predictors with <= K distinct values (persistence, climatology-like) where it is exact.
- **Tie handling bug I hit:** collapsing the quantile edges with `np.unique` and then `searchsorted(edges[1:-1], p)` merges everything into one bin when most p values tie (a 2-valued predictor produced 1 bin and a 3e-3 residual). Use sklearn's pattern: **keep duplicate edges**, `edges = np.quantile(p, np.linspace(0, 1, K + 1))`, `bin = np.searchsorted(edges[1:-1], p, side='left')`, drop empty bins. Equal p values stay together, so a discrete predictor's decomposition is exact.
- UNC must use the same rows' base rate `o_bar (1 - o_bar)`; the values per slice differ.
- Binned REL is biased upward for small samples (Brocker 2008; Ferro & Fricker 2012); with 1.5M rows and 10 bins this is negligible, but slice cells with a few thousand rows should show n.

## Confidence intervals: measured design notes
- Resampling units: 314 target weeks (validation), 6 target years (2015-2020 with 53, 52, 52, 52, 52, 53 weeks; use the ISO year of the **target week label**, so 2020-W53 belongs to 2020).
- Lag-1 autocorrelation of the weekly Brier-difference series (recent minus damped, lead 1) is 0.147; lags 2-26 are within +-0.08. The effective number of independent weeks is roughly 314 / (1 + 2 x 0.15) which is about 240. This is why block length hardly matters here, but implement `block >= 4` anyway (EVAL-03).
- BSS(damped vs recent) lead 1: point 0.0852. Week-block 95% percentile CI, B=1000: L=1 [0.0413, 0.1245]; L=4 [0.0402, 0.1300]; L=8 [0.0402, 0.1302]; L=13 [0.0388, 0.1295]; L=26 [0.0352, 0.1303]. Year-block: [0.0277, 0.1427]. Per-year BSS: 2015 0.099, 2016 0.192, 2017 0.006, 2018 0.009, 2019 0.048, 2020 0.097 (skill is very uneven by year; year-block CI is based on six clusters, 6^6 = 46,656 distinct resamples, so treat it as a coarse sensitivity check and say so in the report).
- BSS > 0 iff the Brier difference > 0 in every replicate, so the percentile CI for BSS excludes 0 exactly when the CI for the Brier difference does. Report both: `BSS = 1 - BS_cand / BS_ref` (gate statistic) and `dBS = BS_ref - BS_cand` (positive = candidate better).
- Slice CIs (season, region) reuse the same `c` matrix restricted to slice weeks; label them exploratory and print no p-values or "significant" (PITFALLS M5). A slice that a replicate misses entirely gives a zero denominator: return NaN and report the fraction of valid replicates.

## Slices and flags
- Latitude bands: reuse `report.LAT_FAR_NORTH = 11.5`, `LAT_MIDDLE_BELT = 9.5` (central = [9.5, 11.5]); counts: far north 2,022 wards, central 1,290, middle 1,523 (by centroid; the 6 empty-geometry wards use the LGA centroid via `static`).
- **Small ward** = ward polygon area < one 0.1 x 0.1 degree cell. Because both areas scale by cos(latitude), the test reduces to `shapely.geometry.shape(geom).area < 0.01` (deg^2); the explicit km^2 variant gives the identical count. Measured on `inputs/wards.geojson`: **3,086 of 4,835 non-empty wards (63.8%)** are smaller than one cell (1,896 are < half a cell, 1,026 < a quarter); by band: far north 1,459 of 2,022, central 709 of 1,290, middle belt 918 of 1,523. Median area / cell = 0.67. 6 wards have empty geometry (already `static.empty_geometry`). Consequence: the flag is not a rare edge case. Report headline metrics for all wards and a "large wards only" row (1,749 wards) rather than excluding small wards by default.
- Implement as a helper reading the hash-verified geojson bytes via `static._read_verified` (or a new `static.ward_area_deg2(data_cfg, wards, data_root)`), not by changing `StaticTable` (its dataclass is exercised by Phase 9 tests). Synthetic fixtures use `_square(lon, lat, d=0.02)` squares of area 0.0004 deg^2, i.e. all "small"; add a larger synthetic ward to test the other side.
- The 6 LGA-average wards: `static.lga_average_ward`.

## Stored predictions: format, size, speed
- Columns and dtypes that worked (1.52M rows): `predictor` categorical, `lead` int8, `ward` categorical (from `dv["ward"]`), `origin_week_index` int16, `target_week_index` int16, `target_week` categorical, `split` categorical, `p` float32, `y` int8, `fold` pandas nullable `Int8`. In memory 28 MB; Parquet (zstd) 7 MB for random p; write 0.37 s, read 0.08 s. Build time from a lead_rows frame 0.26 s.
- One file per (predictor, lead, split): `predictions/<predictor>_L<lead>_<split>.parquet`. Validation total = 5 predictors x 6 leads x 1.52M = 45.6M rows (30 files, roughly 100-200 MB). Train predictions for diagnostics are 156M rows (30 files of 5.2M); make them optional (`--train-predictions/--no-train-predictions`, default on for leads 1 and 6 only) since nothing in this phase's scoring needs them. `recent_climatology` is NaN at early training origins (`counts < 15`); drop NaN rows when storing train diagnostics and let the loader assert no NaN in `p`.
- Provenance in the Parquet footer: build with `pa.Table.from_pandas(df)` then `table.replace_schema_metadata({**table.schema.metadata, b"heatwave_forecast": json.dumps({...}).encode()})`; JSON holds `run_id`, `config_sha256`, `data_sha256`, `predictor`, `lead`, `split`, `schema_version`, `threshold` (optional). Reading: `pq.read_schema(path).metadata`.
- Order: rows are origin-major with wards fastest (`np.tile(arange(n), origins)`/`np.repeat(origins, n)`); all predictors for a (lead, split) share that order, so alignment is an array-equality check on `(ward codes, origin_week_index)`; the loader should re-align by `lexsort` when orders differ and **raise** if key sets differ.

## Test lock mechanics (verified on Windows, git 2.55.0, `core.autocrlf=true`)
- Committed check: `git ls-files --error-unmatch -- docs/forecast/PREREGISTRATION.md` (rc 0 tracked, rc 1 untracked).
- Unmodified check: `git rev-parse HEAD:docs/forecast/PREREGISTRATION.md` equals `git hash-object -- docs/forecast/PREREGISTRATION.md`. Verified with a CRLF working-tree file under autocrlf=true: both gave `c0d0fb45...` before editing; after editing the hash-object value changed (`b87cf495...`). `hash-object` applies the clean filter, so line-ending conversion does not cause false "modified" results. `git diff --quiet HEAD -- <file>` also works (rc 0 clean, rc 1 modified, and rc 1 for staged-but-uncommitted), but the blob-sha comparison is the one that yields the sha you must **record in TEST_LOCK.json**; use `rev-parse HEAD:<path>` for that (requires the file to be in HEAD, so staged-only is correctly rejected).
- Use `artifacts._git(args, repo_root)` (returns None on failure, 10 s timeout) with `repo_root` as a parameter defaulting to `artifacts.REPO_ROOT`; tests pass a `tmp_path` repo. Also reuse the `samefile(toplevel)` guard from `git_info` so a tmp dir nested inside another repo is not mistaken for the project repo.
- `TEST_LOCK.json` fields: `schema_version`, `opened_utc`, `preregistration_path`, `preregistration_blob_sha`, `config_sha256`, `model_bundle_sha256`, `opened_by` (free text). Written atomically (`tmp` then `os.replace`). `open_lock()` must (1) check committed+clean, (2) require the pre-registration text to contain the current `config_sha256` (binds the registration to the config; PITFALLS M5/C9 "metrics differ from the pre-registered config") and no template placeholder marker, (3) refuse to overwrite an existing lock with different hashes (C9 "fails on the second call with a different hash"), (4) log `lock_opened`.
- `require_open(cfg, purpose, data_root=None, repo_root=REPO_ROOT)` on every access: recompute blob sha and `config_hash(cfg)` and compare with the lock file, so tampering with the pre-registration or config **after** opening re-closes the lock. On any failure log `event="test_access_refused"` with reason, then raise `TestLockError` (subclass `RuntimeError`).
- Location: `<local_data_dir>/forecast_runs/TEST_LOCK.json` and `evaluation_log.jsonl` (same base as run folders; `RUN_ID_PATTERN` never matches these names). Refuse a data root inside the repo, as `start_run` does.
- Evaluation log: one JSON object per line, opened with `open(path, "a", encoding="utf-8", newline="\n")`, a single `write(line + "\n")`, `flush()`, `os.fsync()`. Fields: `ts_utc`, `event` (`score`, `lock_opened`, `test_access_refused`, `test_access_granted`), `predictor`, `split`, `n_rows`, `run_id`, `config_sha256`, `outcome`, `reason`. Cheap tamper-evidence: include `prev_sha256` (sha256 of the previous line's bytes) so deletions or edits break the chain; `count_test_runs(log)` returns the number of records with `split == "test"` and `outcome == "granted"/"scored"`. Phase 10 acceptance: `count_test_runs == 0` over the **real** log (refused attempts do not count as runs).
- Single-process appends are safe on Windows with this pattern; no cross-process lock is needed here.

### Where to guard (and what existing tests break)
- `dataset.lead_rows`: add the check when `fold is None and split == "test"` (fold selections only support train/validate). Keep `lead_row_index` unguarded (index only, used by `report.row_count_table` for counts).
- **`dataset.build_issue_table` also exposes test labels** (`heatwave_week_l{k}`, `has_label_l{k}` for rows whose `split_l{k} == "test"`). Guard it too: simplest is to call `require_open` only when any selected row has `split_l{k} == "test"` with a label, or (less invasive) blank those label columns to NaN/False when the lock is closed. Decide in planning; either way Phase 9 tests that build issue tables with origins through `T-1` need checking (`test_forecast_dataset.py` lines 110, 248, 271, 285, 302, 338, `test_forecast_leakage.py` 259).
- `predictions.load`: raise if any row's `split == "test"` (and in the metadata) unless open; `score()` logs every scoring run.
- Raw `targets.lead_label` / `heatwave_week_matrix` arrays cannot be guarded; the lock is a mechanical safeguard for loaders, not a security boundary. Say so in the module docstring.
- **Existing tests that call `lead_rows(..., "test")`:** `tests/forecast/test_forecast_dataset.py:103`, `:262`, and `tests/forecast/test_forecast_leakage.py:197` (comprehension over `splits.SPLIT_NAMES`). They must be updated, e.g. via a fixture `allow_test_rows` that `monkeypatch`es `testlock.require_open` to a no-op (keep dedicated tests that use the real tmp git repo). Do not add an `allow_test=True` public parameter; a bypass argument defeats EVAL-05.
- **Do not let tests write to the real evaluation log.** Add an autouse fixture in `tests/forecast/conftest.py` that monkeypatches the single function through which `testlock` resolves the default data root (e.g. `testlock._default_data_root`) to a per-test `tmp_path`. Otherwise the existing tests above would append refusals/grants to `<local_data_dir>/forecast_runs/evaluation_log.jsonl` and break the "log shows no test run" acceptance.
- Tests that spawn git should be marked `@pytest.mark.slow` (existing convention: `test_git_info_real_repo`). Keep the pure-python lock logic testable with an injected `git` callable so the quick loop still covers closed/open/tampered cases; run the real-git variants under `slow`.

### Pre-registration template
Ship `docs/forecast/PREREGISTRATION.template.md` (committed) with fields: primary metric (BSS vs best baseline), primary leads (1, 2), baselines and reference (best baseline per lead, from BASELINES_VALIDATION), CI method (paired week-block, block 4, B, seed, 95%, plus year-block), go/no-go thresholds, confirmatory slice list (everything else exploratory, M5), config sha256, model-bundle sha256, retrain policy, test years. **Do not** name it `PREREGISTRATION.md`; a committed template at the real path would satisfy check (a) by itself. `open_lock` must reject text containing a placeholder token (e.g. `<<FILL>>`).

## Config changes (strict validator: unknown keys rejected, all keys required)
`config._build` rejects unknown and missing keys per section, and `ForecastConfig` rejects unknown top-level keys, so every new setting must be added to the dataclasses and `forecast.yaml` together. The config hash is computed from the dict (not pinned in tests; `test_config_hash_stable` recomputes it), so adding keys only changes new run ids. `ForecastConfig` is only constructed in `load_forecast_config` (no direct constructions in tests), and the parametrised mutation tests (`test_forecast_config.py` ~line 252) are keyed by section name, so a new section is additive.

Recommended minimal additions:
```yaml
baselines:
  names: [climatology, recent_climatology, persistence, damped_persistence, trend_season]
  recent_climatology_years: 10
  shrinkage_pseudo_count: 50          # new, int >= 0 (0 = no shrinkage)
evaluation:                           # new top-level section (EvaluationConfig)
  bootstrap_b: 1000                   # int >= 1 (tests pass a small B to the function, not config)
  block_weeks: 4                      # int >= 4 (EVAL-03)
  reliability_bins: 10                # int >= 2
  auc_hist_bins: 1000                 # int >= 10 (CI path only)
```
- Reuse `gate.ci_level` (0.95) for CI level and the global `seed` for resampling (derive per-lead streams with `SeedSequence([seed, lead])`); do not add a second seed (the validator deliberately has one global seed).
- Persistence smoothing, LR hyper-parameters (C) and the F1 threshold rule are module constants documented in the report; if you want them hash-tracked, put them in `baselines:` too, but this is optional. `models.logistic_regression` must not be reused.
- `_BASELINE_NAMES` already contains all five names; no change needed.
- Update the tests for the new section (missing key / unknown key / out-of-range value cases) in `tests/forecast/test_forecast_config.py`.

## Common Pitfalls

### Pitfall 1: Static climatology is a strawman and the BSS-vs-climatology headline flatters models
**What goes wrong:** climatology predicts 0.089 against 0.154 observed; any recent-state predictor "beats" it (damped BSS vs climatology about 0.092 at lead 1) mostly by knowing the climate warmed (PITFALLS C6).
**How to avoid:** always report BSS vs recent_climatology and vs the **best baseline** next to BSS vs climatology; print calibration-in-the-large by year; state in the report that the gate uses the best baseline (damped_persistence at leads 1-2).
**Warning signs:** BSS vs climatology large while BSS vs best baseline about 0.

### Pitfall 2: Reading the base rate at the wrong column
**What goes wrong:** `features.base_rate` output at column t is "as of origin t" for **that** week's own same-season window; for a lead-k forecast the correct value is at column t + k (the target week's season), not `hw_base_rate_10y[:, t]`.
**How to avoid:** gather `br[:, origin + lead]`; add a leakage test: truncate/poison the panel after the origin (`fixtures.truncate_panel`, `poison_future`) and assert predictions for origin t are unchanged for all k <= 6.

### Pitfall 3: Quantile-bin ties
**What goes wrong:** `np.unique` on quantile edges collapses discrete predictors into one bin and breaks the Murphy identity. **How to avoid:** keep duplicate edges, bin by `searchsorted(edges[1:-1], p)`, drop empty bins; test with a two-valued predictor.

### Pitfall 4: Resampling the wrong unit or non-paired replicates
**What goes wrong:** row/ward resampling gives half-width far below the true value (C5); independent resamples per predictor destroy pairing. **How to avoid:** one multiplicity matrix per lead shared by all predictors; signature test that bootstrap functions take week/year ids; synthetic perfect-spatial-correlation test where the CI equals the single-site CI.

### Pitfall 5: Prevalence-dependent threshold metrics
**What goes wrong:** the default threshold is the **training** base rate for the lead (about 0.0885 at lead 1), so climatology-type predictors flag a large share of rows, and validation prevalence is 15.4%. **How to avoid:** write threshold, predicted-positive rate and prevalence beside every P/R/F1 row; never rank predictors by F1; no accuracy anywhere.

### Pitfall 6: Persistence evaluated as 0/1
Hard persistence scores 0.2146 (lead 1) and 0.2559 (lead 6). Keep `persist_hard01` out of the baseline set; if shown, label it a diagnostic only.

### Pitfall 7: Test rows leaking through paths other than lead_rows
`build_issue_table` carries test labels; prediction frames written by any script may contain `split == "test"`; the metadata could be edited. Guard all three and log attempts (see Test lock).

### Pitfall 8: A committed template satisfying "pre-registration committed"
See pre-registration section: use a different filename and a placeholder check.

### Pitfall 9: Tests polluting the real evaluation log or lock
Autouse tmp data-root fixture (see above); the real-log "no test run" check is a read-only acceptance step.

### Pitfall 10: Year-block CI over six clusters
Report it as a coarse sensitivity bound with the per-year BSS table beside it; do not use it alone for the gate.

### Pitfall 11: Slice CIs with empty replicates
Return NaN for empty denominators and report valid-replicate counts; do not substitute zeros.

### Pitfall 12: Synthetic panel does not reach validation years
`fixtures.synthetic_panel()` defaults to `last_week="2003-W20"`, so default synthetic panels contain no validation or test rows. Use `synthetic_panel(last_week="2027-W10")` (the pattern at `test_forecast_dataset.py:243`; 6 wards, cheap) for baseline, harness and lock tests.

## Code Examples

### Aligned row comparison without merge (paired scoring)
```python
# Source: designed from measured behaviour (rows are origin-major, ward fastest)
def aligned_arrays(ref, cand):
    r = np.lexsort((ref["ward"].cat.codes.to_numpy(), ref["origin_week_index"].to_numpy()))
    c = np.lexsort((cand["ward"].cat.codes.to_numpy(), cand["origin_week_index"].to_numpy()))
    # categories must match; verify then compare keys
    if not (ref["ward"].cat.categories.equals(cand["ward"].cat.categories)):
        raise ValueError("ward categories differ")
    if len(r) != len(c) or not (
        np.array_equal(ref["ward"].cat.codes.to_numpy()[r], cand["ward"].cat.codes.to_numpy()[c])
        and np.array_equal(ref["origin_week_index"].to_numpy()[r], cand["origin_week_index"].to_numpy()[c])):
        raise ValueError("reference and candidate rows differ")
    return r, c
```

### Quantile-bin Murphy decomposition (tie-safe)
```python
# Source: measured in this session; sklearn calibration_curve uses the same edge/searchsorted pattern
def murphy(p, y, K=10):
    p = np.asarray(p, np.float64).ravel(); y = np.asarray(y, np.float64).ravel()
    edges = np.quantile(p, np.linspace(0.0, 1.0, K + 1))          # keep duplicates
    b = np.searchsorted(edges[1:-1], p, side="left")
    nk = np.bincount(b, minlength=K).astype(float)
    sp = np.bincount(b, weights=p, minlength=K); sy = np.bincount(b, weights=y, minlength=K)
    ok = nk > 0; w = nk[ok] / nk.sum(); pk = sp[ok] / nk[ok]; ok_ = sy[ok] / nk[ok]; ob = y.mean()
    rel = (w * (pk - ok_) ** 2).sum(); res = (w * (ok_ - ob) ** 2).sum(); unc = ob * (1 - ob)
    bs = ((p - y) ** 2).mean()
    return dict(bs=bs, rel=rel, res=res, unc=unc, residual=bs - (rel - res + unc), n_bins=int(ok.sum()))
```

### Replicate statistics from week weights
```python
# c: (B, W) multiplicities; sse_ref, sse_cand, n: (W,) per-target-week sums
bs_ref = (c @ sse_ref) / (c @ n); bs_c = (c @ sse_cand) / (c @ n)
bss = 1.0 - bs_c / bs_ref; dbs = bs_ref - bs_c
lo, hi = np.percentile(bss, [100 * (1 - ci) / 2, 100 * (1 + ci) / 2])   # ci = cfg.gate.ci_level
```

### Binned AUC from per-week histograms (CI path only)
```python
def auc_from_hist(pos, neg):                  # (..., H) counts, edges from full-sample quantiles
    cn = np.cumsum(neg, axis=-1) - neg
    return (pos * (cn + neg / 2)).sum(-1) / (pos.sum(-1) * neg.sum(-1))
```
Point estimate AUC from `roc_auc_score`; the histogram value differed by 2e-7 (0.7019278 vs 0.7019276).

### Parquet with metadata
```python
table = pa.Table.from_pandas(df, preserve_index=False)
meta = {**(table.schema.metadata or {}), b"heatwave_forecast": json.dumps(info, sort_keys=True).encode()}
pq.write_table(table.replace_schema_metadata(meta), path, compression="zstd")
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Rows treated iid for CIs | Block bootstrap over time units, ratio statistics from per-unit sums | CI reflects temporal, not spatial, uncertainty (C5) |
| Skill vs a fixed historical climatology | Skill vs best of {recent climatology, trend, damped persistence} (Hamill & Juras 2006) | Prevents "knows the climate warmed" skill |
| sklearn `brier_score_loss(y_prob=...)` | `brier_score_loss(y_true, y_proba, scale_by_half='auto')` (sklearn 1.9) | Use `y_proba`; 'auto' does not halve for binary y |

**Deprecated/outdated:** `y_prob` keyword of `brier_score_loss` (renamed `y_proba`).

## Runtime State Inventory

Not a rename/refactor/migration phase. Stored state introduced by this phase (all outside the repo): `<local_data_dir>/forecast_runs/<run_id>/predictions/*.parquet`, `TEST_LOCK.json` (not created in this phase), `evaluation_log.jsonl`. Existing: two Phase 9 run folders under `forecast_runs/`. Nothing found needing migration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pseudo-count m = 50 is acceptable as the default (data favour larger m; difference below CI width) | Baselines | Low: tiny Brier effect; user may prefer another m |
| A2 | `xhi_anom_lag0` (max heat index) is the intended "lag-0 Heat Index anomaly" | damped_persistence | Low: mhi gives nearly identical Brier |
| A3 | Interpret "BSS difference (candidate minus reference)" as reporting both BSS vs reference and dBS = BS_ref - BS_cand from the same replicates | CIs | Medium: if the user meant BSS_cand - BSS_ref against a common climatology, add that third quantity (cheap, same engine) |
| A4 | Train diagnostics predictions default to leads 1 and 6 only to bound disk (about 156M rows otherwise) | Stored predictions | Low: CONTEXT says "and train, for diagnostics"; a flag restores all leads |
| A5 | Circular block bootstrap (wrap) is preferred over moving-block | CIs | Low: results identical to 3 digits in measurement |
| A6 | Hash-chain `prev_sha256` in the evaluation log is worthwhile | Test lock | Low: optional hardening |
| A7 | Refusing to overwrite an existing lock with different hashes matches "one test run per config hash" | Test lock | Medium: Phase 14 may need an explicit re-open procedure |

## Open Questions (RESOLVED)

Resolved in `10-CONTEXT.md` under "Resolved after phase research" (2026-10-08).

1. **BSS "difference" definition** (A3). Recommendation: report BSS vs reference and dBS; add BSS_c - BSS_r (against a common climatology) only if the user asks.
2. **Guard behaviour for `build_issue_table`** (raise vs blank test labels). Recommendation: blank labels (NaN / has_label False) for test-target rows when the lock is closed, so Phase 9 callers that only need the feature columns keep working; verify the Phase 9 issue-table tests.
3. **Whether to exclude small wards from headline numbers.** 64% of wards are flagged; recommendation: report all-wards headline plus a large-wards-only row, never drop.
4. **Gate reference for leads 3-6** is trend_season on validation, but the gate only uses leads 1-2 (damped_persistence); record all six per-lead best baselines anyway (Phase 11-14 reuse).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (.venv) | all | yes | 3.12.10 | - |
| scikit-learn / pyarrow / shapely / matplotlib | LR, Parquet, area, optional PNG | yes | 1.9.1 / 21.0.0 / 2.1.2 / 3.10.6 | - |
| git | test lock, run manifest | yes | 2.55.0.windows.3 | none; lock cannot open without git |
| Frozen data | real-data checks/script | yes | `<local_data_dir>/frozen/covariates-v1.0` (data root resolves to `..\..\Heatwave Data`) | tests auto-skip via `@frozen` |
| psutil | - | no | - | not needed |
| Earth Engine | - | not used | - | - |

**Missing dependencies with no fallback:** none. Hardware seen: 12 logical cores.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 (`[tool.pytest.ini_options]` in `pyproject.toml`: `pythonpath=["."]`, markers `frozen`, `slow`) |
| Config file | `pyproject.toml`; shared fixtures in `tests/conftest.py` (auto-skip `frozen`) and `tests/forecast/conftest.py` (session `frozen_panel`, `frozen_static`, `frozen_clim`, `forecast_cfg`) |
| Quick run command | `.venv\Scripts\python.exe -m pytest tests/forecast -m "not frozen and not slow" -x -q` |
| Full suite command | `.venv\Scripts\python.exe -m pytest tests/forecast -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-01 | each baseline returns p in [0,1], no NaN on scored rows, correct row keys == `lead_row_index` | unit (synthetic 2027 panel) | `pytest tests/forecast/test_forecast_baselines.py -m "not frozen and not slow"` | Wave 0 |
| EVAL-01 | recent_climatology unchanged under `poison_future` after origin (k <= 6); climatology/persistence/LR fit uses train rows only (poison validation labels -> identical fit) | unit | same file | Wave 0 |
| EVAL-01 | persistence = hand-computed conditional frequency on a tiny panel; trend aggregated fit equals row-level fit (`allclose`) | unit | same file | Wave 0 |
| EVAL-01 | best baseline per lead = argmin Brier on given predictions; BSS(ref, ref) == 0; persistence lead-1 skill > lead-6 | unit | `test_forecast_metrics.py` / baselines | Wave 0 |
| EVAL-01 | real-data Brier for all five at leads 1 and 6 within tolerance of the table above (e.g., damped lead 1 in [0.123, 0.127]); best baseline lead 1 = damped, lead 6 = trend | `@frozen @slow` | `pytest tests/forecast/test_forecast_baselines_frozen.py` | Wave 0 |
| EVAL-02 | Brier/BSS hand-computed cases; equals `sklearn.brier_score_loss` | unit | `test_forecast_metrics.py` | Wave 0 |
| EVAL-02 | Murphy: exact identity for a 2-valued predictor; residual < 1e-3 for continuous; tie-safe bins; bin means match `calibration_curve(strategy='quantile')` | unit | same | Wave 0 |
| EVAL-02 | AUC only stratified (no pooled field), no accuracy symbol/string in module and report; P/R/F1 carry threshold | unit | same | Wave 0 |
| EVAL-02 | write -> load round trip keeps dtypes, metadata (run_id, config sha, data sha); misaligned rows rejected; harness imports no baseline/model | unit | `test_forecast_predictions.py` | Wave 0 |
| EVAL-03 | resampling unit = weeks/years: signature takes week/year ids; unit count == number of blocks; block < 4 rejected; perfectly spatially correlated synthetic panel -> CI width equals single-site CI | unit | `test_forecast_bootstrap.py` | Wave 0 |
| EVAL-03 | paired: BSS(ref, ref) CI is exactly {0}; fixed seed reproducible; sufficient-statistics replicate equals brute-force row resample at small size | unit | same | Wave 0 |
| EVAL-03 | real-data lead-1 damped-vs-recent BSS CI roughly [0.04, 0.13] with B=200 | `@frozen @slow` | frozen file | Wave 0 |
| EVAL-04 | season masks (W53/Dec boundaries, MAM), region/lat bands match `report` constants, year slice, LGA-average and small-ward flags; slice tables keep n; flagged wards excludable | unit | `test_forecast_slices.py` | Wave 0 |
| EVAL-04 | real small-ward count == 3,086 (frozen geojson) | `@frozen` | frozen file | Wave 0 |
| EVAL-05 | lock closed -> `lead_rows(split="test")` and prediction load raise `TestLockError` and log the attempt | unit (stubbed git) | `test_forecast_testlock.py` | Wave 0 |
| EVAL-05 | lock open (tmp git repo, committed prereg, tmp data root) -> access granted and logged; modified/uncommitted/staged-only prereg, config-hash mismatch, template placeholder, changed config after open -> refused | `@slow` (spawns git) | same file | Wave 0 |
| EVAL-05 | CRLF working copy under `core.autocrlf=true` is "clean"; log is append-only JSONL (hash chain intact; `count_test_runs`) | `@slow` | same | Wave 0 |
| EVAL-05 | Phase 10 acceptance: real `evaluation_log.jsonl` contains zero test runs; no `PREREGISTRATION.md` committed (template only) | script check/`@frozen` read-only | `pytest tests/forecast/test_forecast_testlock.py -k real_log` | Wave 0 |
| EVAL-05 | Phase 9 regression: updated tests (`test_forecast_dataset.py` 103/262, `test_forecast_leakage.py` 197) pass with the `allow_test_rows` fixture | unit | `pytest tests/forecast/test_forecast_dataset.py tests/forecast/test_forecast_leakage.py -m "not frozen and not slow"` | exists, edit |
| Script | `scripts/forecast_baselines.py` end-to-end on a synthetic data root (small B) writes predictions, summary with caption and the locked-test note; refuses to write inside repo/frozen | `@slow` subprocess | `test_forecast_baselines_script.py` | Wave 0 |

### Synthetic vs @frozen
Synthetic (`synthetic_panel(last_week="2027-W10")`, 6 wards) covers all logic; `@frozen` covers only magnitudes (Brier tolerances, small-ward count, CI ranges) and uses the session fixtures. Keep real-data tests few and mark them `slow` too, because a full six-lead fit takes minutes; B=200 in tests, never 1000. The quick loop must stay under about 60 s: avoid real git subprocesses and real-panel loading in it.

### Sampling Rate
- **Per task commit:** the single new test module for the task, `-m "not frozen and not slow"`.
- **Per wave merge:** `pytest tests/forecast -m "not frozen and not slow" -q` plus the edited Phase 9 modules.
- **Phase gate:** `pytest tests/forecast -q` (frozen + slow) green, then `scripts/forecast_baselines.py` run on the real data, then read-only check that the real evaluation log has zero test runs.

### Wave 0 Gaps
- [ ] `tests/forecast/test_forecast_baselines.py`, `..._metrics.py`, `..._bootstrap.py`, `..._slices.py`, `..._predictions.py`, `..._testlock.py`, `..._baselines_frozen.py`, `..._baselines_script.py`
- [ ] `tests/forecast/conftest.py`: autouse tmp default data-root for `testlock`; `allow_test_rows` fixture; tmp git repo helper (set `user.name`/`user.email`, `core.autocrlf` configurable)
- [ ] Config additions (`baselines.shrinkage_pseudo_count`, `evaluation` section) and their config tests
- [ ] Update three existing `lead_rows(..., "test")` call sites
- [ ] No framework install needed

## Security Domain

`security_enforcement` is not set to false in config, so included, scoped to this offline local-file phase.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | - |
| V3 Session Management | no | - |
| V4 Access Control | partial | the test lock is the access control for test rows: committed/clean pre-registration + lock file + audit log |
| V5 Input Validation | yes | validate prediction files (schema, dtypes, p in [0,1], no NaN, split names, lead in cfg.leads, hex shas); config validator for new keys; reject paths outside run folder / inside repo or frozen |
| V6 Cryptography | partial | sha256 via `hashlib` only (blob sha from git, config hash, file hashes); nothing hand-rolled |
| V12 Files | yes | atomic writes (`tmp` + `os.replace`), never write into `frozen/`, run folder names from `RUN_ID_PATTERN` |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Test labels read via an unguarded loader | Information disclosure / Tampering | guard `lead_rows`, `build_issue_table`, prediction loader; log attempts |
| Pre-registration edited after lock opened | Tampering | recompute blob sha on every access, compare with lock |
| Evaluation log edited/truncated | Repudiation | append-only open mode, hash chain, acceptance check reads the log |
| Command injection through git paths | Elevation | `subprocess.run([...])` list form (as `artifacts._git`), fixed relative path constant, `--` separator |
| Writing predictions into frozen/repo | Tampering | reuse the in-repo / frozen-folder refusal pattern from `artifacts.start_run` and `dataset.feature_cache_dir` |
| Malicious Parquet metadata | Tampering | parse metadata as JSON only, validate fields and hex shas; no pickle |

## Sources

### Primary (HIGH confidence)
- Repo code read directly: `heatwave/forecast/{dataset,splits,targets,climatology,static,artifacts,config,features,weeks,data,report,fixtures,registry}.py`, `forecast.yaml`, `tests/forecast/*`, `tests/conftest.py`, `pyproject.toml`, `requirements.txt`, `docs/forecast/DATA_REPORT.md`.
- `.planning/phases/10-.../10-CONTEXT.md`, `.planning/research/PITFALLS.md` (C5-C9, M3, M5), `.planning/research/ARCHITECTURE.md` (Predictor, harness, config).
- Hands-on measurements (this session, real frozen data, read-only): row counts, baseline Briers for six leads, pseudo-count sweep, bootstrap CIs and ACF, Murphy decomposition residuals, small-ward count, Parquet size/speed, LR timings; git lock mechanics in a tmp repo under `core.autocrlf=true`; sklearn 1.9.1 signatures via `inspect`.

### Secondary (MEDIUM confidence)
- Methodological references named from training knowledge and the repo's PITFALLS document, not re-fetched this session: Hamill & Juras 2006 (varying climatology), Politis & Romano 1992 (circular block bootstrap), Brocker 2008 and Ferro & Fricker 2012 (reliability bias), Murphy 1973 (decomposition). [ASSUMED] as citations; the numerical behaviour reported above was verified directly.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH (nothing new; versions read from the environment)
- Architecture: HIGH (dense-array path and sufficient-statistics bootstrap prototyped and timed)
- Baseline numbers: HIGH for this data/config; sensitive to choices flagged in Assumptions (m, xhi vs mhi)
- Test-lock mechanics: HIGH for git behaviour on this machine; MEDIUM for guard placement trade-offs (open question 2)
- Pitfalls: HIGH (most reproduced numerically)

**Research date:** 2026-10-08
**Valid until:** 2026-11-07 (stable; re-check only if the frozen data version, Phase 9 APIs or sklearn pin change)
