# Phase 9: Features, Targets, Splits and Leakage Suite - Research

**Researched:** 2026-10-06
**Domain:** leakage-safe as-of feature engineering on a dense (ward x ISO-week) numpy panel; target alignment; target-week splits; leakage tests
**Confidence:** HIGH on measured facts and numpy mechanics; MEDIUM on std-floor and base-rate min-history choices (design choices, flagged)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Everything built from `heatwave.forecast.data.load_panel` over frozen `covariates-v1.0`; never the live CSV.
- Ward metadata from frozen `inputs/wards.geojson` (hash-checked against MANIFEST): wardcode, lgacode, statename, geozone, geometry. 6 LGA-average wards from frozen `wards_lga_average.csv`, flagged in the static table. Empty-geometry wards take the centroid of their LGA union.
- Label: `heatwave_week = 1` when `heatwave_days >= 3` in the target week (NOT `heatwave_event_count`); every doc/report repeats this.
- Issue rows are (ward, `last_obs_week` = t). Lead k in 1-6: `target_week` = t + k on the integer week index. Rows whose target is past the end of data have no label and are excluded from training/evaluation.
- Timing fields on every row: `last_obs_week` (index + label); `issue_date` = Sunday of week t + `latency_days`; `target_week` (index + label) and `target_week_start`; `lead_weeks`; `effective_days_ahead` = (`target_week_start` - `issue_date`) in days.
- Latency: measure via live Earth Engine query (latest `DAILY_AGGR` date vs today), store in `forecast.yaml` `latency_days` rounded up to whole days, record (date, latest image date, gap) in the data report. Live query is a script, not a CI test.
- Train-only climatology: per-ward, per-ISO-week-of-year mean and std per weekly variable, fit only on training target years 1991-2014, pooled +-2 weeks; W53 pools with W52 and W01. Fitted object records fit range (first/last week index and dates) and data sha. Anomaly = (value - mean)/std with a std floor. Reused unchanged for validation, test, operational rows.
- Features (as-of t, every feature `max_lookahead = 0`; planner may refine names, must keep families): recent heat (anomalies of mean/max heat index; `heatwave_days`, `hot_nights`, `heatwave_week` indicator; lags 0-3, rolling means 2/4/8 weeks ending at t); land/humidity (soil-moisture anomaly lag0 + 4-wk mean; rainfall anomaly 4-/8-wk sums; RH anomaly lag0 + 4-wk mean); season (sin/cos of TARGET week's week-of-year, plus lead); trend/base rate (trailing 26- and 52-week `heatwave_week` fraction; trailing 10-year same-season +-2 week base rate up to t; trailing 3-year mean HI anomaly; NO raw year index); spatial context (LGA mean and state mean of lag-0 HI anomaly and of `heatwave_days`, same week t); static (centroid lat/lon, geozone NWZ/NEZ/NCZ, no ward id, `lga_average_ward` flag). Dense (ward x week) panel with array shifts, float32; 6 lead targets are columns on the same issue-row table.
- Splits by target week start: train < 2014-12-29 <= validate < 2021-01-04 <= test. Embargo: training rows whose target falls within `embargo_weeks` before a held-out cutoff are dropped; `embargo_weeks` = 6 + 8 = **14** (update forecast.yaml). Expanding-window CV: for fold year Y in 2005..2020 (configurable `cv_first_year`), train on targets before Jan 1 of ISO year Y minus the embargo; validate on targets in ISO year Y. Test rows labelled `split = "test"` only; lock enforcement is Phase 10.
- Leakage suite (synthetic in CI + `@frozen` real-data variant): (a) truncation invariance; (b) poison the future; (c) train-only stats unchanged when val/test change; (d) registry guard `max_lookahead = 0`, nonzero registration fails; (e) mutation check - injected leaky feature caught by (a) and (b); (f) split integrity incl. Mondays and 2020-W53; (g) target alignment.
- Data report: script writes to a Phase 8 run folder and a committed `docs/forecast/DATA_REPORT.md`: prevalence by year, region (geozone; far north > 11.5N; middle belt < 9.5N), era (1991-2000, 2001-2010, 2011-2020, 2021-2026), split; measured latency; effective-days-ahead table per lead; caption "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT".
- Optional feature cache `<local_data_dir>/forecast_cache/<data_sha8>/<config_hash8>/`, outside the repo; nothing large committed.

### Claude's Discretion
Module names (suggested `climatology.py`, `features.py`, `targets.py`, `dataset.py`, `splits.py`, `registry.py`, `scripts/forecast_data_report.py`), the feature naming scheme, the std floor value, cache format (parquet).

### Deferred Ideas (OUT OF SCOPE)
Baselines, metrics, bootstrap, test lock (Phase 10); single-feature AUC leakage screen (Phase 10); climate-driver features (Phase 16).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FEAT-01 | `heatwave_week` target per lead 1-6, aligned to target week | Integer-index alignment `y[:, t+k]`; prevalence measured below |
| FEAT-02 | Timing fields on every row | Formula + a discrepancy in CONTEXT numbers (see Open Question 1); latency measured = 9 days |
| FEAT-03 | As-of features | Vectorised numpy recipes (sliding_window_view, cumsum, anchor gather, reduceat); measured cost |
| FEAT-04 | Leakage suite incl. mutation check | Test design, fast on synthetic panel; registry with `max_lookahead` |
| FEAT-05 | Target-week splits, embargo, expanding CV | Config changes (`cv_first_year`, embargo 14), split function design |
| FEAT-06 | Prevalence by year/region/era + latency | Measured numbers, ward metadata recipe |
</phase_requirements>

## Summary

Everything the phase needs is pure numpy/pandas on the existing dense `Panel` (4841 wards x 1863 weeks x 8 float32, ~288 MB; `load_panel` takes ~19 s on this machine because of the sha256 + parquet parse, so tests must load it once per session). No new dependencies are needed: numpy 2.3.3, pandas 2.3.2, pyarrow 21, shapely 2.1.2 (already in requirements.txt), scipy, scikit-learn, pytest 8.4.1, earthengine-api 1.6.8 are installed. [VERIFIED: pip list in .venv]. geopandas is NOT installed; use json + shapely.

Key measured facts: weekly `heatwave_week` prevalence is 11.66% overall, 6.6% (1991-2000), 11.2% (2001-2010), 11.6% (2011-2020), 21.5% (2021-2026 through W38); by split train 8.4% / validate 15.4% / test 21.5%. There is a strong regime shift, so validation is not representative of test (PITFALLS C6) and the report must say so. The measured ERA5-Land latency today is 9 days (latest `DAILY_AGGR` image 2026-09-27 on 2026-10-06; the 2026-10-01 value in CONTEXT was ~8). The CONTEXT effective-days-ahead examples (-2 / +5 at latency 8) do not match the stated formula (formula gives -7 / 0): the planner must resolve this, because it means lead 2 is also a nowcast/zero-day-ahead at latency >= 8.

**Primary recommendation:** Build one `FeatureStore`: a dict of (wards x weeks) float32 arrays computed by pure functions of the panel prefix, registered in a registry with `max_lookahead=0`; assemble per-lead row tables by integer-index gather; keep every window "trailing, full-window-or-NaN"; prove it with truncation/poison tests on a ~12-year synthetic in-memory Panel (not the parquet fixture).

## Architectural Responsibility Map

Single-tier offline Python batch library (no browser/server tiers).

| Capability | Primary Tier | Secondary | Rationale |
|------------|-------------|-----------|-----------|
| Panel load/verify | `forecast/data.py` (exists) | - | Phase 8 |
| Static ward metadata | new `forecast/static.py` | data.py hash helpers | reads frozen `inputs/wards.geojson` + `wards_lga_average.csv`, hash-verified |
| Climatology fit/apply | `forecast/climatology.py` | weeks.py | fit-on-train object with provenance |
| Features / registry | `features.py`, `registry.py` | climatology | pure as-of functions |
| Targets + timing | `targets.py` | config | label and timing fields |
| Splits / CV folds | `splits.py` | config.SplitsConfig | cutoffs from week_start |
| Row assembly / cache | `dataset.py` | artifacts.py | per (lead, split) row selection |
| Data report | `scripts/forecast_data_report.py` | artifacts.run_folder | markdown + run folder |
| Latency probe | same script (or `scripts/measure_latency.py`) | `heatwave/auth.py` | live EE, not CI |

## Standard Stack

### Core (all already installed; no installs)
| Library | Version | Purpose |
|---------|---------|---------|
| numpy | 2.3.3 | dense array features, `sliding_window_view`, `np.add.reduceat`, `cumsum` |
| pandas | 2.3.2 | row tables, report groupbys |
| pyarrow | 21.0.0 | parquet cache |
| shapely | 2.1.2 | centroids, LGA union (`shapely.shape`, `unary_union`) |
| pytest | 8.4.1 | markers: existing `frozen` marker auto-skips |
| earthengine-api | 1.6.8 | latency probe via `heatwave.auth.init_ee()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| numpy dense arrays | pandas rolling on a long 9M-row frame | slower, reorder/merge leakage risk (PITFALLS C1b); rejected |
| geopandas | json + shapely | geopandas not installed and not needed |
| hypothesis | seeded numpy RNG parametrised tests | hypothesis not installed; do not add |

**Installation:** none. Package Legitimacy Audit: no new external packages recommended, so the gate does not apply (slopcheck not run).

## Architecture Patterns

### Data flow
```
frozen parquet --load_panel--> Panel(values n x T x 8, week_index, week_start)
frozen inputs/wards.geojson + wards_lga_average.csv --static.py--> StaticTable(ward arrays)
Panel[train weeks only] --Climatology.fit--> Climatology(mean,std per ward x slot x var; fit range; data sha)
Panel + Climatology + StaticTable --build_feature_store(registry)--> FeatureStore {name: (n,T) float32}, warm-up NaN
FeatureStore + Panel(y) + cfg --dataset.rows(lead k, split)--> issue-row selection (ward idx, t) + features + label y[:, t+k] + timing fields
cfg.splits --splits.assign / cv_folds--> split label by target_week_start, embargo mask, fold masks
all of the above --> leakage tests (synthetic + @frozen), data report
```

### Recommended structure
```
heatwave/forecast/{static,climatology,registry,features,targets,splits,dataset}.py
scripts/forecast_data_report.py
docs/forecast/DATA_REPORT.md        (committed; docs/forecast does not exist yet)
tests/forecast/test_forecast_{climatology,features,targets,splits,leakage,static,report}.py
```

### Pattern 1: Feature = pure function of the prefix, registered
Each feature is `fn(ctx) -> (n, T) float32` where `ctx` exposes only the panel arrays and the fitted climatology; the registry entry holds `name, family, max_lookahead, window, fn`. `register()` raises `ValueError` if `max_lookahead != 0` (and for unknown/duplicate names). Declared lookahead is a promise; tests (a)/(b) are the proof.

### Pattern 2: Trailing windows, full-window-or-NaN
```python
from numpy.lib.stride_tricks import sliding_window_view as swv
def trail_mean(x, w):                      # x (n,T) ; value at t uses x[t-w+1..t]
    out = np.full(x.shape, np.nan, np.float32)
    out[:, w-1:] = swv(x, w, axis=1).mean(axis=-1, dtype=np.float64)
    return out
def lag(x, k):                             # value at t = x[t-k]
    out = np.full(x.shape, np.nan, np.float32); out[:, k:] = x[:, :-k] if k else x; return out
```
Measured: 26- and 52-week rolling of y on the real panel took 2.1 s total. `sliding_window_view` is a view; each output cell depends only on its own window, so truncation/poison invariance is bit-exact. Never use `shift(-k)`, `center=True`, or ffill/interpolate. Use `[:, :-k]` style slicing guarded for k=0.

### Pattern 3: Lead-aligned label by index gather
`label_k[:, t] = y[:, t+k]` for t in `0..T-k-1`; rows with `t+k > T-1` are masked out (`has_label`), never filled. Build via index arrays (`tgt = t + k`), not row shifting; assert in test (g) using an independent pandas/date join on `week_start + 7k days`.

### Pattern 4: Timing fields
With week t start Monday `s_t`, Sunday `S_t = s_t + 6d`, `issue_date = S_t + latency_days`, `target_week_start = s_t + 7k d`, `effective_days_ahead = 7k - 6 - latency_days`. At latency 8: lead1 -7, lead2 0, lead3 +7. At latency 9 (measured): -8, -1, +6, +13, +20, +27. Store dates as `datetime64[D]` and compute days via integer arithmetic. See Open Question 1.

### Pattern 5: Climatology (ISO week slots, +-2 pooling, W53)
- slot = ISO week 1..53. Position `p(w) = w` for w <= 52, `p(53) = 52.5`. Circular distance with period 52: `d = |p_i - p_j|; d = min(d, 52 - d)`. Membership matrix `M[i,j] = d <= 2` (53x53). Result: W53 pools {W51, W52, W53, W01, W02}; W52 pools {W50..W02 incl. W53}; W01 pools {W51, W52, W53, W01, W02, W03}. Matches "W53 pools with W52 and W01".
- Fit (measured working): `S = train week positions`; one-hot `oh (|S|, 53)`; `s1 = x[:, S] @ oh`, `s2 = (x[:, S]**2) @ oh` in float64; `N = oh.sum(0) @ M.T`; `mean = (s1 @ M.T)/N`; `var = (s2 @ M.T)/N - mean**2`. This is a few matrix products per variable (seconds). Minimum pooled N per slot on real train data = 99 (ward-level observations per slot, i.e. >= 99 weeks pooled; fine). For better numerical behaviour compute variance via mean-centred second pass (values ~90 F, float64 is adequate).
- Train range: weeks with `week_start < splits.train_end` (2014-12-29), i.e. index of 2014-W52 inclusive. Record `first_week_index, last_week_index, first/last date, data_sha256, n_weeks, pooling=2, std_floor`.
- Anomalies: `(x - mean[:, slot_t]) / max(std, floor)` via gather `mean[:, slot_of_week]` (n,T).
- Std floor (measured sd distributions on train): heat index sd min 0.85 (units are degrees F-scale, mean ~92); RH sd min 1.08; precipitation sd 0.002 in dry slots (20.6% of cells < 5% of median sd 8.0 mm) and soil moisture sd 0.0 in 8.9% of cells (median 0.0235). Recommended: `floor_v = 0.1 * median over (ward,slot) of sd_v` (precip ~0.8 mm, soil ~0.0024), documented constant `STD_FLOOR_FRAC = 0.1`. [ASSUMED] value; note that dry-season anomalies for precipitation can still be large; optionally clip anomalies to +-10 only in the model stage, not here.
- Per-fold climatology: PITFALLS C3 says refit per CV fold; CONTEXT locks one fit on 1991-2014 reused for everything. CV fold validation years 2005-2014 therefore lie inside the climatology fit window (predictor-only information, no label involved). Recommend: implement `Climatology.fit(panel, end_week_exclusive)` so a per-fold fit is possible, use the single 1991-2014 fit in Phase 9, and document it as a known mild optimism in the CV folds. [flagged, Open Question 3]

### Pattern 6: Trailing 10-year same-season base rate (no leakage)
For each t: for j = 1..10 and d in -2..+2, take the week with ISO (year(t)-j, min(isoweek(t), weeks_in_year(year(t)-j))) shifted by d weeks; gather `y[:, anchor_j + d]` where index >= 0; accumulate sum and per-t count. All anchors are >= ~50 weeks before t (+2 max), so they are in the past by construction. Divide by count; NaN where count < `min_obs`. Vectorise by building `anchor_j (T,)` with date arithmetic on the week_start array (not a Python loop per t: my first prototype used a per-t Python loop and took 75 s; vectorise with `np.datetime64` year/week arithmetic or precompute a `(year, week) -> index` dict and map arrays once; the 50 gathers themselves are cheap). Measured warm-up: count >= 15 (i.e. >= 3 prior years) from 1994-W04 (index 159); a full 10 years (count 50) only from 2001-W04. Recommend `min_obs = 15` (NaN before 1994-W04) and let the count be implicit; LightGBM handles NaN, logistic needs a train-only imputer in Phase 12.
- Because W53 clipping (use W52 when the earlier year has no W53) and +-2 pooling are inside the function, truncation invariance holds exactly (integer counts in float64 are exact).

### Pattern 7: Spatial same-week context
Sort wards by LGA key (lgacode is not unique across states by itself? verify: use `(statename, lgacode)` composite key; 7023 vs '07023' formatting differs, so keep lgacode as string and key by `lgacode` after checking uniqueness in the static test). `np.add.reduceat(X[order], starts, axis=0)` over the ward axis yields group sums for all weeks at once (float64), divide by counts, scatter back with the inverse index. Same for state. Same-week-t only (no future). Include self in the mean. Cost is a few seconds for 4 arrays on the real panel.

### Pattern 8: Splits and embargo
- Assign each (t, k) row by `target_week_start` using `cfg.splits.split_for_week_start` logic vectorised on the integer week index: cutoff indices `i_train_end = week_start_to_index(train_end)`, `i_validate_end = week_start_to_index(validate_end)` (both are Mondays, validated by config). `split = train if tgt < i_train_end; validate if tgt < i_validate_end; else test`.
- Embargo (rows dropped from the training side): train rows kept only if `tgt < i_train_end - embargo_weeks`; for CV fold Y with start index `i_Y = index of Monday of ISO week 1 of Y`: train if `tgt < i_Y - embargo_weeks`, validate if `i_Y <= tgt < i_{Y+1}`. The validation side itself is not embargoed (matches CONTEXT). The final refit before test (Phase 10/12) uses train+validate with the same embargo against `validate_end`.
- Use ISO-year week-1 Mondays `date.fromisocalendar(Y, 1, 1)`; 2015-W01 starts 2014-12-29 (train_end) and 2021-W01 starts 2021-01-04 (validate_end), both already enforced by `SplitsConfig`. 2020-W53 (2020-12-28..2021-01-03) is validate. The 2026 partial year (through W38) means CV years stop at 2020 anyway.
- With embargo 14: the last train target is index(2014-12-29) - 15; lead-6 origin rows are consumed accordingly.

### Anti-Patterns to Avoid
- Climatology/statistics fit on the whole file; any `groupby().transform` over the full time axis.
- Rolling windows with future weeks (the same-season +-2 pooling must NOT use neighbours t+1, t+2 of the current year; use only prior-year anchors).
- Shifting by row position on a frame that may be unsorted or has week gaps; use integer week index arrays.
- Raw year index or week-of-year integer as a feature (use sin/cos of target week; period 52.1775 or day-of-year of `week_start + 3 days` over 365.25 per M2 guidance). Recommend `doy_mid = (week_start + 3d).dayofyear`, `sin/cos(2*pi*doy_mid/365.25)` of the TARGET week = week t + k (it is a deterministic calendar fact).
- Treating `lead` as the only lead handling: the row table is wide in targets, so models pick a lead column; lead as a feature only when stacked.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trailing window means | loops over weeks | `sliding_window_view` / prefix `cumsum` | exact, fast, prefix-only |
| Group means across wards | per-week python loops | `np.add.reduceat` on group-sorted rows | all weeks at once |
| ISO calendar | string slicing of labels | `weeks.py` index/label helpers + `date.fromisocalendar` | W53 correctness |
| Geometry centroid/union | manual polygon math | shapely `shape(...).centroid`, `unary_union` | MultiPoint-empty handling |
| Provenance | ad-hoc logging | `artifacts.run_folder` / `start_run` | Phase 8 API |
| Hash verification | new hashing | `data.sha256_file`, `read_manifest` | existing, byte-exact |
| EE auth | new auth | `heatwave.auth.init_ee()` | single entry point |

## Runtime State Inventory
Not a rename/migration phase: omitted.

## Static ward metadata (verified hands-on)
- `inputs/wards.geojson`: 19.4 MB, 4841 features, loads with `json.load` in 0.35 s; sha256 equals MANIFEST `inputs_sha256["wards.geojson"]` (key is relative to the frozen dir `inputs/` copy, i.e. `'wards.geojson'`; the frozen copy is `<frozen>/covariates-v1.0/inputs/wards.geojson`). [VERIFIED: ran sha256 compare, True]
- Properties present: `wardcode`, `lgacode` (string, e.g. '27024'; Benue has '7023' without zero pad), `lganame`, `statename`, `statecode`, `geozone` (e.g. 'NCZ'), `urban`, `area`, `status`, others.
- Geometry types: 4748 Polygon, 87 MultiPolygon, **6 MultiPoint with empty coordinates** (area 0, status 'Invalid') = exactly the six LGA-average wards NASAKW04, PLSBSA20, PLSBKK06, PLSTNK08, PLSQAP14, BNSVDY02.
- `wards_lga_average.csv` (columns `location,lgacode`, 6 rows) has outputs_sha256 key `wards_lga_average.csv` in MANIFEST (it is in `outputs_sha256`, not `inputs_sha256`): sha `ff0d81ff...b1d5`. Verify both with `sha256_file` against the MANIFEST before use; raise `FrozenDataError` on mismatch.
- Centroid recipe: for non-empty geometries compute `shape(g).centroid` (lon/lat degrees; centroid in geographic coordinates is adequate for a lat/lon feature). For the 6 empty ones, use centroid of `unary_union` of the other wards in the same `lgacode`; fail loudly if the LGA has no non-empty ward.
- The geojson ward set must equal `Panel.wards` (assert set equality; order to Panel order). Static arrays: `lat, lon (float32)`, `geozone` code (NWZ/NEZ/NCZ and others if present; check actual value set in the real test and one-hot over the observed set), `lga_id`, `state_id`, `lga_average_ward (bool)`.
- Synthetic fixture gap: `build_synthetic_frozen` writes an EMPTY FeatureCollection and no `wards_lga_average.csv`, and the six synthetic ward codes are only 3 pseudo-states. Wave 0 must extend the fixtures (backwards-compatibly, e.g. new optional arg or a new `build_synthetic_static`) with a small geojson (6 wards incl. one empty-geometry MultiPoint, LGA/state/geozone fields) and a matching `wards_lga_average.csv` + MANIFEST hash entries.

## Hands-on measurements (real frozen panel, read-only)

| Item | Result |
|------|--------|
| `load_panel` | 19.4 s; shape (4841, 1863, 8); weeks 1991-W02..2026-W38; W53 weeks present in 1992, 1998, 2004, 2009, 2015, 2020 (2026-W53 does not exist yet) |
| Memory | Panel 288 MB; 40 float32 features (40 x 4841 x 1863) = 1.44 GB; machine has 31.7 GB total but only ~5.9 GB free at test time, so avoid float64 full-size intermediates beyond a few at a time and never hold per-lead copies of all rows |
| 26+52-week rolling of y | 2.1 s |
| 10-year base rate | 50 gathers cheap; the 75 s prototype was dominated by a per-t Python date loop (fix by vectorising anchors) |
| `heatwave_week` prevalence | overall 11.66%; hot-day share (heatwave_days/7) 11.18% |
| By era | 1991-2000: 6.6%; 2001-2010: 11.2%; 2011-2020: 11.6%; 2021-2026(W38): 21.5% |
| By split (target-week start) | train (1251 weeks) 8.4%; validate (314) 15.4%; test (298) 21.5% |
| By year | 1991 .072, 1992 .028, 1993 .067, 1994 .014, 1995 .044, 1996 .027, 1997 .161, 1998 .204, 1999 .013, 2000 .029, 2001 .032, 2002 .085, 2003 .051, 2004 .108, 2005 .198, 2006 .182, 2007 .060, 2008 .053, 2009 .181, 2010 .167, 2011 .044, 2012 .020, 2013 .116, 2014 .052, 2015 .140, 2016 .223, 2017 .158, 2018 .105, 2019 .170, 2020 .128, 2021 .177, 2022 .034, 2023 .302, 2024 .241, 2025 .146, 2026 .454 (partial: W02..W38, 1991 starts W02) |
| `heatwave_days` range | 0-7, integer-valued float32 |
| W53 weeks | prevalence 1992 .65, 1998 .81, 2004 .97, 2009 .00, 2015 .00, 2020 .65 (2020-W01 follows at .99) - W53 weeks are single, spatially coherent late-Dec/early-Jan spells, so W53 prevalence is extremely noisy; do not interpret a W53 row on its own; pooled slot stats stay fine |
| Seasonality | prevalence by ISO week in train ranges ~4-12% in W1-W49, so season features matter; the baseline is not constant |
| Base-rate warm-up | >= 3 prior years from 1994-W04; full 10 years from 2001-W04 |
| Other warm-up | lags 0-3: 3 weeks; 8-wk roll: 7; 26-wk roll: 25; 52-wk roll: first valid 1992-W01 (index 51); 3-year (156-wk) HI-anomaly mean: first valid 1993-W52 (index 155) |
| Heat index units | values ~92 (mean) i.e. Fahrenheit-scale, not Celsius; report units explicitly and do not hard-code Celsius thresholds |

**Warm-up policy (recommend):** keep NaN; do NOT forward-fill. Define `core_valid_from = index 155 (1993-W52)` as the first origin where all fixed-width windows (<=156 wk) are full; base rate is allowed NaN until 1994-W04 (index 159). Add a dataset option `drop_warmup=True` (default for training) that removes origins before `max(core, base_rate_min)` = index 159; the dropped origins are about 3.1 of 24 train years' worth of weeks (159 weeks) and must be counted in the report. Because origins before that are only used as history, they stay in the panel.

## Latency measurement (measured live 2026-10-06)
- Method: `from heatwave.auth import init_ee; init_ee(); ee.ImageCollection("ECMWF/ERA5_LAND/DAILY_AGGR").aggregate_max("system:time_start").getInfo()` -> ms epoch; latest image start = **2026-09-27T00:00Z**; run at 2026-10-06T21:16Z; gap = today - latest image date = **9 days**. `init_ee()` worked with `keys/service_account.json` (no extra setup). [VERIFIED: ran query]
- CONTEXT said ~8 days on 2026-10-01 (latest 2026-09-23); the value moves by about a day between measurements. Recommend: the script records `{measured_utc, latest_image_date, gap_days}` and sets `latency_days = ceil(gap_days)` = **9**; consider recording a 2nd measurement on a different day. Do not edit forecast.yaml in research; Phase 9 plan does it. Note the definition: a Sunday's daily image appears ~9 days after that day, so `issue_date = Sunday + 9`.
- Effect: at latency 9 leads 1 and 2 both start before issue (effective days -8 and -1); lead 3 is +6 days. `gate.primary_leads: [2, 3]` includes a nowcast lead; flag for the user (Open Question 1).

## Config changes needed (config.py / forecast.yaml / tests)
- Validator is strict: `_build` rejects unknown AND missing keys in each section; `ForecastConfig.__post_init__` already requires `embargo_weeks >= max(leads)`. So `embargo_weeks: 14` loads without code changes, but tests assert the old values: `tests/forecast/test_forecast_config.py` line 39 (`latency_days == 8`) and line 41 (`embargo_weeks == 6`) must be updated; the parametrised rejection `("splits.embargo_weeks", 5)` stays valid (< 6). `forecast.yaml` is NOT blob-pinned by the untouched-files test (only `config.yaml`, `heatwave/config.py`, `tests/test_config.py` are), so editing it is allowed.
- Add `cv_first_year: int` to `SplitsConfig` (new dataclass field, placed after `embargo_weeks`), add `cv_first_year: 2005` under `splits:` in forecast.yaml, and validate: int (bool rejected), `train_years[0] < cv_first_year <= validate_years[1]`. `config_to_dict` / `config_hash` pick the field up automatically (dataclass fields), which changes the config hash and run ids (no pinned hash values found in tests; verify `test_forecast_config.py` round-trip/snapshot tests still pass). Add rejection cases: missing key, `cv_first_year` = 1991, 2021, True, 2005.5.
- Also consider adding a derived validator: `embargo_weeks >= max(leads) + 8` is a Phase 9 policy, but keep the validator at `>= max(leads)` unless the user wants it enforced; the embargo is tested in the splits tests instead (assert the shipped config satisfies 14).
- `latency_days: 9` in forecast.yaml (after the live measurement).
- `FEATURE_LONGEST_WINDOW_WEEKS` constant: the longest *short* window is 8 (CONTEXT). Note the trend features (52-wk, 10-yr, 3-yr) are longer than 8 weeks; they look back at observations that are feature inputs only (labels in the past, with targets < t), but a training row's trailing base rate includes `y` of earlier weeks whose targets could be < the fold cutoff only - these are all past relative to origin t, so no cross-boundary label leak is introduced by trailing windows at train rows; the embargo of 14 correctly covers max lead + 8. Document this reasoning in `splits.py`.

## Common Pitfalls

### Pitfall 1: lead 2 is a "nowcast" at latency >= 8
**What:** formula `7k - 6 - latency` gives 0 at lead 2 for latency 8. CONTEXT lists -2/+5, which fits neither. **Avoid:** implement the formula, unit-test exact numbers for latency 8 and 9, and report to the user. 
### Pitfall 2: same-season pooling uses next-week neighbours of the current year
The +-2 week pool for the base rate at t must be taken only in prior years; a naive `rolling(centered)` over the same-season slot includes t+1, t+2. Caught by test (a)/(b).
### Pitfall 3: climatology slot of W53 in non-53 years and clipping
Anchor lookup for earlier years lacking W53 must clip to W52 (verified rule); a `KeyError` or a wrap to W01 of the following year misaligns by a week.
### Pitfall 4: cumsum prefix float error across 1863 weeks
Use sliding windows for float quantities; cumsum only for integer-valued 0/1 sums (exact in float64).
### Pitfall 5: 2026 partial year / 1991 starts at W02
By-year prevalence for 1991 and 2026 is partial (and 2026 is late-season only, 45%): label it in the report; era 2021-2026 is only 298 weeks.
### Pitfall 6: label regime shift
Train 8.4% -> validate 15.4% -> test 21.5%: base-rate/trend features tied to trailing windows will lag; this is what the report must show (PITFALLS C6).
### Pitfall 7: memory
Do not materialise (n x T) float64 copies of all features; compute family-by-family, cast to float32, free temporaries. Row tables per (lead, split) should be assembled lazily (train alone is ~6M rows x ~40 x 4 B = ~1 GB).
### Pitfall 8: Ward ordering
Static arrays must be aligned to `Panel.wards` (sorted wardcodes); build via dict lookup, assert equality of sets and no duplicate wardcodes.
### Pitfall 9: lgacode string formats
'7023' vs possible '07023': keep as strings exactly as in the geojson; the CSV reads as int -> read with `dtype=str` and compare after the same normalisation as the geojson; assert the six flagged wards match by wardcode (primary key) and lgacode.

## Code Examples

### Anchor construction (vectorised idea)
```python
# year/iso-week arrays from week_start (np.datetime64[D]); build dict (iso_year, iso_week) -> index once
idx_of = {(y, w): i for i, (y, w) in enumerate(zip(iso_year, iso_week))}
def weeks_in_year(y): return 53 if date(y, 12, 28).isocalendar()[1] == 53 else 52
anchor_j = np.array([idx_of.get((y - j, min(w, weeks_in_year(y - j))), -10**9) for y, w in zip(iso_year, iso_week)])
for d in range(-2, 3):
    idx = anchor_j + d
    ok = (idx >= 0) & (anchor_j > -10**8)
    num[:, ok] += y[:, idx[ok]]; cnt[ok] += 1
```
(One tiny Python loop over T per j is acceptable if the dict is used: ~1863 x 10 dict lookups = ms; the earlier slowness came from `date.fromisocalendar` per element.)

### Group means over wards
```python
order = np.argsort(group_id, kind="stable"); g = group_id[order]
starts = np.r_[0, np.nonzero(np.diff(g))[0] + 1]
sums = np.add.reduceat(X[order].astype(np.float64), starts, axis=0)
means = (sums / np.diff(np.r_[starts, len(g)])[:, None])[np.searchsorted(g[starts], group_id)]
```

### Leakage tests (fast on synthetic)
```python
def test_truncation_invariance(panel, clim):                   # panel: 6 wards x ~600 weeks, in memory
    full = build_feature_store(panel, clim)
    for t in rng.choice(np.arange(core_valid_from, T), 50, replace=False):
        cut = truncate_panel(panel, t)                          # keep weeks <= t (new Panel, same ward order)
        part = build_feature_store(cut, clim)
        for name in full:
            np.testing.assert_array_equal(part[name][:, t], full[name][:, t])   # exact; NaN-aware
def test_poison_future(...):  # values[:, t+1:, :] = rng.normal(1e6,...) or NaN; same assertion
```
Use `np.testing.assert_array_equal` (treats NaN equal) rather than allclose where bit-exactness is expected (it is, by construction); fall back to `assert_allclose(rtol=1e-6, equal_nan=True)` only for spatial group means if reduceat ordering differences appear (they do not, since each column is reduced independently).
Fast variant: truncating once per sampled t costs one feature build on a 6x600 panel, ~ms; 50 origins well under a few seconds. The climatology is passed in fitted once (fit only on train weeks, so truncation after t >= train end does not change it); for origins inside the train window assert separately that truncation changes nothing when the climatology object is frozen.
Mutation test: register a deliberately leaky feature (`lead-1 shift`, `y[:, t+1]`, declared `max_lookahead=0` to bypass the registry guard) in a throw-away registry and assert tests (a) and (b) raise `AssertionError`; a second leaky feature declared with `max_lookahead=1` must fail `register()`.
Train-only stats test (c): fit climatology; multiply/overwrite all weeks >= train_end by garbage; refit -> `np.array_equal` on mean/std and equal recorded fit range/sha fields; and assert `fit_range.last_week_start < train_end`.

## State of the Art
No external method changes; numpy 2.x `sliding_window_view` is stable (added numpy 1.20).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Std floor = 0.1 x median per-variable sd | Pattern 5 | anomaly scale; tunable, needs user nod |
| A2 | Base-rate `min_obs=15` (3 prior years), NaN before 1994-W04 | Pattern 6 | training-row count / warm-up |
| A3 | One climatology (1991-2014) for CV folds, not per-fold refit | Pattern 5 | mild CV optimism on predictor stats |
| A4 | Seasonal encoding via day-of-year of target week mid / 365.25 | Anti-patterns | minor; CONTEXT says "week-of-year" |
| A5 | Geographic-degree centroids acceptable | Static | negligible |
| A6 | latency_days = 9 from a single measurement | Latency | issue_date/effective days shift by 1 |

## Open Questions (RESOLVED)

All questions below are resolved in `09-CONTEXT.md` ("Target and timing" Framing, and "Resolved after phase research", 2026-10-06). In particular, the effective-days-ahead discrepancy is resolved by the user's latency-0 framing and gate leads [1, 2].

1. **Effective-days-ahead numbers conflict with the formula.**
   - Known: CONTEXT states "latency 8: lead 1 -2, lead 2 +5". Stated formula (`target_week_start - issue_date`, issue = Sunday of week t + latency) gives lead1 = -7, lead2 = 0, lead3 = +7 (latency 9: -8, -1, +6). 
   - Unclear: whether CONTEXT intended a different issue_date (e.g. Sunday + latency - 5?) or just miscalculated.
   - Recommendation: implement the stated formula, test the exact values, and surface to the user that lead 2 is zero/negative-days-ahead, so `gate.primary_leads [2,3]` has a nowcast lead (decision for Phase 10 gate).
2. **Latency value:** 9 measured today (was ~8 on 2026-10-01). Take `ceil` of the new measurement (9) as decided; planner should make the script re-runnable and note drift.
3. **Per-fold climatology** (A3): accept the documented mild optimism or pay 16 extra feature builds (anomaly families only).
4. **Warm-up handling:** NaN with `drop_warmup` default; confirm origins before 1994-W04 are excluded from training.
5. **geozone values:** CONTEXT lists NWZ/NEZ/NCZ; only 'NCZ' confirmed in the first record; enumerate real values in the static test (`@frozen`).
6. **Heat-index units:** appear Fahrenheit-scale; confirm against METHODOLOGY before labelling report axes.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | all | yes | 3.12.10 | - |
| numpy/pandas/pyarrow/shapely/scipy/sklearn | features, static | yes | 2.3.3 / 2.3.2 / 21.0.0 / 2.1.2 / 1.18.1 / 1.9.1 | - |
| geopandas | not used | no | - | json + shapely |
| psutil, hypothesis | not used | no | - | tracemalloc / seeded RNG |
| earthengine-api + key | latency probe | yes | 1.6.8; `init_ee()` works | skip, use configured value |
| Frozen data (local_data_dir `../../Heatwave Data`) | @frozen tests | yes | covariates-v1.0 | auto-skipped when absent |
| RAM | real-data build | 31.7 GB total, ~5.9 GB free | - | build per family, float32 |
| `docs/forecast/` dir | DATA_REPORT.md | no (create) | - | script creates |

## Validation Architecture

(`workflow.nyquist_validation` is absent in `.planning/config.json`, so enabled.)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 |
| Config | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["."]`, marker `frozen`); `tests/conftest.py` auto-skips `frozen`-marked tests when the data is absent |
| Quick run | `.venv\Scripts\python.exe -m pytest tests/forecast -q -m "not frozen"` |
| Full suite | `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q` |
| Real-data | `.venv\Scripts\python.exe -m pytest tests/forecast -q -m frozen` (session-scoped `load_panel` ~20 s) |

