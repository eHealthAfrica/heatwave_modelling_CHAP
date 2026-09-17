---
phase: 04-batch-export-covariate-table
reviewed: 2026-09-17T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - heatwave/batch.py
  - heatwave/export.py
  - heatwave/zonal.py
  - scripts/run_batch_export.py
  - tests/test_export.py
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-09-17T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed the Earth Engine async batch-export harness (`heatwave/batch.py`), the
weekly covariate aggregation (`heatwave/export.py`), the new small-ward
fallback code in `heatwave/zonal.py`, the CLI orchestration script
(`scripts/run_batch_export.py`), and the test suite (`tests/test_export.py`).

The weekly aggregation logic in `heatwave/export.py` was traced in detail for
the documented null-vs-zero rule (heat-index columns must stay null on no
usable data; count columns must default to a real `0`). That rule is
implemented correctly and is robust to either of the two plausible EE
`reduceColumns` null-handling semantics (a group entry present with an
explicit-null subkey, or the group entry missing entirely) — both paths
collapse to the same observable `None` result at `_finalize`. No defect found
there.

The real, production-run-affecting defects are in the resumable batch-task
orchestration in `heatwave/batch.py` and `scripts/run_batch_export.py`: the
task-state file is written once at submission time and is **never updated**
with the polled terminal outcome, and the resumability key (`chunk_id` alone)
carries no fingerprint of the parameters that produced it. Both are silent
correctness risks for an hours-long, multi-invocation production run — exactly
the failure mode a resumable-state design exists to prevent. The final-CSV
atomic-write guarantee (`concatenate_chunk_csvs`) is implemented correctly;
the per-chunk CSV write (`write_rows_csv`) is not, though it self-heals on
retry. The new `heatwave/zonal.py` fallback code (`find_small_wards`,
`build_fallback_ward_centroids`) is logically consistent with its documented
row-count and null-provenance guarantees, but rests on two single-point-of-
failure assumptions (single-sample-day classification; raw centroid without
inside-polygon containment) that are worth hardening given they degrade data
quality silently and permanently once triggered.

## Critical Issues

### CR-01: Batch task terminal state is never persisted — a FAILED chunk can never be automatically retried

**File:** `scripts/run_batch_export.py:392-423`, `heatwave/batch.py:90-118`
**Issue:** `submit_or_resume` (heatwave/batch.py:90-118) writes `state[chunk_id] = {"task_id": ..., "asset_id": ..., "state": "SUBMITTED"}` exactly once, at submission time. Nothing in the codebase ever updates that `"state"` field afterward. The `--stage collect` block in `main()` calls `poll_until_complete(...)` and inspects `final_states` locally (lines 395-413), but never writes the result back via `save_task_state` — in fact `save_task_state` is imported (line 55) and never called anywhere in the file.

Consequence: if a chunk's task actually transitions to `FAILED` or `CANCELLED`, the state file still records it as `"SUBMITTED"`, which is in `RESUMABLE_STATES` (heatwave/batch.py:35). On the next invocation of `--stage submit` (e.g. an operator retrying a failed chunk), `submit_or_resume` will see the stale `"SUBMITTED"` entry, treat it as still in-flight, and skip resubmission entirely — silently reusing the dead task id forever. There is no code path to recover from this short of manually editing the JSON state file.

**Fix:**
```python
# scripts/run_batch_export.py, end of the --stage collect block
if args.stage in ("collect", "all"):
    state = load_task_state(args.state_file)
    task_ids = [state[cid]["task_id"] for cid, _ in chunks if cid in state]
    final_states = poll_until_complete(task_ids, poll_interval_s=args.poll_interval)

    # Persist the polled outcome so a later --stage submit can tell a
    # genuinely FAILED/CANCELLED chunk apart from one still resumable.
    for chunk_id, _ in chunks:
        entry = state.get(chunk_id)
        if entry is not None:
            entry["state"] = final_states.get(entry["task_id"], entry.get("state", "UNKNOWN"))
    save_task_state(state, args.state_file)
    ...
```

### CR-02: Chunk resumability is keyed only by `chunk_id`, with no fingerprint of the parameters that built it — a config change across runs silently serves stale data

**File:** `heatwave/batch.py:90-118`, `scripts/run_batch_export.py:336-399`
**Issue:** `submit_or_resume(chunk_id, build_collection_fn, ...)` decides whether to skip rebuilding purely from `chunk_id` (e.g. `"c000"`) being present in the state file with a resumable state. Nothing records or checks the `start_date`, `end_date`, `--ward-batch-size`, or the actual ward-id list that chunk `"c000"` was built from.

`DEFAULT_STATE_FILE` is a fixed path (`outputs/.batch_export_tasks.json`), so two invocations of the script that don't pass an explicit `--state-file` share state. Concretely:
- Run the script once with one `--start-date`/`--end-date`. Later, rerun with a *different* date range (operator correction, or a new backfill window) while forgetting to pass a fresh `--state-file`: `submit_or_resume` finds `"c000"` already `"SUBMITTED"`/`"COMPLETED"` and returns the old task id — the new date range is silently never submitted; the final CSV ends up built from the wrong window with no error.
- Similarly, if `--ward-batch-size` differs between the `submit` invocation and a later `collect` invocation, `plan_ward_chunks` (scripts/run_batch_export.py:136-162) produces a *different* partition of ward ids under the *same* chunk ids (e.g. `"c000"` maps to a different ward subset). The `collect` stage (lines 392-423) recomputes `chunks` independently from `args.ward_batch_size` at collect time and looks up `state[chunk_id]` by that new id — silently pairing the wrong ward set's expectations with whatever asset was actually recorded, or dropping chunks that no longer line up, with no consistency check anywhere.

