---
phase: 04-batch-export-covariate-table
verified: 2026-09-17T00:00:00Z
status: gaps_found
score: 9/10 must-haves verified
overrides_applied: 0
gaps:
  - truth: "D-02/EXPORT-01: `scripts/run_batch_export.py` runs across all 4,841 wards for the script's own default (full 1991-present) date range, and `--stage plan` shows the chunk plan before submitting anything"
    status: failed
    reason: >
      Reproduced live, twice, against heatwave-508110: invoking the script with NO date-range
      override (i.e. the actual D-01 default: `--start-date 1991-01-01` through
      `settings.end_date`) crashes with `ee.ee_exception.EEException: User memory limit exceeded`
      before printing anything -- not just at full 4,841-ward scale, but even with `--max-wards 100`.
      A bounded 9-year range (`--start-date 1991-01-01 --end-date 2000-01-01`) succeeds, and the
      previously-approved checkpoint range (a short window) also succeeds, isolating the cause to the
      SIZE of the default date range, not ward count. This means the actual production configuration
      this phase's D-01/D-02 and EXPORT-01 require -- the full historical default, which is also what
      the human operator's Task-3 checkpoint approval was supposed to certify -- currently cannot even
      reach the "print the plan, submit nothing" stage, let alone the real backfill. Root-caused to a
      regression introduced by the WR-05 review fix (commit e0b0100): `main()` was changed from the
      cheap, lazy `sample_images.first()` (pre-fix) to
      `sample_image_collection.toList(sample_image_collection.size())` followed by
      `.size().getInfo()` -- this eagerly materialises the ENTIRE ~35-year daily ERA5-Land image
      collection into a server-side List just to count it, which exceeds Earth Engine's per-request
      memory quota at that scale. Because this code runs unconditionally at the top of `main()` before
      the `--stage` branch, `--stage plan`, `--stage submit`, and `--stage all` all fail identically --
      the whole script is currently non-functional at its own documented default configuration.
      04-REVIEW-FIX.md's verification section only re-ran the two short-date-range opt-in tests
      (`RUN_EE_BATCH_ROUNDTRIP`, `RUN_EE_PIPELINE_SMOKE`, both ~3-week windows) and the credential-gated
      fast suite (synthetic small fixtures) -- neither exercises the real default full-range
      invocation, so this regression was never re-verified after WR-05 was applied, even though it
      directly undoes the exact `--stage plan` checkpoint evidence (04-04 Task 3) the operator
      approved before the review-fix commits existed.
    artifacts:
      - path: "scripts/run_batch_export.py"
        issue: "main() lines ~426-427: `sample_image_list = sample_image_collection.toList(sample_image_collection.size())` then `sample_image_count = sample_image_list.size().getInfo()` eagerly materialises the full default-range (~35-year) image collection, exceeding Earth Engine's User memory limit; runs unconditionally before the --stage plan/submit/collect branch, so every stage is currently broken at the documented default configuration"
    missing:
      - "Get the sample count without materialising the whole collection as a List -- `sample_image_collection.size().getInfo()` directly (ee.ImageCollection.size() does not require listing every element) -- and fetch only the specific sampled indices lazily, e.g. `sample_image_collection.toList(1, index).get(0)` per index from select_well_separated_sample_indices(), rather than ever converting the entire multi-decade collection into one server-side List"
      - "Re-run `.venv/Scripts/python scripts/run_batch_export.py --stage plan` with NO date overrides (the true default) against the real ward asset after the fix, and confirm it prints the ward count/chunk count/small-ward count/quota warning without raising, restoring the exact checkpoint evidence Task 3 originally certified"
human_verification: []
---

# Phase 4: Batch Export & Covariate Table Verification Report

**Phase Goal:** The weekly ward-level covariate table can be generated end-to-end for all 4,841 wards and handed off to CHAP — the production deliverable.
**Verified:** 2026-09-17
**Status:** gaps_found
**Re-verification:** No — initial verification

## Scope Interpretation

