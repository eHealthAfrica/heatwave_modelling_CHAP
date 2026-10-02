# `outputs/` — what's here and what isn't

Everything in this folder except this file is gitignored (`outputs/*.csv`,
`outputs/.batch_export_tasks*.json`) — nothing here is committed to the repo.
This file exists to explain, to whoever runs the pipeline next, what state
this folder is likely to be in and how to get the real production table.

## `covariate_table.csv` — the real production table

Built by the local pipeline (`python scripts/run_local_pipeline.py`, ~2-3 minutes once the
ERA5-Land files are downloaded; see the root README). First built 2026-10-02:

- 4,841 wards x 1,863 complete ISO weeks (1991-W02 to 2026-W38), 9,018,783 rows, ~520 MB.
- Columns: `time_period, location, heatwave_days, mean_heat_index, max_heat_index,
  heatwave_event_count, hot_nights, total_precipitation_mm, mean_relative_humidity,
  mean_soil_moisture`. No nulls. ERA5-Land rainfall runs ~25-30% low in the far north
  (see `docs/METHODOLOGY.md` section 8).
- Heat Index from daily **maximum** temperature (see `docs/METHODOLOGY.md` section 8).
- Six wards have empty geometry in the asset. They use their LGA's area-weighted average
  and are listed in `wards_lga_average.csv`.

`covariate_table_local_SAMPLE.csv` is the same pipeline on the first 20 wards.

## The Earth Engine batch export (times out on the full record)

`scripts/run_batch_export.py` (fully tested — see
`.planning/phases/04-batch-export-covariate-table/`) was designed to write the
full-history covariate table when run with no `--max-wards`/date-limiting flags:

```
python scripts/run_batch_export.py
```

**As of this writing, that command has not successfully completed.** Two
attempts (2026-09-21/22) to submit even a single ward-batch chunk across the
full historical range (1990-12-31 → 2026-09-14) both ended in Earth Engine's
own `FAILED: "Computation timed out."` after ~12 hours each — one at the
script's default 250-ward batch size (37.7 EECU-hours used), one at 25 wards
(21.3 EECU-hours used). Both hit the *same* ~12-hour wall despite the 10x
difference in ward count, which points at the **35+ year date range**, not
ward count, as the actual driver of the cost — most likely
`heatwave/science/climatology.py`'s day-of-year percentile computation
walking the full multi-decade image collection largely independent of how
many wards are in the batch.

**Before retrying the full backfill:** `plan_ward_chunks` (in
`scripts/run_batch_export.py`) currently only chunks by ward, never by date
range — every one of the 20 planned chunks still spans the full 35-year
range, so the production run as currently designed may hit this same
per-task timeout at every chunk, not just the one already tried. Consider
adding date-range chunking alongside the existing ward-batch chunking (e.g.
one task per ward-batch × per few years, concatenated across both
dimensions) before resubmitting, or confirm with GCP whether this project's
Earth Engine tier allows a longer per-task timeout.

The two failed tasks' IDs and full status are recorded in
`outputs/.batch_export_tasks.json` (local only) for reference; the script's
resumability logic will not blindly reuse them (they're recorded as
`FAILED`, not a resumable state).

## `covariate_table_SAMPLE.csv`

Made with the Earth Engine pipeline *before* the 2026-10-02 humidity/Heat Index fix, so its
values are out of date. A small, **real** (not synthetic/fabricated) sample produced by the exact
same unmodified script at a trivial scale — 5 wards, a 2-month window
(2020-01-01 to 2020-03-01) — to prove the pipeline still works end-to-end
without spending hours of compute:

```
python scripts/run_batch_export.py --stage all \
  --start-date 2020-01-01 --end-date 2020-03-01 \
  --max-wards 5 --ward-batch-size 5 \
  --output outputs/covariate_table_SAMPLE.csv \
  --state-file outputs/.batch_export_tasks_sample.json
```

It has the exact `COVARIATE_COLUMNS` schema
(`time_period,location,heatwave_days,mean_heat_index,max_heat_index,heatwave_event_count`)
that the real table will have, so it's useful for developing/testing
Phase 5's Streamlit viewer against a realistic file — **it is not the
production table and covers only 5 of 4,841 wards over 2 of ~1,880 weeks.**
Do not hand this to CHAP as the real deliverable.
