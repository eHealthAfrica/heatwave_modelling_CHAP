# Roadmap: Heatwave Modelling (CHAP)

## Overview

The journey starts by fixing four concrete, audit-identified issues in the already-built GCP/Earth Engine foundation (auth, boundary loading, ERA5-Land ingestion) so this branch can safely supersede the earlier ad-hoc PR. From there, the Heat Index math already inline in the Streamlit prototype gets relocated into a tested module, unblocking the pipeline's core new capability: per-ward climatology and heatwave day/event detection. That detection logic feeds a batch export that produces the weekly ward-level covariate table — the actual production deliverable consumed by CHAP. Once the table can be generated end-to-end, the Streamlit app is rewritten to read from it (rather than compute live), the methodology and usage are documented, and an optional polish/CI pass closes out the milestone.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation Rework** - Fix 4 audit-identified issues in the existing GCP/EE auth, boundary, and ingest code before this branch supersedes PR #1 (completed 2026-09-13)
- [x] **Phase 2: Heat Index Relocation** - Move RH/Heat-Index math out of the Streamlit script into a tested module (completed 2026-09-13)
- [x] **Phase 3: Climatology & Heatwave Detection** - Per-ward 90th-percentile climatology and heatwave day/event flagging (core new capability) (completed 2026-09-13)
- [x] **Phase 4: Batch Export & Covariate Table** - Produce the CHAP-facing weekly covariate table for all 4,841 wards (production deliverable) (completed 2026-09-17)
- [ ] **Phase 5: Presentation Layer Rewrite** - Streamlit app reads the precomputed covariate table instead of computing live
- [ ] **Phase 6: Documentation** - Methodology doc and rewritten README
- [ ] **Phase 7: Polish (Optional)** - Config edge-case tests and optional CI

## Phase Details

### Phase 1: Foundation Rework

**Goal**: The existing GCP/EE auth, ward boundary loading, and ERA5-Land ingestion are verified correct and the 4 known issues found by an independent codebase audit are fixed, so the codebase is safe to push and supersede PR #1.
**Depends on**: Nothing (first phase; re-verifies/fixes already-built Phases 0-2 code)
**Requirements**: REWORK-01, REWORK-02, REWORK-03, REWORK-04, REWORK-05, REWORK-06, REWORK-07, REWORK-08
**Success Criteria** (what must be TRUE):

  1. Streamlit app reruns (e.g., a slider interaction) do not trigger repeated Earth Engine re-authentication/re-initialization — `init_ee()` is cached
  2. Relative-humidity computation correctly matches each tmean image to its corresponding dewpoint image by date via a robust method, with no silent fallback to unmatched/null values
  3. `requirements.txt` contains no unused/conflicting EE package (`ee==0.2` removed, `earthengine-api` retained)
  4. `heatwave/auth.py` resolves the local service-account key path and the `blessings` stub reliably regardless of the caller's working directory or import order
  5. `heatwave.auth.init_ee()`, `heatwave.data.boundary.load_ward_boundary()` (4,841 wards), and `heatwave.data.ingest.load_era5_land()` are re-verified against the live `heatwave-508110` project, and `streamlit run nigeria_heat_index.py` boots with HTTP 200 and no stderr

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Path-anchor service-account key file, relocate blessings stub, remove ee==0.2 (REWORK-03, REWORK-04)
- [x] 01-02-PLAN.md — Restructure ERA5-Land ingest to single multi-band collection; fix nigeria_heat_index.py join/caching/import-order (REWORK-01, REWORK-02, REWORK-04, REWORK-06, REWORK-08)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-03-PLAN.md — Live integration test suite covering all 8 REWORK requirements (REWORK-01..08)

### Phase 2: Heat Index Relocation

**Goal**: RH/Heat Index math lives in a tested, reusable module rather than being inline in the Streamlit script.
**Depends on**: Phase 1
**Requirements**: HIDX-01, HIDX-02, HIDX-03
**Success Criteria** (what must be TRUE):

  1. `heatwave/science/heat_index.py` exports the RH and Heat Index computation functions, relocated (not rewritten) from `nigeria_heat_index.py`
  2. `tests/test_heat_index.py` verifies the Rothfusz Heat Index formula against known input/output values
  3. `nigeria_heat_index.py` imports and uses `heatwave.science.heat_index` instead of inline definitions, and still boots cleanly