### Phase Requirements -> Test Map
| Req | Behaviour | Type | Command (file) | Exists |
|-----|-----------|------|----------------|--------|
| FEAT-01 | label_k[:, t] == (heatwave_days[:, t+k] >= 3); tail rows masked; independent date-join check; label != event_count | unit (synthetic) | `pytest tests/forecast/test_forecast_targets.py -q` | Wave 0 |
| FEAT-02 | timing fields: issue_date Sunday+latency, eda formula for latency 8 and 9, year-end/W53 boundaries, `eda = target_start - issue` | unit | same file | Wave 0 |
| FEAT-03 | each family value on a hand-computed tiny panel; anomalies zero-mean on train; W53 pooling membership; base rate excludes current-year weeks; group means; warm-up NaN counts; no raw year/ward id in registry | unit | `test_forecast_features.py`, `test_forecast_climatology.py`, `test_forecast_static.py` | Wave 0 |
| FEAT-04 | tests (a)-(e) on synthetic; (d) registry; (e) mutation; frozen variant of (a)/(b) on ~10 origins of the real panel and on a ward subset | unit + `@frozen` | `test_forecast_leakage.py` | Wave 0 |
| FEAT-05 | (f): non-overlap, embargo 14 respected, Monday cutoffs, 2020-W53 in validate, CV folds 2005-2020: `max(train_tgt) < min(val_tgt) - embargo`, test rows labelled; config `cv_first_year` validation | unit | `test_forecast_splits.py`, `test_forecast_config.py` (updated) | Wave 0 / modify |
| FEAT-06 | report builder returns the five tables from a synthetic panel; caption present; latency block formatted; script run on `@frozen` writes run folder + markdown; live EE probe NOT in CI | unit + `@frozen` | `test_forecast_report.py` | Wave 0 |

