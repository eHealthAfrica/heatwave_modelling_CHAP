# `outputs/` — what's here and what isn't

Everything in this folder except this file is gitignored (`outputs/*.csv`,
`outputs/.batch_export_tasks*.json`) — nothing here is committed to the repo.
This file exists to explain, to whoever runs the pipeline next, what state
this folder is likely to be in and how to get the real production table.

## The real production table

`scripts/run_batch_export.py` (unmodified, fully tested — see
`.planning/phases/04-batch-export-covariate-table/`) writes the real,
full-history, all-4,841-ward covariate table to `outputs/covariate_table.csv`
when run with no `--max-wards`/date-limiting flags:

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

A small, **real** (not synthetic/fabricated) sample produced by the exact
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