Per 04-CONTEXT.md D-01/D-02, the ROADMAP's own "Scope note" for this phase, and this verification's
task instructions: the fast test suite verifying correctness on small bounded samples is the
completion bar, NOT the actual full 1991-present, 4,841-ward historical backfill CSV. The absence of a
full-scale `outputs/covariate_table.csv` is explicitly NOT treated as a gap below. What IS in scope,
and what the single gap below is about, is whether the **production script itself, invoked with its
own documented default configuration, actually runs** (specifically the lightweight, non-submitting
`--stage plan` preview D-02 requires) — this is different from requiring the backfill to complete, and
it is directly falsifiable in the current codebase, which is why it is reported.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | EXPORT-01: `scripts/run_batch_export.py` composes the full pipeline and submits async EE batch work for a configurable range | ✗ FAILED (at the script's own default full-range configuration) | Reproduced live twice: default (no-override) invocation and `--max-wards 100` with the default full range both crash with `EEException: User memory limit exceeded` before printing anything; a 9-year bounded range succeeds. See gap above. |
| 2 | D-02: `--stage plan` shows chunk/small-ward/quota info before submitting anything | ✗ FAILED at full default scale | Same crash occurs before any `--stage` branching; unhandled exception, exit via traceback, nothing printed to stdout |
| 3 | EXPORT-02: covariate table schema is exactly the 6 `COVARIATE_COLUMNS`, D-06 `time_period` format | ✓ VERIFIED | `heatwave/export.py` build_covariate_table constructs a fresh `ee.Feature(None, {...})` with exactly the 6 keys; live tests `test_covariate_table_schema_is_exactly_the_export_02_columns` etc. pass; real `outputs/covariate_table_smoke.csv` on disk has the exact header and plausible values (verified directly, see below) |
| 4 | EXPORT-03: mechanism for "no missing wards, no null aggregates" exists and is live-verified on small samples (full-scale CSV explicitly not required) | ✓ VERIFIED | `assert_ward_coverage` + `concatenate_chunk_csvs`'s atomic coverage gate; `aggregate_weekly_metrics`'s canonical-key-backed outer join; D-08 null-vs-zero split; all pinned by passing live tests |
| 5 | EXPORT-04: `tests/test_export.py` verifies schema/aggregation correctness | ✓ VERIFIED | 33 tests collected in `tests/test_export.py`; ran the full suite myself (below) |
| 6 | D-01/D-03/D-04/D-05/D-06/D-07 (async toAsset, submit/poll separation, resumable chunking + script-owned re-concatenation, CSV destination, no new cloud infra) | ✓ VERIFIED | Source-read `heatwave/batch.py` and `scripts/run_batch_export.py`; `toDrive`/`toCloudStorage`/`bigquery` absent; `Export.table.toAsset` present once; atomic `os.replace` promotion in `concatenate_chunk_csvs` |
| 7 | D-08/D-09: centroid-fallback gives sub-pixel wards a genuine value with per-row provenance flag | ✓ VERIFIED | `heatwave/zonal.py` `reduce_to_ward_daily`/`find_small_wards`/`build_fallback_ward_centroids`; `used_fallback_reducer` set on both paths; tests pass |
| 8 | CR-01 fix: polled terminal task state is actually persisted, not left `SUBMITTED` forever | ✓ VERIFIED (real code, not just claim) | `persist_polled_task_states()` defined in `scripts/run_batch_export.py:280-306`, called at line 504 inside the `--stage collect`/`all` block immediately after `poll_until_complete`; dedicated tests `test_persist_polled_task_states_writes_failed_not_submitted` / `..._leaves_unknown_entries_untouched` present and pass |
| 9 | CR-02 fix: chunk resumability is fingerprinted against the parameters that built it | ✓ VERIFIED (real code, not just claim) | `chunk_fingerprint()` in `heatwave/batch.py:91-121` (sha256 of sorted ward ids + date range + sorted fallback ids); threaded through `submit_or_resume`'s new `fingerprint` param (lines 124-172); `scripts/run_batch_export.py` computes/passes it at both submit (line 478) and collect (line 525) time via `is_chunk_fingerprint_stale()` (lines 261-277); 5 dedicated tests present and pass |
| 10 | WR-04 fix: fallback point guaranteed inside its own ward geometry, not a raw (possibly outside-polygon) centroid | ✓ VERIFIED (real code, matches the note that `pointOnSurface()` doesn't exist in this API) | `_representative_point_in_geometry()` in `heatwave/zonal.py:103-131` — confirmed it is NOT `ee.Geometry.pointOnSurface()` (docstring explicitly records that method does not exist in this project's `earthengine-api`, live-verified via `ee.ApiFunction.allSignatures()`/`dir(ee.Geometry)`); instead uses `centroid()` when `geometry.contains(centroid)`, else the geometry's own first vertex; wired into `build_fallback_ward_centroids`; dedicated test `test_zonal_fallback_point_lies_inside_its_own_ward_geometry_even_when_concave` present |
| 11 | WR-05 fix: small-ward classification requires multi-sample consensus, not a single sampled day | ✓ VERIFIED (real code) | `find_small_wards(images, ...)` in `heatwave/zonal.py:46-100` accepts a single image (backward compat) or an iterable, computes `missing_id_sets` per sample and returns `set.intersection(*missing_id_sets)` — a ward is only "small" if EVERY sample agrees; `scripts/run_batch_export.py` adds `select_well_separated_sample_indices()` (lines 166-185) and samples up to 3 spread-out images instead of always index 0; dedicated tests present and pass. **However**, this same change is the root cause of gap #1/#2 above (see artifact/issue) |

**Score:** 9/10 truths verified (the two FAILED rows both stem from the single WR-05-introduced regression, counted once in the gaps section)

### Independent Live Re-Verification (not just trusting SUMMARY/REVIEW-FIX claims)

I did not rely on 04-01/04-04-SUMMARY.md's or 04-REVIEW-FIX.md's narration. I re-ran the following myself, this session, against the real `heatwave-508110` project:

| Check | Command | Result |
|---|---|---|
| Full fast suite (all 4 phases) | `.venv/Scripts/python -m pytest tests/ -q` | **88 passed, 2 skipped**, 153s — matches 04-REVIEW-FIX.md's claimed count exactly, independently reproduced |
| Live batch round-trip (opt-in) | `RUN_EE_BATCH_ROUNDTRIP=1 pytest tests/test_export.py -k round_trip -v --durations=3` | **1 passed**, 109.89s |
| Live end-to-end pipeline smoke (opt-in) | `RUN_EE_PIPELINE_SMOKE=1 pytest tests/test_export.py -k small_sample_pipeline -v --durations=3` | **1 passed**, 39.34s |
| No leftover EE assets from either live test | `ee.data.listAssets(...)` filtered for `roundtrip_smoke`/`covariate_chunk_` | `[]` — clean |
| `--stage plan`, bounded 5-month range, 100 wards | `run_batch_export.py --stage plan --max-wards 100 --start-date 2020-01-01 --end-date 2020-06-01` | Exit 0, correct plan printed |
| `--stage plan`, bounded 9-year range, 100 wards | `run_batch_export.py --stage plan --max-wards 100 --start-date 1991-01-01 --end-date 2000-01-01` | Exit 0, correct plan printed |
| `--stage plan`, TRUE DEFAULT full range, 100 wards | `run_batch_export.py --stage plan --max-wards 100` (no date override) | **CRASH**: `EEException: User memory limit exceeded` |
| `--stage plan`, TRUE DEFAULT full range, all 4,841 wards | `run_batch_export.py --stage plan` (no overrides at all) | **CRASH**: identical `EEException: User memory limit exceeded` |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `heatwave/batch.py` | async export harness + CR-01/CR-02 fixes | ✓ VERIFIED | 266 lines; all exports present; fixes wired |
| `heatwave/export.py` | weekly aggregation, EXPORT-02 schema | ✓ VERIFIED | 383 lines; matches interface contract exactly |
| `heatwave/zonal.py` | D-08/D-09 fallback + WR-04/WR-05 fixes | ✓ VERIFIED | 273 lines; `_representative_point_in_geometry`, multi-sample `find_small_wards` present |
| `scripts/run_batch_export.py` | production entry point | ⚠️ ORPHANED AT SCALE | 561 lines; all required functions present and individually correct, but `main()` crashes unconditionally at the script's own documented default configuration (see gap) |
| `tests/test_export.py` | EXPORT-01..04 coverage | ✓ VERIFIED | 33 tests collected; includes all CR-01/CR-02/WR-05 regression tests |
| `outputs/covariate_table_smoke.csv` | real small-sample output, correct schema | ✓ VERIFIED | Read directly: header exactly `time_period,location,heatwave_days,mean_heat_index,max_heat_index,heatwave_event_count`; real ward codes (10101/10102); no empty aggregate cells |
| `.gitignore` | run artefacts excluded | ✓ VERIFIED | `git check-ignore` confirms `outputs/covariate_table.csv`, `outputs/.batch_export_tasks.json`, `outputs/covariate_table_smoke.csv` all ignored |

### Key Link Verification

| From | To | Via | Status |
|---|---|---|---|
| `heatwave/batch.py` | `ee.batch.Export.table.toAsset` | async submission | ✓ WIRED |
| `heatwave/batch.py` | `ee.data.getTaskStatus` | polling | ✓ WIRED |
| `scripts/run_batch_export.py` | `heatwave.export.build_covariate_table` | per-chunk aggregation | ✓ WIRED |
| `scripts/run_batch_export.py` | `heatwave.batch.submit_or_resume` | resumable submission | ✓ WIRED, with CR-02 fingerprint threaded through |
| `scripts/run_batch_export.py` | `heatwave.batch.save_task_state` | CR-01 persistence | ✓ WIRED (was previously imported-but-unused per IN-01; now called via `persist_polled_task_states`) |
| `scripts/run_batch_export.py` | `heatwave.zonal.find_small_wards` | once-per-run detection | ⚠️ WIRED BUT the multi-sample materialisation feeding it crashes at full scale (see gap) |
| `scripts/run_batch_export.py` | `outputs/covariate_table.csv` | coverage-gated final write | ✓ WIRED (unreachable at full scale only because an earlier step in the same function crashes first) |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| EXPORT-01 | 04-01, 04-04 | Full pipeline across all 4,841 wards, configurable date range | ⚠️ PARTIALLY BLOCKED | Works correctly for any bounded range; crashes at the script's own true default range (the actual production configuration D-01 mandates) |
| EXPORT-02 | 04-03, 04-04 | Exact covariate schema | ✓ SATISFIED | Verified via code, tests, and real smoke CSV |
| EXPORT-03 | 04-02, 04-03, 04-04 | Completeness mechanism (no missing wards, no null aggregates), full-scale CSV explicitly out of scope | ✓ SATISFIED | Coverage gate + null/zero split verified on live small samples per the phase's own scope note |
| EXPORT-04 | 04-01, 04-03, 04-04 | `tests/test_export.py` verifies schema/aggregation | ✓ SATISFIED | 33 tests, independently re-run, all pass |

No orphaned requirements: all 4 requirement IDs (EXPORT-01..04) are declared across the four plans' frontmatter and covered above. REQUIREMENTS.md itself marks all four `[x]` Complete — this verification disagrees with that mark for EXPORT-01 specifically, for the reason above.

### Anti-Patterns Found

None. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers in any of the phase's modified files (`heatwave/batch.py`, `heatwave/export.py`, `heatwave/zonal.py`, `scripts/run_batch_export.py`).

### Human Verification Required

None. The one open item (the `--stage plan` crash at full default scale) is independently, deterministically reproducible by re-running the exact command shown above — it does not require human judgement to confirm, only a code fix and a re-run.

### Gaps Summary

Nine of ten must-have truths are solidly verified, including independent re-execution (not just reading
SUMMARY/REVIEW-FIX narration) of both opt-in live tests and the full fast suite, and direct source
confirmation that all four code-review fixes (CR-01, CR-02, WR-04, WR-05) are genuinely implemented and
wired, not merely claimed. `heatwave/export.py`, `heatwave/zonal.py`, `heatwave/batch.py`, and the
production script's individual functions (`plan_ward_chunks`, `assert_ward_coverage`,
`concatenate_chunk_csvs`, `build_chunk_collection`, `chunk_fingerprint`, `persist_polled_task_states`,
etc.) are all correct, tested, and live-proven at small scale.

