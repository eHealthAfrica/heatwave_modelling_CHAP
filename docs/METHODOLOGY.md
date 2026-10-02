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

Every stage of this Earth Engine pipeline runs server-side (`ee.Image`/`ee.FeatureCollection`
operations). Python only ever requests small, already-aggregated results (a chunk's
finished weekly table, a task's status), never the gridded daily rasters or
the per-ward daily rows themselves.

**The full 1991-present table is produced by the local pipeline instead** (section 8; station validation in section 9),
because the Earth Engine backfill hits a ~12-hour per-task timeout (section 7). Sections
2-6 describe the method both pipelines share. Where the local pipeline differs, section 8
says so: it computes the Heat Index from daily *maximum* temperature and adds hot nights.

## 2. Heat Index (NOAA/NWS algorithm)

Source: `heatwave/science/heat_index.py`.

The Heat Index ("apparent temperature") combines air temperature and
humidity into a single felt-temperature value. This pipeline follows the
full NOAA/National Weather Service procedure
(wpc.ncep.noaa.gov/html/heatindex_equation.shtml), in degrees Fahrenheit:

1. Compute Steadman's simple formula
   `HI = 0.5 * (T + 61 + (T - 68) * 1.2 + R * 0.094)`.
2. If the average of that result and `T` is below 80°F, it is the Heat Index.
3. Otherwise use the Rothfusz regression below, then subtract
   `(13 - R)/4 * sqrt((17 - |T - 95|)/17)` when `R < 13` and 80 ≤ `T` ≤ 112,
   or add `(R - 85)/10 * (87 - T)/5` when `R > 85` and 80 ≤ `T` ≤ 87.

The Rothfusz regression on its own is only valid above roughly 80°F, which
matters here: much of the Harmattan season in northern Nigeria is cooler
than that.

The Rothfusz regression:

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
- **Relative humidity (`R`)** — not a native ERA5-Land band; computed
  from the 2m temperature and 2m dewpoint temperature with the Magnus
  formula, `RH = 100 * e_s(D) / e_s(T)` where
  `e_s(x) = exp(17.625 * x / (243.04 + x))` (Alduchov & Eskridge 1996, `T`
  and `D` in °C), then **clamped to [0, 100]**. The clamp is applied to the
  single-band RH image *before* it is attached to the multi-band composite,
  so it never touches the temperature bands.

  Until 2026-10-02 the pipeline used the linear rule `RH = 100 - 5*(T - D)`.
  That rule is only valid above about 50% RH. In the northern-Nigeria dry
  season, where temperature and dewpoint are often 20-30°C apart, it gave
  0% RH on 63-135 days of 2020 at Abuja, Kano and Maiduguri. Applied to
  ERA5-Land for 2011-2026, the corrected RH and Heat Index leave total
  hot-day counts about the same, but 26-41% of hot days change: days the
  old formula flagged are dropped and others take their place. The biggest
  Heat Index changes (2-4°F higher) are in the hot pre-monsoon months
  (April-June).

Validated in `tests/test_heat_index.py` against NOAA's own published
Heat Index reference table (not a self-derived expectation), and against
a plain-Python version of each branch of the NWS procedure.

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

## 8. Local pipeline (production path for the full table)

Sources: `scripts/download_era5_land_gee.py`, `scripts/run_local_pipeline.py`,
`heatwave/local/`. Added 2026-10-02.

```
ERA5-Land daily files on disk           (scripts/download_era5_land_gee.py)
  -> Heat Index per grid cell per day   (heatwave/local/science.py)
  -> area-weighted ward daily values    (heatwave/local/grid.py)
  -> day-of-year thresholds, hot days,  (heatwave/local/science.py)
     events, hot nights
  -> weekly covariate table             (heatwave/local/pipeline.py)
```

**Data.** `ECMWF/ERA5_LAND/DAILY_AGGR` is downloaded once with Earth Engine's
`computePixels` (one band-year per request, ~30 min for everything) to NetCDF files on the
native 0.1° grid covering 2.5-15.0°E, 4.0-14.0°N. It is the same dataset the Earth Engine
pipeline reads. The download script also fetches soil moisture, wind, pressure,
precipitation and solar radiation, which are not used yet.

**Heat Index from daily maximum temperature.** The Heat Index uses daily *maximum* 2m
temperature with daily mean dewpoint, so it describes the hottest part of the day, when heat
stress peaks. Dewpoint changes little over a day, so the daily mean is a reasonable estimate
of the afternoon value. The formulas are the same as section 2. (The Earth Engine pipeline
still uses daily mean temperature.)

**Ward values.** Each ward's daily value is the mean of the grid cells it overlaps, weighted
by overlap area (square degrees × cos(latitude), i.e. proportional to true area). This
replaces the Earth Engine pipeline's centroid fallback for small wards: a ward smaller than a
cell simply takes that cell's value. The Heat Index is computed per cell, then averaged, as in
section 3. Cells without ERA5-Land data (sea, large lakes) are excluded. A ward that overlaps
only such cells takes the nearest valid cell, and the run logs how many do. **Six wards in
the asset have an empty geometry** (area 0): NASAKW04, PLSBSA20, PLSBKK06, PLSTNK08,
PLSQAP14, BNSVDY02. Each takes the area-weighted average of its whole LGA, where the LGA's
outline is the union of its other wards (10-19 per LGA). They're listed in
`outputs/wards_lga_average.csv`, so their values can be treated as LGA-level rather than
ward-level.

**Thresholds, hot days, events.** Same definitions as sections 4-5: the 90th percentile of
each ward's own values over the 1991-2020 baseline, pooled across a ±5-day window that wraps
the year end, with Feb 29 as its own day of year. A hot day strictly exceeds its threshold,
and 3 or more hot days in a row make an event, counted in the week it starts. Percentiles use
numpy's linear interpolation. Earth Engine's reducer interpolates differently, which makes
little difference with ~330 pooled values per day.

**Hot nights (new column `hot_nights`).** A night is hot when the ward's daily *minimum*
temperature strictly exceeds its own day-of-year threshold, built the same way. This tracks
nights that give no relief from the heat, which is a separate risk factor from daytime heat.

**Extra covariates for CHAP.** Three columns are passed through for disease models. They
don't enter the heatwave definition.

| Column | Meaning |
|---|---|
| `total_precipitation_mm` | weekly total rainfall, mm (ERA5-Land; tiny negative rounding values set to 0) |
| `mean_relative_humidity` | weekly mean of daily RH, %, from daily mean temperature and dewpoint (Magnus) |
| `mean_soil_moisture` | weekly mean top-layer (0-7 cm) volumetric soil water, m³/m³ |

Rainfall comes from ERA5-Land (chosen 2026-10-02) so that every column shares one source.
**Caveat:** against CHIRPS and TerraClimate, ERA5-Land underestimates mean annual rainfall
by about 25-30% in the far north and about 10% in the middle belt. It also shows a
middle-belt drying trend that CHIRPS doesn't (see "Cross-check" below). Year-to-year
variation agrees reasonably well (r = 0.5-0.8). It's fine as a relative covariate, but
should not be used as an absolute rainfall amount or for rainfall trends.

**Weekly table.** One row per (ISO week, ward), with the section 6 columns plus
`hot_nights` and the three covariates above. Only complete 7-day ISO weeks are written, so partial weeks at either end of the
record don't undercount. Every ward has data every day, so there are no nulls.

**Reading trends.** Thresholds are fixed on 1991-2020, so a warming climate shows up as more
hot days and nights in later years. In the first 20 wards, hot days rose from ~14 a year in
1991 to ~138 in 2024. That is the intended behaviour of a fixed baseline, not a bug. Within the
baseline period about 10% of days and nights are flagged, as a 90th percentile implies.

**Regional gradient (checked 2026-10-02).** In 2016-2025, middle-belt wards (latitude
< 9.5°N) average ~79 hot days a year, against ~42 in the far north (> 11.5°N). The cause is
**more warming in the middle belt, not lower day-to-day variability**:

- Across wards, the hot-day rate correlates with recent warming (r = 0.96) far more than
  with variability (r = −0.39).
- Recent Heat Index warming is +1.25°F in the middle belt against +0.33°F in the north.
  Day-to-day variability is similar (3.6°F vs 3.9°F).
- Giving every ward the same warming removes the gap (48 vs 47 days a year). Giving every
  ward the same variability keeps it (62 vs 42).

**Cross-check against independent data (2026-10-02).** These are region means over the same
two regions, 2016-2024 vs 1991-2020. TerraClimate ends in 2024, and the MODIS row compares
2016-2024 with 2001-2015.

| Source | Tmax / LST, north | Tmax / LST, middle | Rain, north | Rain, middle |
|---|---|---|---|---|
| ERA5-Land | +0.03°C | +0.60°C | +8.8% | −8.8% |
| TerraClimate (station-based, CRU) | −0.01°C | +0.36°C | +7.2% | −5.5% |
| CHIRPS (satellite + gauges) | — | — | +9.3% | −0.6% |
| MODIS daytime land surface temperature | −0.49°C | +0.68°C | — | — |

- **Middle-belt warming with a flat far north is confirmed** by every source. ERA5-Land's
  warming is at the high end (TerraClimate shows about 60% of it), so the gap in hot-day
  counts may be somewhat overstated.
- **The far north getting wetter is confirmed** (+7-9% in all three rainfall sources).
- **Middle-belt drying is not confirmed.** CHIRPS, the reference rainfall dataset for the
  region, shows almost no change. Drying therefore can't be stated as the cause of the
  middle-belt warming. Other candidates (land-use change, cloud or aerosol changes) have not
  been examined.
- ERA5-Land also underestimates mean annual rainfall, by about 25-30% in the north (479 mm
  vs 643-674 mm) and about 10% in the middle belt.

## 9. Validation against weather stations

Checked 2026-10-02. **A full validation against station-observed heatwaves is not possible
with open data**, so the table's heatwave indicators are reanalysis-based (ERA5-Land), not
station-confirmed.

**NiMet data is not open.** The NiMet data policy (nimet.gov.ng, *Policy Guidelines on
Access, Use and Sharing of Meteorological Data*) places NGOs and non-profits in the
commercial, fee-paying user category (section 6.1.1). It also forbids passing the data to
third parties without the Director-General's written approval (section 7, clause k). Data
can be bought through nimet.gov.ng/datarequest.

**The open alternative is too sparse.** NOAA's Global Surface Summary of the Day (GSOD) is
free and is built from the synoptic reports that NiMet stations send internationally. It
lists about 20 stations in or near the study area, but none has a usable 1991-2020 record:
the best, Kano, has only 4 of 30 years with 300 or more days of maximum temperature. So
station-based thresholds can't be built on the same baseline as the table. Only Kano (7 of
10), Abuja (6), Minna (5) and Ilorin (3) have mostly complete years in 2016-2025.

