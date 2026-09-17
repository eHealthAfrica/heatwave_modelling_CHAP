---
phase: 04-batch-export-covariate-table
plan: 04
subsystem: data
tags: [earth-engine, batch-export, chunking, csv, cli, argparse, coverage-gate]

# Dependency graph
requires:
  - phase: 04-batch-export-covariate-table
    provides: "04-01's heatwave/batch.py (submit_or_resume/poll_until_complete/read_asset_rows/write_rows_csv async harness); 04-02's find_small_wards/reduce_to_ward_daily fallback_ward_ids; 04-03's heatwave/export.py build_covariate_table and COVARIATE_COLUMNS"
provides:
  - "scripts/run_batch_export.py: the EXPORT-01 production entry point -- V5-validated CLI, deterministic loss-free ward-batch chunk planner, once-per-run D-09 small-ward report, resumable chunked toAsset submit/poll/collect, and atomic coverage-gated final CSV concatenation"
  - "Live-verified chunk plan for the real ward asset: 4,841 wards / 20 chunks at batch size 250 / 73 small (D-08 fallback) wards"
  - "Live-verified 2-chunk/4-ward end-to-end smoke export producing a real outputs/covariate_table_smoke.csv with the exact EXPORT-02 schema"
affects: [05-presentation-layer-rewrite]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Thin orchestrator script pattern: scripts/run_batch_export.py composes heatwave/batch.py + heatwave/export.py + Phase 1-3 modules with zero reimplemented mechanics"
    - "V5 input validation wired through argparse's type= so a free-form CLI string can never reach ee.Filter.date() unparsed"
    - "Deterministic zero-padded chunk ids (c000, c001, ...) as the resumable-submission key, so a resumed run maps to the same chunks as the original"
    - "Coverage gate BEFORE atomic os.replace promotion: the final CSV either does not exist or is provably complete, never half-written"
    - "Once-per-run small-ward detection sliced per chunk, never re-derived inside the per-chunk graph builder (Pitfall 5 provenance-drift guard)"
    - "Placeholder point geometry attached at the export boundary (build_chunk_collection), not inside heatwave/export.py, because Export.table.toAsset rejects null-geometry features but none of COVARIATE_COLUMNS is spatial"

key-files:
  created:
    - scripts/run_batch_export.py
  modified:
    - tests/test_export.py

key-decisions:
  - "D-01/D-02/D-05/D-06/D-07/D-08/D-09 upheld exactly per interface: full-history default range derived from config, chunk/quota warning printed before any submission, script-owned re-concatenation, outputs/covariate_table.csv destination, no new cloud infrastructure, once-per-run small-ward report"
  - "Operator decision (Task 3 checkpoint): chunk plan, small-ward report and smoke CSV output approved as correct; the full 1991-present historical backfill is explicitly DEFERRED -- it is a separate, later, deliberately-triggered operation independent of this plan's completion, per 04-CONTEXT.md D-01/D-02"

requirements-completed: [EXPORT-01, EXPORT-02, EXPORT-03, EXPORT-04]

# Metrics
duration: 48min
completed: 2026-09-17
---

# Phase 4 Plan 4: Production Batch Export Script Summary

**`scripts/run_batch_export.py` composes the full Phase 1-3 pipeline into a validated-CLI, ward-batch-chunked, resumable, coverage-gated production export; a real run against the live 4,841-ward asset planned 20 chunks with 73 small wards, and a real 2-chunk/4-ward smoke export produced a correct-schema CSV -- the operator approved both and explicitly deferred launching the full 1991-present backfill to a later, separate, deliberately-triggered operation.**

## Performance

- **Duration:** 48 min (Tasks 1-2 execution + Task 3 checkpoint automation, across the original session and this wrap-up continuation)
- **Started:** 2026-09-16T13:19:00+01:00
- **Completed:** 2026-09-17 (this continuation closes the plan after operator review)
- **Tasks:** 3 (2 auto + 1 checkpoint:human-verify)
- **Files modified:** 2 (`scripts/run_batch_export.py` created, `tests/test_export.py` extended)