### Synthetic vs @frozen split
- Synthetic (CI, seconds): in-memory `Panel` built directly (a helper `synthetic_panel(n_wards=6, first_week="1991-W02", last_week="2003-W20", seed)` in `fixtures.py`, covering 1992/1998 W53 and >10-year history so the base rate and 156-week windows are exercised; random uniform data like the existing fixture is fine since leakage tests are structural) plus the extended static fixture. The existing parquet fixture (1991-W02..1993-W05, 109 weeks) is too short for the 52/156/520-week features; use it only for load-path tests.
- `@frozen` (local): real-panel truncation/poison on ~10 random origins (build features for a 200-ward subset to keep it fast; full build only for one shape/dtype/NaN-pattern test), real static metadata checks (4841 wards, 6 flagged, 6 empty geometries resolved, set equality with Panel.wards), real prevalence numbers sanity (overall within 0.10-0.13), real-data split cutoffs vs weeks (2020-W53 validate; first test week 2021-W01).

### Sampling Rate
- Per task commit: quick command above (target < 60 s).
- Per wave merge: full suite.
- Phase gate: full suite plus `-m frozen` green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `fixtures.py`: `synthetic_panel(...)` and static fixture (geojson with empty-geometry ward + `wards_lga_average.csv` + MANIFEST entries).
- [ ] `config.py` / `forecast.yaml` / `test_forecast_config.py`: `cv_first_year`, `embargo_weeks: 14`, `latency_days` update (after measurement), updated assertions.
- [ ] New test modules listed above; `scripts/forecast_data_report.py` + `docs/forecast/` directory.

