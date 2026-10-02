# Phase 2: Heat Index Relocation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-13
**Phase:** 2-heat-index-relocation
**Areas discussed:** RH formula clamping, Test reference values

---

## RH formula clamping (carried from Phase 1 code review WR-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix it during relocation | Add .clamp(0, 100) to the RH output as part of the move — small, well-understood fix, and this is the natural point to do it since the code is already being touched and tested | ✓ |
| Relocate as-is, defer the fix | Keep HIDX-01 strictly to moving code unchanged; track the clamping fix as a separate future item | |

**User's choice:** Fix it during relocation (recommended option).
**Notes:** Directly motivated by Phase 1's 01-REVIEW.md WR-01 finding — the unclamped RH formula can produce values below 0% or above 100%, silently feeding into the Heat Index regression. Since Phase 2 already touches and tests this code, deferring the fix further would just re-flag the same known issue in a later phase's review.

---

## Test reference values (HIDX-02)

| Option | Description | Selected |
|--------|-------------|----------|
| NOAA's official Heat Index reference table | Use published NOAA/NWS lookup-table values (e.g. T=90°F, RH=50% → HI≈94°F) as ground truth — authoritative, independently verifiable, no risk of the test just re-deriving the same formula it's checking | ✓ |
| Self-computed reference values | Compute expected outputs by hand from the Rothfusz formula itself for a few chosen inputs | |

**User's choice:** NOAA's official Heat Index reference table (recommended option).
**Notes:** Avoids circularity — a test that only checks the formula against its own hand-computed output doesn't catch a transcription bug in the formula itself. Test inputs should be expressed in ERA5-Land-realistic units (Kelvin) so the test exercises the real unit-conversion path, not an idealized shortcut.

---

## Claude's Discretion

- Whether `compute_relative_humidity` gets its own direct unit test beyond the end-to-end Heat Index test (HIDX-02 only mandates the latter).
- Whether to also clean up code-review Info-level nits in `nigeria_heat_index.py` (unused imports, misleading `tempC` variable name) while the file is touched again for HIDX-03.
- Exact internal structure of `heatwave/science/heat_index.py` — follow the existing `heatwave/data/` subpackage convention.
- Live-EE test pattern for `tests/test_heat_index.py` — reuse Phase 1's `pytest.mark.skipif` credential-gating pattern.

## Deferred Ideas

None — discussion stayed within phase scope.