**Limited check, 2011-2025.** ERA5-Land daily maximum temperature (nearest grid cell) is
compared with GSOD on the days both have data. "Hot" means above that source's own 90th
percentile for the calendar month, over those common days.

| | Kano | Abuja | Minna | Ilorin |
|---|---|---|---|---|
| Common days | 4,093 | 3,400 | 3,131 | 2,903 |
| Daily Tmax: mean difference (ERA5-Land minus station) / correlation | −0.2°C / 0.89 | −0.1°C / 0.90 | −0.2°C / 0.89 | +0.5°C / 0.82 |
| Weekly mean Tmax anomaly: correlation | 0.86 | 0.79 | 0.80 | 0.62 |
| Weekly count of hot days: correlation | 0.68 | 0.66 | 0.66 | 0.39 |
| Weeks ERA5-Land calls hot (3+ hot days) that the station also calls hot | 37% | 46% | 50% | 24% |

ERA5-Land matches the stations closely on temperature itself and on how unusual each week
is. Agreement on *which* weeks are heatwave weeks is moderate: about half, against about
10% by chance. That is expected when an ~11 km grid cell is compared with a single point,
and Ilorin is the weakest match.

**Implications.** A model trained on this table forecasts ERA5-Land-based heat indicators,
not station-observed heatwaves, and reports should say so. The decisive test of the table's
value is whether it improves CHAP's disease forecasts. If NiMet data is obtained later,
repeat this check with station-based thresholds on the full baseline.

## References

- NOAA/NWS Heat Index algorithm (Steadman simple formula + Rothfusz regression with adjustments) — the standard US National
  Weather Service formula (as also used in the original prototype this
  pipeline supersedes).
- WMO/ETCCDI percentile-exceedance heatwave definition — the standard
  climatological approach (World Meteorological Organization / Expert Team
  on Climate Change Detection and Indices) for defining a location-relative
  heat threshold and consecutive-day heatwave events.
- `ECMWF/ERA5_LAND/DAILY_AGGR` — the ERA5-Land daily-aggregated reanalysis
  dataset, as served through Google Earth Engine.
