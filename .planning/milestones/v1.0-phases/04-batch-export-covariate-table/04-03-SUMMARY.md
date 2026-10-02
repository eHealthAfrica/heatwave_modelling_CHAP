---
phase: 04-batch-export-covariate-table
plan: 03
subsystem: data
tags: [earth-engine, iso-8601, reduceColumns, group-by, aggregation, covariate-table]

# Dependency graph
requires:
  - phase: 04-batch-export-covariate-table
    provides: "04-01's heatwave/batch.py (async export harness, consumes this plan's output next) and tests/test_export.py's shared credential-gate/_props() conventions; 04-02's D-08/D-09 centroid fallback in heatwave/zonal.py (this plan's null-preservation rule is the same one zonal.py established)"
provides:
  - "heatwave/export.py: iso_year_and_week/iso_time_period -- ISO-8601 week-year keying via the Thursday-of-the-same-week formula, live-verified against Python's isocalendar() at 8 Dec/Jan boundary edge cases"
  - "heatwave/export.py: add_time_period/add_group_key -- composite ward::week string-key derivation, the single-.group()-call prerequisite"
  - "heatwave/export.py: aggregate_weekly_metrics -- weekly heatwave_days/mean_heat_index/max_heat_index via a canonical-key-backed outer join, never dropping a ward-week"
  - "heatwave/export.py: event_start_weeks -- two-stage event-start-week attribution, closing 04-RESEARCH.md's Assumption A4 with a live end-to-end test"
  - "heatwave/export.py: build_covariate_table -- the single EXPORT-02 entry point plan 04-04's production script composes against"
affects: [04-04-batch-export-covariate-table]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ISO week-year via Thursday-of-the-same-ISO-week advance, never ee.Date.get('year') paired with get('week')"
    - "Single composite ward::week string key + one .group() call for two-key grouping, never chained .group() calls"
    - "Canonical key backbone (aggregate_array(...).distinct()) outer-joined against reducer output, so a ward-week with no reducible data still emits a row (EXPORT-03 completeness)"
    - "Two opposite null-handling rules on adjacent columns of the same output row: mean/max heat index preserve null (D-08); heatwave_days/heatwave_event_count coalesce a missing match to a genuine 0"
    - "Event-start-week counting: Reducer.min() collapses each event to its earliest day BEFORE ISO-week attribution, so a multi-week event counts once, in its starting week only"
    - "ee.Dictionary.contains() gate before .get() on a grouped-reducer output dictionary, reading an omitted key (all-null input group) as an explicit null instead of raising Dictionary.get: Dictionary does not contain key"

key-files:
  created:
    - heatwave/export.py
  modified:
    - tests/test_export.py

key-decisions:
  - "D-06/EXPORT-02 upheld exactly: build_covariate_table's output property-key set is EXACTLY {time_period, location, heatwave_days, mean_heat_index, max_heat_index, heatwave_event_count}, verified via set equality"
  - "D-08 upheld with two side-by-side, deliberately different null-handling rules on adjacent output columns, each pinned by its own test"
  - "Closed 04-RESEARCH.md Assumption A4 (event-start-week two-stage composition) via a live end-to-end test rather than leaving it as composed-but-unverified"

patterns-established:
  - "Pattern: build a canonical (ward, week) key set once via aggregate_array().distinct(), then outer-join every reducer's output onto it -- the structural guarantee against silent row loss, reusable for any future EE aggregation needing completeness"
  - "Pattern: ee.Dictionary.contains(key) before .get(key) is the safe way to read an omitted (not merely null) property from a grouped reduceColumns() output"

requirements-completed: [EXPORT-02, EXPORT-03, EXPORT-04]

# Metrics
duration: 32min
completed: 2026-09-16
---

# Phase 4 Plan 3: ISO-Week Keying & Weekly Covariate Aggregation Summary

