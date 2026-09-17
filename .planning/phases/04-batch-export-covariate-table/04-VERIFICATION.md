---
phase: 04-batch-export-covariate-table
verified: 2026-09-17T00:00:00Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 9/10
  gaps_closed:
    - "D-02/EXPORT-01: `scripts/run_batch_export.py` runs across all 4,841 wards for the script's own default (full 1991-present) date range, and `--stage plan` shows the chunk plan before submitting anything"
  gaps_remaining: []
  regressions: []
human_verification: []
---

# Phase 4: Batch Export & Covariate Table Verification Report

**Phase Goal:** The weekly ward-level covariate table can be generated end-to-end for all 4,841 wards and handed off to CHAP — the production deliverable. Per 04-CONTEXT.md D-01/D-02, the full 1991-present historical backfill running to completion is explicitly NOT a completion criterion — it's a separate, deliberately-deferred manual operation.
**Verified:** 2026-09-17
**Status:** passed
**Re-verification:** Yes — after gap closure (commit `a79f702`, following prior verification `bbdf88e`)

## Scope Interpretation

Unchanged from the prior verification pass. Per 04-CONTEXT.md D-01/D-02, the ROADMAP's own "Scope
note" for this phase, and this verification's task instructions: the fast test suite verifying
correctness on small bounded samples is the completion bar, NOT the actual full 1991-present,
4,841-ward historical backfill CSV. The absence of a full-scale `outputs/covariate_table.csv` is
NOT a gap. What matters — and what the single prior gap was about — is whether the production
script itself, invoked with its own documented default configuration, actually runs (specifically
the lightweight, non-submitting `--stage plan` preview D-02 requires).

## Gap Closure Verification (this session's focus)

The prior verification (`bbdf88e`) found one gap: `main()`'s small-ward sampling step eagerly
materialised the entire ~35-year default-range ERA5-Land image collection into a server-side List
just to count it (`sample_image_collection.toList(sample_image_collection.size())` then
`.size().getInfo()`), exceeding Earth Engine's per-request "User memory limit" and crashing every
`--stage` unconditionally at the script's own true default configuration.

Commit `a79f702` claims to fix this via a new `fetch_small_ward_sample_images()` function. I did
NOT trust that claim — I independently re-read the fixed code and independently re-ran the exact
live commands myself this session, from scratch, against the real `heatwave-508110` project.

### Code-level re-verification (not just trusting the diff description)

Read `scripts/run_batch_export.py` directly (lines 188-216). `fetch_small_ward_sample_images`:
- Gets the count via `sample_image_collection.size().getInfo()` directly — no `.toList()` call
  involved in counting at all, so this step's cost is O(1) regardless of collection size.
- Fetches each of at most 3 well-separated sample indices individually via
  `sample_image_collection.toList(1, index).get(0)` — a length-1 sublist per index, never the
  full collection.
- Is called at `main()` line 457, replacing the old eager-materialisation code path entirely (that
  old code path — `toList(size())` followed by `.size().getInfo()` — no longer exists anywhere in
  the file; confirmed via direct read of the full 590-line file, not a grep-for-absence check).

This is a structurally correct fix: it eliminates the exact eager-list-of-the-whole-collection
pattern that caused the regression, not a cosmetic change that happens to dodge the specific test
case.

### Independent live re-execution (this session, not 04-gap's or REVIEW-FIX's narration)

