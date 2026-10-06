# Phase 9: Features, Targets, Splits and Leakage Suite - Context

**Gathered:** 2026-10-06
**Status:** Ready for planning
**Source:** Decisions agreed with the user during v2.0 setup (PROJECT.md Key Decisions; research/SUMMARY.md adjustments adopted 2026-10-02; approved ROADMAP phase overview). The orchestrator made the concrete choices marked *(orchestrator)* within those decisions. The user said "proceed to phase 9" (2026-10-06).

<domain>
## Phase Boundary

This phase builds and proves leak-free everything a model will consume, without training any model:

- the `heatwave_week` target for leads 1-6, with timing fields;
- as-of features;
- train-only fitted statistics;
- target-week splits with an embargo, and expanding-window CV folds;
- the leakage test suite;
- a pre-model data report (prevalence and measured ERA5-Land latency).

Requirements: FEAT-01 to FEAT-06. Baselines, metrics and the test lock are Phase 10. Models are Phases 11-12.
</domain>

<decisions>
## Implementation Decisions

### Data source
- Everything is built from the Phase 8 loader (`heatwave.forecast.data.load_panel`) over the frozen `covariates-v1.0`. Never use the live CSV.
- Ward metadata comes from the frozen copy `frozen/covariates-v1.0/inputs/wards.geojson`, hash-checked against the MANIFEST: wardcode, lgacode, statename, geozone and geometry.
- The 6 LGA-average wards come from `frozen/covariates-v1.0/wards_lga_average.csv` and are flagged in the static table.
- Wards with empty geometry take the centroid of their LGA union. This matches the pipeline's LGA-average rule.

### Target and timing (FEAT-01, FEAT-02)
- **Label:** `heatwave_week = 1` when `heatwave_days >= 3` in the target week. Three or more hot days, not necessarily consecutive. It is **not** `heatwave_event_count`. Every doc and report repeats this definition.
- **Alignment:** issue rows are (ward, `last_obs_week` = t). For lead k (1-6), `target_week` = t + k on the integer week index. Rows whose target falls past the end of the data have no label and are excluded from training and evaluation.
- **Timing fields on every row:**
  - `last_obs_week` (index and label);
  - `issue_date` = Sunday of week t + `latency_days`;
  - `target_week` (index and label) and `target_week_start`;
  - `lead_weeks`;
  - `effective_days_ahead` = (`target_week_start` − `issue_date`) in days. Zero or negative means the target week had already started at issue time, i.e. a nowcast. With latency 8, lead 1 gives −2 and lead 2 gives +5.
- **Latency:**
  - Measure the real ERA5-Land `DAILY_AGGR` delay with a live Earth Engine query: the latest available date vs today.
  - Store the measured value in `forecast.yaml` `latency_days`, rounded up to whole days.
  - Record the measurement (date, latest image date, gap) in the data report.
  - The live query is a script, not a CI test. CI uses the configured value.

### Train-only climatology (FEAT-03, FEAT-04)
- A per-ward, per-ISO-week-of-year mean and standard deviation for each weekly variable is fitted **only on training target years (1991-2014)**, pooled over ±2 weeks of the year *(orchestrator)*. W53 pools with W52 and W01.
- The fitted object records its fit range (first and last week index and dates) and the data sha. Anomalies are `(value − mean) / std` with a floor on std.
- The fitted object is reused unchanged for validation, test and operational rows.

### Features (as-of week t; every feature `max_lookahead = 0`) (FEAT-03)
*(orchestrator; the planner may refine names, but must keep the families)*

- **Recent heat:**
  - anomalies of `mean_heat_index` and `max_heat_index`;
  - `heatwave_days`, `hot_nights` and the `heatwave_week` indicator;
  - each at lags 0-3 (lag 0 = week t), plus rolling means over 2, 4 and 8 weeks ending at t.
- **Land and humidity:**
  - soil-moisture anomaly (lag 0, 4-week mean);
  - rainfall anomaly (4- and 8-week sums);
  - relative-humidity anomaly (lag 0, 4-week mean).
- **Season:** sin/cos of the **target** week's week-of-year. The calendar position is known at issue time, so it isn't leakage. Also the lead.
- **Trend and base rate:**
  - trailing 26- and 52-week `heatwave_week` fraction;
  - trailing 10-year same-season (±2 weeks) `heatwave_week` base rate up to t;
  - trailing 3-year mean Heat Index anomaly.
  - **No raw year index.**
- **Spatial context (same week t, across wards):** LGA mean and state mean of the lag-0 HI anomaly and of `heatwave_days`.
- **Static:** ward centroid latitude and longitude, geozone (NWZ/NEZ/NCZ). No ward id. Plus the `lga_average_ward` flag.
- **Memory:** features are built on the dense (ward × week) panel with array shifts (float32). The 6 lead targets are columns on the same issue-row table, so leads don't multiply the rows.

