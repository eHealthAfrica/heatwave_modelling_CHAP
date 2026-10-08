# Phase 4: Batch Export & Covariate Table - Pattern Map

**Mapped:** 2026-09-15
**Files analyzed:** 3 (2 new modules + 1 new test file; `heatwave/zonal.py` modified in place, not newly created)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|----------------|
| `heatwave/export.py` (NEW) | service (plain-function EE aggregation module) | transform (server-side group-by/aggregate) | `heatwave/science/climatology.py` | exact (same plain-function, config-driven, `ee.Reducer.group()` module style) |
| `heatwave/zonal.py` (MODIFIED — add D-08 fallback branch) | service (zonal reduction) | transform (per-day `reduceRegions`) | `heatwave/zonal.py` itself (extend existing `reduce_to_ward_daily`, same file) | exact (in-place extension, not a new analog search) |
| `scripts/run_batch_export.py` (NEW) | script / orchestrator (chunk planner + async task submit/poll/collect) | batch + event-driven (submit async task, poll status, collect on completion) | `heatwave/auth.py` (module-level `if __name__ == "__main__":` CLI-entry convention) + `heatwave/data/ingest.py`/`zonal.py` (pipeline composition order) — no prior async-task-polling analog exists in this repo | role-match (no exact prior analog for batch-task polling; closest structural precedent is the existing pipeline call order in `tests/test_heatwave_detection.py`'s `test_end_to_end_climatology_and_event_pipeline`) |
| `tests/test_export.py` (NEW) | test | request-response (live-EE `getInfo()` assertions on small synthetic fixtures) | `tests/test_heatwave_detection.py` | exact (skip-gated live-EE pattern, synthetic fixture builders, `_props()` helper) |

## Pattern Assignments

### `heatwave/export.py` (service, transform) — NEW

**Analog:** `heatwave/science/climatology.py` (module style, config resolution, docstring conventions) + `heatwave/science/heatwave.py` (composite grouping precedent is new to this phase per Pattern 3/4 in RESEARCH.md — no exact prior analog, reproduce RESEARCH.md's verified code directly)

**Imports pattern** (from `heatwave/science/climatology.py` lines 1-19; reuse verbatim style):
```python
from __future__ import annotations

import ee

from heatwave.config import settings
```

**Module docstring / header convention** (from `heatwave/zonal.py` lines 1-14 and `heatwave/science/heatwave.py` lines 1-16): a top-of-file docstring stating (a) what the module reduces/joins, (b) upstream input contract (what row shape it expects — e.g. `ward_id`, `value`, `doy`, `system:time_start`, `is_hot`, `event_id`), (c) downstream consumer, (d) any caller obligations around nulls. `heatwave/export.py` should state its input contract as "one row per (ward, day) from `flag_heatwave_days`/`detect_heatwave_events`'s output: `ward_id`, `value` (heat index), `is_hot`, `event_id`, `system:time_start`" and its output contract as "one row per (ward, ISO week): `time_period`, `location`, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`" (EXPORT-02's exact schema, per CONTEXT.md D-06).

**Config-driven parameter resolution pattern** (from `heatwave/science/climatology.py` lines 88-93 and `heatwave/science/heatwave.py` lines 189-193): resolve tunable parameters from `settings` with `is not None` checks (never bare `or`, to avoid swallowing an explicit `0`) — no new config keys are needed for `export.py` itself (ISO-week/aggregation logic has no tunable parameters per CONTEXT.md), but the same defensive-default idiom applies to any date-range/ward-id-property parameters this module's functions accept:
```python
window_days = window_days if window_days is not None else settings.climatology.pooling_window_days
```

**Core pattern 1 — ISO year/week (verified live, reproduce VERBATIM from 04-RESEARCH.md Pattern 1):**
```python
# Source: verified live against heatwave-508110, this session, cross-checked
# against Python's datetime.isocalendar() ground truth.
def iso_year_and_week(date: ee.Date) -> tuple[ee.Number, ee.Number]:
    """Return (iso_week_year, iso_week) for an ee.Date, matching Python's
    date.isocalendar() exactly -- verified live on 8 edge-case dates
    (2024-12-30/31, 2025-01-01/05, 2023-01-01/02, 2020-12-31, 2021-01-01),
    including both week-53 years and both Dec->Jan wraparound directions.

    ee.Date.get('year') is the plain CALENDAR year, not the ISO week-year --
    e.g. 2024-12-30 (a Monday) is ISO week 2025-W01, but get('year') returns
    2024. Naively pairing get('year') with get('week') silently mis-buckets
    every year's Dec/Jan boundary days.
    """
    iso_weekday = date.getRelative("day", "week").add(1)  # Monday=1 .. Sunday=7
    thursday_of_this_week = date.advance(ee.Number(4).subtract(iso_weekday), "day")
    return thursday_of_this_week.get("year"), date.get("week")
```
**Anti-pattern — do NOT reintroduce:** `f"{date.get('year')}-W{date.get('week')}"` naive pairing. Verified live to silently mis-bucket every Dec/Jan boundary (04-RESEARCH.md Pitfall 2).

**Core pattern 2 — composite-key weekly aggregation (verified live, reproduce VERBATIM from 04-RESEARCH.md Pattern 3):**
```python
# Source: verified live against heatwave-508110, this session.
# CONFIRMED BROKEN (do not use): chaining two .group() calls on the SAME
# reducer produced swapped/incorrect week<->value pairings in live testing.
#   fc.reduceColumns(
#       reducer=ee.Reducer.mean().group(groupField=1, groupName="week")
#                                 .group(groupField=0, groupName="ward_id"),
#       selectors=["ward_id", "week", "value"],
#   )  # -> wrong: "week" and "mean" values cross-assigned in the output

# WORKING pattern: single composite key, single .group() call.
def add_group_key(feature, ward_id_property, time_period_property):
    ward_id = ee.String(feature.get(ward_id_property))
    time_period = ee.String(feature.get(time_period_property))
    return feature.set("group_key", ward_id.cat("::").cat(time_period))
    # "::" chosen because ee.String.split() treats its argument as a regex;
    # a bare "|" needs escaping ("\\|") to avoid matching as regex
    # alternation -- "::" needs no escaping and is very unlikely to appear
    # inside a ward code or an ISO week string.

combined_reducer = (
    ee.Reducer.mean()
    .combine(ee.Reducer.max(), sharedInputs=True)
    .combine(ee.Reducer.count(), sharedInputs=True)
)
grouped = fc.reduceColumns(
    reducer=combined_reducer.group(groupField=1, groupName="group_key"),
    selectors=["value", "group_key"],
)

def to_weekly_feature(g):
    g = ee.Dictionary(g)
    parts = ee.String(g.get("group_key")).split("::")
    return ee.Feature(None, {
        "location": parts.get(0),
        "time_period": parts.get(1),
        "mean_heat_index": g.get("mean"),
        "max_heat_index": g.get("max"),
        "heatwave_days": g.get("count"),  # count of is_hot==1 rows if `value` selector is filtered to is_hot rows first
    })

weekly_fc = ee.FeatureCollection(ee.List(grouped.get("groups")).map(to_weekly_feature))
```
**Anti-pattern — do NOT reintroduce:** chained `.group(groupField=1,...).group(groupField=0,...)` for two-key grouping. Verified live to silently swap values (04-RESEARCH.md Pitfall 4).

**Core pattern 3 — `heatwave_event_count` via event-start-week (reproduce from 04-RESEARCH.md Pattern 4; composition not yet live-verified end-to-end — write a Wave-0 test in `tests/test_export.py` proving it before relying on it, per RESEARCH.md Assumption A4):**
```python
# Source: composed from Pattern 1 + Pattern 3 (both independently verified
# live); this exact composition not yet executed end-to-end -- verify in
# Wave 0 before full-scale use.
def event_start_weeks(events_fc, ward_id_property="ward_id"):
    real_events = events_fc.filter(ee.Filter.neq("event_id", -1))
    real_events = real_events.map(
        lambda f: f.set("event_key", ee.String(f.get(ward_id_property)).cat("::").cat(ee.Number(f.get("event_id")).format()))
    )
    grouped = real_events.reduceColumns(
        reducer=ee.Reducer.min().group(groupField=1, groupName="event_key"),
        selectors=["system:time_start", "event_key"],
    )
    def to_start_feature(g):
        g = ee.Dictionary(g)
        parts = ee.String(g.get("event_key")).split("::")
        start_date = ee.Date(g.get("min"))
        iso_year, iso_week = iso_year_and_week(start_date)  # Pattern 1
        time_period = iso_year.format().cat("-W").cat(iso_week.format("%02d"))
        return ee.Feature(None, {ward_id_property: parts.get(0), "time_period": time_period})
    return ee.FeatureCollection(ee.List(grouped.get("groups")).map(to_start_feature))
    # Then: Pattern 3's composite-key group-and-COUNT (not mean/max) on this
    # small FeatureCollection, grouping by (ward_id_property, "time_period"),
    # gives heatwave_event_count. Left-join into the main weekly table,
    # coalescing missing matches to 0 (a true zero, not a D-08-style null).
```
**Null-vs-zero distinction (important, do not blur):** `heatwave_days`/`mean_heat_index`/`max_heat_index` follow D-08's null-preservation policy (a missing zonal value must never be coalesced to 0). `heatwave_event_count` is the opposite case: a week with zero qualifying event starts is a genuine `0`, not a null — coalesce the left-join's missing matches to `0` here specifically (04-RESEARCH.md Pattern 4).

**Error handling / null handling pattern** (from `heatwave/science/heatwave.py` lines 78-89, the outer-join null-preservation idiom used by `flag_heatwave_days`): use `ee.Algorithms.If(condition, value, None)` to preserve an explicit null rather than defaulting to 0 or dropping the row — the same idiom this phase's D-08/D-09 fallback wiring depends on.

---

### `heatwave/zonal.py` (MODIFIED — D-08 fallback branch)

**Analog:** the file's own existing `reduce_to_ward_daily` (lines 27-77) — extend in place, do not create a parallel function unless the planner decides a separate `reduce_to_ward_daily_with_fallback` wrapper is cleaner; either way, reuse the existing docstring/caller-obligation convention (lines 34-56).

**Existing function to extend** (`heatwave/zonal.py` lines 59-77, current primary reduction — unchanged core, this is what fallback wraps around):
```python
def reduce_one_day(image: ee.Image) -> ee.FeatureCollection:
    date = image.date()
    doy = date.getRelative("day", "year").add(1)
    reduced = image.select(band).reduceRegions(
        collection=wards, reducer=ee.Reducer.mean(), scale=scale
    )

    def set_row_properties(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        return feature.set(
            "ward_id", feature.get(ward_id_property),
            "value", feature.get("mean"),
            "doy", doy,
            "system:time_start", date.millis(),
        )

    return reduced.map(set_row_properties)

return ee.FeatureCollection(image_collection.map(reduce_one_day)).flatten()
```

**D-08 fallback pattern (verified live, reproduce VERBATIM from 04-RESEARCH.md Pattern 2):**
```python
# Source: verified live against heatwave-508110, this session.
# image.reduceRegions(collection=tiny_ward_polygon_fc, reducer=ee.Reducer.mean(), ...)
# -> {'wardcode': 'W-TINY'}  (no 'mean' key at all -- confirmed null/absent)
# image.reduceRegions(collection=tiny_ward_polygon_fc, reducer=ee.Reducer.first(), ...)
# -> {'wardcode': 'W-TINY'}  (STILL absent -- reduceRegions area-weights regardless of reducer)
# image.reduceRegions(collection=<SAME FEATURE'S CENTROID POINT>, reducer=ee.Reducer.first(), ...)
# -> {'wardcode': 'W-TINY', 'first': 4.95...}  -- WORKS, exact shape match with primary path

def build_fallback_ward_centroids(small_wards: ee.FeatureCollection, ward_id_property: str) -> ee.FeatureCollection:
    """Re-key each small ward's geometry to its centroid POINT (not the
    polygon) so reduceRegions can use a non-area-weighted reducer.
    image.sampleRegions() was also tried and does NOT work here -- it still
    requires a full pixel CENTER to fall inside the region, which a small
    ward's original polygon can fail even when its centroid falls squarely
    inside a pixel."""
    return small_wards.map(
        lambda f: ee.Feature(f.geometry().centroid(), {ward_id_property: f.get(ward_id_property)})
    )

def reduce_one_day_with_fallback(image, normal_wards, fallback_ward_centroids, band, scale, ward_id_property):
    primary = image.select(band).reduceRegions(collection=normal_wards, reducer=ee.Reducer.mean(), scale=scale)
    fallback = image.select(band).reduceRegions(collection=fallback_ward_centroids, reducer=ee.Reducer.first(), scale=scale)
    primary = primary.map(lambda f: f.set("value", f.get("mean"), "used_fallback_reducer", False))
    fallback = fallback.map(lambda f: f.set("value", f.get("first"), "used_fallback_reducer", True))
    return primary.merge(fallback)
```
**One-time small-ward detection (do not re-derive per day/per chunk — 04-RESEARCH.md Pitfall 5):** run the primary `reduceRegions` once for one arbitrary day across all 4,841 wards, collect ward IDs whose `mean` is null; persist that static list (Python-side) and reuse it for every day of every chunk. This detection step belongs in `scripts/run_batch_export.py`'s setup phase, not inside `zonal.py`'s per-day loop.

**D-09 loggability:** every output row (both primary and fallback paths) must carry a `used_fallback_reducer` boolean (shown above) so downstream consumers/logs can detect which rows used the lower-fidelity reducer, per CONTEXT.md D-09.

---

### `scripts/run_batch_export.py` (NEW — script/orchestrator)

**Analog:** No exact prior analog exists in this repo (this is the first async-task/CLI-entry-point script). Closest structural precedents:
- `heatwave/auth.py` lines 53-61 for the `if __name__ == "__main__":` CLI-entry convention and `init_ee()` call-first pattern.
- The pipeline composition order demonstrated in `tests/test_heatwave_detection.py`'s `test_end_to_end_climatology_and_event_pipeline` (lines 851-975): `reduce_to_ward_daily` → `compute_climatology_thresholds` → `flag_heatwave_days` → `detect_heatwave_events`, called in that exact order with the same default-parameter shape this script must replicate at full scale.
- 04-RESEARCH.md Pattern 5 for the task-state-file/polling mechanics themselves (no codebase analog; reproduce from research verbatim).

**CLI-entry / auth pattern** (from `heatwave/auth.py` lines 53-61):
```python
def init_ee() -> None:
    """Authenticate and initialize the Earth Engine client. Idempotent."""
    credentials = _load_credentials()
    ee.Initialize(credentials, project=settings.gcp_project_id)


if __name__ == "__main__":
    init_ee()
    print("Earth Engine ready:", ee.Number(1).add(1).getInfo() == 2)
```
`run_batch_export.py` should call `heatwave.auth.init_ee()` once at startup before any EE call, matching every existing test/module's convention (`from heatwave.auth import init_ee; init_ee()` — see `tests/test_integration.py` line 56, `tests/test_heatwave_detection.py` throughout).

**Full pipeline composition order to replicate per chunk** (from `tests/test_heatwave_detection.py` lines 877-975, `test_end_to_end_climatology_and_event_pipeline` — this IS the exact call sequence and default-argument shape the script's per-chunk graph-builder must reproduce at full ward-batch/date-range scale):
```python
from heatwave.auth import init_ee
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
from heatwave.science.heat_index import compute_heat_index, compute_relative_humidity
from heatwave.science.climatology import compute_climatology_thresholds
from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days
from heatwave.zonal import reduce_to_ward_daily
from heatwave.export import ...  # weekly aggregation, this phase's new module

init_ee()
wards = load_ward_boundary()  # then .filter(...) or slice into the chunk's ward-batch
collection = (
    load_era5_land(boundary=wards, start_date=..., end_date=...)
    .map(compute_relative_humidity)
    .map(compute_heat_index)
)
ward_daily_fc = reduce_to_ward_daily(collection, wards)  # + D-08 fallback wiring
climatology_fc = compute_climatology_thresholds(ward_daily_fc, ...)
flagged_fc = flag_heatwave_days(ward_daily_fc, climatology_fc)
events_fc = detect_heatwave_events(flagged_fc, ...)
weekly_fc = ...  # heatwave/export.py's new weekly aggregation, joined with event_start_weeks
```
Note the test's own runtime-fallback comment (lines 903-917): a single lazily-re-evaluated computation graph spanning zonal reduction through event detection measured 65.81s for a 60-row fixture and had to be split into two materialized stages to fit a 30s test budget. This is direct evidence that `run_batch_export.py`'s ward-batch chunking (D-05) is not just a row-count concern but also a computation-graph-depth concern — the chunk planner should keep each per-chunk graph reasonably shallow, matching the precedent of materializing intermediate results rather than chaining unboundedly.

**Async task submission + resumable state-file pattern (verified via official EE docs, reproduce VERBATIM from 04-RESEARCH.md Pattern 5 — no codebase analog):**
```python
# Source: Earth Engine batch task lifecycle verified via official docs this
# session (developers.google.com/earth-engine/guides/processing_environments,
# .../guides/usage): batch tasks have a 10-day max lifetime, are retried up
# to 5 times automatically on failure, ~2 tasks run concurrently per
# noncommercial project on average, and the project's task queue supports up
# to 3,000 pending tasks -- ample headroom for ~10-25 ward-batch chunks.
import json
from pathlib import Path

STATE_FILE = Path("outputs/.batch_export_tasks.json")

def submit_or_resume(chunk_id: str, build_task_fn) -> str:
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    if chunk_id in state and state[chunk_id]["status"] not in ("FAILED", "CANCELLED"):
        return state[chunk_id]["task_id"]
    task = build_task_fn()
    task.start()
    state[chunk_id] = {"task_id": task.id, "status": "SUBMITTED"}
    STATE_FILE.write_text(json.dumps(state, indent=2))
    return task.id

def poll_until_complete(task_ids: list[str], poll_interval_s: int = 30):
    import time
    import ee
    pending = set(task_ids)
    while pending:
        for task_id in list(pending):
            status = ee.data.getTaskStatus(task_id)[0]
            if status["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
                pending.discard(task_id)
        if pending:
            time.sleep(poll_interval_s)
```

**Export destination — use `toAsset()`, never `toDrive()`/`toCloudStorage()` (04-RESEARCH.md Landmine 1 / Pitfall 1):**
```python
task = ee.batch.Export.table.toAsset(
    collection=weekly_fc,
    description=f"covariate_export_{chunk_id}",
    assetId=f"{settings.ward_asset_id.rsplit('/', 1)[0]}/covariate_chunk_{chunk_id}",
)
task.start()
```
(`toDrive()` fails for service-account-only credentials with `StorageQuotaExceeded`; `toCloudStorage()` requires a new GCS bucket, forbidden by D-07.)

**Paginated read-back (avoids the 10MB-request/100MiB-result `getInfo()` quota):**
```python
def download_asset_to_csv(asset_id: str, csv_path: Path, page_size: int = 5000) -> None:
    fc = ee.FeatureCollection(asset_id)
    total = fc.size().getInfo()
    offset = 0
    rows = []
    while offset < total:
        page = fc.toList(page_size, offset).getInfo()
        rows.extend(f["properties"] for f in page)
        offset += page_size
    # write rows to csv_path with csv.DictWriter, fieldnames = EXPORT-02 schema order
```

**Completeness check before final write (EXPORT-03, from 04-RESEARCH.md Security Domain table):** before writing `outputs/covariate_table.csv`, verify the union of all chunk ward-IDs equals the full 4,841-ward set — never concatenate whatever chunk CSVs happen to exist on disk without this check.

**State-file gitignore note:** `outputs/.batch_export_tasks.json` is machine/run-specific (like `keys/service_account.json`, already gitignored at `.gitignore` line 14). The current `.gitignore` (read this session) does NOT yet exclude `outputs/.batch_export_tasks.json` or `outputs/*.csv` — planner should flag adding an `outputs/.batch_export_tasks.json` (or broader `outputs/*` exclusion, if the CSV itself shouldn't be committed) entry as part of this phase's file changes.

---

### `tests/test_export.py` (NEW — test)

**Analog:** `tests/test_heatwave_detection.py` (skip-gated live-EE pattern, synthetic fixture builders, `_props()` helper) — copy this file's structure directly.

**Skip-gate boilerplate to copy verbatim** (`tests/test_heatwave_detection.py` lines 1-24):
```python
"""Live, skip-gated tests verifying zonal reduction, climatology and heatwave detection
against synthetic time series (CLIM-01 through CLIM-06)."""
from __future__ import annotations

import inspect
import os
from datetime import datetime, timezone
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

# NOTE: This gate is intentionally applied per-test (via `_REQUIRES_CREDENTIALS`) rather
# than as a module-level `pytestmark`. A module-level `pytestmark` would also skip
# any credential-free "module exports" smoke test. Do not "restore" the module-level form.
_REQUIRES_CREDENTIALS = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)
```

**`_props()` materialization helper to reuse verbatim** (`tests/test_heatwave_detection.py` lines 58-69):
```python
def _props(fc: ee.FeatureCollection, keys):
    """Materialise a FeatureCollection's properties via a single `.getInfo()` call.

    Returns a plain Python list of dicts, one per feature, containing only the
    requested property keys. An absent property surfaces as `None` rather than
    raising, via `.get(key)`.
    """
    info = fc.getInfo()
    return [
        {key: feature["properties"].get(key) for key in keys}
        for feature in info["features"]
    ]
```

**Credential-free "module exports" smoke test pattern** (`tests/test_heatwave_detection.py` lines 72-76, 261-273, 628-639) — one per new public function, no credentials required:
```python
def test_export_module_exports():
    """EXPORT-02/EXPORT-04: heatwave.export exports its public aggregation functions, no credentials required."""
    from heatwave.export import iso_year_and_week, ...  # actual exported names per planner's implementation

    assert callable(iso_year_and_week)
    ...
```

**Synthetic fixture builder convention to follow** (`tests/test_heatwave_detection.py` lines 27-56, `_make_ward_fc`/`_make_heat_index_collection`, and lines 828-848's `_make_constant_heat_index_collection` for a hand-computable end-to-end fixture): build a small (`_make_ward_daily_fc`-shaped) synthetic FeatureCollection reproducing `detect_heatwave_events`'s exact output row schema (`ward_id`, `value`, `is_hot`, `event_id`, `system:time_start`) directly — do NOT run the real full pipeline in this test file (per CONTEXT.md's Integration Points: EXPORT-04 tests schema/aggregation correctness on a small bounded sample, never the full historical export inline).

**Required test cases (per 04-RESEARCH.md Validation Architecture / Wave 0 Gaps and CONTEXT.md D-08/D-09):**
1. `time_period` ISO-week-year boundary correctness — a fixture spanning a real Dec 30 → Jan 5 range, asserting `time_period` values against hand/`isocalendar()`-computed expectations (mirrors `test_pooling_window_wraps_across_new_year`'s wraparound-fixture style, lines 304-327).
2. Schema exactness — assert output feature properties are exactly `{time_period, location, heatwave_days, mean_heat_index, max_heat_index, heatwave_event_count}`, no more, no fewer (EXPORT-02).
3. D-08 fallback — reuse `test_zonal_reduction_tiny_ward_row_is_null_not_dropped`'s tiny-ward fixture pattern (lines 205-227) but assert the NEW fallback-filled non-null value and `used_fallback_reducer=True`, not a null.
4. `heatwave_event_count` counts event STARTS, not event-touching weeks — a 4-day event starting on a week's last day and continuing into the next week must count once, in the starting week only.
5. Completeness (EXPORT-03 proxy) — no missing wards, no null aggregate columns, on a small bounded multi-ward sample.

## Shared Patterns

### Config-driven parameters, never hardcoded
**Source:** `heatwave/config.py` (whole file) + the `is not None` defensive-default idiom in `heatwave/science/climatology.py` lines 88-93 and `heatwave/science/heatwave.py` lines 189-193.
**Apply to:** `heatwave/export.py`, `scripts/run_batch_export.py`. Any date range, ward-id-property, or ward-batch-size parameter must be a caller argument or read from `settings`, never a bare literal — this is also Security Domain V5 (input validation) for the export date range specifically.

### Null-preservation vs. genuine-zero distinction
**Source:** `heatwave/zonal.py` lines 47-56 (null value = missing data, never coalesced to 0) and `heatwave/science/heatwave.py` lines 55-58, 78-89 (outer-join null preservation via `ee.Algorithms.If`).
**Apply to:** `heatwave/export.py`'s weekly aggregation (heatwave_days/mean/max preserve nulls per D-08) versus `heatwave_event_count` (missing week = genuine 0, per 04-RESEARCH.md Pattern 4) — these are DIFFERENT rules for different columns in the same output row; do not apply one uniformly.

### Plain-function, no-class module style
**Source:** every existing `heatwave/` module (`zonal.py`, `science/climatology.py`, `science/heatwave.py`, `data/ingest.py`, `science/heat_index.py`, `auth.py`, `data/boundary.py`).
**Apply to:** `heatwave/export.py` in full. `scripts/run_batch_export.py` may use plain functions plus an `if __name__ == "__main__":` block (per `heatwave/auth.py`'s convention) — no classes anywhere in this codebase.

### Skip-gated live-EE test pattern
**Source:** `tests/test_heatwave_detection.py` lines 1-24 (per-test `_REQUIRES_CREDENTIALS` marker, not module-level `pytestmark`, to keep credential-free "module exports" smoke tests runnable) and `tests/test_integration.py` lines 16-22 (module-level `pytestmark` variant, used when EVERY test in the file needs credentials).
**Apply to:** `tests/test_export.py` — use the per-test marker variant (like `test_heatwave_detection.py`), since at least one credential-free "module exports" test should exist per established convention.

### `ee.Filter.date()` half-open interval
**Source:** `heatwave/data/ingest.py` line 33 + `tests/test_integration.py` lines 73-87 (`test_load_era5_land`'s docstring: `[start, end)`, a 2020-01-01 to 2020-01-05 window yields exactly 4 daily images, not 5).
**Apply to:** any date-range handling in `run_batch_export.py`'s chunk planner — the configured export end date is exclusive, matching the existing `load_era5_land` contract already in use.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/run_batch_export.py`'s async task-submit/poll/resume harness specifically | script/orchestrator | event-driven (poll until COMPLETED) | No prior async Earth Engine batch-task code exists anywhere in this repo — every existing module/test uses synchronous `getInfo()`. Use 04-RESEARCH.md Pattern 5 (Google's official EE batch-task lifecycle docs) verbatim, reproduced above, in place of a codebase analog. |

## Metadata

**Analog search scope:** `heatwave/` (all modules), `tests/` (all 4 existing test files), `heatwave/config.py`, `config.yaml`, `.gitignore` — full repository source tree excluding `.venv/`, `build/`, `.planning/`.
**Files scanned:** `heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, `heatwave/config.py`, `heatwave/auth.py`, `heatwave/data/ingest.py`, `heatwave/data/boundary.py`, `heatwave/science/heat_index.py`, `tests/test_heatwave_detection.py`, `tests/test_integration.py`, `.gitignore`, `config.yaml`.
**Pattern extraction date:** 2026-09-15
