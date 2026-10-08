# Phase 4: Batch Export & Covariate Table - Research

**Researched:** 2026-09-15
**Domain:** Google Earth Engine asynchronous batch export, full-scale (4,841-ward × ~35-year) server-side aggregation, ISO-week time-series bucketing
**Confidence:** MEDIUM-HIGH (every core API claim and the trickiest date-math/aggregation pattern were verified live against the real `heatwave-508110` project this session; the full-scale runtime estimate is a benchmarked extrapolation, not a full-scale dry run)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Export scope: full historical backfill, not a bounded window
- **D-01:** The production run this phase delivers targets the full 1991-present record for all 4,841 wards, not a bounded recent window. This is a deliberate, explicit choice to accept the full cost/runtime now rather than deferring the historical backfill to a later ops task.
- **D-02:** This is a genuinely large computation (~4,841 wards × ~35 years of daily data feeding weekly aggregation) — expect the actual production export to take substantial real time (likely hours) and consume real Earth Engine compute quota. Flagging this explicitly so it isn't a surprise at execution time.

#### Execution model: asynchronous Earth Engine batch export
- **D-03:** `scripts/run_batch_export.py` must use Earth Engine's asynchronous batch export mechanism (`ee.batch.Export.table...`), not synchronous `getInfo()` calls — required at this scale; Earth Engine's synchronous computation timeout would very likely be exceeded otherwise.
- **D-04:** The script's job is to build the full computation graph (chaining `heatwave/zonal.py` → `heatwave/science/climatology.py` → `heatwave/science/heatwave.py` → weekly aggregation) and submit it as an Earth Engine batch task, then poll for completion. It does not need to hold the process open synchronously waiting — polling/resume behavior is implementation detail for research/planning to work out.
- **D-05:** Whether the full 1991-present graph can be submitted as a single Earth Engine batch task or must be chunked (e.g., by year or ward-batch) to stay within Earth Engine's per-task limits is a genuine open technical question — research territory, not a locked decision. If chunking is required, the script must still produce one final, complete covariate table (concatenating/merging chunks), not leave the user to manually stitch outputs together.

