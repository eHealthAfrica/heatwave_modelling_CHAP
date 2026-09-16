# Requirements: Heatwave Modelling (CHAP)

**Defined:** 2026-09-11
**Core Value:** A correct, complete weekly covariate table can be generated end-to-end from ERA5-Land data for all 4,841 Nigerian wards and handed off to CHAP.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Rework (fix known issues in already-built Phases 0-2 foundation)

- [x] **REWORK-01**: Earth Engine initialization is cached (`st.cache_resource` or equivalent) so Streamlit reruns/interactions do not trigger repeated re-authentication/re-initialization
- [x] **REWORK-02**: Relative-humidity computation matches each tmean image to its corresponding dewpoint image via a robust, verifiable date-matching method (not a fragile per-image `filterDate().first()` call with silent-null risk)
- [x] **REWORK-03**: `requirements.txt` has the unused `ee==0.2` PyPI package removed, keeping only `earthengine-api`
- [x] **REWORK-04**: `heatwave/auth.py` resolves the local service-account key path correctly regardless of the caller's working directory, and the `blessings` stub-out works regardless of import order
- [x] **REWORK-05**: `heatwave.data.boundary.load_ward_boundary()` is re-verified to return all 4,841 ward features with correct properties (`wardname`, `wardcode`, `lganame`, `statename`, `geozone`) against the live `heatwave-508110` project
- [x] **REWORK-06**: `heatwave.data.ingest.load_era5_land()` is re-verified to return correctly date-filtered, boundary-clipped `tmax`/`tmean`/`dewpoint` bands for a sample date range
- [x] **REWORK-07**: `heatwave.config.settings` is verified/tested to load `config.yaml` correctly into the typed `Settings` dataclass
- [x] **REWORK-08**: `streamlit run nigeria_heat_index.py` boots cleanly (HTTP 200, no stderr) using the fixed auth/join logic

### Heat Index Relocation

- [x] **HIDX-01**: RH/Heat-Index computation logic is relocated (not rewritten) from `nigeria_heat_index.py` into `heatwave/science/heat_index.py`
- [x] **HIDX-02**: `tests/test_heat_index.py` verifies the Rothfusz Heat Index formula against known input/output values
- [x] **HIDX-03**: `nigeria_heat_index.py` imports and uses `heatwave.science.heat_index` instead of inline RH/Heat-Index definitions, and still boots cleanly

### Climatology & Heatwave Detection

- [x] **CLIM-01**: Per-ward, per-calendar-day climatology baseline is computed from the 1991-2020 Heat Index record
- [x] **CLIM-02**: The climatology baseline applies a ±5-day pooling window around each calendar day
- [x] **CLIM-03**: Each day in a given date range is flagged as a heatwave day when its Heat Index exceeds the ward's 90th-percentile climatological threshold for that calendar day
- [x] **CLIM-04**: Consecutive heatwave days are grouped into events; only runs of ≥3 consecutive days count as a heatwave event
- [x] **CLIM-05**: Gridded ERA5-Land Heat Index values are correctly reduced to per-ward daily statistics via zonal reduction (`heatwave/zonal.py`)
- [x] **CLIM-06**: `tests/test_heatwave_detection.py` validates climatology computation and day/event detection against synthetic/known test cases

### Batch Export & Covariate Table (production deliverable)

- [x] **EXPORT-01**: `scripts/run_batch_export.py` runs the full ingest → heat-index → climatology → detection pipeline across all 4,841 wards for a configurable date range
- [x] **EXPORT-02**: The generated covariate table matches the target schema exactly: `time_period` (ISO week, e.g. `2020-W23`), `location` (ward ID), `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`
- [x] **EXPORT-03**: Running the pipeline end-to-end for a full sample period produces a complete table (no missing wards, no null aggregates) ready for CHAP handoff
- [x] **EXPORT-04**: `tests/test_export.py` verifies covariate table schema and aggregation correctness

### Presentation Layer Rewrite

- [ ] **APP-01**: `heatwave/app/streamlit_app.py` loads and displays data from the precomputed covariate table rather than computing Heat Index live per selected date
- [ ] **APP-02**: `nigeria_heat_index.py` is retired (removed or replaced) now that its logic lives in `heatwave/science/` and the new app module
- [ ] **APP-03**: The rewritten app boots cleanly (HTTP 200, no stderr) and lets a user browse ward-level heatwave metrics (heatwave days, heat index, event counts) by week

### Documentation

- [ ] **DOC-01**: `docs/METHODOLOGY.md` documents the heatwave detection methodology (WMO/ETCCDI percentile-exceedance, NOAA/NWS Rothfusz Heat Index) and the covariate table schema
- [ ] **DOC-02**: `README.md` is rewritten to accurately describe the current architecture (`heatwave/` package, `scripts/`, `config.yaml`), setup steps, and how to run the batch export and the Streamlit viewer

### Polish (optional, lower priority)

- [ ] **POLISH-01**: `tests/test_config.py` covers config-loading edge cases (missing keys, malformed YAML)
- [ ] **POLISH-02**: (Optional) a CI workflow runs the test suite automatically on push — not required for v1 completion

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Presentation (deferred)

- **DASH-01**: Custom HTML/JS dashboard (Leaflet.js frontend + FastAPI/Flask backend serving Earth Engine tile URLs) as an alternative to Streamlit — assessed feasible in a prior side discussion, not pursued; revisit only if explicitly requested.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Disease forecasting | This pipeline produces an upstream climate covariate only; forecasting happens downstream in CHAP/chap-core |
| Re-deciding cloud infrastructure (GCP project, service account, ward asset, ERA5-Land collection) | Already provisioned and verified live in a prior session; user explicitly excluded these from re-litigation |
| Custom HTML/JS dashboard as primary presentation layer | Feasible but a detour from the roadmap; deferred to v2 (see DASH-01) |
| Mandatory CI/CD | Optional stretch goal only (POLISH-02), not required for v1 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REWORK-01 | Phase 1 | Complete |
| REWORK-02 | Phase 1 | Complete |
| REWORK-03 | Phase 1 | Complete |
| REWORK-04 | Phase 1 | Complete |
| REWORK-05 | Phase 1 | Complete |
| REWORK-06 | Phase 1 | Complete |
| REWORK-07 | Phase 1 | Complete |
| REWORK-08 | Phase 1 | Complete |
| HIDX-01 | Phase 2 | Complete |
| HIDX-02 | Phase 2 | Complete |
| HIDX-03 | Phase 2 | Complete |
| CLIM-01 | Phase 3 | Complete |
| CLIM-02 | Phase 3 | Complete |
| CLIM-03 | Phase 3 | Complete |
| CLIM-04 | Phase 3 | Complete |
| CLIM-05 | Phase 3 | Complete |
| CLIM-06 | Phase 3 | Complete |
| EXPORT-01 | Phase 4 | Complete |
| EXPORT-02 | Phase 4 | Complete |
| EXPORT-03 | Phase 4 | Complete |
| EXPORT-04 | Phase 4 | Complete |
| APP-01 | Phase 5 | Pending |
| APP-02 | Phase 5 | Pending |
| APP-03 | Phase 5 | Pending |
| DOC-01 | Phase 6 | Pending |
| DOC-02 | Phase 6 | Pending |
| POLISH-01 | Phase 7 | Pending |
| POLISH-02 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0 ✓

---
*Requirements defined: 2026-09-11*
*Last updated: 2026-09-11 after initial roadmap creation*