## Accomplishments

- Built `scripts/run_batch_export.py` in full per the plan's `<interfaces>` contract: `parse_iso_date`, `validate_date_range`, `plan_ward_chunks`, `build_chunk_collection`, `assert_ward_coverage`, `concatenate_chunk_csvs`, `main`, plus `EXPORT_DEFAULT_WARD_BATCH_SIZE`, `DEFAULT_OUTPUT_CSV`, `DEFAULT_SMALL_WARD_REPORT`, `ERA5_LAND_EARLIEST_DATE`, `WARD_ID_PROPERTY`.
- Extended `tests/test_export.py` with the 8 planned EXPORT-01/EXPORT-03 tests (V5 date validation, loss-free deterministic ward chunking, the two-directional coverage gate, coverage-gated CSV concatenation, and the opt-in live end-to-end pipeline smoke). 22 non-gated tests pass in under 30 seconds; the full repository suite is green.
- Live-verified the real chunk plan against `heatwave-508110`'s actual boundary asset: **4,841 wards, 20 chunks at the default batch size of 250, 73 wards flagged for the D-08 centroid fallback** (04-RESEARCH.md Open Question 2 answered for the first time with a real number rather than a guess), quota/runtime warning printed, zero Earth Engine tasks submitted under `--stage plan`.
- Live-verified a real 2-chunk/4-ward end-to-end smoke export (`--start-date 2020-06-01 --end-date 2020-06-22 --max-wards 4 --ward-batch-size 2 --output outputs/covariate_table_smoke.csv`): both chunks submitted, polled, collected, and coverage-gate-concatenated into a real CSV with the exact header `time_period,location,heatwave_days,mean_heat_index,max_heat_index,heatwave_event_count`, `time_period` values matching `2020-W2{3,4,5}`, every `location` one of the four sampled ward ids, and no empty `mean_heat_index` cell.
- Found and fixed live (Rule 1 bug, during the first smoke attempt): `build_covariate_table`'s output rows carry no geometry, and `Export.table.toAsset` rejects null-geometry features -- the same failure mode plan 04-01 first hit. Fixed by attaching a placeholder point geometry inside `build_chunk_collection` at the export boundary (not inside `heatwave/export.py`, since none of `COVARIATE_COLUMNS` is spatial and the CSV read-back never reads geometry). Re-verified live: the same smoke export then completed cleanly.
- All EE smoke assets (`covariate_chunk_c000`/`c001` under the smoke run's asset prefix) were deleted after collection; `outputs/.batch_export_tasks_smoke.json` was removed. No smoke artefact remains in the Earth Engine project.
- **Timing measurement (reconstructed from artifact timestamps, not a separately instrumented log):** the smoke run's local artefacts -- `outputs/small_wards_report.csv` (written at the start of `main`, before chunking) and the final `outputs/covariate_table_smoke.csv` (written after both chunks' `COMPLETED` collection and the coverage-gated concatenation) -- carry filesystem mtimes approximately **196 seconds (~3 min 16s) apart**, covering submission, polling, collection and concatenation of both chunks together (2 ward-batches of 2 wards each, 3-week window). This is a coarse reconstruction from file mtimes, not a precise per-chunk submission-to-`COMPLETED` instrumented measurement -- the live checkpoint run's stdout was not persisted to a file this continuation could re-read. Treat the ~196s figure as directionally consistent with, but less precise than, an instrumented per-chunk timer would have produced.

  **SCALE CAVEAT (mandatory, quoted verbatim per Task 3's acceptance criteria):** "This timing comes from 2 ward-batches of 2 wards over a 3-week window. A real production chunk is ~250 wards x ~35 years, orders of magnitude larger. At this tiny size the wall-clock is dominated by fixed Earth Engine per-task queue and startup overhead, NOT by the compute-scaling behaviour that will actually dominate a real chunk. Treat this as a DIRECTIONAL SIGNAL ONLY. It is NOT 04-RESEARCH.md's recommended confirming benchmark (~500 wards x the full 35-year range, Pitfall 3 / Assumption A1), which has deliberately not been run here because running it inline would collapse the fast-loop/production split this phase is built around. 04-RESEARCH.md's ~34-40 hour full-run figure remains a rough order-of-magnitude bound requiring your own judgement, not a prediction these numbers confirm or refute. Straight-line extrapolation from this measurement will OVERSTATE per-ward cost, because it multiplies fixed overhead across every chunk; the compute-scaling term it cannot observe may push the real figure back the other way."

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing EXPORT-01/EXPORT-03 script tests (RED)** - `86ec472` (test)
2. **Task 2: Implement scripts/run_batch_export.py (GREEN)** - `2c888bf` (feat)
   - Live-found geometry bug fix - `e75adf3` (fix)
3. **Task 3: Operator checkpoint (chunk-plan and smoke-export review)** - no code commit; checkpoint automation output reviewed and approved by the operator; full backfill launch explicitly deferred (this SUMMARY records the decision)

**Interim docs commit (previous session):** `9605faf` (docs: record Tasks 1-2 decisions and checkpoint pause position)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `scripts/run_batch_export.py` - New production entry point: validated CLI (`--start-date`/`--end-date`/`--ward-batch-size`/`--max-wards`/`--output`/`--state-file`/`--poll-interval`/`--stage`), ward-batch chunk planner, once-per-run D-09 small-ward report writer, per-chunk pipeline graph builder (`build_chunk_collection`), resumable chunked `submit_or_resume`/`poll_until_complete`, paginated `read_asset_rows` collection, EXPORT-03 two-directional coverage gate (`assert_ward_coverage`), and atomic `os.replace`-promoted final CSV concatenation (`concatenate_chunk_csvs`)
- `tests/test_export.py` - Extended with 8 new tests (7 credential-free/instant, 1 opt-in live pipeline smoke gated on `RUN_EE_PIPELINE_SMOKE=1`) covering V5 date validation, loss-free deterministic chunking, the coverage gate in both directions, coverage-gated concatenation, and the module-exports contract

## Decisions Made

- Implemented exactly per the plan's `<interfaces>` contract: all function signatures and CLI flags match verbatim; all of D-01/D-02/D-05/D-06/D-07/D-08/D-09 upheld as specified in the plan's `must_haves.truths`.
- **Operator decision on the Task 3 checkpoint (recorded verbatim, per this plan's acceptance criteria requiring the go/no-go be recorded):** The chunk plan, small-ward report, and smoke CSV output were reviewed and **approved as correct**. The full 1991-present historical backfill is **explicitly deferred** -- the operator chose to push the current branch to GitHub instead of launching the multi-hour production run now. This does not block Phase 4 completion: per 04-CONTEXT.md D-01/D-02 and this plan's own `<objective>` ("No task in this plan has acceptance criteria requiring the full backfill to complete... `outputs/covariate_table.csv` at full scale is explicitly NOT a completion criterion for this phase"), the full backfill was always meant to be a separate, later, deliberately-triggered operation independent of this phase's plan work.
- No further live Earth Engine calls were made during this wrap-up continuation -- all live verification (the real `--stage plan` run and the real 2-chunk/4-ward smoke export) had already executed and been cleaned up in the prior session before this continuation started.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `Export.table.toAsset` rejects null-geometry features from `build_covariate_table`'s output rows**
- **Found during:** Task 3's checkpoint automation, first live smoke export attempt
- **Issue:** `build_covariate_table`'s output rows carry no geometry (none of `COVARIATE_COLUMNS` is spatial), and `Export.table.toAsset` rejects every null-geometry feature outright -- both smoke chunks initially FAILED with "Unable to export features with null geometry." This is the same failure mode plan 04-01 first hit and documented (round-trip fixture given point geometry).
- **Fix:** `build_chunk_collection` now attaches an arbitrary placeholder point geometry to each feature at the export boundary, inside `scripts/run_batch_export.py` rather than inside `heatwave/export.py` -- `build_covariate_table`'s own contract stays purely tabular, and the CSV read-back (`read_asset_rows(asset_id, COVARIATE_COLUMNS)`) never reads geometry, so the exported schema is unchanged.
- **Files modified:** `scripts/run_batch_export.py`
- **Verification:** Re-ran the same 2-chunk/4-ward smoke export live; both chunks reached `COMPLETED` and the resulting `outputs/covariate_table_smoke.csv` has the exact EXPORT-02 header and no empty aggregate cells.
- **Committed in:** `e75adf3`

---

**Total deviations:** 1 auto-fixed (Rule 1 bug fix), necessary for the smoke export (and, by extension, the real production run) to complete at all.
**Impact on plan:** Essential correctness fix; no scope creep. Zero deviations in Tasks 1-2's core implementation from the plan's `<interfaces>` contract.

## Issues Encountered

- The Task 3 checkpoint's per-chunk wall-clock timing was not captured via a separately instrumented log during the live run; this SUMMARY reconstructs an approximate ~196-second total-run figure from the smoke run's local artefact filesystem timestamps (`outputs/small_wards_report.csv` write at run start vs. `outputs/covariate_table_smoke.csv` write at run completion) rather than a precise per-chunk submission-to-`COMPLETED` timer read from `heatwave.batch.poll_until_complete`'s own state. The mandatory SCALE CAVEAT applies regardless of this imprecision -- at 2 wards / 3 weeks the number is a directional signal only either way, never a precise full-run prediction.

## User Setup Required

None - no external service configuration required. Credentials (`keys/service_account.json`) were already provisioned from Phase 1 and used as-is.

## Next Phase Readiness

- Phase 4 is now complete: all 4 plans (04-01 batch harness, 04-02 D-08/D-09 fallback, 04-03 weekly aggregation, 04-04 this production script) are implemented, tested, and live-verified.
- `scripts/run_batch_export.py` is ready for the operator to launch the real 1991-present, 4,841-ward, 20-chunk historical backfill whenever they choose -- this is a deliberate, separate, monitored operation outside this phase's scope, per D-01/D-02 and this plan's own objective. It is NOT launched by this plan's completion.
- Phase 5 (Presentation Layer Rewrite) can proceed: it depends on `outputs/covariate_table.csv` existing at the schema this plan guarantees (`COVARIATE_COLUMNS`, coverage-gated, atomically written), which is proven correct on real small samples. Phase 5 does not require the full-scale backfill to have run first for its own build-out (the app just needs to read whatever CSV eventually lands at that path), but the CHAP handoff milestone (Phase 4's actual "production deliverable" framing in the roadmap) is only realized once the operator runs the full backfill separately.
- Recommended next operator action outside this phase: push the current branch to GitHub (as the operator indicated), and reconfirm PR #1's status per the existing STATE.md blocker before superseding it.

## Self-Check: PASSED

- FOUND: scripts/run_batch_export.py
- FOUND: tests/test_export.py
- FOUND commit: 86ec472 (Task 1, test)
- FOUND commit: 2c888bf (Task 2, feat)
- FOUND commit: e75adf3 (Task 2 live-found fix)
- FOUND commit: 9605faf (interim docs, prior session)
- FOUND: outputs/small_wards_report.csv (header-only after the smoke run overwrote the full-plan run's 73-row report; both runs' outputs verified live in the prior session)
- FOUND: outputs/covariate_table_smoke.csv (12 data rows, exact EXPORT-02 header, no empty aggregate cells)

---
*Phase: 04-batch-export-covariate-table*
*Completed: 2026-09-17*
