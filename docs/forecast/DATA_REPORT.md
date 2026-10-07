# Pre-model data report: heatwave_week (Phase 9)

heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT

## Label definition

`heatwave_week = heatwave_days >= 3`: a ward-week is positive when at least 3 of its 7 days are heatwave days. This is the weekly `heatwave_days` count in the frozen covariate table, not `heatwave_event_count` (the number of distinct events starting in the week).

## Provenance

- Data version: covariates-v1.0
- Parquet sha256: 82583fbf5deedce2ee1a3cee2ad2b12e36c9c2c83ef14e9f6b102a1eb4a7f137
- Run id: 20261007T074855Z_5d1ae998
- Generated (UTC): 2026-10-07T07:57:01Z
- Wards: 4841; weeks 1991-W02 to 2026-W38
- latency_days (forecast.yaml): 0

## Prevalence by split

| split | weeks | ward_weeks | prevalence |
|---|---|---|---|
| train | 1251 | 6056091 | 8.4% |
| validate | 314 | 1520074 | 15.4% |
| test | 298 | 1442618 | 21.5% |
| overall | 1863 | 9018783 | 11.7% |

Regime shift: prevalence is 8.4% in train, 15.4% in validate and 21.5% in test. Validation is not representative of test, and neither matches training; later phases must respect this shift (calibration, thresholds and skill are not transferable between splits without checking). Splits here are by each week's own start date, before embargo.

## Prevalence by era

| era | weeks | ward_weeks | prevalence |
|---|---|---|---|
| 1991-2000 | 521 | 2522161 | 6.6% |
| 2001-2010 | 522 | 2527002 | 11.2% |
| 2011-2020 | 522 | 2527002 | 11.6% |
| 2021-2026 | 298 | 1442618 | 21.5% |

## Prevalence by region

Geozones NWZ / NEZ / NCZ, and latitude bands: far north (> 11.5N), central (9.5-11.5N), middle belt (< 9.5N).

| grouping | group | wards | ward_weeks | prevalence |
|---|---|---|---|---|
| geozone | NWZ | 2004 | 3733452 | 11.0% |
| geozone | NEZ | 1319 | 2457297 | 11.1% |
| geozone | NCZ | 1518 | 2828034 | 13.0% |
| latitude_band | far_north | 2022 | 3766986 | 10.8% |
| latitude_band | central | 1291 | 2405133 | 11.4% |
| latitude_band | middle_belt | 1528 | 2846664 | 13.0% |

## Prevalence by year

| iso_year | weeks | ward_weeks | prevalence | partial |
|---|---|---|---|---|
| 1991 | 51 | 246891 | 7.2% | yes |
| 1992 | 53 | 256573 | 2.8% | no |
| 1993 | 52 | 251732 | 6.7% | no |
| 1994 | 52 | 251732 | 1.4% | no |
| 1995 | 52 | 251732 | 4.4% | no |
| 1996 | 52 | 251732 | 2.7% | no |
| 1997 | 52 | 251732 | 16.1% | no |
| 1998 | 53 | 256573 | 20.4% | no |
| 1999 | 52 | 251732 | 1.3% | no |
| 2000 | 52 | 251732 | 2.9% | no |
| 2001 | 52 | 251732 | 3.2% | no |
| 2002 | 52 | 251732 | 8.5% | no |
| 2003 | 52 | 251732 | 5.1% | no |
| 2004 | 53 | 256573 | 10.8% | no |
| 2005 | 52 | 251732 | 19.8% | no |
| 2006 | 52 | 251732 | 18.2% | no |
| 2007 | 52 | 251732 | 6.0% | no |
| 2008 | 52 | 251732 | 5.3% | no |
| 2009 | 53 | 256573 | 18.1% | no |
| 2010 | 52 | 251732 | 16.7% | no |
| 2011 | 52 | 251732 | 4.4% | no |
| 2012 | 52 | 251732 | 2.0% | no |
| 2013 | 52 | 251732 | 11.6% | no |
| 2014 | 52 | 251732 | 5.2% | no |
| 2015 | 53 | 256573 | 14.0% | no |
| 2016 | 52 | 251732 | 22.3% | no |
| 2017 | 52 | 251732 | 15.8% | no |
| 2018 | 52 | 251732 | 10.5% | no |
| 2019 | 52 | 251732 | 17.0% | no |
| 2020 | 53 | 256573 | 12.8% | no |
| 2021 | 52 | 251732 | 17.7% | no |
| 2022 | 52 | 251732 | 3.4% | no |
| 2023 | 52 | 251732 | 30.2% | no |
| 2024 | 52 | 251732 | 24.1% | no |
| 2025 | 52 | 251732 | 14.6% | no |
| 2026 | 38 | 183958 | 45.4% | yes |

Partial years: 1991 and 2026 are incomplete (marked partial = yes).

## Timing: effective days ahead

Effective days ahead is the number of days from the issue date to the Monday of the target week at latency_days = 0. The operational columns use the real delay of about 9 days.

| lead_weeks | effective_days_ahead | operational_days_to_target_start | operational_days_to_target_end |
|---|---|---|---|
| 1 | 1 | -8 | -2 |
| 2 | 8 | -1 | 5 |
| 3 | 15 | 6 | 12 |
| 4 | 22 | 13 | 19 |
| 5 | 29 | 20 | 26 |
| 6 | 36 | 27 | 33 |

### Operational note: real ERA5-Land delay

The real ERA5-Land delay was measured once by live Earth Engine query on 2026-10-06: the latest DAILY_AGGR image was 2026-09-27, about 9 days behind (about 8 days on 2026-10-01, latest image 2026-09-23). This is informational only and was not re-measured for this report; no live Earth Engine query was made. forecast.yaml sets latency_days = 0, so lead 1 is the next week after the last observed week. In real use lead 1's week is mostly past by the time the data arrive, and lead 2's week ends about 5 days after the issue date.

## Row counts per lead and split

After the 14-week training embargo and the feature warm-up (first usable origin position 159, 1994-W04; 159 earlier origins dropped as warm-up).

| lead_weeks | split | rows | origins |
|---|---|---|---|
| 1 | train | 5213757 | 1077 |
| 1 | validate | 1520074 | 314 |
| 1 | test | 1442618 | 298 |
| 2 | train | 5208916 | 1076 |
| 2 | validate | 1520074 | 314 |
| 2 | test | 1442618 | 298 |
| 3 | train | 5204075 | 1075 |
| 3 | validate | 1520074 | 314 |
| 3 | test | 1442618 | 298 |
| 4 | train | 5199234 | 1074 |
| 4 | validate | 1520074 | 314 |
| 4 | test | 1442618 | 298 |
| 5 | train | 5194393 | 1073 |
| 5 | validate | 1520074 | 314 |
| 5 | test | 1442618 | 298 |
| 6 | train | 5189552 | 1072 |
| 6 | validate | 1520074 | 314 |
| 6 | test | 1442618 | 298 |

## Caveats

- ISO week 53 occurs rarely and its prevalence is very noisy; do not read it on its own.
- The first panel week is 1991-W02 (1991 starts at W02) and the last is 2026-W38, so the first and last years are partial.
- Labels come from ERA5-Land, a reanalysis, not station observations; they describe modelled heat, not measured heat.

heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT

<!-- generated by scripts/forecast_data_report.py -->