| Check | Command | Result |
|---|---|---|
| `--stage plan`, TRUE DEFAULT full range, `--max-wards 100` | `.venv/Scripts/python scripts/run_batch_export.py --stage plan --max-wards 100` (no date override) | **Exit 0.** Printed `Ward count: 100`, `Chunk count: 1`, `Small-ward count (D-08/D-09): 0`, `Validated export range: 1991-01-01 to 2025-09-15`. No crash — this exact invocation crashed with `EEException: User memory limit exceeded` in the prior verification pass. |
| `--stage plan`, TRUE DEFAULT full range, ALL 4,841 wards, no overrides at all | `.venv/Scripts/python scripts/run_batch_export.py --stage plan` | **Exit 0.** Printed `D-09 small-ward (centroid-fallback) count: 73`, `Ward count: 4841`, `Chunk count: 20 (ward-batch size 250)`, `Small-ward count (D-08/D-09): 73`, quota warning. Matches the fix commit's claimed evidence (`Ward count: 4841, Chunk count: 20, Small-ward count: 73`) exactly, independently reproduced. This is the exact configuration that crashed twice in the prior verification pass, at both 100 wards and all 4,841 wards — now restored. |
| Full fast test suite (all phases) | `.venv/Scripts/python -m pytest tests/ -q` | **90 passed, 2 skipped**, 155.98s — up from the prior verification's independently-reproduced `88 passed, 2 skipped`, exactly the delta the fix commit claims (2 new regression tests). |
| `tests/test_export.py` collection count | `pytest tests/test_export.py --collect-only -q` | **35 tests collected** — up from the prior verification's `33 tests collected`, i.e. exactly 2 new tests, matching the fix commit's stated addition. |
| The 2 new regression tests, run in isolation | `pytest tests/test_export.py -k fetch_small_ward_sample_images -v` | **2 passed**: `test_fetch_small_ward_sample_images_never_materialises_full_collection`, `test_fetch_small_ward_sample_images_returns_empty_for_empty_collection` |
| No stray artefacts left by the two live `--stage plan` runs | `git status --short` | Clean — no untracked/modified files (the only side-effect file, `outputs/small_wards_report.csv`, is gitignored per `.gitignore:23`, confirmed via `git check-ignore -v`) |
| No debt markers introduced by the fix | grep `TBD\|FIXME\|XXX\|TODO\|HACK\|PLACEHOLDER` in `scripts/run_batch_export.py` | No matches |

The gap is closed. `--stage plan` — the lightweight, non-submitting preview the human checkpoint's
Task 3 approval was supposed to certify — now reproduces the exact evidence that approval was based
on, at the script's own true default configuration, with no crash.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | EXPORT-01: `scripts/run_batch_export.py` composes the full pipeline and submits async EE batch work for a configurable range, including its own true default (full 1991-present) range | ✓ VERIFIED (regression fixed) | Independently re-ran `--stage plan` with no date overrides, at both `--max-wards 100` and the full 4,841-ward default: both exit 0, correct output, no crash. Was ✗ FAILED in the prior pass; now closed. |
| 2 | D-02: `--stage plan` shows chunk/small-ward/quota info before submitting anything, at the script's own default configuration | ✓ VERIFIED (regression fixed) | Same commands as #1: `Ward count: 4841`, `Chunk count: 20`, `Small-ward count (D-08/D-09): 73`, quota warning, all printed, exit 0, nothing submitted (`--stage plan` returns before the submit branch, confirmed via source read at line 490-491) |
| 3 | EXPORT-02: covariate table schema is exactly the 6 `COVARIATE_COLUMNS`, D-06 `time_period` format | ✓ VERIFIED (unchanged, re-confirmed via passing test suite this session) | `heatwave/export.py` `build_covariate_table` constructs a fresh `ee.Feature(None, {...})` with exactly the 6 keys; `test_covariate_table_schema_is_exactly_the_export_02_columns` etc. pass in this session's full-suite run |
| 4 | EXPORT-03: mechanism for "no missing wards, no null aggregates" exists and is live-verified on small samples (full-scale CSV explicitly not required) | ✓ VERIFIED (unchanged) | `assert_ward_coverage` + `concatenate_chunk_csvs`'s atomic coverage gate; `aggregate_weekly_metrics`'s canonical-key-backed outer join; D-08 null-vs-zero split; all pinned by passing tests re-run this session |
| 5 | EXPORT-04: `tests/test_export.py` verifies schema/aggregation correctness | ✓ VERIFIED (strengthened) | 35 tests now collected in `tests/test_export.py` (was 33) — the 2 new tests specifically regression-guard the fix; ran the full suite myself this session, all pass |
| 6 | D-01/D-03/D-04/D-05/D-06/D-07 (async toAsset, submit/poll separation, resumable chunking + script-owned re-concatenation, CSV destination, no new cloud infra) | ✓ VERIFIED (unchanged) | Re-read `heatwave/batch.py` and `scripts/run_batch_export.py` this session; no structural change outside the sampling function; `toDrive`/`toCloudStorage`/`bigquery` absent; `Export.table.toAsset` present once |
| 7 | D-08/D-09: centroid-fallback gives sub-pixel wards a genuine value with per-row provenance flag | ✓ VERIFIED (unchanged) | `heatwave/zonal.py` unmodified by the fix commit; `used_fallback_reducer` logic intact; tests pass |
| 8 | CR-01 fix: polled terminal task state is actually persisted, not left `SUBMITTED` forever | ✓ VERIFIED (unchanged) | `persist_polled_task_states()` still at `scripts/run_batch_export.py:311-337`, unmodified by the fix commit; dedicated tests still pass |
| 9 | CR-02 fix: chunk resumability is fingerprinted against the parameters that built it | ✓ VERIFIED (unchanged) | `chunk_fingerprint()` in `heatwave/batch.py` unmodified by the fix commit; 5 dedicated tests present and pass |
| 10 | WR-04 fix: fallback point guaranteed inside its own ward geometry | ✓ VERIFIED (unchanged) | `_representative_point_in_geometry()` in `heatwave/zonal.py`, unmodified by the fix commit |
| 11 | WR-05 fix: small-ward classification requires multi-sample consensus, AND the sampling mechanism that feeds it scales safely to the script's own true default range | ✓ VERIFIED (regression closed) | `find_small_wards` (multi-sample consensus logic, unchanged) is now fed by `fetch_small_ward_sample_images` (new), which gets its count via `.size().getInfo()` directly and fetches at most 3 images lazily via length-1 `.toList(1, index)` calls — proven live at full default scale (73 small wards detected out of 4,841, matching the fix's own claimed evidence) |

