# Phase 3: Climatology & Heatwave Detection - Pattern Map

**Mapped:** 2026-09-13
**Files analyzed:** 4 new files (`heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, `tests/test_heatwave_detection.py`)
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `heatwave/zonal.py` | service (EE pipeline stage) | transform (gridded pixels -> per-ward table) | `heatwave/data/ingest.py` | role-match (module style + `.map()` over `ImageCollection` pattern) |
| `heatwave/science/climatology.py` | service (EE pipeline stage) | batch / transform (aggregate 30-yr baseline -> per-day-per-ward thresholds) | `heatwave/science/heat_index.py` | exact (same package, same plain-function style, same `settings` usage) |
| `heatwave/science/heatwave.py` | service (EE pipeline stage) | event-driven / transform (join + stateful run detection) | `heatwave/science/heat_index.py` | role-match (same module family; no existing stateful/join analog in repo) |
| `tests/test_heatwave_detection.py` | test | request-response (live EE `.getInfo()` assertions) | `tests/test_heat_index.py` | exact (skip-gated live-EE pattern, per-test guard, synthetic `ee.Image`/`ee.FeatureCollection` helper) |

No file in the existing codebase performs zonal reduction, percentile-grouping, joins, or `.iterate()` state machines yet — these are genuinely new capabilities in Phase 3. The analogs below are matched on **module style, config usage, and test scaffolding**, not on algorithmic precedent (there is none in-repo); the concrete EE algorithm idioms come from `03-RESEARCH.md`'s live-verified patterns and are reproduced below as the "core pattern" for each file.

## Pattern Assignments

### `heatwave/zonal.py` (service, transform)

**Analog:** `heatwave/data/ingest.py` (module style, docstring convention, `.map()` over `ImageCollection`) + Research Pattern 1 (zonal reduction algorithm, verified live)

**Imports pattern** (from `heatwave/data/ingest.py` lines 9-13):
```python
from __future__ import annotations

import ee

from heatwave.config import settings
```
Apply the same convention to `heatwave/zonal.py`: `from __future__ import annotations`, module docstring describing the pipeline-stage boundary (see `ingest.py` lines 1-8 for the style — explicitly states what this stage does NOT do, e.g. "per-ward zonal reduction is a later pipeline stage"), then `import ee`, then `from heatwave.config import settings`.

**Module docstring convention** (`heatwave/data/ingest.py` lines 1-8):
```python
"""ERA5-Land ingestion: select configured bands, filter by date, clip to the ward boundary.
...
Only selection/filtering/clipping happens here — per-ward zonal
reduction is a later pipeline stage (heatwave/zonal.py).
"""
```
`heatwave/zonal.py` should open the same way: state precisely what this stage does (gridded -> per-ward-daily `FeatureCollection`) and what it hands off to next (`heatwave/science/climatology.py` / `heatwave.py`).

**Function signature convention** (`heatwave/data/ingest.py` lines 16-20, `heatwave/data/boundary.py` lines 9-11):
```python
def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ee.ImageCollection:
```
Plain function, typed args/return with `ee.*` types, optional params defaulting from `settings` when `None` (see `ingest.py` lines 27-28: `start_date = start_date or settings.start_date`). `zonal.py`'s main function should follow this: explicit `image_collection`, `wards`, `band` (default from Phase 2's `'heat_index'` band name), `scale` params — no hardcoded ward count or date range (D-04).

**Core pattern — zonal reduction, gridded to per-ward-daily rows** (verified live, `03-RESEARCH.md` Pattern 1):
```python
# Source: 03-RESEARCH.md Pattern 1, verified live against heatwave-508110
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
`scale=11132` matches ERA5-Land's verified nominal pixel scale (`image.projection().nominalScale()` -> `11131.949...`). Do not hardcode `11132` as a bare magic number without a named default/constant and a comment citing this verification.

**Critical constraint (Pitfall 1):** every output feature MUST carry `system:time_start` (millis) — `ee.Filter.calendarRange`/`ee.Filter.dayOfYear` used downstream in `climatology.py` read day-of-year from this timestamp, not from the custom `doy` property. Omitting it produces `Collection.filter: Can't apply calendarRange filter to objects without a timestamp.` at `.getInfo()` time.

**Pitfall to guard against (Pitfall 4):** `reduceRegions` silently omits the `mean` property entirely (not `null`) for ward polygons too small relative to the ~11.1km pixel grid (~0.4% pixel-area inclusion threshold). `zonal.py`'s own logic doesn't need defensive code for this in Phase 3 (D-03 scope), but keep the function generic (D-04) so Phase 4's caller can check for missing properties.

---

### `heatwave/science/climatology.py` (service, batch/transform)

**Analog:** `heatwave/science/heat_index.py` (exact module-style match — same package, same `settings` import, same plain-function-no-class convention)

**Imports pattern** (`heatwave/science/heat_index.py` lines 1-6):
```python
"""Relative humidity and Heat Index computation over ERA5-Land ee.Image bands."""
from __future__ import annotations

import ee

from heatwave.config import settings
```
Replicate exactly for `climatology.py`: module docstring naming the requirement(s) covered (CLIM-01, CLIM-02, per `heat_index.py`'s pattern of citing `D-01/WR-01` inline), then the same four-line import block.

**Config usage pattern (never hardcode constants)** (`heatwave/science/heat_index.py` uses `settings.bands.tmean` etc.; `heatwave/config.py` lines 12-18 define `ClimatologyConfig`):
```python
@dataclass(frozen=True)
class ClimatologyConfig:
    baseline_start_year: int
    baseline_end_year: int
    percentile: int
    pooling_window_days: int
    min_consecutive_days: int
```
`climatology.py` functions must read `settings.climatology.percentile`, `settings.climatology.pooling_window_days`, `settings.climatology.baseline_start_year`, `settings.climatology.baseline_end_year` as **defaults** for function parameters (matching the `ingest.py` `start_date = start_date or settings.start_date` pattern), not hardcode `90`/`5`/`1991`/`2020` — this is both a CONTEXT.md decision (Code Context section) and a security/data-integrity item flagged in RESEARCH.md's Security Domain.

**Core pattern 1 — floor-mod helper for wraparound** (verified live, `03-RESEARCH.md` Pattern 3, Pitfall 2):
```python
# Source: 03-RESEARCH.md Pattern 3, verified live against heatwave-508110
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
`ee.Number.mod()` is NOT floor-mod for negative inputs (`ee.Number(-3).mod(366)` returns `-3`, not `363`) — always route wraparound arithmetic through `floor_mod`/`wrapped_day` before calling `calendarRange`. `calendarRange(start, end, ...)` natively wraps when `start > end` — no `ee.Filter.or()` needed once inputs are floor-modded into `[1, 366]`.

**Core pattern 2 — grouped percentile computation, all wards per day in one call** (verified live, `03-RESEARCH.md` Pattern 4):
```python
# Source: 03-RESEARCH.md Pattern 4, verified live against heatwave-508110
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
                 "threshold": ee.Dictionary(g).get(f"p{percentile}")},
            )
        )

    days = ee.List.sequence(1, 366)
    return ee.FeatureCollection(ee.List(days.map(threshold_for_day)).flatten())
