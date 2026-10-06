---
phase: 09-features-targets-splits-and-leakage-suite
plan: 07
subsystem: forecast
tags: [report, prevalence, regime-shift, timing]
requires: [09-05]
provides:
  - heatwave.forecast.report (pure builders and markdown)
  - scripts/forecast_data_report.py
  - docs/forecast/DATA_REPORT.md (committed, real frozen data)
key-files:
  created:
    - heatwave/forecast/report.py
    - scripts/forecast_data_report.py
    - tests/forecast/test_forecast_report.py
    - docs/forecast/DATA_REPORT.md
key-decisions:
  - "Splits in the report are by each week's own start date before embargo; row counts use dataset.lead_row_index (embargo + warm-up)"
  - "Real ERA5-Land delay is a recorded constant (MEASURED_DELAYS); no Earth Engine import anywhere"
requirements-completed: [FEAT-06]
duration: ~40 min
completed: 2026-10-07
---

# Phase 9 Plan 07: Pre-model data report Summary

Prevalence of heatwave_week by year, region, era and split, effective-days-ahead and row counts per lead, plus the measured ~9-day ERA5-Land delay as an operational note, generated from the real frozen data and committed.

## Commits
- 0291a21: report.py builders and markdown renderer
- 21e4891: report script, tests, committed docs/forecast/DATA_REPORT.md

## Headline numbers (real data, 4,841 wards, 1991-W02..2026-W38)
- Overall prevalence 11.7% (research 11.66%)
- Split: train 8.4% (1251 weeks), validate 15.4% (314), test 21.5% (298). A regime shift: validation (~15%) and test (~21%) differ from training (~8%); later phases must respect it.
- Era: 1991-2000 6.6%, 2001-2010 11.2%, 2011-2020 11.6%, 2021-2026 21.5%
- Region: NWZ 11.0%, NEZ 11.1%, NCZ 13.0%; far north 10.8%, central 11.4%, middle belt 13.0%
- Effective days ahead at latency 0: +1, +8, +15, +22, +29, +36; at the real ~9-day delay target start is -8, -1, 6, 13, 20, 27 days
- Row counts after embargo and warm-up (1994-W04, 159 origins dropped): lead 1 train 5,213,757 / validate 1,520,074 / test 1,442,618 rows
- Operational note: delay measured ~9 days on 2026-10-06 (latest image 2026-09-27), ~8 days on 2026-10-01; no live Earth Engine query.

Run folder (not committed): C:\Users\adedo.lukmon\Adedo\Heatwave Data\forecast_runs\20261006T231219Z_5d1ae998

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 394 passed, 19 deselected
- `pytest tests/forecast/test_forecast_report.py -q -m frozen`: passed (overall within 10-13%, eras within 1 pp)
- Caption appears twice in the report; effective-days table grep returns 6 rows

## Deviations from Plan
None. (Config field is `expected_parquet_sha256`; the script's sha override uses it.)

## Requirements
FEAT-06 complete. FEAT-02 has remaining parts in plan 09-08; left pending.

## Self-Check: PASSED
