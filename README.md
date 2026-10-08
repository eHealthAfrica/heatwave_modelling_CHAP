# heatwave_modelling_CHAP

**[Architecture diagram: Heatwave Detection Pipeline](https://claude.ai/code/artifact/f7dfd3f2-5a88-4f9f-b901-731128f0a801)** — an earlier walkthrough of credential resolution, ERA5-Land ingestion, and Heat Index computation; predates the climatology/heatwave-detection and batch-export work described below.

A ward-level heatwave-detection pipeline for Nigeria. It ingests ERA5-Land climate data via Google Earth Engine, computes NOAA/NWS Heat Index per ward, detects heatwave days/events using a WMO/ETCCDI percentile-exceedance climatology, and produces a weekly covariate table for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). It does not forecast disease itself — it produces an upstream climate covariate.

For how the science works — the Heat Index formula, the climatology definition, the covariate table schema — see **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)**. This file covers architecture, setup, and how to run things.

## Architecture

```
heatwave/
  auth.py              Earth Engine authentication (3 credential sources, see Setup)
  config.py             Typed settings loaded from config.yaml
  zonal.py               Gridded ERA5-Land pixels -> per-ward daily values (incl. small-ward fallback)
  batch.py               Async Earth Engine batch-export harness (submit/poll/resume)
  export.py              Per-ward-daily rows -> weekly covariate table
  data/
    boundary.py           Loads the 4,841-ward boundary asset
    ingest.py              Loads/filters the ERA5-Land image collection
  science/
    heat_index.py          RH (Magnus) + Heat Index (NOAA/NWS algorithm)
    climatology.py          Per-ward, per-calendar-day 90th-percentile thresholds
    heatwave.py              Heatwave day flagging + consecutive-event detection
  local/
    science.py             Numpy RH, Heat Index, day-of-year thresholds, events
    grid.py                 Ward boundaries on disk + area weights from grid cells to wards
    pipeline.py              Ward daily series -> weekly covariate table (incl. hot nights)
  app/
    streamlit_app.py        Presentation layer: ward map by week/metric

scripts/
  download_era5_land_gee.py   Downloads ERA5-Land daily files for the local pipeline
  run_local_pipeline.py       Production entry point: full table -> outputs/covariate_table.csv
  run_batch_export.py         Earth Engine batch pipeline (times out on the full record)

config.yaml             Non-secret pipeline configuration (GCP project, climatology params, etc.)
keys/service_account.json   Local GCP credential (gitignored, never committed)
outputs/                Generated tables and reports (gitignored except outputs/README.md)
docs/METHODOLOGY.md      Detection methodology and covariate table schema
tests/                   pytest suite (see Testing)
```

Data flows one direction: `data/` ingests raw ERA5-Land → `science/` computes Heat Index and detects heatwave days/events → `zonal.py`/`export.py` aggregate to the ward/week grain → `scripts/run_batch_export.py` orchestrates all of it at production scale and writes the CSV → `app/streamlit_app.py` only ever reads that finished CSV; it never recomputes anything live.

## Setup

**Requirements:** Python >=3.12, a GCP project registered for Earth Engine, and a service account with Earth Engine access.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

**Credentials.** `heatwave/auth.py` resolves Earth Engine credentials in this order, first match wins:

1. Streamlit secrets (`st.secrets["earthengine"]`) — for a deployed Streamlit app.
2. `EE_SA_JSON` environment variable (the service account key as a JSON string) — for CI or headless environments.
3. A local key file at `keys/service_account.json` — for local development. **Never commit this file**; it's gitignored, and its contents must never be pasted into a chat, issue, or commit message.