```
**Naming note — deliberate rename, do not copy `p90`:** the emitted property is `threshold`, not `p90`. `03-RESEARCH.md`'s Pattern 4/5 snippets (and their sample output dicts) name it `p90` because that was the live-verification scratch form; all four Phase 3 plans and the shipped `heatwave/science/climatology.py` / `heatwave/science/heatwave.py` standardise on `threshold` so that downstream code never encodes the configured percentile in a property name (a config change to p95 must not rename a column). Likewise, the signature above shows literal defaults for readability only — the shipped function takes `percentile=None, window_days=None, baseline_start_year=None, baseline_end_year=None` and resolves each from `settings.climatology` (security V5, see the Config-driven parameters pattern).
Note `groupField=1` is the **index into `selectors`** (`['value', 'ward_id']` -> index 1 = `ward_id`), not a literal property name — verified live. Use `ee.List.sequence(1, 366).map(...)` + `Reducer.group()`, NOT a nested `wards.map(ward -> days.map(...))` loop (anti-pattern per D-04/ward-count-agnostic requirement — nested loop is O(wards x days) separate calls).

**Anti-pattern to flag explicitly in code comments:** do not build a numpy/pandas reference reimplementation of the percentile math (D-02) — `ee.Reducer.percentile([90])` for `[1..10]` returns `9.5`, not numpy's `9.1`. If a docstring or comment cites "expected" percentile values, cite them as "EE-computed, verified live," not mathematically derived.

---

### `heatwave/science/heatwave.py` (service, event-driven/transform)

**Analog:** `heatwave/science/heat_index.py` (module style only — no existing join/stateful-iteration analog in repo)

**Imports pattern:** identical four-line block as `climatology.py` above (`from __future__ import annotations`, `import ee`, `from heatwave.config import settings`).

**Core pattern 1 — join threshold to daily value, flag exceedance (CLIM-03)** (verified live, `03-RESEARCH.md` Pattern 5):
```python
# Source: 03-RESEARCH.md Pattern 5, verified live against heatwave-508110
join_filter = ee.Filter.And(
    ee.Filter.equals(leftField="ward_id", rightField="ward_id"),
    ee.Filter.equals(leftField="doy", rightField="doy"),
)
joined = ee.Join.saveFirst("clim_match").apply(ward_daily_fc, climatology_fc, join_filter)

