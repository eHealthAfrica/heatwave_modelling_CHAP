---
phase: 02-heat-index-relocation
plan: 01
subsystem: science
tags: [earth-engine, ee.Image, heat-index, relative-humidity, pytest, tdd]

# Dependency graph
requires:
  - phase: 01-foundation-rework
    provides: heatwave.auth.init_ee(), heatwave.config.settings.bands.*, heatwave.data.load_era5_land()
provides:
  - heatwave/science/heat_index.py exporting compute_relative_humidity() and compute_heat_index() over ee.Image
  - D-01 RH clamp fix ([0, 100] range enforcement on the single-band expression result)
  - tests/test_heat_index.py verifying Rothfusz Heat Index against 3 NOAA/NWS table values plus D-01 clamp boundaries
affects: [02-02 (nigeria_heat_index.py import update), phase-3-climatology-and-heatwave-detection]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Plain-function science module style matching heatwave/data/ (module docstring, from __future__ import annotations, no classes)"
    - "Per-test pytest.mark.skipif credential gate (not module-level pytestmark) so a credential-free export test can still run"

key-files:
  created:
    - heatwave/science/__init__.py
    - heatwave/science/heat_index.py
    - tests/test_heat_index.py
  modified: []

key-decisions:
  - "D-01/D-02 upheld: .clamp(0, 100) applied only to the single-band RH expression result, before addBands; zero other arithmetic changed"
  - "tempC->tempK identifier rename applied (IN-01) per Task 2's explicit instruction; touched zero arithmetic"
  - "Credential gate applied per-test via a named _REQUIRES_CREDENTIALS decorator rather than module-level pytestmark, so test_science_module_exports (HIDX-01) runs without live GCP credentials"

patterns-established:
  - "science/ subpackage for domain math, following the existing data/ subpackage convention"

requirements-completed: [HIDX-01, HIDX-02]

# Metrics
duration: ~7min
completed: 2026-09-13
---

# Phase 2 Plan 1: Heat Index Relocation Summary

**Relocated RH/Heat Index math into `heatwave/science/heat_index.py` with the D-01 `[0,100]` RH clamp, verified against 3 NOAA/NWS Heat Index table values and 3 clamp-boundary tests using ERA5-Land-realistic Kelvin fixtures.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-09-13T12:13:44Z
- **Completed:** 2026-09-13T12:20:38Z
- **Tasks:** 2 completed
- **Files modified:** 3 (2 created source, 1 created test)

## Accomplishments
- `heatwave/science/heat_index.py` created with `compute_relative_humidity()` and `compute_heat_index()`, relocated verbatim from `nigeria_heat_index.py` (lines 33-64) except for the D-01 clamp and the `tempC`->`tempK` rename
- `tests/test_heat_index.py` proves correctness against 3 independently-published NOAA/NWS table values (96F/50%->108F, 100F/40%->109F, 90F/70%->105F) within +/-1.5F tolerance, plus 3 D-01 clamp-boundary tests (above 100, below 0, source-band integrity)
- Full test suite (15 tests) green; live-EE tests ran against the real `heatwave-508110` project

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the failing NOAA-table and clamp-boundary test suite (RED)** - `a1a93df` (test)
2. **Fixture ordering bug fix (Rule 1 auto-fix)** - `b71044c` (fix)
3. **Task 2: Relocate RH/Heat-Index math into heatwave/science/heat_index.py with the D-01 clamp (GREEN)** - `fd5b7fb` (feat)

_TDD gate sequence confirmed in git log: test (a1a93df) -> fix (b71044c) -> feat (fd5b7fb)._

## Files Created/Modified
- `tests/test_heat_index.py` - 7 tests: HIDX-01 export check (credential-free) + 3 NOAA table Heat Index assertions + 3 D-01 clamp-boundary assertions
- `heatwave/science/__init__.py` - zero-byte package marker
- `heatwave/science/heat_index.py` - `compute_relative_humidity()` (RH formula + D-01 clamp) and `compute_heat_index()` (Rothfusz regression, verbatim coefficients)

## Decisions Made
- D-01/D-02 upheld exactly as specified: `.clamp(0, 100)` on the single-band RH expression result only, before `addBands`; no other formula changes
- Applied the `tempC`->`tempK` rename per Task 2's explicit action text (touched zero arithmetic, verified via `273.15` appearing exactly once and `tempC` appearing zero times)
- Kept the dead `.set('system:time_start', ...)` call per D-02 (not sanctioned for removal this phase)
- Per-test credential gate (not module-level `pytestmark`) so `test_science_module_exports` runs without live GCP credentials, per 02-VALIDATION.md's requirement

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected tmean/tmax band value ordering in `_make_test_image` test fixture helper**
- **Found during:** Task 2 GREEN verification (5 of 7 tests failed unexpectedly after implementation)
- **Issue:** The plan's own action text, PATTERNS.md, and RESEARCH.md all specify `ee.Image.constant([tmean_k, 0, dewpoint_k]).rename([settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint])`, with prose claiming "the middle placeholder 0 occupies the tmax slot." By positional pairing, the middle value (`0`) actually maps to the **tmean** name, not tmax — so every test image's `tmean` band held `0` instead of the intended Kelvin fixture value, corrupting every Heat Index computation and the source-band-integrity check (independent of the clamp fix being verified).
- **Fix:** Reordered the constant value list to `[0, tmean_k, dewpoint_k]` so `tmax`=0 (placeholder), `tmean`=tmean_k, `dewpoint`=dewpoint_k, matching the stated intent.
- **Files modified:** `tests/test_heat_index.py`
- **Verification:** All 7 tests pass after the fix; full 15-test suite green
- **Committed in:** `b71044c`

**2. [Minor, non-blocking] `EE_SA_JSON` grep-count acceptance criterion not literally satisfiable**
- **Found during:** Task 1 acceptance criteria check
- **Issue:** Plan's acceptance criteria states `grep -F -c "EE_SA_JSON" tests/test_heat_index.py` returns 1, but the mandated skip-gate pattern (copied verbatim from `tests/test_integration.py`'s `_HAS_CREDENTIALS`/`pytestmark` structure per the `<action>` instructions) inherently produces the string on two lines (the `os.getenv("EE_SA_JSON")` call and the skip reason string). `tests/test_integration.py` itself yields 3 for the same grep, confirming this criterion doesn't match the established pattern it asks to replicate.
- **Resolution:** Not fixed — following the mandated pattern faithfully was prioritized over an unsatisfiable literal grep count; no functional impact (EE_SA_JSON gating behavior is correct and tested).
- **Files modified:** None (informational only)

---

**Total deviations:** 1 auto-fixed (1 bug), 1 informational (unsatisfiable acceptance criterion, no functional impact)
**Impact on plan:** The fixture bug fix was necessary for correctness — without it, the test suite would have silently validated the wrong band values. No scope creep.

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `heatwave/science/heat_index.py`'s `compute_relative_humidity`/`compute_heat_index` signatures are now the stable contract Phase 3 (Climatology & Heatwave Detection) will import against
- Plan 02-02 (updating `nigeria_heat_index.py` to import from `heatwave.science.heat_index` instead of defining inline, HIDX-03) can now proceed — `nigeria_heat_index.py` was intentionally left untouched by this plan
- No blockers identified

---
*Phase: 02-heat-index-relocation*
*Completed: 2026-09-13*

## Self-Check: PASSED

All created files exist (`heatwave/science/__init__.py`, `heatwave/science/heat_index.py`, `tests/test_heat_index.py`) and all referenced commit hashes (`a1a93df`, `b71044c`, `fd5b7fb`) are present in git log.
