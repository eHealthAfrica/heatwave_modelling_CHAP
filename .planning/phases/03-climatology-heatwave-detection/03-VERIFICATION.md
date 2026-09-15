---
phase: 03-climatology-heatwave-detection
verified: 2026-09-13T00:00:00Z
status: passed
score: 15/15 must-haves verified
overrides_applied: 0
---

# Phase 3: Climatology & Heatwave Detection Verification Report

**Phase Goal:** Each ward has a per-ward climatological heatwave threshold, and heatwave
days/events are correctly flagged against it — the pipeline's core new scientific capability.
**Verified:** 2026-09-13
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

This verification ran the full live test suite against real Earth Engine (credentials present
at `keys/service_account.json`) rather than relying on SUMMARY.md narration. Command:
`.venv/Scripts/python -m pytest tests/ -v` → **49 passed, 0 failed, 0 skipped, 0 errors**
(291s). All 34 tests in `tests/test_heatwave_detection.py` (CLIM-01 through CLIM-06, including
every CR-01/WR-01/WR-02/WR-03 regression test added post-review) ran live and passed, not
merely collected.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | CLIM-01: per-ward, per-calendar-day percentile climatology baseline computed via grouped reducer | ✓ VERIFIED | `heatwave/science/climatology.py::compute_climatology_thresholds`; live tests `test_climatology_threshold_matches_live_verified_ee_percentile`, `test_climatology_thresholds_are_computed_per_ward`, `test_climatology_baseline_year_filter_excludes_outside_years`, `test_climatology_feb29_is_its_own_calendar_day_slot` all PASSED live |
| 2 | CLIM-02: ±N-day pooling window wraps bidirectionally across the year boundary | ✓ VERIFIED | `floor_mod`/`wrapped_day`/`pooling_window_filter` in `climatology.py`; `test_pooling_window_floor_mod_handles_negatives`, `test_pooling_window_wraps_across_new_year`, `test_pooling_window_wraps_at_day_366` PASSED live |
| 3 | CLIM-03: ward-day flagged hot when value strictly exceeds its own ward's, own calendar-day threshold | ✓ VERIFIED | `heatwave/science/heatwave.py::flag_heatwave_days` uses `.gt(...)` (never `.gte`); `test_heatwave_day_flag_marks_values_above_threshold`, `test_heatwave_day_flag_is_strictly_greater_than`, `test_heatwave_day_flag_uses_the_matching_calendar_day_threshold` PASSED live |
| 4 | CLIM-04: consecutive hot days grouped into runs; only runs ≥ min_consecutive_days become events, isolated per ward | ✓ VERIFIED | `tag_consecutive_runs`/`detect_heatwave_events`; `test_heatwave_event_tag_consecutive_runs_matches_verified_sequence`, `test_heatwave_event_requires_min_consecutive_days`, `test_heatwave_event_detection_is_scoped_per_ward` PASSED live, matching the exact verified run-tag sequence |
| 5 | CLIM-05: gridded Heat Index correctly reduced to per-ward-daily rows, including against the real ERA5-Land collection and real ward asset | ✓ VERIFIED | `heatwave/zonal.py::reduce_to_ward_daily`; synthetic zonal tests plus `test_real_era5_land_zonal_reduction_smoke` (3 real largest wards x 5 real ERA5-Land days) all PASSED live |
| 6 | CLIM-06: the four stages compose end-to-end and the full CLIM-01..05 surface is covered by a live-EE test file | ✓ VERIFIED | `test_end_to_end_climatology_and_event_pipeline` chains `reduce_to_ward_daily → compute_climatology_thresholds → flag_heatwave_days → detect_heatwave_events` in one live run and PASSED |
| 7 | CR-01 fix is real: outer join in `flag_heatwave_days` preserves unmatched ward-days with null threshold/is_hot instead of dropping them | ✓ VERIFIED | `heatwave/science/heatwave.py:74` `ee.Join.saveFirst("clim_match", outer=True)`; `flag_one_row` uses `ee.Algorithms.If(clim_match, ..., None)`. Regression test `test_heatwave_day_flag_keeps_unmatched_ward_day_with_null_threshold` constructs a deliberate doy-2 climatology gap, asserts row count stays 3 (not 2), and doy 2's threshold/is_hot are null while doy 1/3 are not — PASSED live |
| 8 | WR-01 fix is real: `min_consecutive_days=0` is respected, not swallowed by config default via `or` truthiness | ✓ VERIFIED | `heatwave/science/heatwave.py:189-193` uses `is not None` ternary, not `or`. Regression test `test_heatwave_event_min_consecutive_days_zero_is_not_overridden_by_config` passes `min_consecutive_days=0` explicitly and asserts `event_id == run_id` exactly (3 distinct events, including the 2-day run that config default 3 would demote) — PASSED live |
| 9 | WR-02 fix is real: `compute_climatology_thresholds`'s output key matches the caller's `ward_id_property`, not a hardcoded `"ward_id"` literal | ✓ VERIFIED | `heatwave/science/climatology.py:128` `ward_id_property: ee.Dictionary(g).get(ward_id_property)`. Regression test `test_climatology_and_heatwave_honor_non_default_ward_id_property` runs both functions with `ward_id_property="wardcode"` end-to-end and asserts the join actually matches (non-null threshold) — PASSED live |
| 10 | WR-03 fix is real: `ClimatologyConfig` validates its fields at construction | ✓ VERIFIED | `heatwave/config.py:20-33` `__post_init__` raises `ValueError` for percentile out of (0,100), start>end, negative pooling window, min_consecutive_days<1. `test_climatology_config_accepts_the_real_config_yaml_values` and 6-case parametrized `test_climatology_config_rejects_malformed_values` PASSED (credential-free, ran unconditionally) |
| 11 | Security V5: climatology/heatwave tuning parameters resolve from config, no hardcoded literals | ✓ VERIFIED | `grep` confirms `settings.climatology.*` used in both modules; no bare `90`/`1991`/`2020`/`min_consecutive_days = 3` literals outside comments |
| 12 | D-04: no Python-level ward loops; functions are ward-count-agnostic | ✓ VERIFIED | `grep -c "for ward in "` returns 0 in both `climatology.py` and `heatwave.py`; ward partitioning uses `aggregate_array(...).distinct().map()` |
| 13 | D-01/D-02: all assertions run against live Earth Engine, no numpy/pandas reference oracle | ✓ VERIFIED | No numpy/pandas/scipy/statistics imports in `tests/test_heatwave_detection.py` or production modules; percentile oracle is EE's own 9.5, not numpy's 9.1 |
| 14 | Full Phase 1-3 regression suite green | ✓ VERIFIED | `pytest tests/ -v` → 49 passed, 0 failed (live run, this session) |
| 15 | Requirement IDs CLIM-01 through CLIM-06 all accounted for | ✓ VERIFIED | Declared across 03-01/02/03/04 PLAN frontmatter; all marked `[x]` Complete in REQUIREMENTS.md; all have live passing test coverage |

