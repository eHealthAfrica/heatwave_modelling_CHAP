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
- ✓ Batch export mechanism producing the CHAP-facing weekly covariate table — async Earth Engine harness, ward-batch chunking, resumable state, small-ward centroid fallback, ISO-week aggregation — Phase 4 (verified 2026-09-17: 10/10 must-haves, 90/90 non-gated live tests passing; 2 critical + 2 data-quality code-review findings fixed, plus one review-fix regression caught by the verifier and fixed, all re-verified live — see Context). Full 1991-present, 4,841-ward historical backfill deliberately deferred as a separate manual operation; two launch attempts since (2026-09-21/22) both hit Earth Engine's own timeout — see Context.
- ✓ Streamlit presentation layer reads the precomputed covariate table instead of computing Heat Index live — `heatwave/app/streamlit_app.py`, a ward map colored by a selectable metric (heatwave days, mean/max Heat Index, event count) for a selectable week — Phase 5 (2026-09-24: 101/101 non-gated tests passing including a live check against the real 4,841-ward asset; `nigeria_heat_index.py` retired)

### Active

<!-- Current scope. Building toward these. -->

- [ ] Document methodology and usage

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Disease forecasting itself — this pipeline produces an upstream climate covariate only; forecasting is CHAP's job downstream.
- Custom HTML/JS dashboard (Leaflet.js + FastAPI/Flask) — assessed as feasible in a prior side discussion but not pursued; Phase 6-equivalent (presentation rewrite) already plans a Streamlit rewrite reading a precomputed table, reducing the need for live tile serving. Revisit only if explicitly requested.
- Re-litigating cloud infrastructure choices (GCP project, service account, ward boundary asset, ERA5-Land collection/bands) — these are already provisioned and verified; carried forward as constraints, not decisions to revisit in this roadmap.
- CI/CD pipeline — optional stretch goal in the final phase, not required for v1 completion.

## Context

**Repo state:** Working directory `heatwave_modelling_CHAP-main/heatwave_modelling_CHAP-main`, on branch `feature/heatwave-508110-phase-0-3-gsd` (renamed from `-phase-0-2-gsd` once Phase 3 landed; renamed again as later phases land) (based on real `origin/main`). This branch is intended to supersede an earlier ad-hoc PR (`#1`, branch `feature/heatwave-508110-phase-0-2` → `main` on `eHealthAfrica/heatwave_modelling_CHAP`) — PR #3 (superseding a briefly-existing, accidentally-closed PR #2) currently tracks Phases 1-3; will be updated to include Phase 4.

**Phases 0-2 are now validated** (as of Phase 1 completion, 2026-09-13) — an independent codebase audit found 4 issues in the ad-hoc prior-session build, and Phase 1 fixed and re-verified all of them:

