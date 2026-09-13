# Phase 2: Heat Index Relocation - Context

**Gathered:** 2026-09-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Move the RH/Heat-Index computation logic out of `nigeria_heat_index.py` and into a tested `heatwave/science/heat_index.py` module (HIDX-01, HIDX-02, HIDX-03). This is primarily a relocation, not a rewrite — with one explicitly scoped correctness fix (RH clamping) carried forward from Phase 1's code review.

</domain>

<decisions>
## Implementation Decisions

### RH formula fix (carried from Phase 1 code review WR-01)
- **D-01:** Add `.clamp(0, 100)` to the relative-humidity output (`100 - 5*(T-D)`) as part of the relocation into `heatwave/science/heat_index.py`. This is a deliberate, scoped exception to "relocated not rewritten" — the code is already being touched and tested here, so this is the natural point to fix a known correctness issue rather than deferring it further.
- **D-02:** No other behavioral changes beyond the clamp — the RH approximation formula itself (`100 - 5*(T-D)`), the Rothfusz Heat Index regression coefficients, and all other logic move verbatim.

### Test reference values (HIDX-02)
- **D-03:** Use NOAA/NWS's official published Heat Index reference table values as the ground truth for `tests/test_heat_index.py`'s known input/output assertions — not self-derived values. This avoids the test just re-deriving and checking against the same formula it's meant to validate.
- **D-04:** Test inputs should be expressed as ERA5-Land-realistic values (Kelvin temperature, matching the actual data pipeline) that convert to the Fahrenheit/RH pairs found in the NOAA table, so the test exercises the same unit-conversion path as production code, not an idealized shortcut.

### Claude's Discretion
- Whether `compute_relative_humidity` needs its own direct unit test or is sufficiently covered by the end-to-end Heat Index test (HIDX-02 only mandates testing "the Rothfusz Heat Index formula" — RH test coverage is additive, not required).
- Whether to also clean up the code-review Info-level nits already present in `nigeria_heat_index.py` (unused `Template`/`MacroElement` imports, the misleading `tempC`-holds-Kelvin variable name) while the file is being touched again for HIDX-03 — low-risk, high-value opportunistic cleanup, but not a hard requirement.
- Exact module-level structure of `heatwave/science/heat_index.py` (e.g., whether RH and Heat Index are separate functions or one combined pipeline function) — follow the existing `heatwave/data/` subpackage convention (plain functions, no classes, `from __future__ import annotations`, module docstring).
- Live-EE test pattern for `tests/test_heat_index.py` — since RH/Heat-Index math operates on `ee.Image`/`ee.Number` objects (server-side), tests inherently require an initialized EE session; follow Phase 1's established `pytest.mark.skipif` credential-gating pattern from `tests/test_integration.py` rather than inventing a new one.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source docs
- `.planning/REQUIREMENTS.md` — HIDX-01, HIDX-02, HIDX-03 exact requirement text
- `.planning/phases/01-foundation-rework/01-REVIEW.md` — WR-01 finding (unclamped RH formula) that motivates D-01
- `.planning/phases/01-foundation-rework/01-03-SUMMARY.md` — the `pytest.mark.skipif` credential-gating pattern to replicate for `tests/test_heat_index.py`

### Existing code this phase touches
- `nigeria_heat_index.py` — current inline `compute_relative_humidity()` and `compute_heat_index()` (lines 32-66) to be relocated; also needs its import updated per HIDX-03
- `heatwave/data/boundary.py` — reference for this codebase's plain-function, no-class module style to replicate in `heatwave/science/heat_index.py`
- `heatwave/config.py` — `settings.bands.tmean` / `settings.bands.dewpoint` band-name references used by the RH computation, unchanged
- `tests/test_integration.py` — the established live-EE, skip-gated test pattern from Phase 1 to follow for `tests/test_heat_index.py`

No external specs/ADRs beyond the project's own docs — the NOAA Heat Index reference table (D-03) is an external authoritative source the test author should look up (e.g., NOAA/NWS Heat Index chart), not a repo file.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `heatwave/data/boundary.py` and `heatwave/data/ingest.py` — both plain-function modules with a docstring header, `from __future__ import annotations`, and direct `ee`-object return types. `heatwave/science/heat_index.py` should match this style.
- `settings.bands.tmean` / `settings.bands.dewpoint` from `heatwave/config.py` — already the correct band-name accessors; no change needed.

### Established Patterns
- ERA5-Land temperature bands are in Kelvin (confirmed by Phase 1 research), but the RH formula's Celsius/Kelvin distinction cancels out in the `T - D` subtraction — this is a naming-clarity issue only (the reviewer's Info finding), not a functional bug; no fix required for correctness, only for the optional cleanup covered under Claude's Discretion.
- Phase 1 established the `pytest.mark.skipif` module-level gate pattern in `tests/test_integration.py` for tests requiring live GCP credentials — reuse this exact pattern, don't invent a new one.

### Integration Points
- `nigeria_heat_index.py` currently defines and calls `compute_relative_humidity`/`compute_heat_index` inline (lines 32-66) — after relocation, it must import from `heatwave.science.heat_index` and still boot cleanly (HIDX-03, re-verified the same way Phase 1's REWORK-08 was: `streamlit.testing.v1.AppTest` in-process boot check).
- Phase 3 (Climatology & Heatwave Detection) will consume `heatwave/science/heat_index.py`'s output directly — keep its public function signature(s) stable and clearly named, since Phase 3's planner will read this module.

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this phase is backend correctness/refactor only, same as Phase 1. The only user-facing surface check is the unchanged Streamlit boot behavior (HIDX-03).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-heat-index-relocation*
*Context gathered: 2026-09-13*