**Score:** 15/15 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `heatwave/zonal.py` | `reduce_to_ward_daily` gridded→per-ward-daily reduction | ✓ VERIFIED | 77 lines, exports function, matches documented row schema, no hardcoded ward count |
| `heatwave/science/climatology.py` | floor-mod helpers, pooling filter, grouped percentile threshold | ✓ VERIFIED | 142 lines, exports `floor_mod`, `wrapped_day`, `pooling_window_filter`, `compute_climatology_thresholds`; WR-02 fix present |
| `heatwave/science/heatwave.py` | threshold join/flagging, run detection, event detection | ✓ VERIFIED | 217 lines, exports `flag_heatwave_days`, `tag_consecutive_runs`, `detect_heatwave_events`; CR-01 and WR-01 fixes present |
| `heatwave/config.py` (`ClimatologyConfig`) | validated config dataclass | ✓ VERIFIED | `__post_init__` validation added per WR-03 |
| `tests/test_heatwave_detection.py` | CLIM-01..06 live coverage plus review-fix regressions | ✓ VERIFIED | 1080 lines, 34 tests collected, all 34 PASSED live in this session |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `zonal.py` | `climatology.py`/`heatwave.py` | `system:time_start` set on every output row | ✓ WIRED | `test_zonal_output_supports_calendarrange_filter` and real-data equivalent PASSED |
| `climatology.py` | `heatwave.py` | `ee.Join.saveFirst(..., outer=True)` keyed on `(ward_id_property, doy)` | ✓ WIRED | Outer join confirmed in source; join-gap regression test PASSED |
| `climatology.py`/`heatwave.py` | `heatwave.config.settings.climatology` | None-defaulting parameters | ✓ WIRED | `grep` confirms all four climatology params + `min_consecutive_days` resolve from settings |
| `heatwave.py` | consecutive-run state machine | `ee.List.iterate` over per-ward, date-sorted flags | ✓ WIRED | `.sort("system:time_start")` present before `tag_consecutive_runs` call; per-ward isolation test PASSED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| CLIM-01 | 03-02, 03-04 | Per-ward, per-calendar-day climatology baseline | ✓ SATISFIED | Live tests passed; REQUIREMENTS.md marked Complete |
| CLIM-02 | 03-02, 03-04 | ±5-day pooling window | ✓ SATISFIED | Live wraparound tests passed |
| CLIM-03 | 03-03, 03-04 | Strict-exceedance heatwave day flagging vs. calendar-day threshold | ✓ SATISFIED | Live tests passed, incl. CR-01 gap regression |
| CLIM-04 | 03-03, 03-04 | ≥3-day consecutive run → event | ✓ SATISFIED | Live tests passed, incl. WR-01 zero-day regression |
| CLIM-05 | 03-01, 03-04 | Zonal reduction, synthetic + real ERA5-Land/real ward asset | ✓ SATISFIED | Live synthetic + real-data smoke test passed |
| CLIM-06 | 03-01/02/03/04 | Test file validates full pipeline, per-stage and composed | ✓ SATISFIED | 34/34 tests passed live, including end-to-end composition |

