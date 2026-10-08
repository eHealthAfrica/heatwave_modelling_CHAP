# Phase 4: Batch Export & Covariate Table - Context

**Gathered:** 2026-09-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Run the full pipeline (ingest → heat index → climatology → detection) across all 4,841 wards and produce the CHAP-facing weekly covariate table — the actual production deliverable (EXPORT-01 through EXPORT-04). Unlike Phases 1-3, this phase's production run is NOT scoped to a small sample: it targets the complete historical record.

</domain>

<decisions>
## Implementation Decisions

### Export scope: full historical backfill, not a bounded window
- **D-01:** The production run this phase delivers targets the full 1991-present record for all 4,841 wards, not a bounded recent window. This is a deliberate, explicit choice to accept the full cost/runtime now rather than deferring the historical backfill to a later ops task.
- **D-02:** This is a genuinely large computation (~4,841 wards × ~35 years of daily data feeding weekly aggregation) — expect the actual production export to take substantial real time (likely hours) and consume real Earth Engine compute quota. Flagging this explicitly so it isn't a surprise at execution time.

### Execution model: asynchronous Earth Engine batch export
- **D-03:** `scripts/run_batch_export.py` must use Earth Engine's asynchronous batch export mechanism (`ee.batch.Export.table...`), not synchronous `getInfo()` calls — required at this scale; Earth Engine's synchronous computation timeout would very likely be exceeded otherwise.
- **D-04:** The script's job is to build the full computation graph (chaining `heatwave/zonal.py` → `heatwave/science/climatology.py` → `heatwave/science/heatwave.py` → weekly aggregation) and submit it as an Earth Engine batch task, then poll for completion. It does not need to hold the process open synchronously waiting — polling/resume behavior is implementation detail for research/planning to work out.
- **D-05:** Whether the full 1991-present graph can be submitted as a single Earth Engine batch task or must be chunked (e.g., by year or ward-batch) to stay within Earth Engine's per-task limits is a genuine open technical question — research territory, not a locked decision. If chunking is required, the script must still produce one final, complete covariate table (concatenating/merging chunks), not leave the user to manually stitch outputs together.

### Output destination: CSV to outputs/
- **D-06:** The finished covariate table is written as a CSV file to `outputs/` (matching this project's existing convention for generated artifacts — see `outputs/03_Implementation_Phases_Status.pdf` etc. from earlier sessions), matching EXPORT-02's schema exactly: `time_period`, `location`, `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`.
- **D-07:** No new cloud infrastructure (GCS bucket, BigQuery dataset) is provisioned in this phase. CHAP's actual ingestion mechanism (API push, GCS pickup, BigQuery, etc.) is explicitly deferred — this phase's job is to produce a correct, complete CSV that could be handed off by any mechanism later.

### Small-ward null-value policy (resolves Phase 3's deferred item)
- **D-08:** When `heatwave/zonal.py`'s primary area-weighted zonal reduction (`ee.Reducer.mean()`) returns null for a ward too small relative to ERA5-Land's ~11.1km pixel size, fall back to a reducer that doesn't require partial-pixel-weight coverage (e.g. a centroid/nearest-pixel sample) so every ward gets a real value. No ward is silently excluded from the final covariate table, and no null is ever coalesced to a fabricated 0 — the fallback produces a genuine (if lower-fidelity) sampled value, which is different from both "drop the row" and "pretend it's zero."
- **D-09:** The fallback's use should be detectable/loggable (e.g., a boolean column or a log line noting which wards used the fallback reducer) so data quality is transparent to whoever consumes the CSV, even though EXPORT-02's schema itself is not expanded with a new required column.

### Claude's Discretion
- Whether the full 1991-present export needs chunking (D-05) — research territory.
- Exact polling/resume mechanics for the async batch task (D-04).
- Whether/how to log which wards used the D-08 fallback reducer — exact mechanism (separate log file, stderr, a non-schema CSV column) is implementation discretion, as long as it's transparent per D-09.
- Whether `tag_consecutive_runs`'s `ee.List.iterate()` state machine (Phase 3, verified only up to ~3,650 elements) needs to switch to the documented array forward-difference fallback at this phase's full ~12,800-day-per-ward scale — benchmark first per Phase 3's own research recommendation; switch only if the benchmark shows it's actually too slow, don't switch preemptively.
- Weekly aggregation logic itself (grouping daily heatwave-day/event-flag rows into ISO weeks, computing `mean_heat_index`/`max_heat_index` per week) has no prior-phase precedent to reuse — this is new code for this phase, follow the established plain-function `heatwave/` module style.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase source docs
- `.planning/REQUIREMENTS.md` — EXPORT-01 through EXPORT-04 exact requirement text
- `.planning/PROJECT.md` — Context section: Phase 3's two carried-forward items (small-ward null policy, now resolved by D-08/D-09; event-detection scale, addressed via the benchmark-first discretion above)
- `config.yaml` — note its `start_date`/`end_date` (1980-01-01 to 2025-09-15) are the Streamlit viewer's defaults, NOT necessarily this phase's export range; the climatology baseline (`baseline_start_year: 1991`, `baseline_end_year: 2020`) is a separate, already-locked concept from the export's own date range (D-01)

### Existing code this phase builds on
- `heatwave/zonal.py`, `heatwave/science/climatology.py`, `heatwave/science/heatwave.py` — all three Phase 3 modules, to be chained together at full scale, unmodified in their core logic except for D-08's fallback-reducer addition to `zonal.py`
- `heatwave/data/ingest.py`, `heatwave/science/heat_index.py` — the earlier pipeline stages this phase's graph also depends on
- `heatwave/config.py` — `settings.climatology.*`, `settings.era5_land_collection`, `settings.bands.*` — reuse, don't hardcode

No external specs/ADRs beyond the project's own docs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The full Phase 1-3 pipeline (`load_era5_land` → `compute_relative_humidity`/`compute_heat_index` → `reduce_to_ward_daily` → `compute_climatology_thresholds` → `flag_heatwave_days` → `detect_heatwave_events`) already exists and is tested — this phase composes it, not rebuilds it.

### Established Patterns
- Plain-function, no-class module style throughout `heatwave/` — new code (e.g. `heatwave/export.py`, weekly aggregation) should match.
- Config-driven parameters via `heatwave.config.settings` — no hardcoded dates/thresholds/percentiles.
- Skip-gated live-EE test pattern from `tests/test_integration.py`/`tests/test_heat_index.py`/`tests/test_heatwave_detection.py` — `tests/test_export.py` (EXPORT-04) should follow it, testing schema/aggregation correctness on a small bounded sample, NOT by waiting for the full historical export to complete inline (that belongs to the actual production invocation, run separately from the fast test loop).

### Integration Points
- `scripts/run_batch_export.py` is a new, standalone script (not a test) — it is the actual production entry point that gets run once (or occasionally re-run) to produce/refresh the real CSV output, distinct from the always-fast `pytest` suite.
- Phase 5's Streamlit rewrite will read this phase's output CSV directly — the exact file path/name this phase settles on should be predictable and documented (e.g., `outputs/covariate_table.csv`).

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this phase is backend/batch-processing only. The output is a CSV file, not a UI.

</specifics>

<deferred>
## Deferred Ideas

- CHAP's actual ingestion mechanism (API, GCS, BigQuery, etc.) — explicitly deferred per D-07, not this phase's job.
- Any new cloud infrastructure provisioning — deferred alongside the above.

</deferred>

---

*Phase: 04-batch-export-covariate-table*
*Context gathered: 2026-09-15*
