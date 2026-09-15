# Phase 3: Climatology & Heatwave Detection - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-13
**Phase:** 3-climatology-heatwave-detection
**Areas discussed:** Test strategy (live-EE vs Nyquist), Phase scope (test scale vs production scale), Leap-year convention

---

## Test strategy: reconciling "live EE, never mocked" with fast feedback (CLIM-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Small synthetic live-EE baseline | Build tiny synthetic ee.Image time series (e.g. a handful of constructed days/years, one test ward) so calls are still real live Earth Engine computation — just tiny in scale, keeping tests fast without ever mocking the EE API itself | ✓ |
| Pure-Python reference reimplementation | Validate the percentile/pooling/event-grouping math with a fast numpy-based reference calculation, decoupled entirely from EE — fastest tests, but doesn't exercise the actual EE percentile reducer's specific interpolation behavior | |

**User's choice:** Small synthetic live-EE baseline (recommended option).
**Notes:** A real 30-year, 4,841-ward climatology test run would take minutes, far exceeding the ~30s Nyquist feedback-latency target established in Phase 1-2. Synthetic small-scale data keeps tests fast while still exercising the real `ee.Reducer.percentile()` behavior rather than approximating it.

---

## Phase scope: algorithm correctness vs production scale

| Option | Description | Selected |
|--------|-------------|----------|
| Correctness on a handful of test wards only | Phase 3 proves the algorithm is right via tests on a small sample (1-3 wards, synthetic or short real date ranges); the full-scale 4,841-ward/30-year run is explicitly Phase 4's job (matches EXPORT-01's wording) | ✓ |
| Validate against all 4,841 wards now | Run the climatology + detection functions across the full ward set as part of Phase 3, even though export/persistence is Phase 4 — more expensive now, but surfaces scale problems earlier | |

**User's choice:** Correctness on a handful of test wards only (recommended option).
**Notes:** Matches the roadmap's own phase boundary — Phase 4 (Batch Export) is explicitly where "the full pipeline across all 4,841 wards" runs (EXPORT-01). The functions themselves must still be ward-count-agnostic (D-04) so Phase 4 can call them unmodified at full scale.

---

## Leap-year / calendar-day convention

| Option | Description | Selected |
|--------|-------------|----------|
| Day-of-year 1-366, Feb 29 gets its own thin baseline | Standard WMO/ETCCDI-style approach: use day-of-year (1-366) as the calendar-day key; Feb 29 has fewer baseline years (~8 of 30) but still gets a real ±5-day pooled percentile, not a fallback | ✓ |
| Month-day matching, merge Feb 29 into Feb 28 | Simpler to implement; Feb 29 shares Feb 28's climatology threshold rather than having its own, avoiding the small-sample-size concern entirely | |

**User's choice:** Day-of-year 1-366, Feb 29 gets its own thin baseline (recommended option).
**Notes:** Consistent with the WMO/ETCCDI percentile-exceedance methodology already cited in PROJECT.md's "What This Is" section — this is the standard climate-science convention, not a simplification.

---

## Claude's Discretion

- Order of operations: zonal reduction before climatology computation (forced by the project's "per-ward" framing and EE computational tractability).
- Exact zonal reducer choice (mean, most likely) — confirm during research.
- Internal module boundaries within the two new `heatwave/science/` modules.
- Exact `ee.Reducer.percentile()` invocation/interpolation parameters — research territory.

## Deferred Ideas

None — discussion stayed within phase scope.
