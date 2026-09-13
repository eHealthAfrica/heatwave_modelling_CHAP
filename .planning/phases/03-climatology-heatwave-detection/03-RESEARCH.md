# Phase 3: Climatology & Heatwave Detection - Research

**Researched:** 2026-09-13
**Domain:** Google Earth Engine server-side time-series analysis (day-of-year climatology, percentile-exceedance heatwave detection, zonal statistics)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Test strategy: reconciling "live EE, never mocked" with fast feedback (CLIM-06)
- **D-01:** Tests use small, synthetic, live Earth Engine computations -- constructed `ee.Image`/`ee.ImageCollection` time series (a handful of synthetic days/years for 1 test ward), not real 30-year ERA5-Land pulls. This keeps every assertion running against the real EE API and real percentile reducer (never mocked, consistent with Phase 1-2 precedent), while staying within Nyquist's ~30s feedback-latency target.
- **D-02:** Do NOT build a pure-Python/numpy reference reimplementation of the percentile/pooling/event-grouping math as the primary test oracle -- the actual `ee.Reducer.percentile()` interpolation behavior must be exercised directly, not approximated by a parallel implementation that could silently diverge from EE's real behavior.

### Phase 3 scope: algorithm correctness, not production scale (CLIM-01 through CLIM-05)
- **D-03:** Phase 3 proves correctness on a small sample (1-3 test wards, synthetic or short real date ranges) -- it does NOT run the climatology/detection pipeline across all 4,841 wards or the full 1991-2020 baseline. Full-scale execution is explicitly out of scope here and belongs to Phase 4's `scripts/run_batch_export.py` (EXPORT-01).
- **D-04:** `heatwave/zonal.py`, `heatwave/science/climatology.py`, and `heatwave/science/heatwave.py` must be written as general, ward-count-agnostic functions (no hardcoded assumptions limiting them to the test scale) -- the small-scale testing decision (D-03) is a testing/validation scope choice, not a code-scope limitation. Phase 4 will call these same functions at full scale without modification.

### Leap-year / calendar-day convention (CLIM-01, CLIM-02)
- **D-05:** Use day-of-year (1-366) as the calendar-day key for climatology, per the standard WMO/ETCCDI percentile-exceedance convention already cited in PROJECT.md. Feb 29 gets its own real ±5-day pooled percentile threshold computed from the ~8 leap years in the 1991-2020 baseline -- it is not merged into or fallback-shared with Feb 28's threshold, despite the smaller sample size.
- **D-06:** The ±5-day pooling window must correctly wrap across day-of-year boundaries in both directions: near day 1 (pool includes late-December days ~361-366) and near day 366 (pool includes early-January days). Window arithmetic must handle this wraparound explicitly, not truncate at the array/range edges.

### Claude's Discretion
- Order of operations: zonal reduction (gridded pixels -> per-ward daily mean Heat Index) happens BEFORE climatology percentile computation -- the climatology baseline and day-flagging both operate on the per-ward daily time series, not on gridded pixel data directly. This follows directly from the project's "per-ward" framing (CLIM-01 says "per-ward, per-calendar-day") and is the only computationally tractable order in Earth Engine (computing percentiles across 4,841 ward-level time series is vastly cheaper than across millions of pixels).
- Exact zonal reducer choice for CLIM-05 (e.g., `ee.Reducer.mean()` over each ward's `ee.Geometry` for the daily Heat Index band) -- mean is the natural choice for a representative ward-level daily value; confirm against `ee.Reducer` API during research.
- Internal module boundaries within `heatwave/science/climatology.py` vs `heatwave/science/heatwave.py` (e.g., whether percentile-threshold computation and day/event flagging are one function or several) -- follow the established plain-function, no-class style from `heatwave/data/` and `heatwave/science/heat_index.py`.
- Exact `ee.Reducer.percentile()` invocation and any interpolation-method parameter needed to match a "90th percentile" definition precisely -- research territory.

### Deferred Ideas (OUT OF SCOPE)

None -- discussion stayed within phase scope. Full-scale (4,841-ward, 30-year) execution is explicitly deferred to Phase 4 per D-03, but that's already the documented roadmap boundary, not a new deferral.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| CLIM-01 | Per-ward, per-calendar-day climatology baseline is computed from the 1991-2020 Heat Index record | Pattern 2 (day-of-year extraction), Pattern 4 (climatology percentile computation), verified live end-to-end in the combined pipeline test |
| CLIM-02 | The climatology baseline applies a ±5-day pooling window around each calendar day | Pattern 3 (wraparound pooling window), Pitfall 2 (floor-mod requirement) -- verified live including the day-1/day-366 wraparound case |
| CLIM-03 | Each day is flagged as a heatwave day when its Heat Index exceeds the ward's 90th-percentile threshold for that calendar day | Pattern 5 (threshold join + exceedance flag) -- verified live with a 2-ward, 5-day synthetic dataset |
| CLIM-04 | Consecutive heatwave days are grouped into events; only runs of ≥3 consecutive days count as an event | Pattern 6 (consecutive-run detection via `List.iterate()`) -- verified live, including the ≥3-day filter logic |
| CLIM-05 | Gridded ERA5-Land Heat Index values are correctly reduced to per-ward daily statistics via zonal reduction (`heatwave/zonal.py`) | Pattern 1 (zonal reduction), Pitfall 4 (small-ward null-result risk) -- verified live against the real ERA5-Land collection's nominal scale |
| CLIM-06 | `tests/test_heatwave_detection.py` validates climatology computation and day/event detection against synthetic/known test cases | Validation Architecture section; Wave 0 Gaps; established test pattern from `tests/test_heat_index.py` |
</phase_requirements>

## Summary

Phase 3 builds the pipeline's core scientific algorithm: reduce gridded ERA5-Land Heat Index pixels to per-ward daily values, compute a per-ward, per-calendar-day 90th-percentile climatology baseline (1991-2020, ±5-day pooling), and flag/group consecutive exceedance days into heatwave events (≥3 days). Every core idiom needed for this was verified live against the real `heatwave-508110` Earth Engine project during this research session (not just read from docs) — a full end-to-end synthetic pipeline (3 years × 2 wards × wraparound-window pooling × grouped percentile) was executed and produced correct, sane results.

The most important finding, with direct implications for D-02: **`ee.Reducer.percentile()` does NOT match numpy's default percentile interpolation.** For the sample `[1..10]`, EE's percentile(90) returns `9.5` while `numpy.percentile(vals, 90)` (default `linear` method) returns `9.1`. This confirms the CONTEXT.md decision to avoid a parallel numpy reference implementation as a test oracle — it would silently diverge from EE's real behavior. Tests must assert against values computed by constructing a second, independently-verifiable EE reducer call (e.g., a manually sorted small sample where the expected EE percentile value is hand-calculated using EE's own documented rule), not against numpy.