The one gap is a genuine, freshly-discovered regression: the WR-05 code-review fix (commit `e0b0100`)
changed `scripts/run_batch_export.py`'s small-ward sampling step from a cheap, lazy `.first()` call to
one that eagerly materialises the entire default-range (~35-year) ERA5-Land image collection into a
server-side list just to count it. At the phase's own documented default configuration — the actual
full 1991-present backfill D-01 specifies, which is also the configuration the human checkpoint's
`--stage plan` approval was supposed to certify — this now crashes with Earth Engine's "User memory
limit exceeded" before printing anything, for EVERY `--stage` value (`plan`, `submit`, `collect`,
`all`), independent of ward count. This was not caught by 04-REVIEW-FIX.md's own verification because
that verification only re-ran the two short-date-range opt-in tests and the small-fixture fast suite —
neither exercises the real default full-range invocation. This means the production script, as it
currently stands, cannot reproduce the exact checkpoint evidence the operator approved before the
review-fix commits existed.

This does NOT mean the full backfill needs to be run to close this gap (that remains correctly deferred
per D-01/D-02/04-VALIDATION.md). It means `--stage plan` (a lightweight, non-submitting, few-second
preview by design) needs to work again at the true default configuration, which requires only the fix
described above (avoid materialising the full collection as a List; get the count via
`ImageCollection.size()` directly and fetch only the needed sample indices lazily) plus a re-run of
`--stage plan` with no overrides to confirm.

---

*Verified: 2026-09-17*
*Verifier: Claude (gsd-verifier)*