### Splits and CV (FEAT-05)
- Each row is assigned by **target week start**: train < 2014-12-29 ≤ validate < 2021-01-04 ≤ test.
- **Embargo:**
  - Training rows whose target falls within `embargo_weeks` before a held-out cutoff are dropped.
  - Set `embargo_weeks` = max(leads) + longest feature window (8), i.e. **14**.
  - Update `forecast.yaml` *(orchestrator)*; the validator already requires ≥ max(leads).
- **Expanding-window CV folds:** for each fold year Y from 2005 to 2020 *(orchestrator; configurable `cv_first_year`)*, train on targets before Jan 1 of ISO year Y minus the embargo, and validate on targets in ISO year Y. These folds feed out-of-fold calibration in Phase 12.
- **Test rows (2021-2026)** are produced by the split code but must not be loaded for modelling. Enforcing the lock is Phase 10 (EVAL-05). Phase 9 only labels them `split = "test"`.

### Leakage suite (FEAT-04)
It runs on the synthetic panel in CI, plus a `@frozen` real-data variant. It checks:
- **(a) truncation invariance:** features at t are identical when the panel is cut after t;
- **(b) poison the future:** overwriting all weeks > t with garbage leaves features at t unchanged;
- **(c) train-only statistics:** the climatology is unchanged when validation or test values change;
- **(d) registry guard:** every registered feature declares `max_lookahead = 0`, and registering one with a nonzero value fails;
- **(e) mutation check:** a deliberately injected leaky feature (for example a lead-1 shift) is caught by (a) and (b);
- **(f) split integrity:** no target-week overlap between splits, the embargo is respected, and cutoffs fall on Mondays, including around 2020-W53;
- **(g) target alignment:** the label at lead k equals `heatwave_days >= 3` at t+k.

### Pre-model data report (FEAT-06)
- A script writes to a run folder (Phase 8 artifacts) and also writes a committed markdown summary, `docs/forecast/DATA_REPORT.md` *(orchestrator)*. It contains:
  - `heatwave_week` prevalence by year;
  - prevalence by region: geozone, plus latitude bands far north > 11.5°N and middle belt < 9.5°N, matching the METHODOLOGY section 8 analysis;
  - prevalence by era: 1991-2000, 2001-2010, 2011-2020 and 2021-2026;
  - prevalence by split;
  - the measured latency;
  - the effective-days-ahead table per lead.
- It always carries the caption "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT".

### Storage
- An optional feature cache under `<local_data_dir>/forecast_cache/<data_sha8>/<config_hash8>/`, outside the repo, so it can't go stale.
- Nothing large is committed.

### Claude's Discretion
- Module names. The suggested ones are `heatwave/forecast/climatology.py`, `features.py`, `targets.py`, `dataset.py`, `splits.py`, `registry.py` and `scripts/forecast_data_report.py`.
- The feature naming scheme, the std floor value, and the cache format (parquet).
</decisions>

<canonical_refs>
## Canonical References

- `.planning/research/PITFALLS.md` — C1 (target leakage), C2 (latency/nowcast), C3 (label baseline overlap), C4 (split boundaries), M1 (label vs event), M2 (week 53), M7 (trend features)
- `.planning/research/ARCHITECTURE.md` — features as an as-of function, registry, cache, leakage tests T1-T8
- `.planning/research/SUMMARY.md` — Adjustments 2, 3, 4 and 8
- Phase 8 code: `heatwave/forecast/{data,weeks,config,artifacts,fixtures}.py`; summaries `.planning/phases/08-forecast-foundation/08-0*-SUMMARY.md` (public API)
- `docs/METHODOLOGY.md` sections 6 and 8 (label definitions, regional analysis), section 9 (reanalysis caveat)
- `forecast.yaml`
</canonical_refs>

<specifics>
## Specific Ideas
- On 2026-10-01 the latest `DAILY_AGGR` date was 2026-09-23, a delay of about 8 days. Re-measure; don't assume.
- In the 1991-2020 baseline, about 9.8% of days are hot. Weekly `heatwave_week` prevalence will differ, because it needs 3 or more hot days. Report the actual numbers.
</specifics>

<deferred>
## Deferred Ideas
- Baselines, metrics, bootstrap and test lock: Phase 10.
- Single-feature AUC leakage screen: Phase 10, since it needs the metric harness.
- Climate-driver features: Phase 16.
</deferred>

---
*Phase: 09-features-targets-splits-and-leakage-suite*