The second most important finding is a **hard API constraint, not a stylistic choice**: `ee.Filter.calendarRange(start, end, 'day_of_year')` (and `ee.Filter.dayOfYear()`) derive the day-of-year **from each element's `system:time_start` timestamp**, not from an arbitrary integer property. Every feature in the per-ward-daily `FeatureCollection` that `heatwave/zonal.py` produces MUST carry `system:time_start` (as millis), or the climatology pooling filter in `heatwave/science/climatology.py` will fail outright with `Collection.filter: Can't apply calendarRange filter to objects without a timestamp.` (verified live). Both `calendarRange` and `dayOfYear` natively support wraparound when `start > end` (verified live: `calendarRange(363, 5, 'day_of_year')` correctly matched Dec 30–31 and Jan 1–5) — so no manual `ee.Filter.or()` combination is needed once wrapped start/end values are computed, but the wrapping arithmetic itself must be done manually with a floor-mod helper because `ee.Number.mod()` does NOT floor negative numbers the way Python's `%` does (verified live: `ee.Number(-3).mod(366)` returns `-3`, not `363`).

**Primary recommendation:** Build the ward-daily table as one flat `ee.FeatureCollection` with `system:time_start` + `ward_id` + `doy` + the zonally-reduced value on every feature; compute climatology thresholds with `ee.List.sequence(1, 366).map(...)` doing one `calendarRange`-filtered, `Reducer.group()`-by-ward percentile call per calendar day (not a nested per-ward loop); join thresholds back to daily values with `ee.Join.saveFirst()` keyed on `(ward_id, doy)`; detect consecutive-day runs with a `List.iterate()` state-machine (verified correct and fast enough — 3,650-element list in ~2s).

## Architectural Responsibility Map

This project is a batch geospatial pipeline, not a multi-tier web app. The "tiers" below are pipeline stages, not client/server layers — this mapping exists to catch capability misassignment between EE server-side computation and Python client orchestration.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Zonal reduction (gridded pixels → per-ward daily value) | EE server-side (`Image.reduceRegions`) | Python orchestration (`heatwave/zonal.py` wraps the call) | Must run inside EE — pulling raw pixels to Python first is intractable at 4,841-ward/30-year scale |
| Climatology percentile computation | EE server-side (`Reducer.percentile` + `Reducer.group`) | Python orchestration (`heatwave/science/climatology.py`) | Percentile-over-pooled-window must be computed by EE's real reducer per D-02; Python only assembles the `ee.List.sequence` loop |
| Day-of-year / wraparound arithmetic | EE server-side (`ee.Number`, `ee.Algorithms.If`) | — | Must stay server-side because it feeds directly into a server-side `Filter.calendarRange` call inside a `.map()`; a client-computed Python day-of-year list works too (see Pattern 2 Alternative) but the server-side version keeps the whole climatology computation in one EE computation graph, avoiding 366 round-trips |
| Threshold-to-day join | EE server-side (`ee.Join.saveFirst`) | — | Both sides of the join are `ee.FeatureCollection` objects; no client-side pandas join needed or appropriate |
| Consecutive-day run detection | EE server-side (`ee.List.iterate`) | Python (only if list length becomes impractical for `.iterate()` at full 30-year scale — see Pitfall 5) | Verified working server-side at test scale; flagged as an open question for Phase 4's full 10,950-day series |
| Config-driven parameters (percentile, pooling window, min consecutive days, baseline years) | Python (`heatwave.config.settings.climatology`) | — | Already implemented (REWORK-07); this phase's functions must read from `settings.climatology`, never hardcode `90`/`5`/`3`/`1991`/`2020` |
| Test orchestration / credential gating | Python (`pytest`, skip-gated) | — | Established pattern from `tests/test_heat_index.py` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `earthengine-api` | 1.6.8 [VERIFIED: local venv `import ee; ee.__version__`] | Server-side percentile/grouping/join/iterate reducers and filters | Already the project's sole geospatial compute engine (Phases 1-2); no alternative under consideration |
| `pytest` | already installed [ASSUMED: version not re-checked this session, unchanged since Phase 2] | Skip-gated live-EE test runner | Established pattern (`tests/test_heat_index.py`, `tests/test_integration.py`) |

### Supporting
No new supporting libraries are needed. This phase is pure Earth Engine server-side computation plus the existing `heatwave.config.settings` typed accessor — no numpy, pandas, or scipy percentile/date logic should be introduced as production code (see Don't Hand-Roll).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ee.List.iterate()` state-machine for run detection | `ee.Array` forward-difference/run-length trick (Gorelick, "Runs with Arrays") [CITED: medium.com/google-earth/runs-with-arrays-400de937510a — page returned HTTP 403 to automated fetch this session; description sourced from search-engine summary only, LOW confidence on exact code] | Array trick is the more idiomatic/performant EE pattern for very long series; `.iterate()` was verified directly in this session and is simpler to reason about for Phase 3's small scale. Revisit for Phase 4 if 30-year (~10,950-element) per-ward `.iterate()` proves slow. |
| Reducer.group() grouped percentile (one call per day, all wards at once) | Nested `wards.map(ward -> days.map(day -> ...))` loop | Nested loop is O(wards × days) separate `reduceColumns` calls — verified the grouped approach does all wards for one day in a single call, which is the ward-count-agnostic, full-scale-friendly pattern D-04 requires |

