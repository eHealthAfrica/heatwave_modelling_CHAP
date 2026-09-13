---
phase: 02-heat-index-relocation
plan: 02
subsystem: science
tags: [earth-engine, ee.Image, heat-index, relative-humidity, streamlit, pytest]

# Dependency graph
requires:
  - phase: 02-heat-index-relocation
    provides: heatwave/science/heat_index.py exporting compute_relative_humidity()/compute_heat_index() (plan 02-01)
provides:
  - nigeria_heat_index.py as a pure consumer of heatwave.science.heat_index (zero inline formula logic)
  - Live confirmation that D-01's RH clamp is now exercised in the app's rendering path
affects: [phase-3-climatology-and-heatwave-detection, phase-5/6-presentation-layer-rewrite]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Presentation script imports domain math from heatwave.science.* rather than defining it inline"

key-files:
  created: []
  modified:
    - nigeria_heat_index.py

key-decisions:
  - "Dead branca Template/MacroElement import removed (Claude's Discretion, code-review IN-02) after confirming zero other references in the file"
  - "heatwave.auth import ordering above geemap import preserved unchanged (Phase 1 blessings-stub constraint)"
  - "No behavior change: .map() call sites, band names, and UI/map code left untouched"

requirements-completed: [HIDX-03]

# Metrics
duration: ~5min
completed: 2026-09-13
---

# Phase 2 Plan 2: Heat Index Relocation (Call-Site Update) Summary

**`nigeria_heat_index.py` now imports `compute_relative_humidity`/`compute_heat_index` from `heatwave.science.heat_index` instead of defining them inline; zero formula logic remains in the app, and the Streamlit boot + full 15-test suite stay green.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-09-13T12:24:00Z
- **Completed:** 2026-09-13T12:28:39Z
- **Tasks:** 2 completed (Task 2 was a verification-only gate, no code changes)
- **Files modified:** 1

## Accomplishments
- `nigeria_heat_index.py` imports `compute_relative_humidity`/`compute_heat_index` from `heatwave.science.heat_index`; both inline `def compute_relative_humidity`/`def compute_heat_index` bodies (Rothfusz coefficients, `.expression()` calls, `100 - 5 * (T - D)`, `273.15` conversion) deleted entirely
- `.map(compute_relative_humidity)` / `.map(compute_heat_index)` call sites preserved verbatim and unchanged in position relative to the STEP 3/4 banner comments
- Dead `from branca.element import Template, MacroElement` import removed (confirmed zero other references; legend renders via `st.markdown(..., unsafe_allow_html=True)`)
- D-01's `[0, 100]` RH clamp (added in plan 02-01) is now live in the app's actual rendering path, since the app calls the relocated clamped function
- Full test suite: 15 passed, 0 failed, 0 errors (7 from `tests/test_heat_index.py`, 7 from `tests/test_integration.py` including `test_streamlit_app_boots_cleanly`, 1 from `tests/test_requirements.py`)
- `tests/test_heat_index.py` re-run in isolation: same 7 passed as at the end of plan 02-01 — D-02 no-drift confirmed after the call-site relocation

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace inline formula definitions with the heatwave.science.heat_index import** - `70e35ab` (feat)
2. **Task 2: Phase regression gate — full suite green and responsibility boundary enforced** - verification-only, no file changes, no separate commit (full suite run confirmed 15/15 passing against Task 1's commit)

**Plan metadata:** (this commit) `docs(02-02): complete heat index relocation plan`

## Files Created/Modified
- `nigeria_heat_index.py` - Now imports RH/Heat-Index math from `heatwave.science.heat_index`; inline formula defs and dead `branca` import removed; `.map()` call sites, UI, map layers, and legend unchanged

## Decisions Made
- Removed the unused `branca` import as sanctioned Claude's-Discretion cleanup (IN-02), verified dead via grep before deletion
- Left `heatwave.auth` import above `geemap.foliumap` import unchanged, per Phase 1's blessings-stub import-order constraint (verified via line-number grep: line 3 vs line 4)
- Task 2 required no code edits — it is a pure regression/verification gate per the plan's own task definition; all acceptance criteria were satisfied by Task 1's edit with no further changes needed

## Deviations from Plan

None - plan executed exactly as written. No auto-fixes were required; Task 1's edit passed all acceptance criteria and the full suite on the first run.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 goal fully met: RH/Heat Index math lives in a single tested module (`heatwave/science/heat_index.py`), and `nigeria_heat_index.py` is a pure consumer with zero formula logic
- HIDX-01, HIDX-02 (plan 02-01) and HIDX-03 (this plan) are all complete and verifiable via automated tests
- Full suite (15 tests) green, ready for `/gsd:verify-work`
- Phase 3 (Climatology & Heatwave Detection) can import `heatwave.science.heat_index`'s stable `compute_relative_humidity`/`compute_heat_index` contract with no further changes needed
- No blockers identified

---
*Phase: 02-heat-index-relocation*
*Completed: 2026-09-13*

## Self-Check: PASSED

`nigeria_heat_index.py` exists with the import present and formula defs absent (confirmed via grep during execution). Commit `70e35ab` present in git log (`git log --oneline` verified below).
