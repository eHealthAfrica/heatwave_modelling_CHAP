# Heatwave Modelling (CHAP)

## What This Is

A ward-level heatwave pipeline for 4,841 wards in 19 northern Nigerian states plus the FCT (not nationwide). It downloads ERA5-Land daily data through Google Earth Engine, computes the NOAA/NWS Heat Index per ward, detects heatwave days, events and hot nights with a WMO/ETCCDI percentile-exceedance climatology, and produces a weekly covariate table for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). The detection layer is rule-based. Milestone v2.0 adds a trained **forecast layer** that predicts the table's heat indicators 1-6 weeks ahead. The project still does not forecast disease itself.

## Core Value

A correct, complete weekly covariate table (`time_period`, `location`/ward, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`, `hot_nights`, `total_precipitation_mm`, `mean_relative_humidity`, `mean_soil_moisture`) can be generated end-to-end from ERA5-Land data for all 4,841 wards in the study area and handed off to CHAP. For v2.0, add honest, calibrated forecasts of those heat indicators that demonstrably beat simple baselines. The Streamlit app is a dev/QA visualization tool, not the production surface — if it broke entirely, the pipeline would still deliver value as long as the covariate table generates correctly.

## Current Milestone: v2.0 Heat Forecasting

**Goal:** Forecast each ward's weekly heat indicators 1-6 weeks ahead, with calibrated probabilities that are proven to beat simple baselines on held-out years and can be passed to CHAP.

**Target features:**
- Feature store of lagged features from the frozen `covariates-v1.0`, with an automated leakage test
- Baselines: climatology, 10-year recent climatology, persistence
- Models per lead (1-6 weeks from the last observed week): regularised logistic regression, LightGBM, LightGBM quantile models for the Heat Index anomaly; isotonic calibration
- Evaluation on a time split (train 1991-2014, validate 2015-2020, test 2021-2026 once): Brier skill score as the headline, ROC AUC, reliability, precision/recall/F1, anomaly error and interval coverage; by lead, season and region; week-block bootstrap CIs; SHAP and ablations
- Go/no-go decision and evaluation report
- Climate drivers (ENSO, tropical Atlantic SST, MJO) added in a later phase, measured by the skill they add
- Operational weekly forecast table for CHAP, versioned and documented

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ GCP/Earth Engine auth, ward boundary loading, and ERA5-Land ingestion are correct and fixed — Phase 1 (verified 2026-09-13: 9/9 must-haves, 8/8 live tests passing against the real `heatwave-508110` project, no mocking)
- ✓ Heat Index/RH math lives in a tested `heatwave/science/heat_index.py` module, no longer inline in the Streamlit script, with the RH output correctly clamped to [0,100] — Phase 2 (verified 2026-09-13: 12/12 must-haves, 15/15 live tests passing including a regression check on Phase 1's suite)
- ✓ Per-ward climatology baseline (90th percentile, day-of-year, ±5-day pooling with correct wraparound) and heatwave day/event detection (join, flag, consecutive-run grouping) — Phase 3 (verified 2026-09-13: 15/15 must-haves, 49/49 live tests passing; one critical code-review finding fixed and re-verified — see Context)
- ✓ Batch export mechanism producing the CHAP-facing weekly covariate table — async Earth Engine harness, ward-batch chunking, resumable state, small-ward centroid fallback, ISO-week aggregation — Phase 4 (verified 2026-09-17: 10/10 must-haves, 90/90 non-gated live tests passing; 2 critical + 2 data-quality code-review findings fixed, plus one review-fix regression caught by the verifier and fixed, all re-verified live — see Context). Full 1991-present, 4,841-ward historical backfill deliberately deferred as a separate manual operation; two launch attempts since (2026-09-21/22) both hit Earth Engine's own timeout — see Context.
- ✓ Streamlit presentation layer reads the precomputed covariate table instead of computing Heat Index live — `heatwave/app/streamlit_app.py`, a ward map colored by a selectable metric (heatwave days, mean/max Heat Index, event count) for a selectable week — Phase 5 (2026-09-24: 101/101 non-gated tests passing including a live check against the real 4,841-ward asset; `nigeria_heat_index.py` retired)
- ✓ Methodology and usage are documented — `docs/METHODOLOGY.md` (Heat Index formula, climatology definition, detection logic, covariate schema, the documented backfill-timeout limitation) and a rewritten root `README.md` (architecture, setup, credential resolution, running tests/batch export/viewer, current status) — Phase 6 (2026-09-28)
- ✓ Config-loading edge cases are covered and a CI safety net runs the suite on every push — `tests/test_config.py` (35 tests) and `.github/workflows/tests.yml` — Phase 7 (2026-09-30). All 28 v1 requirements are now complete.
- ✓ Humidity (Magnus) and Heat Index (full NOAA/NWS method) corrected — PR #8 (2026-10-02, outside GSD)
- ✓ Full 1991-2026 table built by the local pipeline (`heatwave/local/`, `scripts/run_local_pipeline.py`) from ERA5-Land downloaded via Earth Engine computePixels: Heat Index from daily max temperature, hot nights, rainfall/humidity/soil-moisture columns, LGA average for 6 wards without geometry — PRs #9 and #10 (2026-10-02, outside GSD); 166 tests passing
- ✓ Independent cross-check (TerraClimate, CHIRPS, MODIS) and station check (NOAA GSOD; NiMet data is not open) documented in METHODOLOGY sections 8-9 (2026-10-02)
- ✓ Frozen dataset `covariates-v1.0` (git tag on 7ed8d1c; read-only copy and MANIFEST.json under `<local_data_dir>/frozen/covariates-v1.0/`) (2026-10-02)

### Active

<!-- Current scope. Building toward these. -->

- See Current Milestone above and `.planning/REQUIREMENTS.md` (v2.0)

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Disease forecasting itself — this pipeline produces upstream climate covariates (observed and, from v2.0, forecast heat indicators); disease forecasting is CHAP's job downstream.
- Station-confirmed heatwave labels — NiMet data is not open (NGOs are a paid commercial category, no redistribution) and NOAA GSOD is too sparse for a 1991-2020 baseline, so labels stay ERA5-Land-based (METHODOLOGY section 9).
- Building a physical forecast model — ECMWF extended-range (S2S) forecasts serve only as a benchmark or fallback if the trained model shows no skill.
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

**Phase 6 complete (2026-09-28):** `docs/METHODOLOGY.md` (new) documents the full pipeline end-to-end — the Rothfusz Heat Index formula with its coefficient table, the small-ward centroid-fallback mechanism and the ~0.4% pixel-weight threshold that triggers it (73 of 4,841 real wards), the WMO/ETCCDI percentile-exceedance climatology definition and its config-driven parameters, heatwave day/event detection semantics (strict exceedance, event-starts-in-its-starting-week-only), the covariate table schema with its explicit null-vs-zero rules, and the production execution model including the still-unresolved backfill-timeout finding from Phase 4's follow-up work. The root `README.md` was rewritten around current architecture rather than the phase-by-phase narrative used through Phase 5 — a package-layout diagram, setup/credential instructions, exact commands for running tests/the batch export (plan, full, and small-sample forms)/the Streamlit viewer, and a "Current status" section that states plainly that the real full-history covariate table does not exist yet, rather than glossing over it. Built directly, same minimal process as Phase 5, per the same standing user direction to limit GSD ceremony.

**Phase 7 complete (2026-09-30), v1 fully delivered:** `tests/test_config.py` (35 tests, no credentials required) covers `load_settings`'s happy path plus every missing-top-level-key, missing-`bands`-key, missing-`climatology`-key, malformed-YAML, missing-file, and empty-file case, and `ClimatologyConfig`'s `__post_init__` runtime validation (percentile range, baseline-year ordering, pooling-window non-negativity, min-consecutive-days floor) at both its rejecting and boundary-accepting edges — each `load_settings` case writes its own temporary YAML via `tmp_path` rather than touching the real `config.yaml`, so these tests can never affect (or be affected by) the project's actual configuration. `.github/workflows/tests.yml` (new) runs `pytest -v` on every push/PR against `ubuntu-latest` + Python 3.11; it reads an optional `EE_SA_JSON` repository secret so credential-gated live tests run for real when that secret is configured and skip cleanly — not fail — when it isn't, meaning the workflow is useful (catches config/import/pure-logic regressions) from the moment it exists, with full live coverage available the moment a maintainer adds the secret. This closes out all 28 v1 requirements across all 7 phases.

**GitHub state:** PR #1 (`eHealthAfrica/heatwave_modelling_CHAP`, the original ad-hoc Phase 0-2 work) is open but not merged as of last check. PR #3 (`feature/heatwave-508110-phase-0-3-gsd` → `main`) currently tracks Phases 1-3 through GSD's rework; PR #2 briefly existed and was accidentally closed when its source branch was renamed (server-side GitHub branch-rename closes rather than retargets an open PR — noted so it isn't rediscovered as a mystery). A GitHub PAT was pasted into a prior chat session; treat as potentially compromised, do not reuse if it resurfaces — GitHub CLI's `gh auth login --web` device flow is the established re-authentication method for this project, no PAT needed.

## Constraints

- **Cloud infra (fixed, not to be re-decided)**: GCP project `heatwave-508110`, service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`, ward boundary asset `projects/heatwave-508110/assets/shp`, ERA5-Land collection `ECMWF/ERA5_LAND/DAILY_AGGR` with bands `temperature_2m_max`/`temperature_2m`/`dewpoint_temperature_2m` — already provisioned and verified live; carried forward as given.
- **Tech stack**: Python >=3.11 (`pyproject.toml`), `earthengine-api`, `streamlit`, `geemap`, `pandas`, `pytest`/`PyYAML` already in `requirements.txt`, plus `shapely`, `xarray` and `netCDF4` for the local pipeline. v2.0 adds the first ML libraries (expected: scikit-learn, LightGBM).
- **Training data (v2.0)**: models train and test only on the frozen `covariates-v1.0` dataset, never on `outputs/covariate_table.csv`, which is overwritten on every run.
- **Reporting**: reports state that the detection layer is rule-based (with evidence) and keep it separate from the trained forecast layer. Coverage is always "4,841 wards in 19 northern states and the FCT".
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
| Build the full table locally instead of fixing the Earth Engine backfill | EE batch tasks hit a ~12 h timeout; the local pipeline builds everything in ~3 min | ✓ Good — PRs #9 and #10 (2026-10-02) |
| Heat Index from daily max temperature + daily mean dewpoint; add hot nights | Describes peak heat stress; hot nights are a separate health risk | ✓ Good — local pipeline (2026-10-02) |
| Rainfall column from ERA5-Land, not CHIRPS | One consistent source for every column; the ~25-30% low bias in the far north is documented | — Accepted with caveat (2026-10-02) |
| Use GSD again for v2.0 | User request (2026-10-02): "put the workflows in phases and use GSD" | — Pending |
| v2.0 forecast design | Agreed 2026-10-02: heatwave-week probability as the primary target; leads 1-6 from the last observed week; one model per lead; ward unit; train 1991-2014, validate 2015-2020, test 2021-2026 once; baselines climatology, recent climatology and persistence; logistic regression, then LightGBM; climate drivers in a later phase | — Pending |
| Research adjustments adopted (user: "proceed with your recommendations", 2026-10-02) | From `.planning/research/SUMMARY.md` | — Pending |

The adopted adjustments are:
- Add damped-persistence and trend+season baselines. The go/no-go compares against the best baseline.
- Use trend and base-rate level features, with no raw year index.
- **The go/no-go judges leads 2-3** (the first real forecasts; lead 1 is a nowcast).
- Keep the label name `heatwave_week` (`heatwave_days >= 3`), with a definition footnote.
- Calibrate on out-of-fold CV predictions, choosing Platt or isotonic by CV Brier.
- **Refit on 1991-2020 with frozen hyperparameters before the single test.** The operational model is retrained on all years and marked "not independently tested".
- Enforce a test lock and pre-registration.
- Split by target week with an embargo and `week_start` cutoffs.
- Reporting rules and the reanalysis-label caption.
- Pool per-lead models, with LGA-average and small wards flagged.
- **CI moves to Python 3.12.**
- Use provisional CHAP names `heatwave_prob` and `heatwave_week`, to be confirmed with the CHAP team.
- Evaluate drivers with a fresh CV protocol.

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-02 — milestone v2.0 Heat Forecasting started (v1.0 archived)*