def flag_hot(f):
    f = ee.Feature(f)
    threshold = ee.Feature(f.get("clim_match")).get("threshold")  # property name is `threshold` — see the naming note above
    return f.set("threshold", threshold, "is_hot", ee.Number(f.get("value")).gt(ee.Number(threshold)))

flagged = joined.map(flag_hot)
```

**Core pattern 2 — consecutive-run detection state machine (CLIM-04)** (verified live, `03-RESEARCH.md` Pattern 6):
```python
# Source: 03-RESEARCH.md Pattern 6, verified live against heatwave-508110
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
    """flags_sorted_by_date: ee.List of 0/1, one per calendar day for ONE ward,
    IN DATE ORDER. Returns an ee.List of group ids, -1 for non-flagged days,
    same length as input."""
    init_state = ee.List([0, 0, ee.List([])])
    final_state = ee.List(flags_sorted_by_date.iterate(_run_group_step, init_state))
    return ee.List(final_state.get(2))
```
After tagging, filter to runs whose total member count `>= settings.climatology.min_consecutive_days` (read from config, not hardcoded `3`) to produce the final heatwave-event flags. Input `[0,1,1,1,0,1,1,0,0,1,1,1,1,0]` -> group tags `[-1,1,1,1,-1,2,2,-1,-1,3,3,3,3,-1]` (verified live); group 1 (len 3) and group 3 (len 4) qualify, group 2 (len 2) does not.

**Sequencing requirement:** the input list to `tag_consecutive_runs` MUST be per-ward and sorted by date — this function does not group by ward internally; the caller (or a wrapper function in this same module) must partition `flagged` by `ward_id`, sort each partition by date, extract the `is_hot` values as an `ee.List`, then run the state machine per ward.

**Known scale limitation to note in a code comment (Pitfall 5):** `.iterate()` verified correct/fast (<=2s) up to 3,650-element lists (~10 years); NOT verified at Phase 4's full ~10,950-element (30-year) scale. Fine for Phase 3 (D-03 scopes this phase to small samples) but flag as an open question for Phase 4 rather than silently assuming it scales.

---

### `tests/test_heatwave_detection.py` (test, request-response/live-EE)

**Analog:** `tests/test_heat_index.py` (exact match — skip-gated live-EE pattern, per-test credential guard, synthetic-data helper convention)

**Credential-gate pattern** (`tests/test_heat_index.py` lines 1-21, reproduce verbatim except docstring/comment target):
```python
"""Live, skip-gated tests verifying climatology + heatwave detection against
synthetic time series (CLIM-01 through CLIM-06)."""
from __future__ import annotations

