---
phase: 01-foundation-rework
plan: 02
subsystem: data-ingest
tags: [earth-engine, ee.ImageCollection, streamlit, st.cache_resource, relative-humidity]

# Dependency graph
requires:
  - phase: 01-foundation-rework
    provides: "Plan 01-01's path-anchored service-account key file and relocated blessings stub in heatwave/__init__.py"
provides:
  - "load_era5_land() returning a single multi-band ee.ImageCollection (tmax/tmean/dewpoint bands per image)"
  - "Join-free compute_relative_humidity() reading tmean/dewpoint from the same image"
  - "@st.cache_resource-wrapped Earth Engine init in the Streamlit app layer"
  - "Corrected import order so the blessings stub fires before geemap loads in nigeria_heat_index.py"
affects: [phase-2-heat-index-relocation, phase-4-batch-export]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Multi-band ee.ImageCollection.select([...]) instead of per-band collections + client-side join"
    - "@st.cache_resource wrapper kept at the Streamlit app layer only, not inside framework-agnostic modules"

key-files:
  created: []
  modified: [heatwave/data/ingest.py, nigeria_heat_index.py]

key-decisions:
  - "D-01/D-02/D-03 upheld: single multi-band ImageCollection replaces three separately-filtered collections; no ee.Join introduced"
  - "D-04/D-05 upheld: @st.cache_resource wrapper (_cached_init_ee) lives only in nigeria_heat_index.py; heatwave/auth.py's init_ee() stays undecorated and framework-agnostic for Phase 4's scripts/run_batch_export.py"

patterns-established:
  - "Band selection from a single ee.Image via image.select(settings.bands.X) instead of filterDate().first() joins across separate collections"

requirements-completed: [REWORK-01, REWORK-02, REWORK-04, REWORK-06, REWORK-08]

# Metrics
duration: 6min
completed: 2026-09-13
---

# Phase 1 Plan 2: ERA5-Land Join Removal & Streamlit Caching Summary

**Restructured `load_era5_land()` into a single multi-band `ee.ImageCollection` and removed the fragile per-image `filterDate().first()` dewpoint join in `nigeria_heat_index.py`, replacing it with same-image band selection, plus `@st.cache_resource`-wrapped Earth Engine init and corrected import order.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-13T09:11:01Z
- **Completed:** 2026-09-13T09:17:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `heatwave/data/ingest.py`'s `load_era5_land()` now returns one `ee.ImageCollection` carrying `tmax`, `tmean`, and `dewpoint` as three bands per image (removed `Era5LandBands` dataclass and `_select_band()` helper) — eliminates any risk of a silent per-image mismatch between temperature and dewpoint data.
- `nigeria_heat_index.py`'s `compute_relative_humidity()` now selects `tmean`/`dewpoint` bands directly from the same `image` argument via `image.select(...)`, with no `filterDate().first()` join and no `ee.Join` introduced.
- Earth Engine initialization in `nigeria_heat_index.py` is now wrapped in an `@st.cache_resource`-decorated `_cached_init_ee()` function, so repeated Streamlit reruns (slider drags, widget interactions) no longer re-authenticate against Earth Engine. `heatwave/auth.py`'s `init_ee()` remains undecorated and framework-agnostic, staying directly callable from Phase 4's `scripts/run_batch_export.py`.
- Import order in `nigeria_heat_index.py` corrected: `from heatwave.auth import init_ee` now runs before `import geemap.foliumap as geemap`, guaranteeing Plan 01-01's blessings stub (in `heatwave/__init__.py`) executes before geemap is imported.

## Task Commits

Each task was committed atomically:

1. **Task 1: Restructure load_era5_land() into a single multi-band ImageCollection** - `eed1038` (refactor)
2. **Task 2: Fix nigeria_heat_index.py join, caching, and import order** - `243aadc` (fix)

**Plan metadata:** committed as part of this summary commit (docs: complete plan)

## Files Created/Modified
- `heatwave/data/ingest.py` - `load_era5_land()` rewritten to return a single multi-band `ee.ImageCollection`; `Era5LandBands` dataclass and `_select_band()` helper removed
- `nigeria_heat_index.py` - Import order fixed, `init_ee()` wrapped in `@st.cache_resource`, join-based `compute_relative_humidity()` replaced with same-image band selection

## Decisions Made
- Followed plan exactly: D-01/D-02/D-03 (single multi-band collection, no `ee.Join`) and D-04/D-05 (caching wrapper confined to the Streamlit app layer, `heatwave/auth.py` untouched) were both upheld with no deviation.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. One verification-command quirk worth noting: the plan's acceptance-criteria command `grep -A2 "@st.cache_resource" nigeria_heat_index.py | grep -c "init_ee()"` returns `2` instead of the documented `1` on the final code, because the literal substring `init_ee()` also appears inside the function name `_cached_init_ee()` on the line immediately following the decorator. This is a false-positive artifact of substring grep, not an implementation defect — the code matches the plan's literal specification (`@st.cache_resource` decorating a function named `_cached_init_ee` whose body calls `init_ee()`), confirmed by direct file inspection.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `heatwave/data/ingest.py`'s new multi-band return shape is ready for Phase 2's heat-index relocation to consume directly.
- Both files remain syntactically valid (`ast.parse` succeeds); live behavioral verification (app boot, correct RH values against the live Earth Engine project) is deferred to Plan 01-03's `tests/test_integration.py`, which depends on this plan.
- No blockers identified.

---
*Phase: 01-foundation-rework*
*Completed: 2026-09-13*

## Self-Check: PASSED

- FOUND: heatwave/data/ingest.py
- FOUND: nigeria_heat_index.py
- FOUND: .planning/phases/01-foundation-rework/01-02-SUMMARY.md
- FOUND: eed1038 (Task 1 commit)
- FOUND: 243aadc (Task 2 commit)