**Score:** 10/10 truths verified (up from 9/10 in the prior pass; the single previously-failing
concern, counted once across rows 1/2/11, is now closed)

### Deferred Items

None. The full 1991-present, 4,841-ward historical backfill running to completion remains
correctly out of scope per D-01/D-02 (a separate, deliberately-deferred manual operation) — this is
unchanged from the prior verification and is not a gap of any kind, deferred or otherwise.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `heatwave/batch.py` | async export harness + CR-01/CR-02 fixes | ✓ VERIFIED (unchanged) | Untouched by the fix commit; re-confirmed via passing tests this session |
| `heatwave/export.py` | weekly aggregation, EXPORT-02 schema | ✓ VERIFIED (unchanged) | Untouched by the fix commit |
| `heatwave/zonal.py` | D-08/D-09 fallback + WR-04/WR-05 fixes | ✓ VERIFIED (unchanged) | Untouched by the fix commit |
| `scripts/run_batch_export.py` | production entry point | ✓ VERIFIED (was ⚠️ ORPHANED AT SCALE, now fixed) | 590 lines; new `fetch_small_ward_sample_images()` (lines 188-216) replaces the eager-materialisation code path; `main()` now runs successfully at its own true default configuration, live-confirmed at both 100 and 4,841 wards |
| `tests/test_export.py` | EXPORT-01..04 coverage | ✓ VERIFIED (strengthened) | 35 tests collected (was 33); 2 new regression tests specifically guard against reintroducing the fixed pattern (`test_fetch_small_ward_sample_images_never_materialises_full_collection` asserts every `.toList()` call requests exactly 1 element, raising otherwise) |
| `outputs/covariate_table_smoke.csv` | real small-sample output, correct schema | ✓ VERIFIED (unchanged) | Not touched this session; prior direct read stands |
| `.gitignore` | run artefacts excluded | ✓ VERIFIED (unchanged, re-confirmed) | `git check-ignore -v outputs/small_wards_report.csv` confirms coverage, re-checked this session after the live `--stage plan` runs wrote to it |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| `heatwave/batch.py` | `ee.batch.Export.table.toAsset` | async submission | ✓ WIRED (unchanged) |
| `heatwave/batch.py` | `ee.data.getTaskStatus` | polling | ✓ WIRED (unchanged) |
| `scripts/run_batch_export.py` | `heatwave.export.build_covariate_table` | per-chunk aggregation | ✓ WIRED (unchanged) |
| `scripts/run_batch_export.py` | `heatwave.batch.submit_or_resume` | resumable submission | ✓ WIRED, with CR-02 fingerprint threaded through (unchanged) |
| `scripts/run_batch_export.py` | `heatwave.batch.save_task_state` | CR-01 persistence | ✓ WIRED (unchanged) |
| `scripts/run_batch_export.py` | `heatwave.zonal.find_small_wards` | once-per-run detection, fed by `fetch_small_ward_sample_images` | ✓ WIRED AND scales safely to full default range — previously "wired but crashes at scale," now live-confirmed working at 4,841 wards |
| `scripts/run_batch_export.py` | `outputs/covariate_table.csv` | coverage-gated final write | ✓ WIRED (unchanged; `--stage plan` correctly returns before reaching this, confirmed at line 490-491) |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| EXPORT-01 | 04-01, 04-04 | Full pipeline across all 4,841 wards, configurable date range | ✓ SATISFIED (was ⚠️ PARTIALLY BLOCKED) | Now works correctly at its own true default full-range configuration, live-confirmed at both 100 and 4,841 wards, in addition to every bounded range already verified |
| EXPORT-02 | 04-03, 04-04 | Exact covariate schema | ✓ SATISFIED (unchanged) | Verified via code, tests, and real smoke CSV |
| EXPORT-03 | 04-02, 04-03, 04-04 | Completeness mechanism (no missing wards, no null aggregates), full-scale CSV explicitly out of scope | ✓ SATISFIED (unchanged) | Coverage gate + null/zero split verified on live small samples per the phase's own scope note |
| EXPORT-04 | 04-01, 04-03, 04-04 | `tests/test_export.py` verifies schema/aggregation | ✓ SATISFIED (strengthened) | 35 tests, independently re-run this session, all pass |