import os
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

# NOTE: per-test gate (not module-level pytestmark) so a no-credentials-required
# export/smoke test can still run without live GCP creds — same rationale as
# tests/test_heat_index.py.
_REQUIRES_CREDENTIALS = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)
```
Apply the `_REQUIRES_CREDENTIALS` decorator **per-test**, not as a module-level `pytestmark` — `test_heat_index.py`'s comment (lines 13-17) explicitly documents why: it must remain possible to run a no-credentials `test_science_module_exports`-style smoke test (`pytest tests/test_heatwave_detection.py -k export`).

**No-credentials smoke test pattern** (`tests/test_heat_index.py` lines 45-50):
```python
def test_science_module_exports():
    """HIDX-01: heatwave.science.heat_index exports both functions, no credentials required."""
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    assert callable(compute_relative_humidity)
    assert callable(compute_heat_index)
```
Add an analogous `test_science_modules_export()` (or three, one per new module) asserting `callable(...)` for the key public functions of `zonal.py`, `climatology.py`, `heatwave.py` — runnable without credentials.

**Synthetic-`ee.Image`-helper pattern** (`tests/test_heat_index.py` lines 24-29):
```python
def _make_test_image(tmean_k: float, dewpoint_k: float) -> ee.Image:
    from heatwave.config import settings

    return ee.Image.constant([0, tmean_k, dewpoint_k]).rename(
        [settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint]
    )
```
For `test_heatwave_detection.py`, write an equivalent local helper `_make_synthetic_ward_daily_fc(...)` (per RESEARCH.md's Wave 0 Gaps recommendation) that builds a small `ee.FeatureCollection` directly (via `ee.FeatureCollection(ee.List([...]))` of `ee.Feature(None, {...})` objects with `system:time_start`, `doy`, `ward_id`, `value` properties) rather than round-tripping through real `ee.Image`s — matches D-01's "constructed `ee.Image`/`ee.ImageCollection` time series" instruction while keeping helper construction simple for tabular (not gridded) test data. Do NOT introduce a shared `conftest.py` for this — keep the helper local to this test file (Wave 0 Gaps: "no other test file needs to share it yet").

**Value-extraction pattern** (`tests/test_heat_index.py` lines 32-42, adapt for `FeatureCollection` instead of `Image`):
```python
def _band_value(image: ee.Image, band_name: str):
    return (
        image.select(band_name)
        .reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=ee.Geometry.Point([0, 0]),
            scale=1000,
        )
        .get(band_name)
        .getInfo()
    )