## Security Domain

Local offline analysis phase; no auth/session/user input surfaces. ASVS V5 input validation applies to config (`cv_first_year`, geojson parsing) and V6/integrity to hashing: reuse `sha256_file` and refuse on mismatch; never write inside the frozen folder (open "rb" only); do not commit `keys/service_account.json` or print credentials in the latency script; feature cache and run folders live outside the repo.

| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| Tampered ward metadata | Tampering | hash-check geojson + csv against MANIFEST before parse |
| Path traversal in cache dir | Tampering | derive cache path from sha8/config_hash8 only; assert it is inside `local_data_dir` and outside the repo |
| Secret leakage via script output | Info disclosure | log only dates/gap, never credentials |

## Sources

### Primary (HIGH)
- Repo code read: `heatwave/forecast/{data,weeks,config,artifacts,fixtures}.py`, `forecast.yaml`, `tests/conftest.py`, `tests/forecast/test_forecast_config.py`, `heatwave/auth.py`, Phase 8 summaries 03-05.
- `.planning/research/PITFALLS.md` C1-C4, M1, M2, M7.
- Hands-on runs on the real frozen data and live Earth Engine query (2026-10-06).

### Secondary / Tertiary
- None; numpy API usage from experience of stable APIs [ASSUMED for any version-specific behaviour, but exercised in the prototype runs on numpy 2.3.3].

## Metadata
**Confidence:** stack HIGH (installed, exercised); architecture HIGH; pitfalls HIGH; design thresholds (A1, A2) MEDIUM.
**Research date:** 2026-10-06. **Valid until:** ~30 days (latency should be re-measured at execution).