No orphaned requirements: all 4 requirement IDs (EXPORT-01..04) are declared across the four plans'
frontmatter and covered above. REQUIREMENTS.md marks all four `[x]` Complete — this verification now
agrees with that mark on all four, including EXPORT-01, where the prior pass had disagreed.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in any of the phase's modified
files (`heatwave/batch.py`, `heatwave/export.py`, `heatwave/zonal.py`, `scripts/run_batch_export.py`,
`tests/test_export.py`), re-checked this session against the post-fix code.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| `--stage plan` at true default range, 100 wards, does not crash | `run_batch_export.py --stage plan --max-wards 100` | Exit 0, correct plan printed | ✓ PASS |
| `--stage plan` at true default range, all 4,841 wards, does not crash | `run_batch_export.py --stage plan` (no overrides) | Exit 0; `Ward count: 4841`, `Chunk count: 20`, `Small-ward count: 73` | ✓ PASS |
| Small-ward sampling never lists more than 1 element per request regardless of collection size | `test_fetch_small_ward_sample_images_never_materialises_full_collection` (fake collection declares size 12,784, raises on any `toList(n)` with `n != 1`) | 1 passed | ✓ PASS |

### Human Verification Required

None. The gap was deterministically reproducible and is now deterministically confirmed fixed by
direct re-execution of the exact previously-failing commands.

### Gaps Summary

No gaps remain. The prior verification's single gap — `scripts/run_batch_export.py`'s `main()`
crashing with `EEException: User memory limit exceeded` at its own true default (full
1991-present) date range, for every `--stage` value, independent of ward count — is closed by
commit `a79f702`.

Verified independently this session, not by trusting the fix commit's message or 04-gap narration:
- Read the fixed code directly: the eager `sample_image_collection.toList(sample_image_collection.size())` pattern is gone entirely; replaced by an O(1) `.size().getInfo()` count plus per-index length-1 `.toList(1, index)` fetches.
- Re-ran the exact two commands that crashed in the prior pass (`--stage plan --max-wards 100` and `--stage plan` with zero overrides at 4,841 wards) against the real `heatwave-508110` project: both now exit 0 with correct, matching output.
- Re-ran the full fast test suite: 90 passed, 2 skipped (up from the prior pass's independently-reproduced 88 passed, 2 skipped) — the delta is exactly the 2 new regression tests, both of which pass and which specifically fail if the fixed pattern is ever reintroduced.
- Confirmed no stray artefacts, no debt markers, and no unrelated regressions were introduced by the fix (all other 9 previously-verified truths were spot-checked as unmodified by the fix commit and still pass).

Phase 4's goal — the weekly ward-level covariate table can be generated end-to-end for all 4,841
wards and handed off to CHAP, with the full historical backfill itself correctly deferred as a
separate manual operation per D-01/D-02 — is achieved. All 4 requirement IDs (EXPORT-01..04) are
satisfied.

---

*Verified: 2026-09-17*
*Verifier: Claude (gsd-verifier)*