```
For feature-collection-based assertions, the equivalent is calling `.getInfo()` directly on a filtered/mapped `ee.FeatureCollection` (or `.aggregate_array(...)`) and asserting on the returned Python list/dict — see Pattern 4/5/6 outputs in RESEARCH.md for the exact shape (`{'doy': ..., 'ward_id': ..., 'threshold': ...}` dicts — RESEARCH.md prints that third key as `p90`; the shipped name is `threshold`, per the naming note above).

**Test-per-requirement structure** (`tests/test_heat_index.py`'s one-test-per-NOAA-value convention, lines 53-141): mirror this with one test per CLIM requirement, using `pytest.approx` where an exact EE-computed value has been live-verified (never a numpy-derived expectation, per D-02/Pitfall 3):
- `test_zonal_reduction_...` (CLIM-05) — `-k zonal`
- `test_climatology_baseline_...` / `test_pooling_window_wraparound_...` (CLIM-01/CLIM-02) — `-k climatology` / `-k pooling`
- `test_heatwave_day_flag_...` (CLIM-03) — `-k flag`
- `test_heatwave_event_grouping_...` (CLIM-04) — `-k event`

Matches RESEARCH.md's exact `pytest -k` selectors in its Phase Requirements -> Test Map table — use these `-k`-matchable substrings in test function names so the documented commands work as written.

**`init_ee()` call convention** (`tests/test_heat_index.py` line 59, every credentialed test):
```python
from heatwave.auth import init_ee
...
init_ee()
```
Call explicitly inside every `_REQUIRES_CREDENTIALS`-gated test, not once at module scope — matches `init_ee()`'s documented idempotency (`tests/test_integration.py` `test_init_ee_idempotent`).

---

## Shared Patterns

### Config-driven parameters (never hardcode climatology constants)
**Source:** `heatwave/config.py` lines 12-18 (`ClimatologyConfig`), `config.yaml` lines 21-26
**Apply to:** `heatwave/science/climatology.py` and `heatwave/science/heatwave.py` — all percentile/window/consecutive-day/baseline-year values must default from `settings.climatology.*`, exactly as `heatwave/data/ingest.py` defaults `start_date`/`end_date` from `settings.start_date`/`settings.end_date` (lines 27-28: `start_date = start_date or settings.start_date`).

### Plain-function, no-class module style
**Source:** `heatwave/science/heat_index.py`, `heatwave/data/boundary.py`, `heatwave/data/ingest.py` (all of them)
**Apply to:** all three new production modules — `from __future__ import annotations`, module docstring stating the pipeline-stage boundary, `import ee`, `from heatwave.config import settings`, then top-level `def` functions with typed `ee.*` signatures. No classes anywhere in this codebase's `heatwave/` package.

### Skip-gated live-EE test pattern with per-test credential guard
**Source:** `tests/test_heat_index.py` lines 1-21 (guard construction), lines 45-50 (no-credentials smoke test), every `@_REQUIRES_CREDENTIALS` test (lines 53+)
**Apply to:** `tests/test_heatwave_detection.py` in full — this is the single most load-bearing shared pattern for CLIM-06.

### `system:time_start` propagation requirement
**Source:** `03-RESEARCH.md` Pitfall 1 (verified live); precedent for propagating `system:time_start` through a `.map()` transform already exists in `heatwave/science/heat_index.py` line 40: `return image.addBands(HI.set('system:time_start', image.get('system:time_start')))`
**Apply to:** `heatwave/zonal.py` (must set on every output feature) and any intermediate transform in `climatology.py`/`heatwave.py` that constructs new `ee.Feature`s from joined/grouped data — if a downstream `calendarRange`/`dayOfYear` filter is ever applied again after such a transform, the timestamp must survive or be re-set.

## No Analog Found

None outright — every new file has at least a role/style-level analog in the existing `heatwave/` package (see table above). The specific EE *algorithms* (zonal `reduceRegions`, grouped percentile, `Join.saveFirst`, `.iterate()` run detection) have no prior in-repo implementation to copy — for those, the "analog" is the live-verified RESEARCH.md code (Patterns 1, 3-6), which should be treated as equally authoritative as an in-repo file since it was executed against the real `heatwave-508110` project this session.

## Metadata

**Analog search scope:** `heatwave/` (all subpackages), `tests/` (all files), `config.yaml`, `heatwave/config.py`
**Files scanned:** `heatwave/science/heat_index.py`, `heatwave/data/boundary.py`, `heatwave/data/ingest.py`, `heatwave/config.py`, `heatwave/auth.py`, `config.yaml`, `tests/test_heat_index.py`, `tests/test_integration.py`
**Pattern extraction date:** 2026-09-13
