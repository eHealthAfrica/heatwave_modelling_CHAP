# heatwave_modelling_CHAP

**[Architecture diagram: Heatwave Detection Pipeline](https://claude.ai/code/artifact/f7dfd3f2-5a88-4f9f-b901-731128f0a801)** -- full walkthrough of credential resolution, ERA5-Land ingestion, Heat Index computation, the live Streamlit app, and the (built-but-unwired) climatology/heatwave-detection library, with every data source itemized.

A ward-level heatwave-detection pipeline for Nigeria. It ingests ERA5-Land climate data via Google Earth Engine, computes NOAA/NWS Heat Index per ward, detects heatwave days/events using a WMO/ETCCDI percentile-exceedance climatology, and produces a weekly covariate table for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). It does not forecast disease itself — it produces an upstream climate covariate.

## Development Status

This branch (`feature/heatwave-508110-phase-0-4-gsd`) reworks the project's original prototype through a structured plan → execute → verify pipeline, fixing several issues found along the way and adding the core heatwave-detection algorithm and its production batch pipeline. It supersedes an earlier, ad-hoc version of the same Phase 0-2 work ([PR #1](https://github.com/eHealthAfrica/heatwave_modelling_CHAP/pull/1)) and extends it through Phase 4.

### What changed from the original prototype

The original prototype (`main` branch) was a single-file Streamlit script (`gee.py` + `nigeria_heat_index.py`) that authenticated to Earth Engine inline, pulled a coarser ERA5 (not ERA5-Land) climate record for Northern Nigeria only, and computed Heat Index live on every map interaction. This rework replaces that with a tested `heatwave/` package and a nationwide, GRID3-based ward boundary (4,841 wards).

### Phase 1 — Foundation Rework

Re-verified and fixed four issues found during an independent audit of the initial rework:
- **Dewpoint/temperature join bug** — the original code matched each day's temperature image to its dewpoint image via a fragile `filterDate().first()` call. Fixed by restructuring ERA5-Land ingestion (`heatwave/data/ingest.py`) into a single multi-band collection, since both bands come from the same source data and are already aligned by day — no join needed at all.
- **Missing caching** — `heatwave/auth.py`'s Earth Engine initialization was re-run on every Streamlit interaction. Caching is now applied at the app layer only (`@st.cache_resource`), keeping the auth module itself reusable by non-Streamlit code (e.g. Phase 4's batch export).
- **Supply-chain issue** — `requirements.txt` pinned an unused package, `ee==0.2`, which turned out to be a namespace-colliding decoy package (not related to `earthengine-api`) and the actual source of a `blessings` import dependency. Removed.
- **Fragile path/import-order handling** — `heatwave/auth.py`'s credential file path and a `geemap` compatibility stub both depended on incidental call-order assumptions. Fixed with an explicit, CWD-independent path and an unconditional package-level stub.
- Added a live, credential-gated integration test suite (`tests/test_integration.py`) that runs against the real GCP project rather than mocks.

### Phase 2 — Heat Index Relocation

Moved the RH/Heat-Index math out of the Streamlit script and into `heatwave/science/heat_index.py`, so it's testable independent of the UI. The relative-humidity calculation is now clamped to a valid `[0, 100]` range (it previously had no bound). Tests validate the Heat Index formula against NOAA's own published reference table, not just internally-derived values.

### Phase 3 — Climatology & Heatwave Detection

The pipeline's core new scientific capability, not present in the original prototype at all:
- `heatwave/zonal.py` — reduces gridded ERA5-Land pixel data down to one Heat Index value per ward per day.
- `heatwave/science/climatology.py` — computes each ward's 90th-percentile Heat Index threshold for each calendar day of the year, from the 1991-2020 baseline, pooling a ±5-day window around each day (including correct handling of the wrap-around at the December/January boundary and Feb 29 in leap years).
- `heatwave/science/heatwave.py` — flags days where a ward's Heat Index exceeds its own climatological threshold, then groups consecutive hot days into heatwave events (3 or more consecutive days).
- Verified on small samples (a handful of test wards); running this across all 4,841 wards for the full 30-year baseline is Phase 4's job.

### Phase 4 — Batch Export & Covariate Table

The production deliverable: `scripts/run_batch_export.py` runs the full pipeline (ingest → Heat Index → climatology → detection → weekly aggregation) across all 4,841 wards and writes the CHAP-facing covariate table.