#### Output destination: CSV to outputs/
- **D-06:** The finished covariate table is written as a CSV file to `outputs/` (matching this project's existing convention for generated artifacts), matching EXPORT-02's schema exactly: `time_period`, `location`, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`.
- **D-07:** No new cloud infrastructure (GCS bucket, BigQuery dataset) is provisioned in this phase. CHAP's actual ingestion mechanism (API push, GCS pickup, BigQuery, etc.) is explicitly deferred — this phase's job is to produce a correct, complete CSV that could be handed off by any mechanism later.

#### Small-ward null-value policy (resolves Phase 3's deferred item)
- **D-08:** When `heatwave/zonal.py`'s primary area-weighted zonal reduction (`ee.Reducer.mean()`) returns null for a ward too small relative to ERA5-Land's ~11.1km pixel size, fall back to a reducer that doesn't require partial-pixel-weight coverage (e.g. a centroid/nearest-pixel sample) so every ward gets a real value. No ward is silently excluded from the final covariate table, and no null is ever coalesced to a fabricated 0.
- **D-09:** The fallback's use should be detectable/loggable (e.g., a boolean column or a log line noting which wards used the fallback reducer) so data quality is transparent to whoever consumes the CSV, even though EXPORT-02's schema itself is not expanded with a new required column.

### Claude's Discretion
- Whether the full 1991-present export needs chunking (D-05) — research territory.
- Exact polling/resume mechanics for the async batch task (D-04).
- Whether/how to log which wards used the D-08 fallback reducer — exact mechanism (separate log file, stderr, a non-schema CSV column) is implementation discretion, as long as it's transparent per D-09.
- Whether `tag_consecutive_runs`'s `ee.List.iterate()` state machine (Phase 3, verified only up to ~3,650 elements) needs to switch to the documented array forward-difference fallback at this phase's full ~12,800-day-per-ward scale — benchmark first per Phase 3's own research recommendation; switch only if the benchmark shows it's actually too slow, don't switch preemptively.
- Weekly aggregation logic itself (grouping daily heatwave-day/event-flag rows into ISO weeks, computing `mean_heat_index`/`max_heat_index` per week) has no prior-phase precedent to reuse — this is new code for this phase, follow the established plain-function `heatwave/` module style.

### Deferred Ideas (OUT OF SCOPE)
- CHAP's actual ingestion mechanism (API, GCS, BigQuery, etc.) — explicitly deferred per D-07, not this phase's job.
- Any new cloud infrastructure provisioning — deferred alongside the above.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXPORT-01 | `scripts/run_batch_export.py` runs the full ingest → heat-index → climatology → detection pipeline across all 4,841 wards for a configurable date range | Architecture Patterns (chunked-task pipeline, task-state file for resume); Common Pitfalls 1-4; Environment Availability |
| EXPORT-02 | The generated covariate table matches the target schema exactly: `time_period` (ISO week), `location`, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count` | Pattern 1 (verified live ISO-week/year computation), Pattern 3 (verified live composite-key weekly aggregation), Pattern 4 (event-start-week counting) |
| EXPORT-03 | Full-period run produces a complete table (no missing wards, no null aggregates) | Pattern 2 (D-08 fallback reducer, verified live), Common Pitfall 5 (small-ward null handling) |
| EXPORT-04 | `tests/test_export.py` verifies covariate table schema and aggregation correctness | Validation Architecture section; Wave 0 Gaps |
</phase_requirements>

## Summary

Phase 4 does not introduce a new technical domain so much as it stress-tests Phase 3's already-built pipeline (`heatwave/zonal.py` → `climatology.py` → `heatwave.py`) at real scale and adds two genuinely new pieces: (1) an asynchronous Earth Engine batch-export/poll harness, and (2) ISO-week aggregation logic that has no prior-phase precedent. Both pieces contain a landmine that this session's live verification against `heatwave-508110` directly caught:

**Landmine 1 (export destination):** `ee.batch.Export.table.toDrive()` is documented to fail for service-account-only credentials with a `StorageQuotaExceeded`/"Service Accounts do not have storage quota" error — a widely-reported, real-world failure mode, not a hypothetical. `ee.batch.Export.table.toCloudStorage()` needs an existing GCS bucket, and D-07 explicitly forbids provisioning new cloud infrastructure. The one destination that requires **zero new infrastructure** and works cleanly with a bare service account is `ee.batch.Export.table.toAsset()` — it writes into the project's own Earth Engine asset namespace (the same namespace the ward boundary asset already lives in), well within its 250GB/10,000-asset/100M-features-per-table quota. **Recommendation: export to an EE table asset, then read it back via paginated `FeatureCollection.getInfo()`/`toList(pageSize, offset)` calls (not a single unbounded `getInfo()`), writing rows straight to the local CSV.** This respects D-07, D-03, and D-06 simultaneously and needs no new Python dependencies (the already-installed `earthengine-api` covers everything).

**Landmine 2 (ISO week math):** `ee.Date.get('week')` DOES follow ISO-8601 week numbering (Monday-start weeks, week 1 = week containing the year's first Thursday) — verified live against Python's `datetime.isocalendar()` as ground truth across 8 edge-case dates including two `week-53` years and both Dec→Jan boundary directions, with 100% agreement. **However, `ee.Date.get('year')` returns the plain calendar year, not the ISO week-numbering year** — so `2024-12-30` (a Monday) returns `week=1, year=2024`, which is `2024-W01`, not the correct `2025-W01`. Naively concatenating `get('year')` and `get('week')` will silently split late-December/early-January data into wrong or duplicate week buckets every single year at the boundary — a real, reproducible bug, not a theoretical edge case, and it fires every year of the 35-year backfill. A verified-live formula for computing the correct ISO week-year is provided in Pattern 1 below.

**Landmine 3 (full-scale runtime):** A live benchmark of `detect_heatwave_events` (Phase 3's per-ward `.iterate()`-based event detector, run unmodified) shows roughly linear cost in total row count, at ~2.0-2.3 ms/row, measured from 2,000 rows up to 36,500 rows. Extrapolating (a real extrapolation, not a full-scale run — flagged as an assumption) to the full ~4,841-ward × ~12,800-day (~35-year) scale of ~62 million rows suggests **~34-40 hours of compute for the event-detection stage alone if submitted as one single unchunked task** — well past a comfortable single-task budget even though it is technically under Earth Engine's 10-day batch task lifetime limit. This strongly supports D-05's chunking path: split the full run into ward-batches (e.g., ~200-500 wards per task), each producing its own small EE table asset, submitted as separate batch tasks (Earth Engine batch tasks average only ~2 concurrently running per noncommercial project, but queue depth up to 3,000, so wall-clock time is roughly total-compute ÷ 2, still "hours," consistent with D-02's own framing). No evidence from this session's testing suggests `tag_consecutive_runs`'s `.iterate()` itself is pathologically slow at a single ward's full ~12,800-day series (benchmarked directly: 6.7-11s, no blow-up) — the discretion item's recommended action is to **keep `.iterate()` unchanged and chunk by ward-batch**, not switch to the array forward-difference algorithm, unless a larger confirming benchmark (recommended below) shows otherwise.

**Primary recommendation:** Build `scripts/run_batch_export.py` as (1) a ward-batch chunker (e.g., ~200-500 wards/chunk) that for each chunk builds the full ingest→heat_index→zonal→climatology→heatwave→weekly-aggregation graph and submits `ee.batch.Export.table.toAsset()`, (2) a JSON task-state file (`outputs/.batch_export_tasks.json` or similar) recording each chunk's task ID so the script is safely re-runnable/resumable without resubmitting completed work, (3) a polling loop (or a separate `--poll`/`--collect` invocation) that waits for `COMPLETED` tasks and paginates their resulting table assets down into per-chunk CSVs, and (4) a final concatenation step merging all chunk CSVs into the one `outputs/covariate_table.csv` EXPORT-02 requires.

## Architectural Responsibility Map

This project is a batch geospatial pipeline, not a multi-tier web app — the "tiers" below are pipeline stages / execution contexts.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Full-scale zonal/climatology/detection computation | EE server-side (batch computation graph) | — | Must stay server-side at 4,841-ward × 35-year scale; pulling raw daily data to Python first is intractable (~62M rows) |
| Weekly (ISO-week) aggregation | EE server-side (`reduceColumns` + `Reducer.group()`) | — | New code this phase; must happen BEFORE export so the exported/downloaded table is the small (~8.8M-row) weekly grain, not the ~62M-row daily grain |
| Batch task submission & lifecycle | Python orchestration (`ee.batch.Export.table.toAsset(...).start()`) | — | `scripts/run_batch_export.py`'s job per D-03/D-04 |
| Task-state tracking / resume | Python orchestration (local JSON state file) | — | D-04 explicitly allows the script to not hold the process open; a state file is what makes re-running it safe |
| Result retrieval (asset → local CSV) | Python orchestration (paginated `FeatureCollection.toList(...).getInfo()` calls) | EE server-side (asset already materialized, cheap to read) | Reading a materialized asset is cheap; a single unbounded `getInfo()` on ~8.8M rows would exceed the documented 10MB request / 100MiB result quotas |
| Small-ward fallback-reducer detection | EE server-side (one-time geometric/null check) | Python (persists the small-ward-id list for reuse across all chunks) | D-08; must be computed once, not re-derived per chunk/per day |
| CSV schema/column shape (EXPORT-02) | Python orchestration (final concatenation + column ordering) | — | The last, cheap, purely local step |
| Config-driven parameters (date range, wards, climatology settings) | Python (`heatwave.config.settings`) | — | Already implemented; this phase's new code must read from it, not hardcode |
| Test orchestration / credential gating | Python (`pytest`, skip-gated) | — | Established pattern from Phases 1-3 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `earthengine-api` | 1.6.8 [VERIFIED: live `import ee; ee.__version__` in this project's `.venv`, this session] | All batch export, task polling, and server-side aggregation | Already the project's sole geospatial compute engine; no alternative under consideration |
| `pytest` | 8.4.1 [VERIFIED: `requirements.txt`, this session] | Skip-gated live-EE test runner | Established pattern from Phases 1-3 |

### Supporting
**No new packages are needed for this phase.** `google-cloud-storage` and `google-api-python-client` are already in `requirements.txt` (installed for `geemap`'s own dependency chain, not currently used directly by `heatwave/`), but the recommended `toAsset()` + paginated-`getInfo()` path (see Summary) needs neither — it uses only `earthengine-api`'s own client. Python's standard-library `csv`/`json` modules are sufficient for writing the output CSV and the task-state file. This deliberately avoids introducing a Drive-API or GCS-client code path that D-07 would then require justifying as "new infrastructure usage."

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ee.batch.Export.table.toAsset()` + paginated read-back | `ee.batch.Export.table.toDrive()` | Documented, real-world `StorageQuotaExceeded` failure for service-account-only credentials (this project's only credential path) — [MEDIUM confidence: cross-referenced Google Developer forum threads and Google Drive Community reports, not reproduced live in this session since doing so would require actually attempting a Drive export against the real service account, which risks leaving a failed/partial task]. Rejected primary path. |
| `ee.batch.Export.table.toAsset()` + paginated read-back | `ee.batch.Export.table.toCloudStorage()` | Requires an existing GCS bucket; D-07 forbids provisioning a new one, and no existing bucket was found in this project's constraints/config. Viable ONLY if the user later decides to provision a bucket outside this phase's scope. |
| Ward-batch chunking (~200-500 wards/task) | Chunking by year instead of by ward | Chunking by year does not reduce the per-task row count as effectively for the detection stage's per-ward operations (each yearly chunk would still need to touch all 4,841 wards' partial time series, complicating the run-length state machine across chunk boundaries — a mid-run split would incorrectly truncate events spanning a chunk boundary). Ward-batch chunking cleanly avoids this because `detect_heatwave_events` already partitions by ward; splitting along that same axis never truncates a run mid-event. |
| Keep `ee.List.iterate()` for run detection | Switch to the "Runs with Arrays" forward-difference/array-masking technique (Gorelick) | Live-benchmarked: `.iterate()` handled a single ward's full ~12,800-day series in 6.7-11s with no sign of blow-up (see Common Pitfall 3 / Metadata). Per CONTEXT.md's discretion ("switch only if the benchmark shows it's actually too slow"), the evidence does not support switching. Revisit only if a larger confirming benchmark (recommended: ~500 wards × full 35 years) shows super-linear behavior. |

**Installation:** None — no new packages.

**Version verification:** `earthengine-api==1.6.8` confirmed via `.venv/Scripts/python.exe -c "import ee; print(ee.__version__)"`, this session [VERIFIED: local environment]. `pytest==8.4.1` confirmed directly from `requirements.txt` [VERIFIED: local file].

## Package Legitimacy Audit

**Not applicable — this phase introduces zero new external package dependencies.** It exclusively uses `earthengine-api` (already installed and audited in Phase 1) and Python's standard library (`csv`, `json`). No `pip install`, no `slopcheck` run, and no registry verification is required.

## Architecture Patterns

### System Architecture Diagram

```
config.yaml (settings.start_date/end_date OVERRIDDEN by this phase's
own full-history range per D-01 -- NOT the Streamlit-viewer defaults)
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ scripts/run_batch_export.py -- CHUNK PLANNER               │
│ Splits the full 4,841-ward asset into ward-batches          │
│ (e.g. 200-500 wards each -> ~10-25 chunks)                   │
└───────────────────────┬───────────────────────────────────┘
                         │ for each chunk (ward subset)
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Existing Phase 1-3 pipeline, called UNCHANGED, per chunk:    │
│  load_era5_land -> compute_relative_humidity/heat_index      │
│  -> reduce_to_ward_daily (+ D-08 fallback branch, NEW)        │
│  -> compute_climatology_thresholds -> flag_heatwave_days      │
│  -> detect_heatwave_events                                    │
└───────────────────────┬───────────────────────────────────┘
                         │ per-ward-daily FeatureCollection (this chunk)
                         ▼
┌───────────────────────────────────────────────────────────┐
│ heatwave/export.py -- WEEKLY AGGREGATION (NEW, this phase)   │
│  1. compute ISO (year,week) per row (Pattern 1)               │
│  2. composite-key group by (ward_id, time_period) for         │
│     heatwave_days / mean_heat_index / max_heat_index          │
│     (Pattern 3)                                                │
│  3. composite-key group by (ward_id, event start's time_period)│
│     for heatwave_event_count (Pattern 4)                       │
│  4. join the two grouped tables -> one row per (ward, week)   │
└───────────────────────┬───────────────────────────────────┘
                         │ weekly covariate FeatureCollection (this chunk, ~small)
                         ▼
┌───────────────────────────────────────────────────────────┐
│ ee.batch.Export.table.toAsset(...).start()                  │
│ -> writes to projects/heatwave-508110/assets/<chunk_asset>   │
│ -> task ID recorded in a local JSON state file                │
└───────────────────────┬───────────────────────────────────┘
                         │ poll task.status() until COMPLETED (D-04)
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Paginated read-back: ee.FeatureCollection(assetId)            │
│  .toList(pageSize, offset).getInfo() loop -> per-chunk CSV     │
│ (avoids the 10MB-request / 100MiB-result getInfo() quota)     │
└───────────────────────┬───────────────────────────────────┘
                         │ all chunks COMPLETED + downloaded
                         ▼
┌───────────────────────────────────────────────────────────┐
│ Concatenate per-chunk CSVs -> outputs/covariate_table.csv     │
│ (EXPORT-02 schema, EXPORT-03 completeness check)               │
└───────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
heatwave/
├── export.py                       # NEW: weekly aggregation + fallback-reducer wiring
└── zonal.py                        # MODIFIED: add D-08 fallback branch (small-ward detection + centroid reducer)
scripts/
└── run_batch_export.py             # NEW: chunk planner, task submit/poll/collect, CSV concat (EXPORT-01)
tests/
└── test_export.py                  # NEW: EXPORT-04, schema/aggregation correctness on a small bounded sample
outputs/
├── covariate_table.csv             # final deliverable (D-06)
└── .batch_export_tasks.json        # NEW (discretion): task-state file for resumability
```

### Pattern 1: ISO-8601 week number AND week-year, verified live
**What:** `ee.Date.get('week')` correctly implements ISO-8601 week numbering (verified live: Monday-start weeks via `getRelative('day','week')` returning 0 for Monday; week 1 = week containing the year's first Thursday). `ee.Date.get('year')` does **not** auto-adjust to the ISO week-numbering year at the Dec/Jan boundary — you must derive it explicitly via the "Thursday of the same ISO week" trick.
**When to use:** Every row's `time_period` computation — this is the single most important piece of new logic in this phase, and it is wrong in the "obvious" naive form.
**Verified live, this session, against `heatwave-508110`, cross-checked against Python's `datetime.date(...).isocalendar()` as ground truth on 8 dates including two week-53 years and both wraparound directions — 100% match:**
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
**Do NOT** use `ee.Date.get('year')` paired with `ee.Date.get('week')` directly — verified live to produce `(2024, 1)` for both `2024-12-30` and `2025-01-01`, which are actually the SAME ISO week (`2025-W01`) but would land in two different `time_period` buckets (`"2024-W01"` and `"2025-W01"`), silently splitting one week's ward-days across two rows every single year of the 35-year backfill.

### Pattern 2: D-08 fallback reducer for small wards — verified live
**What:** The primary `reduceRegions(reducer=ee.Reducer.mean())` call returns a row with the `mean`/`value` property entirely null for wards below EE's ~0.4%-pixel-weight inclusion threshold (Phase 3 finding, re-confirmed live this session). CONTEXT.md's suggested fix — sampling at the ward's **centroid point** rather than its polygon — was tested live and works; a same-shaped `reduceRegions` call over the polygon (even with `ee.Reducer.first()`) does NOT work (still empty/null, since `reduceRegions` still area-weights).
**When to use:** Once, to identify the (expected small) set of wards that need fallback treatment; then for every day, for that fixed small ward subset only — not for all 4,841 wards on every day.
**Verified live, this session:**
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
**How to identify the fallback ward set once:** run the primary `reduceRegions` for a single arbitrary day across all 4,841 wards, collect the ward IDs whose `mean` is null. This is a purely geometric property of the ward polygon vs. the fixed ERA5-Land grid — it does not vary by date — so it only needs to be computed once per production run, not per chunk/per day.

### Pattern 3: Weekly aggregation via a composite string key — verified live, and a real EE gotcha avoided
**What:** `reduceColumns` supports grouping by only ONE field per `.group()` call. Grouping by two fields (ward + week) by naively **chaining** `.group(groupField=1,...).group(groupField=0,...)` was tried live this session and **produced silently wrong, swapped output** (values and week numbers ended up cross-assigned) — this is a real trap, not a hypothetical one. The verified-working fix: build a single composite string key (`ward_id + "::" + time_period`) as an extra property, group by that ONE field, then split the key back apart with `ee.String.split()` after grouping.
**When to use:** Both weekly aggregates in EXPORT-02 (`heatwave_days`, `mean_heat_index`, `max_heat_index`) and the event-start-week count (Pattern 4).
**Verified live, this session — exact output matched hand-computed expected values:**
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
Live-verified output for a 2-ward, 2-week, 6-row synthetic fixture matched hand-computed `mean`/`max`/`count` exactly for all four (ward, week) groups.

### Pattern 4: `heatwave_event_count` = events STARTING that week, not hot days that week
**What:** Per PROJECT.md's schema note, `heatwave_event_count` counts distinct events by their START week, not every week they touch. This is a two-stage version of Pattern 3: first collapse each event (`ward_id`, `event_id` pair, excluding `NO_RUN`) down to its single earliest `system:time_start` (its start date), convert that start date to `(ward_id, time_period)` via Pattern 1, then apply Pattern 3's composite-key group-and-count to those event-start rows only.
**When to use:** Building the `heatwave_event_count` column, joined into the Pattern-3 weekly table by `(ward_id, time_period)`. Weeks with zero qualifying event starts must be filled with `0` (unlike D-08's null-value prohibition — an actual absence of any hot run starting that week is a genuine, correct zero, not a missing-data null).
**Confidence:** MEDIUM — the composite-key grouping technique itself (Pattern 3) was verified live; this two-stage composition (min-date-per-event, then group-count-by-week-of-that-date) was reasoned from that verified building block but not executed end-to-end live this session. Recommend a small Wave-0 test proving it before relying on it for the full production run.
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

### Pattern 5: Chunked batch export with a resumable task-state file
**What:** Submit one `ee.batch.Export.table.toAsset()` task per ward-batch chunk; record each task's ID in a local JSON file immediately after `.start()`; a re-run of the script reads this file first and skips re-submitting chunks whose recorded task is already `RUNNING`/`COMPLETED`.
**When to use:** `scripts/run_batch_export.py`'s main loop, satisfying D-04's "does not need to hold the process open synchronously" and D-05's chunking requirement together.
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

### Anti-Patterns to Avoid
- **`ee.batch.Export.table.toDrive()` with a service-account-only credential:** documented real-world failure (`StorageQuotaExceeded`) for this exact credential setup. Use `toAsset()` instead.
- **Provisioning a new GCS bucket to use `toCloudStorage()`:** explicitly forbidden by D-07.
- **Pairing `ee.Date.get('year')` with `ee.Date.get('week')` for `time_period`:** silently wrong at every Dec/Jan boundary — verified live. Use Pattern 1's Thursday-of-week formula for the year component.
- **Chaining two `.group()` calls on one reducer to group by two fields:** verified live to produce silently swapped/wrong output. Use a single composite string key instead (Pattern 3).
- **A single unbounded `FeatureCollection.getInfo()` on the full ~8.8M-row weekly table (or the ~62M-row daily table):** will hit the documented 10MB-request / 100MiB-result quotas. Paginate with `.toList(pageSize, offset).getInfo()` in a loop, or use `ee.data.listFeatures`.
- **Submitting the full 1991-present × 4,841-ward graph as one single batch task:** the live-benchmarked linear extrapolation suggests ~34-40 hours for the event-detection stage alone — technically within the 10-day task lifetime but a poor reliability/observability tradeoff versus ~10-25 independently-retryable ward-batch chunks.
- **Re-deriving the D-08 small-ward set from scratch for every day/every chunk:** it's a static geometric property; compute it once and reuse.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Grouping rows by two keys | A Python-side pandas `groupby` after pulling ~62M rows to the client | A single composite string key + one EE `Reducer.group()` call (Pattern 3) | Verified live; keeps the whole aggregation server-side; pulling 62M rows to Python first defeats the purpose of using EE at all |
| ISO week-year at the Dec/Jan boundary | A hand-rolled "if week==1 and month==12 then year+1" heuristic | The Thursday-of-week formula (Pattern 1) | The heuristic version gets leap-week years (53-week years) wrong; the Thursday trick is the actual ISO-8601 definition and was verified exactly against Python's own `isocalendar()` |
| Downloading a large `ee.FeatureCollection` | `ee.batch.Export.table.toDrive()`/manual Drive-API OAuth flow | `ee.batch.Export.table.toAsset()` + paginated `toList().getInfo()` | Avoids the service-account Drive quota failure entirely, needs zero new infrastructure or dependencies |
| Task polling/retry bookkeeping | A custom database or Redis-backed job queue | A single local JSON file tracked alongside `outputs/` | This is a one-shot/occasional-rerun batch script (per CONTEXT.md's Integration Points), not a persistent service — a flat file is proportionate |

**Key insight:** Every new piece of engineering this phase needs (two-key grouping, ISO week-year math, large-collection download) has a documented or live-verifiable EE-native or stdlib-native solution. The two places this session's live testing caught a **real, silently-wrong** result (chained `.group()`, and naive year+week pairing) are exactly the two places a planner/implementer would otherwise ship a subtly incorrect covariate table that looks fine in small samples and only breaks at real-world Dec/Jan boundaries or multi-key aggregation — both now have verified-correct replacements documented above.

## Common Pitfalls

### Pitfall 1: Service-account credentials cannot reliably use `Export.table.toDrive()`
**What goes wrong:** The export task fails with a `StorageQuotaExceeded` / "Service Accounts do not have storage quota" error.
**Why it happens:** Google Cloud service accounts do not have their own Google Drive storage quota by default (a widely-reported issue across many Google APIs, not specific to Earth Engine); Drive uploads attributed to a bare service account (no Shared Drive, no domain-wide delegation) have nowhere to be billed/stored.
**How to avoid:** Use `ee.batch.Export.table.toAsset()` instead (Pattern in Summary/Standard Stack) — it uses the EE project's own asset storage, which the service account already has write access to (it created the ward boundary asset there).
**Warning signs:** A batch task that reaches `RUNNING` then transitions to `FAILED` with a Drive-quota-related error message in `task.status()['error_message']`.

### Pitfall 2: `ee.Date.get('year')` is calendar year, not ISO week-year
**What goes wrong:** `time_period` values computed as `f"{date.get('year')}-W{date.get('week')}"` are wrong for every date in the last few days of December and first few days of January, every single year — verified live (`2024-12-30` and `2025-01-01` both compute `get('year')=` their own calendar year despite being the SAME real ISO week `2025-W01`).
**Why it happens:** ISO week 1 of a year can start in the previous calendar year (and the last ISO week of a year can extend into the next calendar year); `Date.get('year')` does not know this.
**How to avoid:** Use Pattern 1's "Thursday of the same ISO week" formula to derive the correct week-year component.
**Warning signs:** A covariate table with two different `time_period` rows for the same ward covering overlapping dates near a year boundary, or a `time_period` like `"2024-W01"` appearing right next to `"2024-W53"`/`"2025-W01"` out of chronological order.

### Pitfall 3: `.iterate()`-based run detection is benchmarked linear, not proven safe at 100% scale
**What goes wrong:** Nothing observed directly — but the confirming evidence is a benchmarked extrapolation (2,000 to 36,500 rows, live-measured ~2.0-2.3ms/row) applied to a ~1,700x larger target (~62M rows), not a full-scale dry run.
**Why it happens:** Earth Engine's actual behavior at genuinely huge computation-graph sizes (memory limits, per-task compute ceilings) is not fully documented; small-scale linearity does not guarantee large-scale linearity.
**How to avoid:** Chunk by ward-batch (Pattern 5) so no single task's computation graph approaches the scale where this uncertainty matters, AND run one larger confirming benchmark (recommended: ~500 wards × the full ~35-year range, ~6.4M rows) before committing to the full production run's chunk size.
**Warning signs:** A chunk-sized task that fails with `Computation timed out` or `User memory limit exceeded` specifically at the event-detection stage (not zonal reduction or climatology, which don't use `.iterate()`).

### Pitfall 4: Chaining `Reducer.group()` calls to group by two fields silently swaps values
**What goes wrong:** `reducer.group(groupField=1,...).group(groupField=0,...)` was tested live this session and produced output where the "week" and "value" fields were cross-assigned between groups — wrong, but not obviously wrong (no error is thrown; it just returns plausible-looking incorrect numbers).
**Why it happens:** The `groupField` index semantics for a second, outer `.group()` call do not straightforwardly refer to the original `selectors` list the way a first `.group()` call's index does — the exact re-indexing rule was not documented anywhere found in this session's research, only empirically observed to produce wrong output.
**How to avoid:** Never chain two `.group()` calls for a two-key grouping. Use Pattern 3's composite-string-key + single-`.group()` approach instead.
**Warning signs:** Aggregated values that look plausible in isolation but don't match hand-computed expectations when checked against a small, fully-traceable fixture — exactly the kind of bug that survives a cursory smoke test.

### Pitfall 5: A ward's small-geometry status must be checked once, not derived from a live null on every chunk
**What goes wrong:** If a future implementer re-checks "is this ward's zonal value null today?" inside the per-day/per-chunk loop instead of using a precomputed static ward-ID set, the fallback logic becomes both slower (redundant checks) and potentially inconsistent (if a transient computation quirk ever produced a spurious null for a normally-fine ward on one specific day, that day's row would use a different reducer than the rest of that ward's time series, silently corrupting time-series continuity for the run-detection state machine, which assumes homogeneous per-ward data provenance).
**How to avoid:** Determine the small-ward-ID set exactly once (one primary `reduceRegions` pass over all wards for one arbitrary day, collect nulls), persist that list, and reuse it for every day of every chunk (Pattern 2).
**Warning signs:** A ward whose `used_fallback_reducer` flag (D-09) is `True` on some days and `False` on others within the same production run — this should never happen and indicates the detection logic was re-run per-day instead of once.

## Code Examples

All snippets below were executed live against the real `heatwave-508110` Earth Engine project during this research session unless otherwise marked.

### ISO week-year, verified against Python ground truth
```python
# Source: verified live, this session -- 100% match against
# datetime.date(*ymd).isocalendar() across 8 edge-case dates:
# 2024-12-30, 2024-12-31, 2025-01-01, 2025-01-05, 2023-01-01,
# 2023-01-02, 2020-12-31, 2021-01-01 (covers both week-53 years
# in this set and both Dec->Jan wraparound directions).
def iso_year_and_week(date):
    iso_weekday = date.getRelative("day", "week").add(1)
    thursday = date.advance(ee.Number(4).subtract(iso_weekday), "day")
    return thursday.get("year"), date.get("week")
```

### D-08 fallback reducer, verified live
See Pattern 2 above — `build_fallback_ward_centroids` + `reduce_one_day_with_fallback`, exact live-verified output included inline as comments.

### Weekly composite-key aggregation, verified live
See Pattern 3 above — full working `reduceColumns`/`.group()`/`.split()` pipeline, live output matched hand-computed expectations exactly for a 2-ward/2-week/6-row fixture.

## State of the Art

| Old Approach (Phase 3 scope) | Current Approach (Phase 4 scope) | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Small synthetic samples (1-3 wards), correctness-only, no export | Full 4,841-ward × ~35-year production run, exported asynchronously | Phase 3 → Phase 4 boundary, by design (D-03 in 03-CONTEXT.md) | All of Phase 3's functions are reused unchanged except `zonal.py`'s new D-08 fallback branch; the genuinely new work is entirely in export/aggregation, not detection algorithms |
| `getInfo()` for test assertions | `ee.batch.Export.table.toAsset()` + paginated read-back for the real production artifact | This phase | `getInfo()` remains fine for `tests/test_export.py`'s small bounded-sample checks (EXPORT-04); it must never be used for the full-scale run (EXPORT-01) |

**No externally-sourced "old vs. new EE API" deprecation found this session** — the core reducers/filters/join/iterate primitives used are the same ones Phase 3 already verified as current (`earthengine-api` 1.6.8, stable API surface).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The ~2.0-2.3ms/row benchmark measured up to 36,500 rows extrapolates roughly linearly all the way to the full ~62M-row scale (~34-40 hours for the event-detection stage alone) | Summary, Pitfall 3 | MEDIUM-HIGH — this is a ~1,700x extrapolation from the largest sample actually measured. If EE's actual behavior is super-linear at huge scale (e.g. due to memory pressure or computation-graph-depth effects not observable at small scale), the real per-chunk runtime could be substantially worse, and the recommended ~200-500-ward chunk size might need to be much smaller. **Mitigation already built into the recommendation:** run one larger confirming benchmark (~500 wards × full 35-year range) before committing to a specific chunk size for the real production run — this is called out explicitly as a required pre-production step, not left implicit. |
| A2 | `ee.batch.Export.table.toDrive()` fails for service-account-only credentials with a storage-quota error | Summary, Standard Stack, Pitfall 1 | LOW-MEDIUM — this claim is cross-referenced from multiple independent community/forum reports (Google Developer forums, Google Drive Community, a similar n8n GitHub issue) describing the identical failure mode for service-account Drive uploads generally, but was NOT reproduced live against `heatwave-508110` this session (deliberately avoided, since a live reproduction would require actually attempting a Drive export and potentially leaving stray Drive/task artifacts). If this project's specific service account somehow has a working Drive quota (e.g. because of an org-level Workspace policy not visible in this research), `toDrive()` could actually work — but `toAsset()` remains strictly safer and equally valid regardless, so this assumption does not block the recommendation even if wrong. |
| A3 | This project is on Earth Engine's "noncommercial" quota tier (relevant to the "~2 average concurrent batch tasks" and task-queue figures cited) | Standard Stack, Pattern 5 | LOW — not confirmed from any config file or prior-phase document in this repo. If the project is actually on a paid/commercial tier, concurrency could be higher, which only makes the chunking recommendation MORE comfortable (shorter wall-clock), never worse. |
| A4 | The two-stage event-start-week composition (Pattern 4) works correctly when actually run at scale | Pattern 4 | MEDIUM — the individual building blocks (Pattern 1's ISO-week math, Pattern 3's composite-key grouping) were each independently verified live, but this exact two-stage pipeline (min-date-per-event, then group-count-by-week) was not executed end-to-end in this session. Recommend a small Wave-0 test (a handful of wards, a handful of synthetic events spanning a week boundary) before relying on it for the full production run. |

**If this table is empty:** N/A — see entries above.

## Open Questions (RESOLVED)

All three questions below were closed by Phase 4's plan set -- each is now owned by a specific task that
produces a real measurement rather than leaving the question open into implementation. The resolution
note appended to each records which task closes it and what evidence that task produces.

1. **What is the actual per-chunk task runtime at a realistic (not synthetic-tiny) intermediate scale?**
   - What we know: Linear-looking cost up to 36,500 synthetic rows (~2.0-2.3ms/row); Phase 3's live-verified `.iterate()` behavior up to 12,800 elements for a single ward shows no blow-up.
   - What's unclear: Whether this holds at the ~1-10M-row range a single real ward-batch chunk (200-500 wards × 35 years) would actually contain.
   - Recommendation: Before submitting the full ~10-25-chunk production run, submit ONE real chunk (e.g., the smallest or an arbitrary mid-size ward-batch) and measure its actual `task.status()` timestamps end-to-end as a go/no-go calibration for the rest.
   - **RESOLVED by plan 04-04 Task 3** (the blocking operator checkpoint), which submits two real ward-batch chunks end to end and records each chunk's measured submission-to-`COMPLETED` wall-clock read from the recorded task status rather than estimated, then presents it to the operator as the D-01/D-02 go/no-go input. **Caveat carried into that task:** its calibration chunks are deliberately tiny (2 ward-batches of 2 wards over a 3-week window), so the measurement is a directional signal dominated by fixed per-task queue/startup overhead -- it is NOT the ~500-ward x full-35-year confirming benchmark recommended in Pitfall 3 / Assumption A1, and Task 3's operator-facing output says so explicitly.

2. **Does the real ward asset actually contain any wards small enough to trigger D-08's fallback path?**
   - What we know: Phase 3's research flagged this as an open question and explicitly deferred it to Phase 4; this session did not inspect the real 4,841-ward geometries (that would require a live query against the actual asset, which was deliberately deferred to implementation/Wave-0 rather than research, to avoid a long-running live call in the research session).
   - What's unclear: The count and identity of any real small wards.
   - Recommendation: The one-time "run primary `reduceRegions` for one day across all 4,841 real wards, collect nulls" step (Pattern 2) doubles as the answer to this question — build it as an early, cheap diagnostic step in `scripts/run_batch_export.py`, and log the count/list found (satisfies D-09).
   - **RESOLVED by plan 04-02's `find_small_wards` plus plan 04-04 Task 2's once-per-run invocation** (which writes `outputs/small_wards_report.csv` and a stderr count, satisfying D-09), with the resulting count and ward identities reviewed by the operator in **plan 04-04 Task 3, step 2 of `<how-to-verify>`** -- the first real answer to whether any of the 4,841 wards actually falls below ERA5-Land's pixel-weight threshold.

3. **Exact behavior of `ee.data.listFeatures` vs. `FeatureCollection.toList(pageSize, offset).getInfo()` for paginated download — which is more robust/faster at ~1M+ rows per chunk?**
   - What we know: Both are documented to support pagination; `toList(...).getInfo()` is the simpler, more commonly demonstrated pattern in this codebase's existing test style (`_props()` helper in `tests/test_heatwave_detection.py` already uses a single `getInfo()` for small collections).
   - What's unclear: Neither was benchmarked at the ~1M-row-per-chunk scale in this session.
   - Recommendation: Prototype the paginated download loop against a small real (not synthetic) exported asset early in implementation (Wave 0), measuring wall-clock per page, before assuming a specific page size works well at full chunk scale.
   - **RESOLVED by plan 04-01 Task 3**, which executes the real `Export.table.toAsset()` submit -> poll -> paginated read-back -> delete round-trip live against `heatwave-508110` using a `page_size` smaller than the row count, confirming every row comes back exactly once and recording the measured wall-clock. The same task also closes the `[ASSUMED, MEDIUM confidence]` asset-write-permission row in the Environment Availability table below. The adopted pattern is `toList(pageSize, offset).getInfo()`; `ee.data.listFeatures` was not taken up.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `earthengine-api` | All EE computation, batch export, task polling | ✓ [VERIFIED: live, this session] | 1.6.8 | — |
| Live GCP credentials (`keys/service_account.json`) | Real batch export submission, live tests | ✓ [VERIFIED: file exists, live EE calls succeeded against `heatwave-508110` throughout this research session, including creating/reading live computed FeatureCollections] | — | Tests skip cleanly via the established `_REQUIRES_CREDENTIALS` pattern if absent |
| EE project asset write permission (`projects/heatwave-508110/assets/`) | `Export.table.toAsset()` (the recommended export path) | Not directly re-verified this session (no test asset was created/left behind, to avoid leaving artifacts in the live project without explicit sign-off) — but the service account already successfully wrote the ward boundary asset in this same namespace in a prior session, so write access is established by precedent. [ASSUMED, MEDIUM confidence: same namespace, same account, prior success — but not re-verified live this session for a NEW asset write] | — | If write access to a new asset path is somehow restricted, `toCloudStorage()` (requires a new bucket, blocked by D-07) or `toDrive()` (likely blocked by service-account quota per Pitfall 1) would need re-evaluation — flag as a checkpoint before full production. |
| Disk space in `outputs/` for the final CSV (~8.8M rows × 6 columns, roughly a few hundred MB) | D-06 | Not measured this session | — | If disk space is constrained, per-chunk CSVs could be written to a different volume before final concatenation |
| `pytest` | Test execution | ✓ [VERIFIED: `requirements.txt`] | 8.4.1 | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** Asset-write-permission risk (see table) has a documented but D-07-constrained fallback; flagged as a pre-production checkpoint rather than a blocker.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 [VERIFIED: `requirements.txt`] |
| Config file | none — no `pytest.ini`/`setup.cfg` in repo; defaults used (established pattern) |
| Quick run command | `pytest tests/test_export.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXPORT-01 | `scripts/run_batch_export.py` runs the full pipeline for a configurable (small, bounded) date range/ward sample without hitting sync timeouts | live-EE unit/smoke, small sample only (per CONTEXT.md's Integration Points — never wait for the full historical export inline in the fast test loop) | `pytest tests/test_export.py -k batch_export -x` | ❌ Wave 0 |
| EXPORT-02 | Output schema matches exactly: `time_period`, `location`, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count` | live-EE unit | `pytest tests/test_export.py -k schema -x` | ❌ Wave 0 |
| EXPORT-03 | No missing wards, no null aggregates, on a small bounded sample (proxy for the real full-scale completeness guarantee) | live-EE unit | `pytest tests/test_export.py -k completeness -x` | ❌ Wave 0 |
| EXPORT-04 | `tests/test_export.py` exists and validates schema/aggregation correctness | (this file itself) | `pytest tests/test_export.py -x` | ❌ Wave 0 |

Additional test-worthy items surfaced by this research (not separate requirement IDs, but load-bearing for EXPORT-02/03 correctness):
- ISO week-year boundary correctness (Pattern 1) — assert against a fixture spanning a real Dec 30 → Jan 5 range, checking `time_period` values against hand/`isocalendar()`-computed expectations.
- D-08 fallback reducer produces a non-null value with `used_fallback_reducer=True` for a deliberately tiny synthetic ward, matching Phase 3's existing `test_zonal_reduction_tiny_ward_row_is_null_not_dropped` fixture pattern but asserting the NEW fallback-filled value instead of asserting null.
- `heatwave_event_count` counts event STARTS, not event-touching weeks, for an event that spans a week boundary (a 4-day event starting on a week's last day and continuing into the next week must count once, in the starting week).

### Sampling Rate
- **Per task commit:** `pytest tests/test_export.py -x`
- **Per wave merge:** `pytest tests/ -x` (full suite, includes Phase 1-3 regression per established precedent)
- **Phase gate:** Full suite green before `/gsd:verify-work`; the actual full-scale production run (EXPORT-01's real invocation) is a separate, manually-triggered, long-running operation outside the fast test loop, per CONTEXT.md's Integration Points.

### Wave 0 Gaps
- [ ] `tests/test_export.py` — does not exist yet; this phase's own deliverable (EXPORT-04). Follow the skip-gated, live-EE pattern from `tests/test_heatwave_detection.py`.
- [ ] `heatwave/export.py` — does not exist yet; houses the weekly-aggregation logic (Patterns 1, 3, 4) and the D-08 fallback wiring (Pattern 2) if not placed directly in `zonal.py`.
- [ ] `scripts/run_batch_export.py` — does not exist yet; houses the chunk planner, task submission/polling (Pattern 5), and final CSV concatenation.
- [ ] A small live smoke test proving Pattern 4's two-stage event-start-week composition end-to-end (flagged as Assumption A4/Open Question territory — not yet executed).
- [ ] A real (not purely synthetic) `Export.table.toAsset()` round-trip test — submit a tiny real task, poll it to `COMPLETED`, read it back via pagination — to close Open Question 3 and de-risk the Environment Availability asset-write-permission assumption, ideally run once early in implementation rather than assumed throughout planning.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Reuses Phase 1's `heatwave/auth.py` service-account credential resolution, unchanged |
| V3 Session Management | No | No session concept in this batch pipeline |
| V4 Access Control | No | Single service-account, internal batch pipeline; no multi-user surface |
| V5 Input Validation | Partial | The export date range must be read from `heatwave.config.settings` (or an explicit, validated CLI argument to `run_batch_export.py`), never an unvalidated free-form string passed straight into `ee.Filter.date()` |
| V6 Cryptography | No | No cryptographic operations introduced; credential handling unchanged from Phase 1 |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| A partially-failed chunked export silently produces an incomplete `outputs/covariate_table.csv` (some ward-batches missing) that looks complete | Data Integrity (indirect) | The final concatenation step must verify the union of all chunk ward-IDs equals the full 4,841-ward set (EXPORT-03's "no missing wards") before writing the final CSV, not just concatenate whatever chunk CSVs happen to exist on disk |
| A stray/incomplete local `outputs/.batch_export_tasks.json` gets committed to git, or a real task ID is hardcoded into a script instead of read from the state file | Tampering (config drift), minor Information Disclosure (task IDs are not secret but are project-specific clutter) | `.gitignore` the task-state file (it is machine/run-specific, like `keys/service_account.json` already is for credentials) |
| Silent small-ward-fallback drift (Pitfall 5) — a ward's data provenance changes mid-series without detection | Data Integrity (indirect) | D-09's loggable/detectable fallback flag, computed once and applied consistently (Pattern 2) |

This phase does not process externally-submitted user input or handle end-user authentication — as in Phase 3, the primary "security" concern in this domain is data-integrity correctness (silent incompleteness, config drift), not a traditional attack surface.

## Sources

### Primary (HIGH confidence — verified live this session against `heatwave-508110`)
- Live EE execution of ~10 discrete test snippets this session, covering: `ee.Date.get('week')`/`get('year')`/`getRelative('day','week')` ISO-week semantics (cross-checked against Python's `datetime.isocalendar()` across 8 dates), `ee.Image.reduceRegions()` with `Reducer.mean()`/`Reducer.first()` on both polygon and centroid-point geometries (D-08 fallback), `ee.Image.sampleRegions()`/`ee.Image.sample()` behavior on sub-pixel-weight geometries, chained vs. composite-key `Reducer.group()` behavior (confirmed the chained form produces wrong output; confirmed the composite-key form produces correct output), and `tag_consecutive_runs`/`detect_heatwave_events` scale benchmarking (2,000 to 36,500 rows; single-ward 3,650/10,950/12,800-element `.iterate()` runs)
- `heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, `heatwave/data/ingest.py`, `heatwave/science/heat_index.py`, `heatwave/config.py`, `heatwave/auth.py`, `heatwave/data/boundary.py`, `config.yaml`, `requirements.txt`, `tests/test_heatwave_detection.py`, `.planning/phases/03-climatology-heatwave-detection/03-RESEARCH.md` — all read directly from the repo this session
- Google Earth Engine official documentation (fetched this session):
  - https://developers.google.com/earth-engine/guides/exporting_tables (export destinations, parameters, table asset limits: 100M features / 1,000 properties / 100,000 vertices per row)
  - https://developers.google.com/earth-engine/guides/usage (quotas: 250GB/10,000-asset storage, 3,000-task queue, 10MB request / 100MiB result limits, ~2 average concurrent batch tasks for noncommercial projects)
  - https://developers.google.com/earth-engine/guides/processing_environments (10-day max batch task lifetime, 5 automatic retries, interactive 5-minute/tens-of-MB limit vs. batch's asynchronous high-latency design)

### Secondary (MEDIUM confidence)
- Google Developer forums, Google Drive Community, and a corroborating n8n GitHub issue — multiple independent reports of `StorageQuotaExceeded`/"Service Accounts do not have storage quota" errors for bare service-account Drive uploads generally (not Earth-Engine-specific, but directly applicable) — https://discuss.google.dev/t/storagequotaexceeded-the-users-drive-storage-quota-has-been-exceeded-for-service-account/104375, https://support.google.com/drive/thread/164666886, https://github.com/n8n-io/n8n/issues/26050
- https://developers.google.com/earth-engine/apidocs/export-table-toasset, https://developers.google.com/earth-engine/apidocs/export-table-todrive, https://developers.google.com/earth-engine/apidocs/export-table-tocloudstorage — parameter signatures (WebSearch summary, cross-checked against the `exporting_tables` guide fetch above)
- https://developers.google.com/earth-engine/apidocs/ee-data-listfeatures — pagination API existence and parameter shape (`pageSize`, `pageToken`), not exercised live this session

### Tertiary (LOW confidence — not independently verified)
- "Runs with Arrays" (Noel Gorelick) — https://medium.com/google-earth/runs-with-arrays-400de937510a — returned HTTP 403 to automated fetch again this session (same as Phase 3's research); description sourced only from search-engine summary. Not needed for this phase's recommendation (the live benchmark supports keeping `.iterate()`), retained only as a documented fallback if a future larger-scale benchmark shows `.iterate()` degrading.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; existing `earthengine-api`/`pytest` versions confirmed directly this session
- Architecture (export destination, ISO-week math, composite-key aggregation): HIGH — every one of these was independently reproduced live against the real `heatwave-508110` project this session, including catching two real, silently-wrong naive approaches (chained `.group()`, naive year+week pairing) before they could reach implementation
- Full-scale runtime/chunking: MEDIUM — grounded in a real live benchmark, but that benchmark's largest sample (36,500 rows) is ~1,700x smaller than the real full-scale target (~62M rows); flagged explicitly as Assumption A1 with a concrete required pre-production mitigation step (one real-scale calibration chunk)
- D-08 fallback mechanism: HIGH — the exact working pattern (centroid point + `Reducer.first()` + `reduceRegions`) was live-verified against a deliberately-sized sub-threshold synthetic ward this session
- Pitfalls: HIGH for Pitfalls 2, 4, 5 (all directly reproduced/reasoned from live results this session); MEDIUM for Pitfalls 1, 3 (reasoned from strong secondary evidence / partial live benchmarking, not a full live reproduction of the failure mode itself, to avoid leaving artifacts in the live production project)

**Research date:** 2026-09-15
**Valid until:** 2026-10-15 (30 days — Earth Engine's batch export API and quota figures are stable; re-verify quota numbers if the project is ever moved onto a different EE quota tier, and re-verify the ~2ms/row runtime assumption specifically if `earthengine-api` is upgraded past 1.6.8 before this phase's implementation begins)