**Installation:** No new packages to install — `earthengine-api` and `pytest` are already in `requirements.txt`/the venv.

**Version verification:** `earthengine-api==1.6.8` confirmed via `python -c "import ee; print(ee.__version__)"` in the project's own `.venv` [VERIFIED: local environment].

## Package Legitimacy Audit

**Not applicable — this phase introduces zero new external package dependencies.** It exclusively uses `earthengine-api` (already installed and audited in Phase 1) and `pytest` (already installed, used in Phases 1-2). No `pip install`, no `slopcheck` run, and no registry verification is required for this phase's Standard Stack.

## Architecture Patterns

### System Architecture Diagram

```
                 ┌─────────────────────────────────────────────┐
                 │  heatwave/data/ingest.py (existing, Phase 1) │
                 │  ee.ImageCollection: gridded, multi-band,    │
                 │  date-filtered, boundary-clipped ERA5-Land   │
                 └───────────────────┬───────────────────────────┘
                                     │ .map(compute_relative_humidity → compute_heat_index)
                                     ▼
                 ┌─────────────────────────────────────────────┐
                 │  heatwave/science/heat_index.py (existing)   │
                 │  adds 'heat_index' band per image             │
                 └───────────────────┬───────────────────────────┘
                                     │ ee.ImageCollection (heat_index band)
                                     ▼
                 ┌─────────────────────────────────────────────┐
                 │  heatwave/zonal.py  (NEW — CLIM-05)           │
                 │  .map(image.reduceRegions(wards, mean, scale))│
                 │  → flatten into ONE ee.FeatureCollection:     │
                 │  rows = (ward_id, system:time_start, doy,     │
                 │          mean_heat_index)                     │
                 └───────────────────┬───────────────────────────┘
                                     │ ward-daily FeatureCollection (all years)
                        ┌────────────┴─────────────┐
                        │                            │
                        ▼                            ▼
     ┌───────────────────────────────┐   ┌───────────────────────────────┐
     │ heatwave/science/climatology.py│   │ (same table, full date range) │
     │ (NEW — CLIM-01, CLIM-02)       │   │ used directly as "daily       │
     │ filter to baseline years       │   │ values to flag" input below   │
     │ (1991-2020) →                  │   └───────────────┬───────────────┘
     │ ee.List.sequence(1,366).map(   │                    │
     │   day -> wrapped ±5 window ->  │                    │
     │   calendarRange filter ->      │                    │
     │   Reducer.percentile(90)       │                    │
     │     .group(by ward_id) )       │                    │
     │ → climatology FeatureCollection│                    │
     │   rows = (ward_id, doy, p90)   │                    │
     └───────────────┬─────────────────┘                    │
                     │                                       │
                     └──────────────┬────────────────────────┘
                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │  heatwave/science/heatwave.py (NEW —          │
                 │  CLIM-03, CLIM-04)                            │
                 │  1. ee.Join.saveFirst on (ward_id, doy) →     │
                 │     attach threshold to each daily row        │
                 │  2. is_hot = value > threshold                │
                 │  3. per ward: sort by date, List.iterate()    │
                 │     state machine → consecutive-run group ids │
                 │  4. filter runs where length >= 3 (min_       │
                 │     consecutive_days) → final heatwave-day    │
                 │     flags + event groupings                   │
                 └─────────────────────────────────────────────┘
                                    │
                                    ▼
                    (Phase 4: scripts/run_batch_export.py
                     calls these same functions at full scale,
                     aggregates to weekly covariate table)
```

### Recommended Project Structure
```
heatwave/
├── zonal.py                    # NEW: gridded -> per-ward-daily FeatureCollection
└── science/
    ├── heat_index.py           # existing (Phase 2)
    ├── climatology.py          # NEW: per-ward, per-calendar-day p90 threshold
    └── heatwave.py             # NEW: threshold join, day flagging, event detection
tests/
└── test_heatwave_detection.py  # NEW: CLIM-06, synthetic live-EE tests
```

