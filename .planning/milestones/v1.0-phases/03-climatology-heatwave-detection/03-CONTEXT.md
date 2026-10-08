# Phase 3: Climatology & Heatwave Detection - Context

**Gathered:** 2026-09-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the pipeline's core new scientific capability: per-ward, per-calendar-day climatology baseline computation (90th percentile, 1991-2020, ±5-day pooling) and heatwave day/event detection (≥3 consecutive days above threshold), including zonal reduction from gridded ERA5-Land pixels to per-ward daily statistics. Delivers `heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, and `tests/test_heatwave_detection.py` (CLIM-01 through CLIM-06). This phase proves the algorithm is correct on a small scale — full 4,841-ward/30-year production execution is explicitly Phase 4's job (EXPORT-01).

</domain>

<decisions>
## Implementation Decisions

### Test strategy: reconciling "live EE, never mocked" with fast feedback (CLIM-06)
- **D-01:** Tests use small, synthetic, live Earth Engine computations — constructed `ee.Image`/`ee.ImageCollection` time series (a handful of synthetic days/years for 1 test ward), not real 30-year ERA5-Land pulls. This keeps every assertion running against the real EE API and real percentile reducer (never mocked, consistent with Phase 1-2 precedent), while staying within Nyquist's ~30s feedback-latency target.
- **D-02:** Do NOT build a pure-Python/numpy reference reimplementation of the percentile/pooling/event-grouping math as the primary test oracle — the actual `ee.Reducer.percentile()` interpolation behavior must be exercised directly, not approximated by a parallel implementation that could silently diverge from EE's real behavior.

### Phase 3 scope: algorithm correctness, not production scale (CLIM-01 through CLIM-05)
- **D-03:** Phase 3 proves correctness on a small sample (1-3 test wards, synthetic or short real date ranges) — it does NOT run the climatology/detection pipeline across all 4,841 wards or the full 1991-2020 baseline. Full-scale execution is explicitly out of scope here and belongs to Phase 4's `scripts/run_batch_export.py` (EXPORT-01).
- **D-04:** `heatwave/zonal.py`, `heatwave/science/climatology.py`, and `heatwave/science/heatwave.py` must be written as general, ward-count-agnostic functions (no hardcoded assumptions limiting them to the test scale) — the small-scale testing decision (D-03) is a testing/validation scope choice, not a code-scope limitation. Phase 4 will call these same functions at full scale without modification.

### Leap-year / calendar-day convention (CLIM-01, CLIM-02)
- **D-05:** Use day-of-year (1-366) as the calendar-day key for climatology, per the standard WMO/ETCCDI percentile-exceedance convention already cited in PROJECT.md. Feb 29 gets its own real ±5-day pooled percentile threshold computed from the ~8 leap years in the 1991-2020 baseline — it is not merged into or fallback-shared with Feb 28's threshold, despite the smaller sample size.
- **D-06:** The ±5-day pooling window must correctly wrap across day-of-year boundaries in both directions: near day 1 (pool includes late-December days ~361-366) and near day 366 (pool includes early-January days). Window arithmetic must handle this wraparound explicitly, not truncate at the array/range edges.

### Claude's Discretion
- Order of operations: zonal reduction (gridded pixels → per-ward daily mean Heat Index) happens BEFORE climatology percentile computation — the climatology baseline and day-flagging both operate on the per-ward daily time series, not on gridded pixel data directly. This follows directly from the project's "per-ward" framing (CLIM-01 says "per-ward, per-calendar-day") and is the only computationally tractable order in Earth Engine (computing percentiles across 4,841 ward-level time series is vastly cheaper than across millions of pixels).
- Exact zonal reducer choice for CLIM-05 (e.g., `ee.Reducer.mean()` over each ward's `ee.Geometry` for the daily Heat Index band) — mean is the natural choice for a representative ward-level daily value; confirm against `ee.Reducer` API during research.
- Internal module boundaries within `heatwave/science/climatology.py` vs `heatwave/science/heatwave.py` (e.g., whether percentile-threshold computation and day/event flagging are one function or several) — follow the established plain-function, no-class style from `heatwave/data/` and `heatwave/science/heat_index.py`.
- Exact `ee.Reducer.percentile()` invocation and any interpolation-method parameter needed to match a "90th percentile" definition precisely — research territory.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source docs
- `.planning/REQUIREMENTS.md` — CLIM-01 through CLIM-06 exact requirement text
- `.planning/PROJECT.md` — Constraints section: climatology parameters locked in `config.yaml` (baseline 1991-2020, 90th percentile, ±5-day pooling, ≥3-day events)
- `config.yaml` — `climatology.baseline_start_year`, `baseline_end_year`, `percentile`, `pooling_window_days`, `min_consecutive_days` (already defined, read not re-decided)

### Existing code this phase builds on
- `heatwave/science/heat_index.py` — the exact per-day, per-ward-eventually Heat Index values this phase's climatology is computed FROM; also the plain-function module style to replicate in the two new `heatwave/science/` modules
- `heatwave/data/boundary.py` — `load_ward_boundary()`, the `ee.FeatureCollection` this phase's zonal reduction operates over
- `heatwave/data/ingest.py` — `load_era5_land()`, the multi-band `ee.ImageCollection` this phase's Heat Index pipeline consumes
- `heatwave/config.py` — `settings.climatology.*` typed accessors, already implemented and tested (REWORK-07)
- `tests/test_heat_index.py` — the established skip-gated, live-EE, `pytest.approx`-tolerance test pattern to replicate for `tests/test_heatwave_detection.py`

No external specs/ADRs beyond the project's own docs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `heatwave/science/heat_index.py`'s `compute_heat_index()` — this phase's climatology operates on its output band (`heat_index`), not raw temperature/humidity.
- `heatwave.config.settings.climatology` — `ClimatologyConfig` dataclass already exposes `baseline_start_year=1991`, `baseline_end_year=2020`, `percentile=90`, `pooling_window_days=5`, `min_consecutive_days=3`. Use these, don't hardcode the numbers.

### Established Patterns
- Plain-function, no-class modules with `from __future__ import annotations`, module docstring, `import ee`, `from heatwave.config import settings` — established across `heatwave/data/` and `heatwave/science/heat_index.py`; new `heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py` should match.
- Skip-gated live-EE test pattern (`pytest.mark.skipif` on credential presence, explicit `init_ee()` call, `.getInfo()` before asserting, `pytest.approx` for tolerance) — established in `tests/test_integration.py` and `tests/test_heat_index.py`.

### Integration Points
- Phase 4's `scripts/run_batch_export.py` (not built yet) will call these three new modules' functions at full 4,841-ward, 30-year scale — signatures and behavior must be stable and ward-count-agnostic (D-04).
- `heatwave/zonal.py` sits between `heatwave/data/ingest.py`'s gridded output and `heatwave/science/climatology.py`'s per-ward time-series input — it is the boundary where "gridded pixels" become "per-ward daily values."

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this phase is backend algorithm work only, same as Phases 1-2. No Streamlit changes.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Full-scale (4,841-ward, 30-year) execution is explicitly deferred to Phase 4 per D-03, but that's already the documented roadmap boundary, not a new deferral.

</deferred>

---

*Phase: 03-climatology-heatwave-detection*
*Context gathered: 2026-09-13*