- **Asynchronous execution.** At this scale, Earth Engine's synchronous computation limits would be exceeded, so the script submits `ee.batch.Export.table` tasks and polls for completion, rather than blocking inline. Each run's progress is tracked in a resumable state file, keyed by a fingerprint of the parameters that built each chunk (so a differently-configured rerun can never silently reuse stale results).
- **Chunked by ward batch.** A live benchmark of the event-detection step suggested the full 35-year run could take on the order of 34-40 hours if attempted as a single computation, so the export is split into ~20 chunks of ~250 wards each, concatenated into one final CSV once every chunk completes.
- **Small-ward fallback.** `heatwave/zonal.py` gained a fallback path for wards too small relative to an ERA5-Land pixel to get a valid area-weighted value — it samples a representative in-polygon point instead, so every ward gets a real value in the final table (73 of the 4,841 real wards use this path), each one flagged for transparency, never silently dropped or defaulted to zero.
- **Human checkpoint before the real backfill.** Before any multi-hour production run, the pipeline surfaces a `--stage plan` preview (ward/chunk/small-ward counts, a quota-and-runtime warning) and a real small-scale smoke export for review — the actual full 1991-present backfill is a deliberate, separate operation the operator triggers when ready, not something that happens automatically.
- Research along the way caught two bugs before they shipped: pairing a calendar year with an ISO week number is wrong at the December/January boundary (needs the "Thursday of the same week" convention instead), and Earth Engine silently returns wrong values if you chain two `.group()` reducer calls instead of grouping by one composite key. A code review after execution found and fixed two critical issues (a task-tracking bug that could leave a failed export chunk permanently stuck as "in progress," and a resumability gap that could silently mix data from differently-configured runs), plus a follow-up regression the fixes themselves introduced (a scale bug that broke the `--stage plan` preview at full scale) — caught during phase verification and fixed before merge.

Phases 1-4 combined are covered by 90 tests that run live against the real Earth Engine project (`heatwave-508110`), plus two additional opt-in tests that submit real Earth Engine batch tasks (kept out of the default fast test loop since they take minutes, not seconds).

**Update — full backfill attempted, not yet completed.** After the checkpoint above was approved, the real 1991-present historical backfill was launched. Two attempts (one at the script's default 250-ward chunk size, one at 25 wards) both ended in Earth Engine's own `"Computation timed out."` after ~12 hours each, despite the 10x difference in ward count — strong evidence that the 35+ year date range, not ward count, drives the cost, which means the current ward-only chunking may hit the same wall at every chunk of the full run, not just the one already tried. A genuine small-scale real sample (5 wards, a 2-month window) completed successfully and is available for Phase 5 development. See `outputs/README.md` for the full account, exact numbers, and suggested next steps (most likely: chunk by date range in addition to ward batch).

### Phase 5 — Presentation Layer Rewrite

Replaced the original live-computing Streamlit script with `heatwave/app/streamlit_app.py`, which reads the precomputed weekly covariate table instead of recomputing Heat Index on every interaction:

- **Map of wards by week.** A ward-boundary map, colored by a selectable metric (heatwave days, mean/max Heat Index, or event count) for a selectable ISO week, plus a sortable data table below it. Wards with no data for the selected week render grey rather than a misleading color.
- **`nigeria_heat_index.py` retired.** Its logic already lived in `heatwave/science/`; the file itself is now removed (APP-02).
- **Development-friendly without a full backfill.** The app points at `outputs/covariate_table.csv` by default (overridable via a `COVARIATE_TABLE_PATH` environment variable), and shows a clear on-screen message rather than crashing if that file doesn't exist yet — relevant since the full historical backfill (see Phase 4 update above) hasn't completed. The small real sample from `outputs/README.md` works as a drop-in stand-in during development.
- Built directly rather than through the full GSD discuss/plan/research/review sequence, per explicit direction to reduce process ceremony at this stage of the project; still fully tested (11 new tests plus a retargeted boot-test, including one live check against the real 4,841-ward boundary asset — 101/101 non-gated tests passing project-wide, no regressions).

### What's next (Phases 6-7)

- **Phase 6 — Documentation:** full methodology write-up and a rewritten README covering setup, architecture, and usage end-to-end (this section will be superseded by that pass).
- **Phase 7 — Polish:** optional test/CI hardening.

See `.planning/PROJECT.md` and `.planning/ROADMAP.md` for full project context and phase-by-phase detail.

