# heatwave_modelling_CHAP

A ward-level heatwave-detection pipeline for Nigeria. It ingests ERA5-Land climate data via Google Earth Engine, computes NOAA/NWS Heat Index per ward, detects heatwave days/events using a WMO/ETCCDI percentile-exceedance climatology, and produces a weekly covariate table for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). It does not forecast disease itself — it produces an upstream climate covariate.

## Development Status

This branch (`feature/heatwave-508110-phase-0-3-gsd`) reworks the project's original prototype through a structured plan → execute → verify pipeline, fixing several issues found along the way and adding the core heatwave-detection algorithm. It supersedes an earlier, ad-hoc version of the same Phase 0-2 work ([PR #1](https://github.com/eHealthAfrica/heatwave_modelling_CHAP/pull/1)) and extends it through Phase 3.

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

All three phases are covered by 49 tests that run live against the real Earth Engine project (`heatwave-508110`) — no mocked Earth Engine calls anywhere in the suite.

### What's next (Phases 4-7)

- **Phase 4 — Batch Export & Covariate Table:** run the full pipeline across all 4,841 wards and produce the weekly covariate table CHAP consumes.
- **Phase 5 — Presentation Layer Rewrite:** the Streamlit app reads the precomputed table instead of computing live.
- **Phase 6 — Documentation:** full methodology write-up and a rewritten README covering setup, architecture, and usage end-to-end (this section will be superseded by that pass).
- **Phase 7 — Polish:** optional test/CI hardening.

See `.planning/PROJECT.md` and `.planning/ROADMAP.md` for full project context and phase-by-phase detail.