1. **Dewpoint date-matching join bug** — `nigeria_heat_index.py`'s `compute_relative_humidity()` matches each `tmean` image to its dewpoint image via a per-image `era5_2d.filterDate(tempDate, tempDate.advance(1, 'day')).first()` call. This is fragile: no guaranteed exact match, silent `null`/`first()`-of-empty behavior on gaps, and inefficient (client-side loop of server-side filters instead of a proper join).
2. **Missing `st.cache_resource` on Earth Engine init** — `init_ee()` is called unconditionally at Streamlit module load with no caching, causing full re-authentication and re-initialization of the Earth Engine client on every Streamlit rerun/interaction (slider drag, widget change), which is slow and wasteful.
3. **Unused `ee==0.2` PyPI package** — pinned in `requirements.txt` alongside `earthengine-api==1.6.8`. `ee` (the PyPI package, not the `earthengine-api`'s `ee` import namespace) is unused dead weight and a source of confusion/potential version conflicts.
4. **Fragile relative-path/import-order dependencies in `heatwave/auth.py`** — `_LOCAL_KEY_FILE = "keys/service_account.json"` is a relative path that only resolves correctly if the process's current working directory is the repo root; the `blessings` module stub-out (`sys.modules.setdefault(...)`) only works if `heatwave.auth` is imported before `geemap`, which is an implicit ordering contract not enforced anywhere.

Phase 1 re-verified and fixed all 4 issues (not a rebuild — a targeted fix-and-test pass); Phase 2+ now builds on top of this validated foundation. One non-blocking residual risk carried forward from Phase 1's code review: the relocated `blessings` stub in `heatwave/__init__.py` is import-order-dependent in principle (though the actual reported bug is fixed and tested end-to-end) — worth a follow-up regression test in a future phase.

**Phase 2 complete (2026-09-13):** RH/Heat-Index math relocated from `nigeria_heat_index.py` into `heatwave/science/heat_index.py`, verbatim except for one scoped fix — the RH output (`100 - 5*(T-D)`) is now clamped to [0,100] (carried forward from Phase 1's WR-01 finding), applied correctly to the single-band expression before `addBands()` (clamping the full multi-band composite would have corrupted the temperature bands — caught during research). Tests use NOAA's official Heat Index reference table as ground truth with `pytest.approx` tolerance, not exact equality. `nigeria_heat_index.py` now imports from the new module with zero formula-logic duplication remaining in the presentation layer.

**Phase 3 complete (2026-09-13):** `heatwave/zonal.py` (gridded→per-ward daily reduction), `heatwave/science/climatology.py` (day-of-year pooled 90th-percentile thresholds, with a verified floor-mod fix for wraparound near day 1/366 — `ee.Number.mod()` truncates rather than floors, a genuine landmine caught during research), and `heatwave/science/heatwave.py` (threshold join, day flagging, consecutive-event detection) are built and tested on small synthetic samples (1-3 wards), per D-03 — full 4,841-ward/30-year execution is Phase 4's job. A code review after execution found and fixed one **critical** bug: `flag_heatwave_days`'s climatology join defaulted to an inner join, silently dropping ward-days with no matching threshold and corrupting the consecutive-run state machine (which assumes gapless daily input). Fixed to an outer join with explicit null propagation; verified live.

**Phase 4 complete (2026-09-17):** `scripts/run_batch_export.py` — the production entry point running the full pipeline via Earth Engine's asynchronous batch export (submit → poll → resumable state → paginated read-back → chunked concatenation), never synchronous `getInfo()`. Both items Phase 3 deferred are now resolved:
1. **Small-ward null handling** — resolved via a centroid-based fallback reducer (`heatwave/zonal.py`'s `find_small_wards`/`build_fallback_ward_centroids`): a ward too small for the primary area-weighted reduction gets a real sampled value from a representative in-polygon point, never a fabricated 0, with a `used_fallback_reducer` provenance flag. 73 of the 4,841 real wards trigger this fallback (confirmed live).
2. **Run-detection scale** — benchmarked live rather than switched pre-emptively; extrapolated event-detection runtime at full scale (~34-40hrs unchunked) argued for ward-batch chunking (20 chunks of ~250 wards) rather than an algorithm change, which is what was implemented.

Research caught two silent-bug landmines before implementation (naive calendar-year pairing with ISO week number is wrong at the Dec/Jan boundary; chaining two `Reducer.group()` calls silently swaps values instead of erroring) and found the originally-assumed Google Drive export destination fails outright for a service account — resolved via `Export.table.toAsset()` + paginated read-back, needing no new cloud infrastructure. A code review found 2 **critical** bugs (task-state file never persisted the polled outcome, so a failed chunk looked eternally resumable; resumability keyed only by chunk-id with no fingerprint of the building parameters, risking silent stale-data reuse across differently-configured runs) plus 2 data-quality warnings (fallback centroid could fall outside a concave ward polygon; small-ward classification from a single sampled day risked permanent misclassification from one anomaly) — all fixed and re-verified live. The data-quality fix for small-ward classification itself then introduced a scale regression (eagerly materializing the full ~35-year image collection just to count it, exceeding Earth Engine's memory limit at the script's own default configuration) — caught by the phase verifier's independent re-execution (not just trusted from summaries), fixed, and re-verified live before the phase was marked complete.

The human checkpoint built into Phase 4's plan (a real, live `--stage plan` run: 4,841 wards / 20 chunks / 73 small wards / quota warning, plus a real small-scale smoke export) was reviewed and approved. **The full 1991-present historical backfill itself has NOT been run** — it is a separate, deliberately-deferred, multi-hour operation (`scripts/run_batch_export.py` with no `--max-wards`/`--stage` limiting flags), independent of this phase's completion per the locked D-01/D-02 decision.

**Backfill launch attempted 2026-09-21/22, both attempts timed out — important finding for whoever runs it next.** Two real attempts to submit a single ward-batch chunk across the full historical range (1990-12-31 → 2026-09-14) both ended in Earth Engine's own `FAILED: "Computation timed out."` after ~12 hours each:
| Wards | EECU-hours used before timeout |
|---|---|
| 250 (the script's default ward-batch-size) | 37.7 |
| 25 | 21.3 |

Both hit the *same* ~12-hour wall despite a 10x difference in ward count — strong evidence the **date range (35+ years), not ward count, drives the cost**, most likely the day-of-year climatology graph (`heatwave/science/climatology.py`) walking the full multi-decade image collection largely independent of how many wards are in the batch. **Practical implication: `plan_ward_chunks` currently only chunks by ward, never by date range — the 20-chunk production plan as designed may hit this same per-task timeout at full scale, regardless of the ~250-ward batch size, since every chunk still spans the full 35-year range.** Before attempting the full backfill again, whoever picks this up should either (a) add date-range chunking alongside the existing ward-batch chunking (e.g., one task per ward-batch × per few years, then concatenate across both dimensions), or (b) confirm with GCP support/docs whether Earth Engine's batch-task timeout can be raised for this project's tier. A genuine small-scale *real* sample (not the full backfill) — 5 wards, a 2-month window — completed quickly and is documented in `outputs/README.md`; `scripts/run_batch_export.py` and all `heatwave/` modules are unmodified by this finding.

**Already-provisioned cloud infrastructure** (done, not being re-decided — see Constraints):
- GCP project `heatwave-508110`, registered for Earth Engine.
- Service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`, key at local `keys/service_account.json` (gitignored, never committed).
- Ward boundary asset `projects/heatwave-508110/assets/shp` (GRID3 NGA Operational Wards), 4,841 wards nationwide, verified live.
- Data source `ECMWF/ERA5_LAND/DAILY_AGGR` (~11.1km, daily, from 1950-01-02); bands `temperature_2m_max`, `temperature_2m`, `dewpoint_temperature_2m`.

**Reference docs that could not be parsed during intel ingestion** (`.docx`/`.pdf`, may contain fuller methodology/roadmap detail): `outputs/01_Heatwave_Methodology.docx`, `outputs/02_Implementation_Roadmap.docx`, `outputs/03_Implementation_Phases_Status.docx`/`.pdf`. If these become available as text/markdown, re-ingest — they may refine phase detail below.

**Phase 5 complete (2026-09-24):** `heatwave/app/streamlit_app.py` replaces `nigeria_heat_index.py` (now removed, APP-02). The pure color/scale logic (`color_for_value`, `metric_bounds`, `build_styled_wards`) is separated from the Streamlit UI section, which is gated behind `if __name__ == "__main__":` — both `streamlit run` and `AppTest.from_file()` execute the file with `__name__ == "__main__"`, so the app behaves identically under either, while the pure functions stay safely unit-testable via a normal Python import (a plain top-level Streamlit script has no such guard and cannot be safely imported for its logic — this only mattered once tests needed to reach the helpers directly). Ward geometry comes from the same `heatwave.data.boundary.load_ward_boundary()` used since Phase 1; the covariate CSV's `location` column joins against the boundary's `wardcode` property via a single `ee.Dictionary` lookup built client-side and applied server-side (`ee.FeatureCollection.style(styleProperty=...)`), so the ~4,841 ward polygons themselves are never pulled into Python — only their rendered map tiles are, same rendering approach the retired app used. Missing/null metric values render grey, never a fabricated color position. The real `outputs/covariate_table.csv` doesn't exist yet (see the backfill-timeout finding above); the app shows a clear error and stops rather than crashing, and a `COVARIATE_TABLE_PATH` environment variable lets it point at a sample/fixture CSV for development. Built and verified with minimal process (no separate discuss/plan/research/review agent passes) per explicit user direction to limit GSD ceremony at this stage of the project.

**GitHub state:** PR #1 (`eHealthAfrica/heatwave_modelling_CHAP`, the original ad-hoc Phase 0-2 work) is open but not merged as of last check. PR #3 (`feature/heatwave-508110-phase-0-3-gsd` → `main`) currently tracks Phases 1-3 through GSD's rework; PR #2 briefly existed and was accidentally closed when its source branch was renamed (server-side GitHub branch-rename closes rather than retargets an open PR — noted so it isn't rediscovered as a mystery). A GitHub PAT was pasted into a prior chat session; treat as potentially compromised, do not reuse if it resurfaces — GitHub CLI's `gh auth login --web` device flow is the established re-authentication method for this project, no PAT needed.

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
| Presentation layer shape: map of wards by week, selectable metric | User-selected option during Phase 5 discussion; matches the ward-level, weekly-aggregated shape of the covariate table itself | ✓ Good — implemented in `heatwave/app/streamlit_app.py` (2026-09-24) |
| Rework/rebuild Phases 1-5 and remaining phases with reduced GSD ceremony after Phase 4 | Explicit user instruction ("limit the use of gsd at this point") following an environment reset; full discuss/plan/research/review agent sequence no longer required for every phase | ✓ Good — Phase 5 delivered directly, 101/101 non-gated tests passing, no regressions |

---
*Last updated: 2026-09-24 after Phase 5 (Presentation Layer Rewrite) completion*
