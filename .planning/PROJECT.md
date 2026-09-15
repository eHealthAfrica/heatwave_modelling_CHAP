# Heatwave Modelling (CHAP)

## What This Is

A ward-level heatwave-detection pipeline for Nigeria. It ingests ERA5-Land climate data via Google Earth Engine, computes NOAA/NWS Heat Index per ward, detects heatwave days/events using a WMO/ETCCDI percentile-exceedance climatology, and produces a weekly covariate table for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). It does not forecast disease itself — it produces an upstream climate covariate.

## Core Value

A correct, complete weekly covariate table (`time_period`, `location`/ward, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`) can be generated end-to-end from ERA5-Land data for all 4,841 Nigerian wards and handed off to CHAP. The Streamlit app is a dev/QA visualization tool, not the production surface — if it broke entirely, the pipeline would still deliver value as long as the covariate table generates correctly.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ GCP/Earth Engine auth, ward boundary loading, and ERA5-Land ingestion are correct and fixed — Phase 1 (verified 2026-09-13: 9/9 must-haves, 8/8 live tests passing against the real `heatwave-508110` project, no mocking)
- ✓ Heat Index/RH math lives in a tested `heatwave/science/heat_index.py` module, no longer inline in the Streamlit script, with the RH output correctly clamped to [0,100] — Phase 2 (verified 2026-09-13: 12/12 must-haves, 15/15 live tests passing including a regression check on Phase 1's suite)
- ✓ Per-ward climatology baseline (90th percentile, day-of-year, ±5-day pooling with correct wraparound) and heatwave day/event detection (join, flag, consecutive-run grouping) — Phase 3 (verified 2026-09-13: 15/15 must-haves, 49/49 live tests passing; one critical code-review finding fixed and re-verified — see Context)

### Active

<!-- Current scope. Building toward these. -->

- [ ] Implement batch export producing the weekly covariate table for all 4,841 wards (the production deliverable)
- [ ] Rewrite the Streamlit presentation layer to read the precomputed covariate table instead of computing live
- [ ] Document methodology and usage

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Disease forecasting itself — this pipeline produces an upstream climate covariate only; forecasting is CHAP's job downstream.
- Custom HTML/JS dashboard (Leaflet.js + FastAPI/Flask) — assessed as feasible in a prior side discussion but not pursued; Phase 6-equivalent (presentation rewrite) already plans a Streamlit rewrite reading a precomputed table, reducing the need for live tile serving. Revisit only if explicitly requested.
- Re-litigating cloud infrastructure choices (GCP project, service account, ward boundary asset, ERA5-Land collection/bands) — these are already provisioned and verified; carried forward as constraints, not decisions to revisit in this roadmap.
- CI/CD pipeline — optional stretch goal in the final phase, not required for v1 completion.

## Context

**Repo state:** Working directory `heatwave_modelling_CHAP-main/heatwave_modelling_CHAP-main`, on branch `feature/heatwave-508110-phase-0-2-gsd` (based on real `origin/main`), 1 commit ahead (`02864e0`, "Fresh-start rework: config/auth consolidation + ward-level ERA5-Land switch (Phases 0-2)"). This branch is intended to supersede an earlier ad-hoc PR (`#1`, branch `feature/heatwave-508110-phase-0-2` → `main` on `eHealthAfrica/heatwave_modelling_CHAP`) once the known issues below are fixed via GSD's plan → execute → verify pipeline.

**Phases 0-2 are now validated** (as of Phase 1 completion, 2026-09-13) — an independent codebase audit found 4 issues in the ad-hoc prior-session build, and Phase 1 fixed and re-verified all of them:

1. **Dewpoint date-matching join bug** — `nigeria_heat_index.py`'s `compute_relative_humidity()` matches each `tmean` image to its dewpoint image via a per-image `era5_2d.filterDate(tempDate, tempDate.advance(1, 'day')).first()` call. This is fragile: no guaranteed exact match, silent `null`/`first()`-of-empty behavior on gaps, and inefficient (client-side loop of server-side filters instead of a proper join).
2. **Missing `st.cache_resource` on Earth Engine init** — `init_ee()` is called unconditionally at Streamlit module load with no caching, causing full re-authentication and re-initialization of the Earth Engine client on every Streamlit rerun/interaction (slider drag, widget change), which is slow and wasteful.
3. **Unused `ee==0.2` PyPI package** — pinned in `requirements.txt` alongside `earthengine-api==1.6.8`. `ee` (the PyPI package, not the `earthengine-api`'s `ee` import namespace) is unused dead weight and a source of confusion/potential version conflicts.
4. **Fragile relative-path/import-order dependencies in `heatwave/auth.py`** — `_LOCAL_KEY_FILE = "keys/service_account.json"` is a relative path that only resolves correctly if the process's current working directory is the repo root; the `blessings` module stub-out (`sys.modules.setdefault(...)`) only works if `heatwave.auth` is imported before `geemap`, which is an implicit ordering contract not enforced anywhere.

Phase 1 re-verified and fixed all 4 issues (not a rebuild — a targeted fix-and-test pass); Phase 2+ now builds on top of this validated foundation. One non-blocking residual risk carried forward from Phase 1's code review: the relocated `blessings` stub in `heatwave/__init__.py` is import-order-dependent in principle (though the actual reported bug is fixed and tested end-to-end) — worth a follow-up regression test in a future phase.

**Phase 2 complete (2026-09-13):** RH/Heat-Index math relocated from `nigeria_heat_index.py` into `heatwave/science/heat_index.py`, verbatim except for one scoped fix — the RH output (`100 - 5*(T-D)`) is now clamped to [0,100] (carried forward from Phase 1's WR-01 finding), applied correctly to the single-band expression before `addBands()` (clamping the full multi-band composite would have corrupted the temperature bands — caught during research). Tests use NOAA's official Heat Index reference table as ground truth with `pytest.approx` tolerance, not exact equality. `nigeria_heat_index.py` now imports from the new module with zero formula-logic duplication remaining in the presentation layer.

**Phase 3 complete (2026-09-13):** `heatwave/zonal.py` (gridded→per-ward daily reduction), `heatwave/science/climatology.py` (day-of-year pooled 90th-percentile thresholds, with a verified floor-mod fix for wraparound near day 1/366 — `ee.Number.mod()` truncates rather than floors, a genuine landmine caught during research), and `heatwave/science/heatwave.py` (threshold join, day flagging, consecutive-event detection) are built and tested on small synthetic samples (1-3 wards), per D-03 — full 4,841-ward/30-year execution is Phase 4's job. A code review after execution found and fixed one **critical** bug: `flag_heatwave_days`'s climatology join defaulted to an inner join, silently dropping ward-days with no matching threshold and corrupting the consecutive-run state machine (which assumes gapless daily input). Fixed to an outer join with explicit null propagation; verified live. **Two items explicitly deferred to Phase 4, not yet resolved:**
1. **Small-ward null handling policy** — `zonal.py` correctly surfaces a null `value` (not a silently-substituted 0) for ward polygons below Earth Engine's pixel-weight inclusion threshold, but the *policy* for what to do with those ward-days in the final covariate table is undecided — Phase 4 must decide before EXPORT-01 runs against all 4,841 real wards (some of which may be small enough to trigger this).
2. **Run-detection scale** — the `ee.List.iterate()`-based consecutive-run state machine was verified correct and fast (<2s) up to ~3,650 elements (~10 years) but has NOT been verified at Phase 4's full ~10,950-element (30-year) scale. Benchmark before reusing `tag_consecutive_runs` unchanged; a documented fallback (array forward-difference run-length pattern) exists if it proves too slow.

**Already-provisioned cloud infrastructure** (done, not being re-decided — see Constraints):
- GCP project `heatwave-508110`, registered for Earth Engine.
- Service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`, key at local `keys/service_account.json` (gitignored, never committed).
- Ward boundary asset `projects/heatwave-508110/assets/shp` (GRID3 NGA Operational Wards), 4,841 wards nationwide, verified live.
- Data source `ECMWF/ERA5_LAND/DAILY_AGGR` (~11.1km, daily, from 1950-01-02); bands `temperature_2m_max`, `temperature_2m`, `dewpoint_temperature_2m`.

**Reference docs that could not be parsed during intel ingestion** (`.docx`/`.pdf`, may contain fuller methodology/roadmap detail): `outputs/01_Heatwave_Methodology.docx`, `outputs/02_Implementation_Roadmap.docx`, `outputs/03_Implementation_Phases_Status.docx`/`.pdf`. If these become available as text/markdown, re-ingest — they may refine phase detail below.

**GitHub state:** PR #1 (`eHealthAfrica/heatwave_modelling_CHAP`) is open but not merged as of last check — status should be reconfirmed before pushing this branch. A GitHub PAT was pasted into a prior chat session; treat as potentially compromised, do not reuse if it resurfaces, request a fresh token if git/PR operations are needed.

## Constraints

- **Cloud infra (fixed, not to be re-decided)**: GCP project `heatwave-508110`, service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`, ward boundary asset `projects/heatwave-508110/assets/shp`, ERA5-Land collection `ECMWF/ERA5_LAND/DAILY_AGGR` with bands `temperature_2m_max`/`temperature_2m`/`dewpoint_temperature_2m` — already provisioned and verified live; carried forward as given.
- **Tech stack**: Python >=3.11 (`pyproject.toml`), `earthengine-api`, `streamlit`, `geemap`, `pandas`, `pytest`/`PyYAML` already in `requirements.txt`.
- **Credential handling**: service account key must never be committed (`keys/service_account.json`, gitignored, diff-scanned before every commit). `heatwave/auth.py` credential resolution order: Streamlit secrets → `EE_SA_JSON` env var → local key file.
- **Climatology parameters (config.yaml, fixed)**: baseline period 1991-2020, 90th percentile threshold, ±5-day pooling window, ≥3 consecutive days = heatwave event.
- **Windows/PowerShell tooling**: each shell tool call is a fresh shell (PATH/`cd` don't persist); multi-line git commit messages with embedded quotes break `git commit -m` on Windows (use `git commit -F <file>`); `robocopy` doesn't delete files absent from source.
- **Production surface**: the weekly covariate table is the real deliverable, consumed by CHAP downstream. The Streamlit app is dev/QA tooling only — do not over-invest in its polish relative to pipeline correctness.

## Key Decisions

<!-- Decisions that constrain future work. Add throughout project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GCP project `heatwave-508110` / service account `heatwave-pipeline@...` / ward asset `projects/heatwave-508110/assets/shp` / ERA5-Land collection `ECMWF/ERA5_LAND/DAILY_AGGR` | Already provisioned and verified live in a prior session; user explicitly directed these not be re-litigated | ✓ Good — locked, carried forward |
| Climatology definition: 1991-2020 baseline, 90th percentile, ±5-day pooling, ≥3 consecutive days = event | WMO/ETCCDI percentile-exceedance standard, recorded in `config.yaml` from a prior session | ✓ Good — implemented and tested in Phase 3 (2026-09-13); day-of-year 1-366 keying with Feb 29 given its own real threshold, not merged into Feb 28 |
| Heat Index formula: NOAA/NWS Rothfusz regression | Standard method, already implemented inline in `nigeria_heat_index.py`; Phase 2 relocates (not rewrites) it | ✓ Good — relocated to `heatwave/science/heat_index.py` (2026-09-13), coefficients verbatim, RH output now clamped |
| Re-do Phases 0-2 through GSD plan → execute → verify (not treat as already-complete) | Independent codebase audit found 4 concrete issues that must be fixed before this branch supersedes PR #1 | ✓ Good — Phase 1 complete, all 4 fixed and re-verified live (2026-09-13) |
| Custom HTML/JS dashboard (Leaflet.js + FastAPI) as Streamlit replacement | Feasible but a detour; presentation-layer rewrite phase already covers the real need (precomputed table, less live tile serving) | ⚠️ Revisit only if explicitly asked — not pursuing now |

---
*Last updated: 2026-09-13 after Phase 3 (Climatology & Heatwave Detection) completion*