**Plans**: 2 plans

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Test-first NOAA-table suite, then relocate RH/Heat-Index math into `heatwave/science/heat_index.py` with the D-01 clamp (HIDX-01, HIDX-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — Point `nigeria_heat_index.py` at the science module, delete inline defs, full-suite + AppTest boot regression gate (HIDX-03)

### Phase 3: Climatology & Heatwave Detection

**Goal**: Each ward has a per-ward climatological heatwave threshold, and heatwave days/events are correctly flagged against it — the pipeline's core new scientific capability.
**Depends on**: Phase 2
**Requirements**: CLIM-01, CLIM-02, CLIM-03, CLIM-04, CLIM-05, CLIM-06
**Success Criteria** (what must be TRUE):

  1. For any ward, a 90th-percentile calendar-day climatology baseline is computed from 1991-2020 Heat Index data, with a ±5-day pooling window
  2. Each day in a given date range is correctly flagged as a heatwave day when its Heat Index exceeds the ward's climatological threshold for that calendar day
  3. Consecutive heatwave days are correctly grouped into events, with only runs of ≥3 consecutive days counted as heatwave events
  4. Gridded ERA5-Land Heat Index values are correctly reduced to per-ward daily statistics via zonal reduction
  5. `tests/test_heatwave_detection.py` validates climatology computation and day/event detection against synthetic/known test cases

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Zonal reduction: gridded Heat Index to per-ward-daily FeatureCollection, plus the CLIM-06 test file scaffold (CLIM-05, CLIM-06)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md — Wraparound-safe pooling window and per-ward, per-calendar-day percentile thresholds (CLIM-01, CLIM-02, CLIM-06)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03-PLAN.md — Threshold join, heatwave-day flagging, and consecutive-run event detection (CLIM-03, CLIM-04, CLIM-06)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 03-04-PLAN.md — End-to-end pipeline composition test plus a real ERA5-Land / real ward-asset smoke test (CLIM-01..CLIM-06)

### Phase 4: Batch Export & Covariate Table

**Goal**: The weekly ward-level covariate table can be generated end-to-end for all 4,841 wards and handed off to CHAP — the production deliverable.
**Depends on**: Phase 3
**Requirements**: EXPORT-01, EXPORT-02, EXPORT-03, EXPORT-04
**Success Criteria** (what must be TRUE):

  1. `scripts/run_batch_export.py` runs the full ingest -> heat-index -> climatology -> detection pipeline across all 4,841 wards for a configurable date range
  2. The generated covariate table matches the target schema exactly: `time_period` (ISO week), `location` (ward ID), `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`
  3. Running the pipeline end-to-end for a full sample period produces a complete table (no missing wards, no null aggregates) ready for CHAP handoff
  4. `tests/test_export.py` verifies covariate table schema and aggregation correctness

**Scope note**: the plans below verify the export machinery on small bounded samples inside a 30-second
feedback loop. The real full 1991-present, 4,841-ward backfill is a separate, deliberate, monitored,
hours-long invocation of `scripts/run_batch_export.py` (see 04-VALIDATION.md "Manual-Only
Verifications"); a full-scale `outputs/covariate_table.csv` is explicitly NOT a completion criterion
for this phase.

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 04-01-PLAN.md — Earth Engine async batch-export harness (`heatwave/batch.py`) plus a real live `Export.table.toAsset` round-trip de-risk, and the `tests/test_export.py` scaffold (EXPORT-01, EXPORT-04)
- [x] 04-02-PLAN.md — D-08 small-ward centroid fallback and D-09 provenance flag in `heatwave/zonal.py` (EXPORT-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-03-PLAN.md — `heatwave/export.py`: ISO week-year keying, single-composite-key weekly aggregation, event-start-week counting, exact EXPORT-02 schema (EXPORT-02, EXPORT-03, EXPORT-04)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-04-PLAN.md — `scripts/run_batch_export.py`: validated CLI, ward-batch chunk planner, chunked submit/poll/collect, coverage-gated CSV concatenation, operator checkpoint (EXPORT-01..EXPORT-04)

### Phase 5: Presentation Layer Rewrite

**Goal**: The dev/QA visualization tool reads the precomputed covariate table instead of recomputing Heat Index live for every interaction.
**Depends on**: Phase 4
**Requirements**: APP-01, APP-02, APP-03
**Success Criteria** (what must be TRUE):

  1. `heatwave/app/streamlit_app.py` loads and displays data from the precomputed covariate table rather than live per-date Earth Engine computation
  2. `nigeria_heat_index.py` is retired (removed or replaced) now that its logic lives in `heatwave/science/` and the new app module
  3. The rewritten app boots cleanly (HTTP 200, no stderr) and lets a user browse ward-level heatwave metrics (heatwave days, heat index, event counts) by week

**Plans**: TBD
**UI hint**: yes

### Phase 6: Documentation

**Goal**: The pipeline's methodology and usage are documented well enough for a new contributor (or the user's future self) to understand and run it.
**Depends on**: Phase 5
**Requirements**: DOC-01, DOC-02
**Success Criteria** (what must be TRUE):

  1. `docs/METHODOLOGY.md` documents the heatwave detection methodology (WMO/ETCCDI percentile-exceedance, NOAA/NWS Rothfusz Heat Index) and the covariate table schema
  2. `README.md` accurately describes the current architecture (`heatwave/` package, `scripts/`, `config.yaml`), setup steps, and how to run the batch export and the Streamlit viewer

**Plans**: TBD

### Phase 7: Polish (Optional)

**Goal**: Remaining config edge cases are covered and a CI safety net exists, at the user's discretion — a stretch goal, not required for v1 completion.
**Depends on**: Phase 6
**Requirements**: POLISH-01, POLISH-02
**Success Criteria** (what must be TRUE):

  1. `tests/test_config.py` covers config-loading edge cases (missing keys, malformed YAML)
  2. (Optional) a CI workflow runs the test suite automatically on push

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation Rework | 3/3 | Complete    | 2026-09-13 |
| 2. Heat Index Relocation | 2/2 | Complete    | 2026-09-13 |
| 3. Climatology & Heatwave Detection | 4/4 | Complete    | 2026-09-13 |
| 4. Batch Export & Covariate Table | 4/4 | Complete    | 2026-09-17 |
| 5. Presentation Layer Rewrite | 0/TBD | Not started | - |
| 6. Documentation | 0/TBD | Not started | - |
| 7. Polish (Optional) | 0/TBD | Not started | - |