**Fix:** Record a fingerprint of the parameters that produced a chunk (e.g. a hash of `(sorted(ward_ids), start_date, end_date, sorted(fallback_ward_ids))`) in the state entry, and have `submit_or_resume` compare it against a freshly computed fingerprint before trusting a resumable state:
```python
import hashlib, json

def _chunk_fingerprint(ward_ids, start_date, end_date, fallback_ward_ids):
    payload = json.dumps(
        {"ward_ids": sorted(ward_ids), "start": start_date, "end": end_date,
         "fallback": sorted(fallback_ward_ids)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# in submit_or_resume: compare recorded.get("fingerprint") to the caller-supplied
# fingerprint; treat a mismatch as non-resumable and force a resubmission
# (or raise, forcing the operator to pick a fresh --state-file).
```

## Warnings

### WR-01: Per-chunk CSV write is not atomic, unlike the final concatenation

**File:** `heatwave/batch.py:193-212`
**Issue:** `write_rows_csv` opens `csv_path` directly in `"w"` mode and streams rows into it. If the process is interrupted mid-write (e.g. a transient network error partway through `read_asset_rows`'s pagination), a truncated `cNNN.csv` is left on disk under its real, final-looking filename — unlike `concatenate_chunk_csvs` in `scripts/run_batch_export.py:238-292`, which correctly uses a temp file + `os.replace`. It self-heals on the next `--stage collect` run (the file gets overwritten), so it cannot corrupt the *final* table, but it leaves operator-confusing partial artefacts and is an inconsistency against the module's own "atomic write" framing.
**Fix:** Write to a `tempfile.NamedTemporaryFile` in `csv_path.parent`, then `os.replace` onto `csv_path`, mirroring `concatenate_chunk_csvs`'s pattern.

### WR-02: No retry/backoff around Earth Engine reads during pagination

**File:** `heatwave/batch.py:167-190`
**Issue:** `read_asset_rows` calls `fc.size().getInfo()` and, per page, `ee.List(fc.toList(page_size, offset)).getInfo()` with no retry logic. A single transient network error or EE rate-limit response aborts the entire `--stage collect` run, discarding progress on every chunk already read in that same loop iteration (they'll be re-read from the still-materialized EE asset on retry, which is correct but wasteful for an hours-long job).
**Fix:** Wrap each `.getInfo()` call in a small bounded retry loop with exponential backoff.

### WR-03: Unbounded, silent polling in the production entry point

**File:** `heatwave/batch.py:126-164`, `scripts/run_batch_export.py:392-396`
**Issue:** `main()`'s `--stage collect` calls `poll_until_complete(task_ids, poll_interval_s=args.poll_interval)` without a `timeout_s`, so a stuck/queued task blocks forever with no operator-visible progress (the loop itself has no logging between iterations). For a job explicitly documented as "hours-long," this makes a genuine hang indistinguishable from normal progress.
**Fix:** Add a `--poll-timeout` CLI flag threaded through to `poll_until_complete`, and log a per-iteration summary (e.g. pending count, most recent states) inside the polling loop.

### WR-04: Fallback-ward centroid is not verified to fall inside the ward's own polygon

**File:** `heatwave/zonal.py:76-100`
**Issue:** `build_fallback_ward_centroids` re-keys a small ward's geometry to `feature.geometry().centroid()`. For a concave or multi-part (e.g. island-inclusive) polygon — exactly the kind of irregular shape a sub-pixel-weight "small ward" is likely to be — the raw geometric centroid can fall outside the polygon entirely, or inside a neighboring ward, producing a sampled value that has no relationship to the ward it is nominally representing. This is silent: nothing checks containment or logs when it happens.
**Fix:** Use `ee.Geometry.pointOnSurface()` (guaranteed to lie within the geometry) instead of `.centroid()`, or add a containment check (`geometry.contains(geometry.centroid())`) and fall back to `pointOnSurface()` only when needed.

### WR-05: Small-ward classification is a single-sample-day decision with no cross-check

**File:** `heatwave/zonal.py:41-73`, `scripts/run_batch_export.py:344-350`
**Issue:** `find_small_wards` is run once against one arbitrary image (`sample_image = ee.Image(sample_images.first())` in `scripts/run_batch_export.py:347`), and its result is reused, unchanged, for the entire multi-decade export — by design, per the module's own documentation, since ward smallness is meant to be a static geometric property. But the actual test performed is a live data condition (whether `reduceRegions` happened to yield a `mean` for that one specific day), not a static geometric computation. Any incidental data anomaly on that single sampled day (rare EE nodata sliver, boundary rasterization jitter) would permanently and silently downgrade an otherwise normal-sized ward to the lower-fidelity centroid-fallback path for every day of the entire run, with no independent verification.
**Fix:** Sample 2-3 well-separated dates and only classify a ward as "small" if every sample agrees, or independently cross-validate the flagged ward-id list against a geometric criterion (e.g. ward area vs. one pixel's area) before trusting it for the full run.

## Info

### IN-01: `save_task_state` imported but never called

**File:** `scripts/run_batch_export.py:55`
**Issue:** Confirms CR-01: the import is present in the `heatwave.batch` import list but there is no call site anywhere in the file.
**Fix:** Wire it up per CR-01's fix.

### IN-02: `--max-wards` accepts a negative value without validation

**File:** `scripts/run_batch_export.py:315, 333-334`
**Issue:** `ward_ids = ward_ids[: args.max_wards]` silently applies Python's negative-slice semantics (drops the last `N` wards) when `--max-wards` is negative, rather than erroring on an obviously-invalid input.
**Fix:** Validate `args.max_wards is None or args.max_wards >= 0` and print a usage error otherwise.

---

_Reviewed: 2026-09-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
