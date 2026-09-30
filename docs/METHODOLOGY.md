# Methodology

How this pipeline turns raw ERA5-Land climate data into a per-ward, per-week
heatwave covariate table. This is the reference for *what* is computed and
*why*; for *how to run it*, see the root [README.md](../README.md).

## 1. Overview

```
ERA5-Land (ECMWF/ERA5_LAND/DAILY_AGGR)
  -> Heat Index per pixel per day        (heatwave/science/heat_index.py)
  -> per-ward daily Heat Index           (heatwave/zonal.py)
  -> per-ward, per-calendar-day 90th-    (heatwave/science/climatology.py)
     percentile climatology threshold
  -> per-ward daily heatwave-day flag    (heatwave/science/heatwave.py)
     and consecutive-run event detection
  -> weekly covariate table              (heatwave/export.py)
```

Every stage runs server-side inside Earth Engine (`ee.Image`/`ee.FeatureCollection`
operations), not in Python with data pulled client-side — this is what makes
the pipeline viable at the full scale of 4,841 wards x ~35 years of daily
data. Python only ever requests small, already-aggregated results (a chunk's
finished weekly table, a task's status), never the gridded daily rasters or
the per-ward daily rows themselves.

## 2. Heat Index (NOAA/NWS Rothfusz regression)

Source: `heatwave/science/heat_index.py`.

The Heat Index ("apparent temperature") combines air temperature and
humidity into a single felt-temperature value. This pipeline uses the
standard NOAA/National Weather Service Rothfusz regression, in degrees
Fahrenheit:

```
HI = c1 + c2*T + c3*R + c4*T*R + c5*T^2 + c6*R^2 + c7*T^2*R + c8*T*R^2 + c9*T^2*R^2
```

where `T` is air temperature in °F and `R` is relative humidity as a
percentage (0-100), with the standard NOAA coefficients:

| Coefficient | Value |
|---|---|
| c1 | -42.379 |
| c2 | 2.04901523 |
| c3 | 10.14333127 |
| c4 | -0.22475541 |
| c5 | -0.00683783 |
| c6 | -0.05481717 |
| c7 | 0.00122874 |
| c8 | 0.00085282 |
| c9 | -0.00000199 |

Inputs, both derived from ERA5-Land bands:

- **Temperature (`T`)** — `temperature_2m` (mean 2m air temperature), converted
  from Kelvin to Fahrenheit.
- **Relative humidity (`R`)** — not a native ERA5-Land band; approximated
  from the 2m temperature and 2m dewpoint temperature via the standard
  linear approximation `RH = 100 - 5*(T - D)` (both `T` and `D` in °C),
  then **clamped to [0, 100]**. The clamp exists because the raw linear
  approximation can otherwise drift outside a physically valid humidity
  range at extreme temperature/dewpoint spreads; clamping is applied to the
  single-band RH image *before* it is attached to the multi-band composite,
  so it never touches the temperature bands.

Validated in `tests/test_heat_index.py` against NOAA's own published
Heat Index reference table (not a self-derived expectation).

## 3. Zonal reduction: gridded pixels -> per-ward daily values

Source: `heatwave/zonal.py`.

ERA5-Land is a ~11.1km-resolution grid (`ERA5_LAND_NOMINAL_SCALE_M = 11132`,
the collection's own verified nominal pixel scale). Each day's gridded Heat
Index image is reduced to one value per ward via an area-weighted mean
(`ee.Image.reduceRegions` with `ee.Reducer.mean()`), producing one row per
(ward, day): `ward_id`, `value`, `doy` (day-of-year, 1-366),
`system:time_start`.

**Small-ward fallback.** A ward polygon that covers less than roughly 0.4%
of a pixel's area yields no value at all from the area-weighted reducer —
this affects **73 of Nigeria's 4,841 wards** (confirmed against the live
boundary asset). Rather than silently dropping these wards or fabricating a
`0`, the pipeline:

1. Identifies small wards once per run (`find_small_wards`), cross-checked
   against 2-3 well-separated sample dates so one anomalous day can't
   misclassify a ward.
2. Re-samples each small ward at a single representative point guaranteed to
   lie on its own polygon (`_representative_point_in_geometry` — the
   centroid when it falls inside the polygon, otherwise the polygon's own
   first vertex; this matters for concave, multi-part, or hole-containing
   ward shapes) using a non-area-weighted `ee.Reducer.first()`.
3. Flags every such row with `used_fallback_reducer = True`, so the
   provenance of a lower-fidelity sampled value is always visible, never
   silently indistinguishable from a full area-weighted mean.

A `value` that is still null after this (a ward with no fallback applied and
below the area-weight threshold) is preserved as `null`, never coalesced to
`0` — downstream stages treat null as "no data," not "no heatwave."

## 4. Climatology: per-ward, per-calendar-day 90th-percentile threshold

Source: `heatwave/science/climatology.py`. Method: WMO/ETCCDI-style
percentile-exceedance climatology, the standard approach for defining
heatwave thresholds relative to a location's own historical baseline
(rather than a fixed absolute temperature, which would be meaningless
across Nigeria's varied climate zones).

Configured in `config.yaml`, section `climatology`:

| Parameter | Default | Meaning |
|---|---|---|
| `baseline_start_year` / `baseline_end_year` | 1991 / 2020 | The 30-year reference period each ward's threshold is computed from |
| `percentile` | 90 | A day counts as a heatwave day when Heat Index exceeds this percentile of the ward's own baseline distribution for that calendar day |
| `pooling_window_days` | 5 | Each calendar day's threshold pools observations from a ±5-day window around it (11 days total), not just that single date across 30 years, for a large-enough sample |
| `min_consecutive_days` | 3 | Minimum run length of consecutive hot days to count as a heatwave *event* |

For each ward and each day-of-year (1-366, with Feb 29 given its own real
slot rather than merged into Feb 28), the threshold is the 90th percentile
of that ward's Heat Index values across the pooling window, across every
year in the baseline period. The pooling window wraps correctly across the
December/January boundary (day 366 pools with days 1-5, and vice versa).

`ee.Reducer.percentile()`'s interpolation method does not match numpy's
default `'linear'` interpolation (e.g. EE returns 9.5 for the sample
`1..10` at p90, where numpy's default returns 9.1) — this is Earth Engine's
own well-defined behavior, used consistently, not a bug to reconcile against
a numpy reference.

## 5. Heatwave day and event detection

Source: `heatwave/science/heatwave.py`.

1. **Day flagging** (`flag_heatwave_days`): each ward-day row is joined to
   its own ward's, own calendar-day's climatology threshold (an outer join
   keyed on both ward and day-of-year — an inner join would silently drop
   ward-days with no matching threshold and corrupt the event state
   machine below, which requires gapless daily input). A day is flagged hot
   (`is_hot = 1`) when its Heat Index **strictly exceeds** (not
   greater-or-equal) the threshold. A ward-day with no matching threshold
   gets `is_hot = null`, never a default `0`.

2. **Event detection** (`detect_heatwave_events`): consecutive hot days,
   per ward, in date order, are grouped into runs. A run only becomes a
   qualifying **heatwave event** once it reaches `min_consecutive_days` (3)
   consecutive days — a 1- or 2-day hot spell is not a heatwave event under
   this definition, even though its individual days are still counted in
   `heatwave_days`.

## 6. Weekly aggregation: the covariate table

Source: `heatwave/export.py`. Every per-ward-daily row is bucketed into its
**ISO 8601 week** (`YYYY-Www`, e.g. `2020-W23`) and aggregated per
(ward, week):

| Column | Type | Meaning | Null vs. zero |
|---|---|---|---|
| `time_period` | string | ISO week, `YYYY-Www` | — |
| `location` | string | ward ID (`wardcode`) | — |
| `heatwave_days` | int | count of hot days (`is_hot = 1`) that week | **0** when no hot days occurred — a real, meaningful zero |
| `mean_heat_index` | float | mean Heat Index across the week's usable data | **null** when no usable data exists for that ward-week — never a fabricated 0 |
| `max_heat_index` | float | max Heat Index across the week's usable data | **null**, same rule as mean |
| `heatwave_event_count` | int | count of qualifying events **starting** in that week | **0** when no event started that week |

Two deliberately opposite null-handling rules meet in this table: a week
with no hot days is a genuine `0` for `heatwave_days`, but a week with no
usable temperature data at all is `null` for `mean_heat_index`/
`max_heat_index` — collapsing these two different situations into the same
value would make "no data" indistinguishable from "confirmed mild week,"
which would silently corrupt any downstream model trained on this table.

An event is counted only in its **starting** week — a 5-day heatwave that
begins on a week's last day and continues into the next week counts once,
in the starting week, and zero times in the week it merely continues into.

**ISO week-year note:** `time_period`'s year component follows the ISO
week-year convention, not the plain calendar year — e.g. December 30, 2024
(a Monday) belongs to ISO week `2025-W01`. Naively pairing Earth Engine's
`ee.Date.get('year')` (a calendar year) with its week number would silently
mis-bucket every year's December/January boundary; `heatwave/export.py`
uses the "Thursday of the same ISO week" trick to get the year component
right, verified against Python's `date.isocalendar()` across boundary-year
edge cases.

### Every distinct (ward, week) gets exactly one row

`aggregate_weekly_metrics` builds its output from the canonical set of every
(ward, week) pair actually present in the input, not just from whatever a
reducer happens to return — so a ward-week is never silently dropped from
the table, even when it has no usable data at all (in which case its metric
columns are null and `heatwave_days`/`heatwave_event_count` are `0`).

## 7. Production execution model

Source: `scripts/run_batch_export.py`. See the root README's "Running the
batch export" section for exact commands. In brief:

- The full pipeline (sections 2-6 above) cannot run as a single synchronous
  Earth Engine computation at full scale (4,841 wards x ~35 years) — it
  would exceed Earth Engine's synchronous computation limits. The script
  instead submits **asynchronous Earth Engine batch export tasks**
  (`ee.batch.Export.table.toAsset`), one per **ward-batch chunk** (~250
  wards each by default, ~20 chunks for the full ward set), polls each to
  completion, then concatenates every chunk's result into one final CSV.
- Each chunk's task state is tracked in a resumable state file, keyed by a
  fingerprint of the exact parameters (ward ids, date range, small-ward
  set) it was built from — so a differently-configured re-run can never
  silently reuse a stale, mismatched result.
- **Known limitation (found 2026-09-21/22, not yet resolved in code):**
  Earth Engine enforces its own per-task wall-clock timeout of roughly 12
  hours. Two real single-chunk attempts across the full historical date
  range (1990-12-31 to 2026-09-14) — one at 250 wards, one at 25 — both hit
  this timeout, at nearly identical elapsed time despite the 10x difference
  in ward count. This is strong evidence that the **date range**, not ward
  count, drives per-task cost (most likely the day-of-year climatology
  computation walking the full multi-decade image collection largely
  independent of how many wards are in the batch), meaning the current
  ward-only chunking strategy may hit the same wall at every chunk of a
  full production run, not just the ones already tried. See
  `outputs/README.md` for the full account, exact task IDs, and EECU-hour
  usage. Before attempting the full backfill again: add date-range
  chunking alongside the existing ward-batch chunking, or confirm with
  GCP/Earth Engine support whether this project's tier allows a longer
  per-task timeout.

## References

- NOAA/NWS Rothfusz Heat Index regression — the standard US National
  Weather Service formula (as also used in the original prototype this
  pipeline supersedes).
- WMO/ETCCDI percentile-exceedance heatwave definition — the standard
  climatological approach (World Meteorological Organization / Expert Team
  on Climate Change Detection and Indices) for defining a location-relative
  heat threshold and consecutive-day heatwave events.
- `ECMWF/ERA5_LAND/DAILY_AGGR` — the ERA5-Land daily-aggregated reanalysis
  dataset, as served through Google Earth Engine.