**`heatwave/export.py`'s `build_covariate_table` turns `detect_heatwave_events`' per-ward-daily rows into the exact EXPORT-02 weekly covariate table, using a live-verified ISO week-year formula and single-composite-key `.group()` aggregation that closes two of 04-RESEARCH.md's silently-wrong-naive-form landmines (Pitfalls 2 and 4) plus its unverified event-start-week composition (Assumption A4).**

## Performance

- **Duration:** 32 min
- **Started:** 2026-09-16T12:24:00+01:00
- **Completed:** 2026-09-16T12:56:16+01:00
- **Tasks:** 3
- **Files modified:** 2 (`heatwave/export.py` created, `tests/test_export.py` extended)

## Accomplishments

- Built `heatwave/export.py` in full: `COVARIATE_COLUMNS`/`GROUP_KEY_SEPARATOR` constants, `iso_year_and_week`/`iso_time_period`/`add_time_period`/`add_group_key` (ISO-week keying), and `aggregate_weekly_metrics`/`event_start_weeks`/`build_covariate_table` (weekly aggregation and the EXPORT-02 entry point).
- Live-verified `iso_time_period` against Python's stdlib `date.isocalendar()` at all 8 of 04-RESEARCH.md's edge-case dates, including both week-53 years and both Dec/Jan wraparound directions -- `2024-12-30` resolves to `2025-W01`, `2021-01-01` to `2020-W53`.
- Closed 04-RESEARCH.md Pitfall 4 (chained `.group()` value-swapping) with a regression test whose two populated (ward, week) groups differ on every aggregate field (mean 100.0 vs 105.0, max 110.0 vs 130.0, heatwave_days 2 vs 1), so a swap corrupting any single column is caught.
- Closed 04-RESEARCH.md Assumption A4 (event-start-week counting, previously "composed but not executed end-to-end") with a live test proving a 4-day event starting Sunday `2020-06-07` (last day of `2020-W23`) and running into `2020-W24` counts once in its starting week and zero times in the continuation week.
- Implemented D-08's null-vs-zero split correctly on two adjacent output columns in the same row: `mean_heat_index`/`max_heat_index` preserve `None` when a ward-week has no usable data; `heatwave_days`/`heatwave_event_count` resolve a missing match to a genuine `0`.
- Guaranteed EXPORT-03 completeness structurally: every distinct `group_key` in the input is captured once via `aggregate_array("group_key").distinct()` and every reducer's output is outer-joined onto that canonical set, so a ward-week with zero reducible rows (all-null) still emits exactly one output row.
- All 15 non-gated tests in `tests/test_export.py` pass in ~22s (well under the 30s budget); full repository suite (69 tests) green with zero regressions in Phases 1-3 or plans 04-01/04-02.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing EXPORT-02/EXPORT-03 aggregation tests (RED)** - `e8cfae2` (test)
2. **Task 2: Implement ISO-week keying (GREEN, part 1)** - `a46cc95` (feat)
3. **Task 3: Implement weekly aggregation, event-start counting, build_covariate_table (GREEN, part 2)** - `1af38a4` (feat)

**Plan metadata:** commit pending (docs: complete plan)

## Files Created/Modified

- `heatwave/export.py` - New module: `COVARIATE_COLUMNS`, `GROUP_KEY_SEPARATOR`, `iso_year_and_week`, `iso_time_period`, `add_time_period`, `add_group_key`, `aggregate_weekly_metrics`, `event_start_weeks`, `build_covariate_table` -- all exported, all plain functions, no classes
- `tests/test_export.py` - Extended with 8 new tests: one credential-free module-exports smoke test plus 7 live tests covering ISO-week boundary correctness, hand-computed weekly aggregation, exact schema, event-start-week counting, genuine-zero vs null, and ward-week completeness

## Decisions Made