The GCP project, ward boundary asset, and ERA5-Land collection/bands are fixed in `config.yaml` (already provisioned; not something you need to set up yourself — see `.planning/PROJECT.md`'s Constraints section if you need the specifics).

**Verify the setup:**

```
python -m heatwave.auth
```

prints `Earth Engine ready: True` on success.

## Running the tests

```
pytest
```

The suite runs live against the real Earth Engine project (no mocking) but is fast — small, bounded samples, not production-scale data. A handful of tests are automatically skipped if no credentials are configured (`keys/service_account.json` or `EE_SA_JSON` absent); `tests/test_config.py` and `tests/test_requirements.py` never need credentials at all. As of the last full run: **166 passed, 2 skipped** (the 2 skips are opt-in tests that submit real Earth Engine batch export tasks and take minutes rather than seconds — not part of the default fast loop). Forecast tests (`tests/forecast`) are counted separately.

The v2.0 forecasting work adds scikit-learn 1.9.1, lightgbm 4.7.0 and shap 0.52.0 (all pinned in `requirements.txt`). The `heatwave.forecast` package never imports Earth Engine (enforced by `tests/forecast/test_forecast_isolation.py`). The frozen dataset can be integrity-checked with `python scripts/verify_frozen.py --outputs-only`, and `pytest -m frozen` runs the real-data tests (skipped automatically when the data is absent).

A GitHub Actions workflow (`.github/workflows/tests.yml`) runs this same suite on every push/PR. It reads an optional `EE_SA_JSON` repository secret — configure it to get full live coverage in CI, or leave it unset and the credential-gated tests skip cleanly while the credential-free tests still catch regressions.

## Building the full table locally

This is how `outputs/covariate_table.csv` is produced. It runs the same method on locally
downloaded ERA5-Land files, avoiding the Earth Engine timeout below. It computes the Heat
Index from daily **maximum** temperature and adds `hot_nights`, plus weekly rainfall,
relative humidity and soil moisture as extra covariates for CHAP (see
`docs/METHODOLOGY.md` section 8).

```
python scripts/download_era5_land_gee.py   # once; ~30 min, ~3 GB; re-run to add new days
python scripts/run_local_pipeline.py       # all wards, 1991-present
```

Data goes under `local_data_dir` in `config.yaml` (default `../../Heatwave Data`, or set
`HEATWAVE_DATA_DIR`). The ward boundaries are fetched from Earth Engine once and cached
there as `wards.geojson`. For a quick check, use
`python scripts/run_local_pipeline.py --max-wards 20 --output outputs/covariate_table_local_SAMPLE.csv`.

## Running the batch export

`scripts/run_batch_export.py` is the Earth Engine entry point: it runs the full ingest → Heat Index → climatology → detection → weekly-aggregation pipeline and writes the CHAP-facing covariate table.

**Preview a run without submitting anything** (ward/chunk counts, small-ward count, a quota/runtime warning):

```
python scripts/run_batch_export.py --stage plan
```

**Run the full historical backfill** (all 4,841 wards, the full configured date range — this is a multi-hour operation that consumes real Earth Engine compute quota):

```
python scripts/run_batch_export.py
```

> **Known limitation:** two real attempts at the full backfill (2026-09-21/22) both hit Earth Engine's own ~12-hour per-task timeout — evidence that the multi-decade date range, not ward count, drives the cost, so the current ward-only chunking may hit this same wall at every chunk. See `docs/METHODOLOGY.md` section 7 and `outputs/README.md` for the full account. The full table is now built locally instead (above).

**Run a small, real, fast sample instead** (useful for development — this is exactly how `outputs/covariate_table_SAMPLE.csv` was produced):

```
python scripts/run_batch_export.py --stage all \
  --start-date 2020-01-01 --end-date 2020-03-01 \
  --max-wards 5 --ward-batch-size 5 \
  --output outputs/covariate_table_SAMPLE.csv \
  --state-file outputs/.batch_export_tasks_sample.json
```

The script is resumable: `--stage submit` submits Earth Engine batch tasks and records their state; `--stage collect` polls existing tasks and concatenates finished chunks into the output CSV. Re-running `--stage all` (or `submit` then `collect`) picks up from wherever the recorded task state left off, rather than resubmitting completed work — see `docs/METHODOLOGY.md` section 7 for how this works.

## Running the Streamlit viewer

```
streamlit run heatwave\app\streamlit_app.py
```

By default it reads `outputs/covariate_table.csv`. Point it at a different file (e.g. the sample above, while the real backfill hasn't completed) via an environment variable:

```
$env:COVARIATE_TABLE_PATH = "outputs\covariate_table_SAMPLE.csv"   # PowerShell
streamlit run heatwave\app\streamlit_app.py
```

If launching the script directly (rather than through `streamlit run`) or otherwise seeing `ModuleNotFoundError: No module named 'heatwave'`, make sure the repository root is on `PYTHONPATH`:

```
$env:PYTHONPATH = "<path to this repo>"    # PowerShell
```

The app shows a ward map colored by a selectable metric (heatwave days, mean/max Heat Index, event count, or hot nights when the table has them) for a selectable ISO week, plus a sortable data table. Wards with no data for the selected week render grey rather than a misleading color — this is expected, not a bug, especially against the small sample table.

## Current status

All planned functionality (Phases 1-5) is implemented and tested:

- **Foundation** — Earth Engine auth, ward boundary loading (4,841 wards), ERA5-Land ingestion.
- **Heat Index** — NOAA/NWS algorithm (simple formula below 80°F, Rothfusz regression with adjustments above), with RH from the Magnus formula, in a tested standalone module.
- **Climatology & detection** — per-ward 90th-percentile thresholds, heatwave day/event flagging.
- **Batch export** — the production pipeline that produces the weekly covariate table, with small-ward fallback handling and resumable async execution.
- **Presentation layer** — the Streamlit viewer described above, reading the precomputed table.
- **Local pipeline** — downloads ERA5-Land and builds the full 1991-present table on one machine, with Heat Index from daily maximum temperature, a hot-nights column, and rainfall, humidity and soil-moisture covariates.

- **Polish** — config-loading edge cases (`tests/test_config.py`) and an optional CI workflow (`.github/workflows/tests.yml`) that runs the suite on every push/PR.

**Full table:** `outputs/covariate_table.csv` is built by the local pipeline (see "Building the full table locally"). The Earth Engine batch export still times out on the full record.

All 28 v1 requirements across all 7 phases are complete.

For full phase-by-phase project history, decisions, and rationale, see `.planning/PROJECT.md` and `.planning/ROADMAP.md`.