No orphaned requirements: all six CLIM IDs mapped to phase 3 in REQUIREMENTS.md are claimed by at least one plan's `requirements:` frontmatter.

### Anti-Patterns Found

None. `grep` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER` across `heatwave/zonal.py`, `heatwave/science/heatwave.py`, `heatwave/science/climatology.py`, `heatwave/config.py` returned zero matches. No stub return values, no empty handlers, no hardcoded empty data feeding rendering/output paths (this phase produces no UI).

### Code Review Fix Verification (specific to this task's request)

1. **CR-01 outer-join fix present in code, not just claimed:** Confirmed at `heatwave/science/heatwave.py:74` — `ee.Join.saveFirst("clim_match", outer=True).apply(...)`, with `flag_one_row` using `ee.Algorithms.If(clim_match, ..., None)` to null out `threshold`/`is_hot` rather than drop the row. Matches the review's suggested fix exactly.
2. **CR-01 regression test exercises the fix and passes live:** `test_heatwave_day_flag_keeps_unmatched_ward_day_with_null_threshold` deliberately omits a climatology row for doy 2, asserts the row count stays 3 (would drop to 2 under the old inner join), and asserts doy 2's `threshold`/`is_hot` are null while doy 1/3 are populated. Ran live against real Earth Engine in this verification session and **PASSED**.
3. **WR-01, WR-02, WR-03 fixes are genuinely applied, not just described:**
   - WR-01: `heatwave/science/heatwave.py:189-193` uses the `is not None` ternary (not `or`) for `min_consecutive_days`. Regression test passes `min_consecutive_days=0` and asserts it is honored (PASSED live).
   - WR-02: `heatwave/science/climatology.py:128` keys the output dict by the `ward_id_property` argument itself, not a hardcoded `"ward_id"` literal. Regression test runs both `compute_climatology_thresholds` and `flag_heatwave_days` with `ward_id_property="wardcode"` end-to-end and confirms the join matches (PASSED live).
   - WR-03: `heatwave/config.py:20-33` adds `__post_init__` validation to `ClimatologyConfig`. Both the accepts-valid-config test and the 6-case parametrized rejects-malformed-values test PASSED (credential-free, ran in this session).

Git history independently confirms the claimed commits exist and are properly scoped: `028d1ba` (CR-01), `bddf29c` (WR-01), `9eef7f7` (WR-02), `3a4c806` (WR-03).

### Human Verification Required

None. This phase is pure server-side Earth Engine computation with no UI; every claim was verified by executing the live test suite directly against real GCP credentials rather than relying on SUMMARY.md or REVIEW-FIX.md narration.

### Gaps Summary

No gaps found. All must-haves for CLIM-01 through CLIM-06 are verified against actually-executed code (not just static inspection), and all four review-identified defects (1 critical, 3 warnings) have fixes present in the source and are covered by regression tests that were run live in this verification session, not merely re-stated from SUMMARY.md/REVIEW-FIX.md.

---

_Verified: 2026-09-13_
_Verifier: Claude (gsd-verifier)_