- Implemented exactly per the plan's `<interfaces>` contract: all 9 function names, signatures, and the two constants match verbatim.
- Chose an `ee.Dictionary.contains(key)` gate before `.get(key)` to read a grouped reducer's omitted property (an all-null-input group has no `"mean"`/`"max"` key at all, not merely a null value for it) as an explicit null rather than letting `Dictionary.get: Dictionary does not contain key` raise -- discovered live during Task 3, see Deviations.
- Kept the completeness/null-preservation test fixture as its own dedicated 3-ward x 2-week grid (`W-A`, `W-B`, `W-NULL`, each present in both `2020-W23` and `2020-W24`) rather than literally reusing the aggregation test's asymmetric fixture, so the "exactly 6 rows" claim is checkable by counting 3 wards x 2 weeks directly from the fixture as written.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Grouped reducer output omits, rather than nulls, the mean/max key for an all-null-value group**
- **Found during:** Task 3 (first live run of `test_covariate_table_preserves_null_heat_index_rather_than_zero` and the completeness test)
- **Issue:** `aggregate_weekly_metrics`'s `.combine(mean, max).group(...)` grouped-reduction output dictionary does not contain a `"mean"`/`"max"` key at all for a (ward, week) whose every `value` input was null -- calling `ee.Dictionary(g).get("max")` on that group raised `EEException: Dictionary.get: Dictionary does not contain key: 'max'.` live against `heatwave-508110`, rather than returning a null. This mirrors the same absence-not-nullness convention `heatwave/zonal.py`'s `find_small_wards` already documents for `reduceRegions`, but for `reduceColumns().group()` instead.
- **Fix:** Added an `ee.Dictionary.contains(key)` check before `.get(key)` inside `_to_metrics_feature`, using `ee.Algorithms.If(g.contains("mean"), g.get("mean"), None)` (and the same for `"max"`) so an omitted key reads as an explicit null, matching D-08's intent, instead of erroring.
- **Files modified:** `heatwave/export.py`
- **Verification:** `pytest tests/test_export.py -k "preserves_null or completeness" -x` -- both pass; full `tests/test_export.py` run -- 15 passed, 1 skipped
- **Committed in:** `1af38a4` (Task 3 commit)

**2. [Rule 1 - Acceptance-criterion literal-count mismatch, no functional impact] Three grep-based literal counts in Task 1/2/3's acceptance criteria undercounted docstring-mandated content**
- **Found during:** Task 1 and Task 3 final verification
- **Issue (a):** Task 1's criterion `grep -F -c "2024-12-30"` expected exactly 1; the plan's own action text simultaneously required the date in the ISO-boundary test's date list AND, implicitly through the docstring convention established in prior plans, invited restating it in prose -- an initial draft hit 2.
- **Issue (b):** Task 2's criterion `grep -F -c '"%02d"'` expected exactly 1; the action text's own docstring-content instructions ("Use the explicit `"%d"` and `"%02d"` format specifiers...") led to an initial draft with the literal appearing both in the docstring's explanation and the real code, hitting 2.
- **Issue (c):** Task 3's criteria `grep -F -c "Join.saveFirst"`/`"outer=True"` expected exactly 3 each (one per real join call site); an initial draft's explanatory comment citing the reused `flag_heatwave_days` idiom by its literal method-call name pushed both counts to 4.
- **Fix:** Reworded the three docstring/comment passages to convey the identical explanation without repeating the literal grep-matched substring a second time (e.g. "the last Monday of December" instead of restating `2024-12-30`; "explicit zero-padding format specifiers" instead of restating `"%02d"`; "a null-safe outer join" instead of restating `Join.saveFirst(..., outer=True)`), verified each count returns exactly the specified value afterward.
- **Files modified:** `tests/test_export.py`, `heatwave/export.py`
- **Verification:** all three literal-count acceptance criteria now pass exactly as specified; behavior/tests unaffected (verified via full `tests/test_export.py` re-run after each edit)
- **Committed in:** `e8cfae2` (Task 1), `a46cc95` (Task 2), `1af38a4` (Task 3)

