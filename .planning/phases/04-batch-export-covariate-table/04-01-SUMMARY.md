---
phase: 04-batch-export-covariate-table
plan: 01
subsystem: infra
tags: [earthengine, batch-export, ee.batch.Export.table.toAsset, pytest, csv]

# Dependency graph
requires:
  - phase: 03-climatology-heatwave-detection
    provides: heatwave/zonal.py, heatwave/science/climatology.py, heatwave/science/heatwave.py (the pipeline this phase's export composes)
provides:
  - heatwave/batch.py — Earth Engine asynchronous batch-export harness (toAsset submission, resumable task-state file, polling, paginated read-back, CSV writing)
  - tests/test_export.py — EXPORT-04 test file, extended by plans 04-03/04-04
  - A live-verified fact (not an assumption): the service account can create a new Earth Engine table asset in the configured namespace
  - A live-verified fact: paginated toList(page_size, offset) read-back returns every row exactly once with page_size smaller than the row count
affects: [04-02-batch-export-covariate-table, 04-03-batch-export-covariate-table, 04-04-batch-export-covariate-table]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Async EE batch export: Export.table.toAsset(...).start() then separate poll_until_complete(), never getInfo() on the full result"
    - "Resumable task-state file (outputs/.batch_export_tasks.json) keyed by chunk_id, gates resubmission on RESUMABLE_STATES"
    - "Asset-id guard: submit_table_export raises ValueError before any EE call if the final path segment lacks the covariate_ prefix"
    - "Paginated read-back generator over ee.FeatureCollection.toList(page_size, offset), never an unbounded getInfo()"
    - "Per-test credential gate (_REQUIRES_CREDENTIALS) plus a second independent opt-in env-var gate (_RUNS_LIVE_ROUNDTRIP) for quota-consuming live tests"

key-files:
  created:
    - heatwave/batch.py
    - tests/test_export.py
  modified:
    - .gitignore

key-decisions:
  - "D-03/D-04/D-05/D-07 upheld exactly as specified: toAsset-only destination, submit/poll separated, resumable via task-state file, no new cloud infrastructure referenced"
  - "Task-state test named test_batch_task_state_file_save_then_load_returns_same_state instead of the plan's literal test_batch_task_state_file_round_trip, because both that name and the live round-trip test's name would otherwise match -k round_trip, violating 04-VALIDATION.md's published exactly-one-match selector contract"
  - "Round-trip fixture uses ee.Feature(<point geometry>, {...}) instead of the plan-specified ee.Feature(None, {...}) after live testing proved Export.table.toAsset rejects null-geometry features"

patterns-established:
  - "Pattern: covariate_ prefix guard as a structural safeguard against ever overwriting the ward boundary asset (T-04-11)"
  - "Pattern: null-preserving CSV writer (csv.DictWriter with restval=\"\") so a missing value never becomes a fabricated 0"

requirements-completed: [EXPORT-01, EXPORT-04]

# Metrics
duration: 24min
completed: 2026-09-16
---

# Phase 4 Plan 1: Earth Engine Batch-Export Harness Summary

**`heatwave/batch.py` async toAsset submit/poll/paginated-read/CSV-write harness, live-verified against heatwave-508110 with a real 44-second submit-to-COMPLETED round trip.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-09-16T11:13:04+01:00
- **Completed:** 2026-09-16T11:35:51+01:00
- **Tasks:** 3
- **Files modified:** 3 (`heatwave/batch.py` created, `tests/test_export.py` created then amended, `.gitignore` modified)

## Accomplishments

- Built the full async Earth Engine batch-export harness (`heatwave/batch.py`): `chunk_asset_id`, `load_task_state`/`save_task_state`, `submit_table_export`, `submit_or_resume`, `task_state`, `poll_until_complete`, `read_asset_rows`, `write_rows_csv` — all exported, all plain functions, no classes.
- Stood up `tests/test_export.py` (EXPORT-04): one credential-free module-exports smoke test, six instant credential-free batch-harness unit tests, and one opt-in live round-trip test gated behind `RUN_EE_BATCH_ROUNDTRIP=1`.
- Closed both of 04-RESEARCH.md's open risks with real, measured evidence rather than assumptions (see "Live De-Risk Findings" below).
- Gitignored the machine-specific run artefacts (`outputs/.batch_export_tasks.json`, `outputs/*.csv`).

## Live De-Risk Findings (Task 3)

These were the two things this plan existed to prove before any later plan builds on top of them:

1. **Asset-write permission (closes 04-RESEARCH.md's `[ASSUMED, MEDIUM confidence]` Environment Availability row):** VERIFIED. The service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com` can create a **new** Earth Engine table asset in `settings.ward_asset_id`'s parent namespace (`projects/heatwave-508110/assets`) via `ee.batch.Export.table.toAsset(...).start()`. This is now a measured fact, not an assumption.
2. **Paginated read-back (closes Open Question 3):** VERIFIED. `read_asset_rows(asset_id, columns, page_size=2)` against a 3-row asset — a page size deliberately smaller than the row count — returned every row exactly once, matching all submitted property values after sorting by `location`. The pagination loop was genuinely exercised across more than one page (2 pages for 3 rows).
3. **Measured end-to-end wall-clock time for a 3-row table:** **44.01 seconds** from `.start()` to a poll result of `COMPLETED` (measured via `pytest --durations=3` on the full test body, which also includes the paginated read-back and asset deletion). This is the fixed per-task queue+startup overhead 04-04's chunk-count decision must trade off against per-chunk compute — consistent with 04-RESEARCH.md's recommendation to keep the chunk count in the ~10-25 range rather than hundreds of tiny chunks.
4. **No unexpected `task.status()` error observed** on the successful run. One informative error *was* observed on the first attempt (see Deviations below) and led directly to a fix, not a blocker.
5. **No artefact left behind:** confirmed via `ee.data.listAssets({'parent': 'projects/heatwave-508110/assets'})` filtered for `roundtrip_smoke` — result was `[]`, both immediately after the passing run and again at final verification.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tests/test_export.py (RED)** - `d2826f9` (test)
2. **Task 2: Implement heatwave/batch.py async export harness (GREEN)** - `e5bf808` (feat)
3. **Task 3: Execute the live round-trip and fix the fixture bug found live** - `7477145` (fix)

**Plan metadata:** commit pending (docs: complete plan)

## Files Created/Modified

- `tests/test_export.py` - EXPORT-04 test file: per-test credential gate, second opt-in `RUN_EE_BATCH_ROUNDTRIP` gate, `_props()` helper, 6 instant credential-free batch-harness tests, 1 real live round-trip test
- `heatwave/batch.py` - Earth Engine async batch-export harness: `CHUNK_ASSET_PREFIX`/`CHUNK_ASSET_BASENAME`/`DEFAULT_STATE_FILE`/`DEFAULT_PAGE_SIZE`/`DEFAULT_POLL_INTERVAL_S`/`TERMINAL_STATES`/`RESUMABLE_STATES` constants; `chunk_asset_id`, `load_task_state`, `save_task_state`, `submit_table_export`, `submit_or_resume`, `task_state`, `poll_until_complete`, `read_asset_rows`, `write_rows_csv`
- `.gitignore` - added `outputs/.batch_export_tasks.json` and `outputs/*.csv` under a new "Batch export run artefacts" section

## Decisions Made

- **Test naming to satisfy the load-bearing `-k` selector contract:** the plan's `<behavior>` spec named the task-state test `test_batch_task_state_file_round_trip`, but 04-VALIDATION.md's published `-k round_trip` selector (and this plan's own acceptance criteria: "`-k round_trip --collect-only -q` collects exactly 1 test id") requires that only the live round-trip test match that substring. Renamed to `test_batch_task_state_file_save_then_load_returns_same_state`, preserving the exact same behavior and assertions, with a comment explaining why.
- **Docstring wording avoiding literal API-name repetition:** `heatwave/batch.py`'s module docstring and `submit_table_export`'s docstring originally repeated `Export.table.toAsset`, `toDrive`, and `toCloudStorage` literally, which conflicted with acceptance criteria requiring exact counts (`toAsset` exactly once — the real code call; `toDrive`/`toCloudStorage` zero times outside comments). Reworded to convey the same rationale descriptively ("Drive-based export", "Cloud-Storage-bucket-based export") without repeating the literal method names outside the one real call site.
- **Round-trip fixture geometry:** switched from `ee.Feature(None, {...})` (as literally specified in the plan's `<action>`) to `ee.Feature(ee.Geometry.Point(...), {...})` after the live run proved Earth Engine's asset table export rejects null-geometry features. See Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test-name collision with the published `-k round_trip` selector**
- **Found during:** Task 1 (writing `tests/test_export.py`)
- **Issue:** The plan's `<behavior>` section names two tests, `test_batch_task_state_file_round_trip` and `test_batch_export_asset_round_trip`, both containing the substring `round_trip`. The plan's own acceptance criteria require `pytest tests/test_export.py -k round_trip --collect-only -q` to collect exactly 1 test id, and 04-VALIDATION.md publishes `-k round_trip` as the selector for the live de-risk test specifically. As specified, both names would match, violating that contract.
- **Fix:** Renamed the credential-free task-state test to `test_batch_task_state_file_save_then_load_returns_same_state`, with a comment explaining why, and kept its assertions/behavior identical to the plan's spec.
- **Files modified:** `tests/test_export.py`
- **Verification:** `pytest tests/test_export.py -k round_trip --collect-only -q` now collects exactly `test_batch_export_asset_round_trip`
- **Committed in:** `d2826f9` (Task 1 commit)

**2. [Rule 1 - Bug] Live Export.table.toAsset rejects null-geometry features**
- **Found during:** Task 3 (first live execution of the round-trip test)
- **Issue:** The plan's `<action>` specified building the round-trip fixture as three `ee.Feature(None, {...})` rows. Live execution against `heatwave-508110` failed with the task transitioning to `FAILED` and error message `Unable to export features with null geometry.` (confirmed via `ee.batch.Task.list()[i].status()['error_message']`, not merely inferred) — this is an Earth Engine `Export.table.toAsset` constraint, not a permission or quota problem.
- **Fix:** Gave each fixture feature an arbitrary point geometry (`ee.Geometry.Point([...])`) unused by any property-based assertion. Re-ran the live test; it passed (44.01s end-to-end), all 3 rows round-tripped correctly, and the failed attempt's asset (which was never actually created, per `listAssets`) left no residue.
- **Files modified:** `tests/test_export.py`
- **Verification:** `RUN_EE_BATCH_ROUNDTRIP=1 pytest tests/test_export.py -k round_trip -v --durations=3` — 1 passed; `listAssets` confirms no `roundtrip_smoke` asset remains
- **Committed in:** `7477145` (Task 3 commit)

**3. [Rule 1 - Bug] Docstring literal-string repetition conflicted with grep-based acceptance criteria**
- **Found during:** Task 2 (writing `heatwave/batch.py`)
- **Issue:** The plan's `<action>` instructed the module docstring to state the export-destination rationale using the literal method names `Export.table.toAsset()`, `toDrive()`, and `toCloudStorage()`. The same task's acceptance criteria require `grep -c "Export.table.toAsset"` to return exactly 1 (the one real call site) and `grep -c "toDrive\|toCloudStorage"` to return 0 outside comment lines — both violated by writing those names into a non-comment docstring.
- **Fix:** Reworded the module docstring and `submit_table_export`'s docstring to convey the identical rationale (Drive lacks service-account storage quota; Cloud Storage would require new infrastructure forbidden by D-07) without repeating the literal API names outside the one functional call.
- **Files modified:** `heatwave/batch.py`
- **Verification:** all grep-based acceptance criteria pass (see Issues Encountered)
- **Committed in:** `e5bf808` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 Rule 1 bug fixes: a test-selector collision, a live EE fixture constraint, and a docstring/acceptance-criteria conflict)
**Impact on plan:** All three were necessary corrections to make the plan's own acceptance criteria and the live Earth Engine behavior consistent. No scope creep — no production code path was altered beyond what the plan specified; only test fixtures and docstring wording changed.

## Issues Encountered

- `grep -v '^#' heatwave/batch.py | grep -F -c "settings.ward_asset_id"` initially returned 2 (one in `chunk_asset_id`'s docstring, one in the real code) against an acceptance criterion of exactly 1. Fixed by rewording the docstring to describe the same behavior ("the configured ward asset's parent namespace") without repeating the literal attribute-access string.
- Piping several `grep -c` checks together with `&&` silently truncated the verification run because `grep -c` exits 1 when a pattern's count is 0 (a false "failure" for a should-be-zero check). Reran the checks with `;` separators instead of `&&` so every criterion was actually observed.

## User Setup Required

None - no external service configuration required. Credentials (`keys/service_account.json`) were already provisioned from Phase 1 and used as-is.

## Next Phase Readiness

- `heatwave/batch.py`'s interface (`chunk_asset_id`, `submit_or_resume`, `poll_until_complete`, `read_asset_rows`, `write_rows_csv`) is stable and live-proven; plans 04-03 and 04-04 can compose against it exactly as documented in this plan's `<interfaces>` section without further de-risking.
- `tests/test_export.py` is ready to be extended by 04-03 (weekly aggregation tests) and 04-04 (chunk planner tests) per the shared-file convention CONTEXT.md/04-PATTERNS.md establish.
- No blockers. The one thing worth flagging forward: the measured 44s per-task overhead for a trivial 3-row table is a real, non-trivial fixed cost per Earth Engine batch task — 04-04's chunk-count decision (D-05) should treat this as a hard per-chunk floor, not just a research estimate.

## Self-Check: PASSED

- FOUND: heatwave/batch.py
- FOUND: tests/test_export.py
- FOUND: .gitignore
- FOUND commit: d2826f9 (Task 1, test)
- FOUND commit: e5bf808 (Task 2, feat)
- FOUND commit: 7477145 (Task 3, fix)

---
*Phase: 04-batch-export-covariate-table*
*Completed: 2026-09-16*