### Pattern 1: Zonal reduction — gridded pixels to per-ward daily rows
**What:** For each image (day) in the Heat Index `ImageCollection`, call `image.reduceRegions()` once against the full ward `FeatureCollection`, then flatten all days into one long-format table.
**When to use:** Always — this is the CLIM-05 boundary between gridded and per-ward data, and must run before any climatology/detection logic (Claude's Discretion, confirmed sound).
**Example (verified live against `heatwave-508110`):**
```python
# Source: verified live, ee.Image.reduceRegions apidocs
# https://developers.google.com/earth-engine/apidocs/ee-image-reduceregions
def reduce_to_ward_daily(image_collection, wards, band="heat_index", scale=11132):
    def reduce_one_day(image):
        date = image.date()
        doy = date.getRelative("day", "year").add(1)  # 1-366, verified live
        reduced = image.select(band).reduceRegions(
            collection=wards, reducer=ee.Reducer.mean(), scale=scale
        )
        return reduced.map(
            lambda f: f.set(
                "doy", doy,
                "system:time_start", date.millis(),  # REQUIRED for calendarRange later
            )
        )

    return ee.FeatureCollection(image_collection.map(reduce_one_day)).flatten()
```
`scale=11132` matches ERA5-Land's verified nominal pixel scale (`image.projection().nominalScale()` → `11131.949...` [VERIFIED: live call against `ECMWF/ERA5_LAND/DAILY_AGGR`]).

### Pattern 2: Day-of-year extraction (1-366, WMO/ETCCDI-style)
**What:** `ee.Date.getRelative('day', 'year')` returns a 0-based day offset; add 1 for the 1-366 convention D-05 requires.
**Verified live behavior (leap vs. non-leap divergence after Feb, exactly as D-05 anticipates):**
```python
# Source: verified live against heatwave-508110
ee.Date("2020-02-29").getRelative("day", "year").getInfo()  # 59 -> doy 60 (leap year)
ee.Date("2020-03-01").getRelative("day", "year").getInfo()  # 60 -> doy 61 (leap year)
ee.Date("2021-03-01").getRelative("day", "year").getInfo()  # 59 -> doy 60 (non-leap year)
```
Feb 29 gets doy=60 in leap years and does not exist in non-leap years — this is exactly the "Feb 29 gets its own real slot, not merged" behavior D-05 locks in, using the simplest possible EE idiom. No custom calendar-remapping logic is needed.

### Pattern 3: ±N-day pooling window with correct wraparound (D-06)
**What:** `ee.Number.mod()` does NOT floor-mod negative numbers (`ee.Number(-3).mod(366)` → `-3`, verified live — this is truncated/JS-style modulo, not Python's `%`). A floor-mod helper is required before handing values to `calendarRange`.
**Critical constraint (verified live):** `ee.Filter.calendarRange(start, end, 'day_of_year')` reads day-of-year from **`system:time_start`**, not from any custom property. Calling it on a `FeatureCollection` whose features lack `system:time_start` raises `Collection.filter: Can't apply calendarRange filter to objects without a timestamp.` — verified by direct reproduction.
**Wraparound is native once inputs are normalized** — `calendarRange(363, 5, 'day_of_year')` (start > end) correctly matched both Dec 30-31 and Jan 1-5 in a live test; no `ee.Filter.or()` needed.
```python
# Source: verified live against heatwave-508110
def floor_mod(n, m):
    n = ee.Number(n)
    r = n.mod(m)
    return ee.Number(ee.Algorithms.If(r.lt(0), r.add(m), r))

def wrapped_day(n):
    """Map any integer day offset onto the 1-366 range, wrapping correctly
    in both directions (verified: -3 -> 363, 367 -> 1, 730 -> 364)."""
    n = ee.Number(n)
    return floor_mod(n.subtract(1), 366).add(1)

def pooling_window_filter(doy, window_days):
    doy = ee.Number(doy)
    start = wrapped_day(doy.subtract(window_days))
    end = wrapped_day(doy.add(window_days))
    return ee.Filter.calendarRange(start, end, "day_of_year")
```
Full end-to-end verification: for a 3-synthetic-year (2018/2019/leap-2020), 2-ward dataset covering only Jan 1-10 and Dec 27-31, querying `doy=366` (which only exists in 2020) still produced a sensible pooled 90th-percentile threshold — because its ±5 window correctly wrapped to include 3 years of Dec 27-31 and Jan 1-5 data (verified live, 6-row combined output, values matched the synthetic generators' expected ranges for both wards).

### Pattern 4: Climatology percentile, computed for all wards in one pass per calendar day
**What:** Use `ee.List.sequence(1, 366).map(...)`, and inside the per-day function use `reduceColumns` with `Reducer.percentile([90]).group(groupField, groupName)` to get one percentile per ward per day in a single reducer call — not a nested wards × days loop. Also filter to the baseline years (1991-2020) via `ee.Filter.calendarRange(startYear, endYear, 'year')` before pooling.
```python
# Source: verified live against heatwave-508110
def compute_climatology_thresholds(ward_daily_fc, percentile=90, window_days=5,
                                    baseline_start_year=1991, baseline_end_year=2020):
    baseline = ward_daily_fc.filter(
        ee.Filter.calendarRange(baseline_start_year, baseline_end_year, "year")
    )

    def threshold_for_day(doy):
        doy = ee.Number(doy)
        pooled = baseline.filter(pooling_window_filter(doy, window_days))
        grouped = pooled.reduceColumns(
            reducer=ee.Reducer.percentile([percentile]).group(
                groupField=1, groupName="ward_id"
            ),
            selectors=["value", "ward_id"],
        )
        groups = ee.List(grouped.get("groups"))
        return groups.map(
            lambda g: ee.Feature(
                None,
                {"doy": doy, "ward_id": ee.Dictionary(g).get("ward_id"),
                 "p90": ee.Dictionary(g).get(f"p{percentile}")},
            )
        )

    days = ee.List.sequence(1, 366)
    return ee.FeatureCollection(ee.List(days.map(threshold_for_day)).flatten())
```
Verified live: `groupField=1` refers to the **index into the `selectors` list** (`['value', 'ward_id']` → index 1 = `ward_id`), not a literal property name — confirmed by output correctly separating ward `'A'` and `'B'` percentiles from an interleaved 20-row test collection.

### Pattern 5: Join threshold to daily value, flag exceedance
**What:** `ee.Join.saveFirst('clim_match').apply(primary, secondary, filter)` performs an attribute-only (non-spatial) equi-join between two `FeatureCollection`s.
```python
# Source: verified live against heatwave-508110
join_filter = ee.Filter.And(
    ee.Filter.equals(leftField="ward_id", rightField="ward_id"),
    ee.Filter.equals(leftField="doy", rightField="doy"),
)
joined = ee.Join.saveFirst("clim_match").apply(ward_daily_fc, climatology_fc, join_filter)

def flag_hot(f):
    f = ee.Feature(f)
    threshold = ee.Feature(f.get("clim_match")).get("p90")
    return f.set("threshold", threshold, "is_hot", ee.Number(f.get("value")).gt(ee.Number(threshold)))

flagged = joined.map(flag_hot)
```
Verified live with a 2-ward, 5-day synthetic dataset — join and threshold comparison produced correct `is_hot` values matching hand-computed expectations for every row.

### Pattern 6: Consecutive-day run detection (≥3-day event grouping, CLIM-04)
**What:** Earth Engine has no native stateful "run-length" primitive. The verified working approach is a `List.iterate()` state machine carrying `[prevFlag, currentGroupId, tagsSoFar]`, incrementing the group id each time a `0→1` transition occurs.
```python
# Source: verified live against heatwave-508110, pattern independently derived and
# empirically verified (not copied from a specific doc page — see State of the Art)
def _run_group_step(curr, state):
    state = ee.List(state)
    prev_flag = ee.Number(state.get(0))
    group_id = ee.Number(state.get(1))
    tags_so_far = ee.List(state.get(2))
    curr = ee.Number(curr)
    new_group_id = ee.Number(ee.Algorithms.If(
        curr.eq(1),
        ee.Algorithms.If(prev_flag.eq(1), group_id, group_id.add(1)),
        group_id,
    ))
    tagged = ee.Algorithms.If(curr.eq(1), new_group_id, -1)
    return ee.List([curr, new_group_id, tags_so_far.add(tagged)])

def tag_consecutive_runs(flags_sorted_by_date):
    """flags_sorted_by_date: ee.List of 0/1 (or booleans cast to 0/1), one per
    calendar day for ONE ward, IN DATE ORDER. Returns an ee.List of group ids,
    -1 for non-flagged days, same length as input."""
    init_state = ee.List([0, 0, ee.List([])])
    final_state = ee.List(flags_sorted_by_date.iterate(_run_group_step, init_state))
    return ee.List(final_state.get(2))
```
Verified: input `[0,1,1,1,0,1,1,0,0,1,1,1,1,0]` produced group tags `[-1,1,1,1,-1,2,2,-1,-1,3,3,3,3,-1]`. After tagging, filter to runs where `group id`'s total count `>= min_consecutive_days` (3) — group 1 (length 3) and group 3 (length 4) qualify as heatwave events per CLIM-04; group 2 (length 2) does not.
**Scaling check performed:** `.iterate()` over synthetic lists of length 365, 1,000, and 3,650 all completed correctly in 0.9-2.0s (verified live) — safely fast for Phase 3's small-scale tests. Not tested at Phase 4's full ~10,950-day (30-year) scale — see Pitfall 5.

### Anti-Patterns to Avoid
- **Building a numpy/pandas reference reimplementation of the percentile or windowing math as a test oracle:** D-02 explicitly forbids this, and this session's live verification proves why — EE's percentile reducer (`9.5` for `[1..10]` p90) does not match numpy's default (`9.1`). A parallel implementation would either fail correctly-passing tests or, worse, pass while silently testing the wrong number.
- **Using a custom `doy` property with `calendarRange`/`dayOfYear` filters:** these filters ignore custom properties and require `system:time_start` — verified to throw a hard error otherwise.
- **Nested `wards.map(ward -> days.map(...))` loops for climatology:** works but does not scale — `Reducer.group()` computes all wards for one calendar day in a single reducer call, which is the correct D-04 ward-count-agnostic pattern.
- **Assuming `ee.Number.mod()` behaves like Python's `%`:** verified it does not for negative inputs; always floor-mod explicitly before feeding into `calendarRange`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 90th-percentile computation | A numpy/scipy percentile calculation over `.getInfo()`-pulled arrays | `ee.Reducer.percentile([90])` | D-02; verified numerically different from numpy's default, and pulling 30-years × 4,841-wards of raw data to Python defeats the point of server-side EE computation |
| Day-of-year / calendar-day extraction | Custom Python `datetime.timetuple().tm_yday` logic applied after `.getInfo()` | `ee.Date.getRelative('day','year')` (server-side) | Keeps the whole climatology computation graph server-side; verified to naturally produce the WMO/ETCCDI-style leap-year divergence D-05 wants with zero extra code |
| Consecutive-run / event grouping | A pandas `groupby` + `shift()` diff trick after pulling flags to Python | `ee.List.iterate()` state machine (server-side) — see Pattern 6 | Works at test scale without a client round-trip per ward; if Phase 4 scale proves this too slow, the *documented* EE alternative is the array forward-difference trick (see Alternatives Considered), not an ad hoc pandas reimplementation |
| Ward-to-day join (attach threshold to each daily row) | Manual client-side dict lookup after two separate `.getInfo()` calls | `ee.Join.saveFirst()` with an equals filter | Verified working server-side; avoids two large `.getInfo()` payloads for what should be one server-side computation |

**Key insight:** Every "hand-roll" temptation in this domain (percentile math, calendar-day math, run detection) has a corresponding EE server-side primitive that was verified in this session to work correctly. The only real engineering decision left for the planner is data-shape design (the long-format ward-daily `FeatureCollection`), not algorithm reimplementation.

## Common Pitfalls

### Pitfall 1: `calendarRange`/`dayOfYear` require `system:time_start`, not a custom `doy` property
**What goes wrong:** Filtering a `FeatureCollection` by `ee.Filter.calendarRange(start, end, 'day_of_year')` when features only have a custom integer `doy` property (no timestamp) throws `Collection.filter: Can't apply calendarRange filter to objects without a timestamp.`
**Why it happens:** These filters compute day-of-year internally from each element's `system:time_start`; they do not accept an arbitrary property as the comparison field.
**How to avoid:** `heatwave/zonal.py` must set `system:time_start` (millis) on every output feature, in addition to (optionally) a convenience `doy` property for debugging/joins.
**Warning signs:** The exact error string above, thrown at `.filter()` call time (server-side, surfaces on `.getInfo()`).

### Pitfall 2: `ee.Number.mod()` is not floor-mod for negative inputs
**What goes wrong:** `ee.Number(-3).mod(366)` returns `-3`, not `363`. A naive `doy.subtract(window).mod(366)` wraparound implementation silently produces negative "day-of-year" values near Jan 1, which then either error out of `calendarRange` (which requires values `>= 0`, verified: passing `-3` throws `Filter.calendarRange: Start and end date values must be >= 0`) or, worse, produce wrong-but-valid-looking results if not caught.
**Why it happens:** EE's `Number.mod()` follows a "sign follows dividend" (truncated) convention, common in JS/C-family languages, not Python's floored `%`.
**How to avoid:** Use an explicit floor-mod helper (`r = n.mod(m); r = If(r < 0, r + m, r)`) before ever passing a wraparound-adjusted day value into `calendarRange` — see Pattern 3.
**Warning signs:** `EEException: Filter.calendarRange: Start and end date values must be >= 0` — this error is actually a helpful early signal that floor-mod wasn't applied; do not "fix" it by clamping to 0, fix the mod arithmetic.

### Pitfall 3: `ee.Reducer.percentile()` does not match numpy's percentile definition
**What goes wrong:** A test or sanity-check that computes "the expected 90th percentile" using `numpy.percentile()` and asserts EE's output matches will fail — not due to a bug, but because they use different interpolation rules (verified: `9.5` vs `9.1` for `[1..10]`, p90).
**Why it happens:** EE's percentile reducer computes percentiles directly for small samples (`up to maxRaw`) using its own internal rule, not numpy's default `linear` method; the official docs do not publish the exact interpolation formula, only that behavior differs by sample size (direct computation vs. histogram-derived for larger `N`).
**How to avoid:** Per D-02, never use numpy as the test oracle. Construct known small samples in tests and either (a) hand-verify the expected value against EE's actual live output during test-writing (documenting the expected value as "EE-computed, verified live" rather than "mathematically derived"), or (b) assert structural properties (e.g., "the p90 threshold for a ward with 9 low values and 1 very high value is greater than the 9 low values") rather than exact numeric equality where the precise interpolation rule matters.
**Warning signs:** A test failing with a small, consistent numeric discrepancy (~0.4 in the `[1..10]` example) rather than a gross logic error — this is the signature of an interpolation mismatch, not a code bug.

### Pitfall 4: Small ward polygons silently produce no zonal-reduction output
**What goes wrong:** `image.reduceRegions(collection=wards, reducer=ee.Reducer.mean(), scale=11132)` returns a feature with the `mean` property **entirely absent** (not `null`, not `0` — missing from the properties dict) when a ward polygon's area is too small relative to the pixel grid. Verified live: a 250m-radius test polygon (~0.16% of one ~11,132m ERA5-Land pixel's area) produced a feature with only its original `ward_id` property; no `mean` key at all.
**Why it happens:** EE's weighted reducers (including `mean`) only include a pixel if at least ~0.4% of that pixel's area intersects the region (officially documented threshold). A polygon smaller than ~0.4% of one ~11.1km pixel's area (roughly a ≥354m×354m square, or a circle of radius ≥335m) may intersect no pixel enough to count.
**How to avoid:** For Phase 3's own synthetic test wards, deliberately size test ward geometries well above this threshold (e.g., buffer ≥ 1km) to avoid this failure mode obscuring the actual algorithm test. For Phase 4 (real 4,841-ward asset), flag this as an open risk — some small urban wards may legitimately be smaller than one ERA5-Land pixel's effective weighted-inclusion threshold, and `run_batch_export.py` should check for/handle missing `mean` properties rather than assuming every ward always yields a value.
**Warning signs:** A ward's daily value row is missing entirely from the zonal-reduction output (not present with a null value — simply absent), which will then silently disappear from all downstream joins/percentile calculations for that ward on that day.

### Pitfall 5: `ee.List.iterate()` at full 30-year scale is untested
**What goes wrong:** Nothing observed at test scale — but Phase 3 only verified `.iterate()` up to a 3,650-element list (~10 years). Phase 4's real per-ward series will be closer to ~10,950 elements (30 years × 365.25 days), and `.iterate()` builds a deep, sequentially-dependent EE computation graph that could hit server-side recursion-depth or timeout limits at that scale (a documented general EE anti-pattern is deeply nested `.iterate()`/`.map()` chains, though no publicly documented hard limit number was found in this session's research).
**Why it happens:** `.iterate()` unrolls into a chain of nested function calls proportional to list length; EE's evaluation has practical (if not precisely documented) limits on computation graph depth and per-request compute time.
**How to avoid:** Phase 3 can safely use `.iterate()` as-is (D-03 explicitly scopes this phase to small samples). Flag for Phase 4 planning: benchmark `.iterate()` at the real ~10,950-element scale before committing to it for the full batch export; the documented fallback is the array-based forward-difference/run-length pattern (Alternatives Considered) or a per-ward client-side `.getInfo()` + Python grouping pass (acceptable at 4,841 sequential or batched calls, though slower).
**Warning signs:** Timeouts or `Computation timed out` / `User memory limit exceeded` errors specifically on the event-detection step at full-scale, not on zonal reduction or climatology (which don't use `.iterate()`).

## Code Examples

All examples below were executed live against the real `heatwave-508110` Earth Engine project during this research session (not copied from documentation without verification).

### Full verified end-to-end climatology computation (3 synthetic years, 2 wards, wraparound window)
```python
# Source: verified live against heatwave-508110, this session
# Synthetic 3-year (2018,2019,leap-2020) series, Jan 1-10 + Dec 27-31 only, 2 wards.
# Querying doy=366 (exists only in 2020) still yields a sane pooled threshold because
# its +/-5 window wraps to include 3 years of Dec 27-31 and Jan 1-5 data.
# Result (actual live output):
#   {'doy': 366, 'p90': 38.49, 'ward_id': 'A'}   # base value ~30-40
#   {'doy': 366, 'p90': 88.17, 'ward_id': 'B'}   # base value ~80-90
```
(Full code for this test is Pattern 3 + Pattern 4 combined — see above; re-run to reproduce.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Manually combining `ee.Filter.or()` of two `dayOfYear`/`calendarRange` ranges for wraparound | Passing `start > end` directly to a single `calendarRange`/`dayOfYear` call | N/A — this was a pre-research assumption in CONTEXT.md's framing ("Window arithmetic must handle this wraparound explicitly, not truncate"), disproven by live testing this session | Simpler implementation than assumed; no `Filter.or()` needed, only correct floor-mod arithmetic to produce valid wrapped start/end integers |

**Assumption disproven during research:** CONTEXT.md's D-06 anticipated needing to "handle wraparound explicitly" — true, but the explicit handling needed is entirely in the floor-mod arithmetic (Pitfall 2), not in combining multiple filters. `calendarRange`/`dayOfYear` already wrap natively once given valid (0-366, non-negative) start/end values with `start > end`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The "Runs with Arrays" (Gorelick) forward-difference array pattern is a viable, documented EE-community-standard alternative to `.iterate()` for run-length detection | Alternatives Considered, Pitfall 5 | LOW — this is offered only as a fallback option for Phase 4 if `.iterate()` proves too slow at full scale; it is not used in any Phase 3 recommendation. The actual `.iterate()` pattern recommended for Phase 3 was independently verified live, not sourced from this citation. |
| A2 | `pytest` version is unchanged since Phase 2 (not re-verified this session) | Standard Stack | LOW — no version-specific pytest feature is used by this phase; any recent pytest version works with the existing skip-gate pattern |
| A3 | EE's exact percentile interpolation formula for small-N direct computation (why `[1..10]` p90 = 9.5) is not officially published; the 9.5 result was empirically observed, not derived from a documented formula | Pitfall 3 | MEDIUM — if the planner or implementer needs to hand-verify an *exact* expected percentile value for a test assertion, they must re-run the live EE reducer to get the ground truth rather than deriving it mathologically, since the underlying rule is undocumented (only "computed directly for small N" is documented) |

**If this table is empty:** N/A — see entries above. All core algorithmic claims (percentile behavior, wraparound, join, iterate, zonal null pitfall) were independently verified live against the real EE project this session, not merely cited or assumed.

## Open Questions (RESOLVED — deferred to Phase 4 per D-03/D-04)

All three questions below are out of Phase 3's scope by decision, not unresolved design gaps: D-03 scopes this phase to small-sample algorithmic correctness (deferring full-scale `.iterate()` behaviour and any real-ward-geometry inspection to Phase 4's `scripts/run_batch_export.py` research), and D-04 requires only that the shipped functions be ward-count-agnostic, not that they be benchmarked at 4,841-ward scale here. Each is already carried into the plans as a documented code comment or an accepted threat (T-03-11, T-03-17, T-03-18), so Phase 3 may be marked complete with these open.

1. **[Deferred to Phase 4 per D-03] Does `.iterate()`-based run detection scale to the full ~10,950-day, 4,841-ward Phase 4 workload?**
   - What we know: Verified correct and fast (≤2s) up to 3,650 synthetic elements (~10 years) for one ward.
   - What's unclear: Behavior at ~10,950 elements × 4,841 wards (Phase 4 scale) — untested this session, and no hard EE documented limit was found to reason about analytically.
   - Recommendation: Phase 3 should proceed with `.iterate()` (D-03 explicitly scopes this phase to small-scale correctness). Phase 4's research/planning should include a dedicated benchmark of the run-detection step at or near full scale before committing to the batch export architecture.

2. **[Deferred to Phase 4 per D-03/D-04] How should Phase 4 handle wards whose zonal reduction returns no value (Pitfall 4)?**
   - What we know: `reduceRegions` silently omits the output property (not null — absent) for polygons below EE's ~0.4%-pixel-weight inclusion threshold.
   - What's unclear: Whether any of the real 4,841 Nigerian wards are actually this small (would require inspecting the real ward-asset geometries, out of Phase 3's scope per D-03).
   - Recommendation: Phase 3's own tests should use adequately-sized synthetic wards (≥1km) to avoid this failure mode masking algorithm bugs. Flag explicitly for Phase 4 research to check the real ward asset's minimum polygon area against the ~354m×354m threshold.

3. **[Deferred — not a Phase 3 blocker, per D-02] Exact EE percentile interpolation rule (Pitfall 3 / A3)** — undocumented; workaround (live-verify expected test values, avoid numpy oracle) is sufficient for Phase 3's correctness goal but is a standing minor gap in understanding, not a blocker.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `earthengine-api` | All EE server-side computation in this phase | ✓ [VERIFIED: local venv] | 1.6.8 | — |
| Live GCP credentials (`keys/service_account.json`) | Skip-gated live tests (`tests/test_heatwave_detection.py`, following `test_heat_index.py` pattern) | ✓ [VERIFIED: file exists at `keys/service_account.json`, live EE calls succeeded against `heatwave-508110` throughout this research session] | — | Tests skip cleanly via the established `_REQUIRES_CREDENTIALS` pattern if absent in CI |
| `pytest` | Test execution | ✓ [ASSUMED: unchanged since Phase 2, not re-verified this session] | unchanged | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None — all required dependencies are present and were exercised live during this research session.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest [ASSUMED: version unchanged since Phase 2] |
| Config file | none — no `pytest.ini`/`setup.cfg` in repo; defaults used (established pattern) |
| Quick run command | `pytest tests/test_heatwave_detection.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLIM-01 | Per-ward, per-calendar-day climatology baseline computed from a synthetic 1991-2020-style Heat Index record | live-EE unit | `pytest tests/test_heatwave_detection.py -k climatology -x` | ❌ Wave 0 (this phase's own deliverable) |
| CLIM-02 | ±5-day pooling window applied, including wraparound near day 1/366 | live-EE unit | `pytest tests/test_heatwave_detection.py -k pooling -x` | ❌ Wave 0 |
| CLIM-03 | A day is flagged as a heatwave day when Heat Index exceeds the ward's 90th-percentile threshold for that calendar day | live-EE unit | `pytest tests/test_heatwave_detection.py -k flag -x` | ❌ Wave 0 |
| CLIM-04 | Consecutive heatwave days grouped into events; only runs ≥3 days count | live-EE unit | `pytest tests/test_heatwave_detection.py -k event -x` | ❌ Wave 0 |
| CLIM-05 | Gridded ERA5-Land Heat Index correctly reduced to per-ward daily statistics | live-EE unit | `pytest tests/test_heatwave_detection.py -k zonal -x` | ❌ Wave 0 |
| CLIM-06 | `tests/test_heatwave_detection.py` exists and validates the above against synthetic/known cases | (this file itself) | `pytest tests/test_heatwave_detection.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_heatwave_detection.py -x`
- **Per wave merge:** `pytest tests/ -x` (full suite, includes Phase 1-2 regression per established precedent in `tests/test_integration.py`)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_heatwave_detection.py` — does not exist yet; this phase's own deliverable (CLIM-06). Follow the skip-gated, live-EE, `pytest.approx`-tolerance pattern from `tests/test_heat_index.py` (per-test `_REQUIRES_CREDENTIALS` decorator, not module-level `pytestmark`, so a no-credentials-required export/smoke test can still run per the Phase 2 precedent).
- [ ] No shared fixtures/conftest currently exist for constructing synthetic multi-year `ee.FeatureCollection`/`ee.ImageCollection` test data — recommend a small helper (e.g., `_make_synthetic_ward_daily_fc(...)`) local to the new test file, following the existing `_make_test_image()` helper pattern in `tests/test_heat_index.py`, rather than introducing a new `conftest.py` (no other test file needs to share it yet).
- [ ] Framework install: none needed — `pytest` and `earthengine-api` already present.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | This phase adds no new auth surface; credential handling is entirely Phase 1's `heatwave/auth.py`, unchanged |
| V3 Session Management | No | No session concept in this batch pipeline |
| V4 Access Control | No | No multi-user access-control surface — single service-account, internal pipeline |
| V5 Input Validation | Partial | Climatology parameters (`percentile`, `pooling_window_days`, `min_consecutive_days`, baseline years) must be read from `heatwave.config.settings.climatology` (already typed/validated per REWORK-07), never accepted as unvalidated external input within this phase's functions |
| V6 Cryptography | No | No cryptographic operations introduced; credential handling unchanged from Phase 1 |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Hardcoding climatology constants (90, 5, 3, 1991, 2020) instead of reading `settings.climatology` | Tampering (config drift) | Always read from `heatwave.config.settings.climatology`, as CONTEXT.md's Code Context section already mandates |
| Silent data loss from small-ward zonal reduction (Pitfall 4) producing missing-not-null values that get treated as "0 heatwave days" downstream | Information Disclosure / Data Integrity (indirect) | Explicitly check for missing zonal-reduction properties rather than assuming every ward-day row exists; do not let a missing value silently default to 0 in aggregation |

This phase does not process any externally-submitted user input or handle end-user authentication — the primary "security" concern in this domain is data-integrity correctness (silent nulls, config drift), not a traditional attack surface.

## Sources

### Primary (HIGH confidence — verified live this session against `heatwave-508110`)
- Live EE execution of ~20 discrete test snippets covering: `ee.Date.getRelative`, `ee.Filter.calendarRange`, `ee.Filter.dayOfYear`, `ee.Number.mod`, `ee.Reducer.percentile`, `ee.Reducer.percentile().group()`, `ee.Image.reduceRegions`, `ee.Join.saveFirst`, `ee.List.iterate`, and ERA5-Land's actual nominal projection scale
- `heatwave/science/heat_index.py`, `heatwave/data/boundary.py`, `heatwave/data/ingest.py`, `heatwave/config.py`, `config.yaml`, `tests/test_heat_index.py` — read directly from the repo this session
- Google Earth Engine API reference pages (content extracted from embedded JSON in page HTML, not the AI-summarized WebFetch tool which returned generic/unreliable text for these JS-rendered pages):
  - https://developers.google.com/earth-engine/apidocs/ee-reducer-percentile
  - https://developers.google.com/earth-engine/apidocs/ee-image-reduceregions
  - https://developers.google.com/earth-engine/apidocs/ee-filter-dayofyear
  - https://developers.google.com/earth-engine/apidocs/ee-filter-calendarrange
  - https://developers.google.com/earth-engine/apidocs/ee-date-getrelative
  - https://developers.google.com/earth-engine/apidocs/ee-date-get
  - https://developers.google.com/earth-engine/apidocs/ee-number-mod
  - https://developers.google.com/earth-engine/apidocs/ee-list-sequence
  - https://developers.google.com/earth-engine/apidocs/ee-reducer-group
  - https://developers.google.com/earth-engine/apidocs/ee-list-iterate

### Secondary (MEDIUM confidence)
- https://developers.google.com/earth-engine/guides/reducers_reduce_region — general reduceRegion/scale guidance (WebFetch AI-summary; cross-checked against verified live behavior)
- https://developers.google.com/earth-engine/guides/reducers_grouping — general grouped-reduction guidance (WebFetch AI-summary; cross-checked against verified live `Reducer.group()` test)

### Tertiary (LOW confidence — not independently verified)
- "Runs with Arrays" (Noel Gorelick, Google Earth Engine team) — https://medium.com/google-earth/runs-with-arrays-400de937510a — returned HTTP 403 to automated fetch tools this session; description sourced only from search-engine result snippets. Offered only as a Phase 4 fallback option, not used in any Phase 3 recommendation.
- "Heatwave Explorer - Technical Details Report" (ResearchGate) — https://www.researchgate.net/publication/396230293 — confirms the general percentile-threshold + consecutive-day-grouping methodology is a known, existing GEE application pattern, but the PDF itself could not be fetched (403); not used as a source of specific code idioms.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; existing `earthengine-api` version confirmed live in the project's own venv
- Architecture: HIGH — every core pattern (zonal reduction, wraparound pooling, grouped percentile, join, run detection) was executed live end-to-end against the real `heatwave-508110` project, not just read from docs
- Pitfalls: HIGH for Pitfalls 1-4 (all directly reproduced live); MEDIUM for Pitfall 5 (reasoned from partial live testing, not full-scale reproduction)

**Research date:** 2026-09-13
**Valid until:** 2026-10-13 (30 days — Earth Engine API surface for these core reducers/filters is stable; re-verify if `earthengine-api` is upgraded past 1.6.8 before Phase 3 implementation begins)