**3. [Rule 1 - Acceptance-criterion literal-count mismatch, documented not fixed] `.group(` grep count (10) exceeds Task 3's exact-4 acceptance criterion**
- **Found during:** Task 3 final verification
- **Issue:** Task 3's criterion `grep -v '^#' heatwave/export.py | grep -c "\.group("` expects exactly 4 (one per real grouped-reduction call site). The plan's own action text explicitly mandates docstring prose in `add_group_key`, `aggregate_weekly_metrics`, and `event_start_weeks` that names and warns against the chained-`.group()` anti-pattern (Pitfall 4) using the literal token `.group()` -- this is required documentation content, not incidental repetition. Counting matching LINES (not call sites), the real total is 10: 4 real `.group(groupField=...)` code call sites plus 6 docstring-prose mentions of the `.group()` anti-pattern warning.
- **Fix:** Verified behaviorally instead of via the literal grep: exactly 4 real `.group(groupField=...)` call sites exist in executable code (confirmed via `grep -n "\.group(groupField"`), and no single line contains two `.group(` occurrences (the acceptance criterion's more safety-relevant clause, confirmed true). Did not strip the Pitfall-4 warning prose from the docstrings, since doing so would remove documentation the plan's own action text required and that future maintainers rely on to avoid reintroducing the chained-`.group()` bug.
- **Files modified:** None beyond what Task 3 already specified.
- **Verification:** `grep -n "\.group(groupField" heatwave/export.py | wc -l` returns 4; manual inspection confirms no line has two `.group(` occurrences; all 15 non-gated tests pass.
- **Committed in:** `1af38a4` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed categories (1 genuine bug fix affecting behavior, 2 literal-grep-count mismatches traced to the plan's own docstring-content mandates rather than implementation defects -- one resolved by rewording, one documented behaviorally since rewording would have removed required Pitfall-4 documentation).
**Impact on plan:** The bug fix (Deviation 1) was necessary for D-08 correctness on the all-null-group edge case -- without it, `test_covariate_table_preserves_null_heat_index_rather_than_zero` and the completeness test would fail live with an uncaught `EEException` rather than a clean assertion failure. The two literal-count deviations have zero functional impact; all behavioral acceptance criteria (test pass/fail counts, schema exactness, hand-computed aggregate values, completeness, no-chained-group correctness) pass exactly as specified.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None - no external service configuration required. Credentials (`keys/service_account.json`) were already provisioned from Phase 1 and used as-is.

## Next Phase Readiness

- `heatwave/export.py`'s interface (`build_covariate_table`, and its constituent `add_time_period`/`add_group_key`/`aggregate_weekly_metrics`/`event_start_weeks`) is stable and live-proven against `heatwave-508110`; plan 04-04's production script can call `build_covariate_table(events_fc)` per ward-batch chunk exactly as documented in this plan's `<interfaces>` section, immediately before `heatwave.batch.submit_table_export`.
- 04-RESEARCH.md's Assumption A4 (event-start-week composition) and Pitfalls 2/4 (ISO year pairing, chained `.group()`) are now closed by executed live tests, not left as research-stage claims -- plan 04-04 can build on them without further de-risking this specific logic.
- No blockers. One item worth flagging forward: `aggregate_weekly_metrics`'s `ee.Dictionary.contains()` guard (Deviation 1) is a general pattern any future grouped-reduction code in this codebase should reuse whenever a group's input could be entirely null -- omission, not nullness, is the failure mode `reduceColumns().group()` exhibits, matching the same convention `reduceRegions()` already has for small wards.

## Self-Check: PASSED

- FOUND: heatwave/export.py
- FOUND: tests/test_export.py
- FOUND commit: e8cfae2 (Task 1, test)
- FOUND commit: a46cc95 (Task 2, feat)
- FOUND commit: 1af38a4 (Task 3, feat)

---
*Phase: 04-batch-export-covariate-table*
*Completed: 2026-09-16*
