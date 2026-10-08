# Milestones

## v1.0 Heatwave Detection Pipeline (Shipped: 2026-10-02)

**Phases completed:** 7 phases. Phases 1-4 ran through GSD (13 plans, 30 tasks); phases 5-7 were built directly at the user's request. Archive: `milestones/v1.0-ROADMAP.md`, `milestones/v1.0-REQUIREMENTS.md`, `milestones/v1.0-phases/`.

**Key accomplishments:**

- Earth Engine pipeline: auth, ward boundaries, ERA5-Land ingestion, Heat Index module, per-ward 90th-percentile climatology, heatwave day/event detection, resumable batch export and the weekly covariate table (PRs #3, #5).
- Streamlit map viewer reading the precomputed table; METHODOLOGY.md and README; config tests and CI (PRs #6, #7).
- Follow-up work before v2.0 (outside GSD, 2026-10-02):
  - Fixed relative humidity (Magnus) and the Heat Index (full NOAA/NWS method). 26-41% of hot days changed (PR #8).
  - The full 1991-2026 backfill timed out in Earth Engine, so the table is now built by a local pipeline from ERA5-Land downloaded through Earth Engine. It takes about 3 minutes for 4,841 wards x 1,863 weeks (PRs #9 and #10).
  - Heat Index from daily maximum temperature; new hot_nights, rainfall, humidity and soil-moisture columns; LGA average for 6 wards without geometry.
  - Cross-check against TerraClimate, CHIRPS and MODIS, and station check against NOAA GSOD. NiMet data isn't open. See METHODOLOGY sections 8-9.
  - Frozen dataset `covariates-v1.0` (git tag; read-only copy and MANIFEST.json under `<local_data_dir>/frozen/`).

---
