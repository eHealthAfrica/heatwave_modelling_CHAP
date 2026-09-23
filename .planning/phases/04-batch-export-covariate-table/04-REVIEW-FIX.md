# Phase 4 Code Review — Fixes Applied

**Date:** 2026-09-17
**Source review:** `04-REVIEW.md` (2 critical, 5 warnings, 2 info)
**Scope fixed:** CR-01, CR-02 (both critical), WR-04, WR-05 (data-quality warnings), IN-01 (resolved as a byproduct of CR-01)
**Deferred (operational hardening, not data-correctness):** WR-01, WR-02, WR-03, IN-02

## CR-01 — Batch task terminal state now persisted

**Commit:** `817407e`

`scripts/run_batch_export.py` now calls the previously-imported-but-unused `save_task_state` after every poll. Added `persist_polled_task_states(state, chunks, final_states, state_file)`, invoked right after `poll_until_complete` in the `--stage collect` block. A chunk that actually transitions to `FAILED`/`CANCELLED` is now recorded as such, instead of staying at `"SUBMITTED"` forever — a later `--stage submit` retry can now tell a dead task apart from one still resumable.

Tests: `test_persist_polled_task_states_writes_failed_not_submitted`, `test_persist_polled_task_states_leaves_unknown_entries_untouched`.

## CR-02 — Chunk resumability now fingerprinted

**Commit:** `3d803d4`

`heatwave/batch.py` adds `chunk_fingerprint(ward_ids, start_date, end_date, fallback_ward_ids)` (sha256 of sorted ids + date range), threaded through `submit_or_resume` as an optional parameter. A fingerprint mismatch now forces resubmission instead of silently trusting stale state. `scripts/run_batch_export.py`'s submit stage computes and passes the fingerprint; a symmetric `is_chunk_fingerprint_stale()` helper covers the collect stage, which recomputes chunks independently from `--ward-batch-size` and had the same staleness exposure.

Tests: `test_chunk_fingerprint_is_ward_id_and_fallback_order_independent`, `test_chunk_fingerprint_changes_with_date_range_or_ward_set`, `test_batch_submit_or_resume_reuses_when_fingerprint_matches`, `test_batch_submit_or_resume_resubmits_on_fingerprint_mismatch`, `test_is_chunk_fingerprint_stale_detects_mismatch_but_not_legacy_entries`.

## WR-04 — Fallback ward point now guaranteed inside its own geometry

**Commit:** `7d30e70`

**Deviation from the review's literal suggestion:** `ee.Geometry.pointOnSurface()` does not exist in this project's pinned `earthengine-api` client — confirmed live (`AttributeError`), not assumed from the review text. `heatwave/zonal.py` instead adds `_representative_point_in_geometry(geometry)`: uses `centroid()` when the geometry actually contains it, otherwise falls back to the geometry's own first vertex (always on the geometry). Verified live against a donut-shaped polygon whose true centroid provably falls in the hole.

Test: `test_zonal_fallback_point_lies_inside_its_own_ward_geometry_even_when_concave`.

## WR-05 — Small-ward classification now requires multi-sample consensus

**Commit:** `e0b0100`

`find_small_wards` now accepts a single image (backward compatible) or an iterable of images, classifying a ward as small only when every sample agrees it's missing a `mean`. `scripts/run_batch_export.py` adds `select_well_separated_sample_indices()` and samples up to 3 well-separated images instead of always index 0, removing the single-anomalous-day misclassification risk.

Tests: `test_zonal_find_small_wards_requires_consensus_across_samples`, `test_zonal_find_small_wards_still_accepts_a_single_image`, `test_select_well_separated_sample_indices_spans_the_full_range`, `test_select_well_separated_sample_indices_handles_small_totals`.

## Verification

- Fast suite (default, no live-quota-consuming tests): 88 passed, 2 skipped — no regressions across all 4 phases.
- Both pre-existing opt-in, env-gated live tests re-run explicitly against real Earth Engine after the fixes, confirming the CR-01/CR-02 signature changes and WR-04/WR-05 `zonal.py` changes don't break the live paths:
  - `RUN_EE_BATCH_ROUNDTRIP=1` round-trip test — passed
  - `RUN_EE_PIPELINE_SMOKE=1` full-pipeline smoke test — passed

## Not fixed (left as documented, non-blocking)

- **WR-01** (non-atomic per-chunk CSV write) — self-heals on retry per the review's own note; deferred.
- **WR-02** (no retry/backoff on EE reads during pagination) — operational hardening for the eventual full backfill, not a correctness bug.
- **WR-03** (unbounded/silent polling) — same category as WR-02.
- **IN-02** (`--max-wards` negative-value validation) — minor input-validation gap, no data-integrity impact.
