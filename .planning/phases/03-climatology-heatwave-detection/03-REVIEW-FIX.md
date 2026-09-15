---
phase: 03-climatology-heatwave-detection
fixed_at: 2026-09-13T15:51:05Z
review_path: .planning/phases/03-climatology-heatwave-detection/03-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-09-13T15:51:05Z
**Source review:** .planning/phases/03-climatology-heatwave-detection/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (CR-01 critical; WR-01, WR-02, WR-03 warnings)
- Fixed: 4
- Skipped: 0

Info-level findings IN-01 and IN-02 were explicitly excluded from scope per
the fix request and were not touched.

## Fixed Issues

### CR-01: Inner join in `flag_heatwave_days` silently drops unmatched ward-days, corrupting consecutive-run detection

**Files modified:** `heatwave/science/heatwave.py`, `tests/test_heatwave_detection.py`
**Commit:** 028d1ba
**Applied fix:** Changed `ee.Join.saveFirst("clim_match")` to
`ee.Join.saveFirst("clim_match", outer=True)` in `flag_heatwave_days`, then
updated `flag_one_row` to use `ee.Algorithms.If(clim_match, ..., None)` so a
ward-day with no matching climatology threshold now gets an explicit-null
`threshold`/`is_hot` row instead of being silently dropped -- mirroring the
existing explicit-null pattern already used for `value_property`. Also added
a "Join contract" paragraph to `flag_heatwave_days`'s docstring and a
"Caller contract (CR-01)" paragraph to `detect_heatwave_events`'s docstring
documenting that `tag_consecutive_runs`/`detect_heatwave_events` require a
gapless, one-row-per-calendar-day input per ward, and that `flagged_fc` must
come from `flag_heatwave_days` (or an equivalent gapless source) to satisfy
that invariant -- the review offered "add an explicit precondition check
*or* documented caller contract" as alternatives; a documented contract was
chosen over a runtime gap-detection check to keep the fix narrowly scoped to
the join defect itself, since implementing full calendar-gap detection would
be a materially larger, separately-reviewable change. Added
`test_heatwave_day_flag_keeps_unmatched_ward_day_with_null_threshold`, which
constructs a 3-day ward-daily fixture with a deliberate climatology gap at
doy 2 and asserts the row count stays 3 (not 2) with only doy 2's
threshold/is_hot null -- this test fails against the old inner-join code
(doy 2's row would vanish, dropping the count to 2) and passes against the fix.

### WR-01: `min_consecutive_days=0` is silently overridden by the config default

**Files modified:** `heatwave/science/heatwave.py`, `tests/test_heatwave_detection.py`
**Commit:** bddf29c
**Applied fix:** Changed `min_consecutive_days = min_consecutive_days or settings.climatology.min_consecutive_days`
to the `is not None` ternary form, matching the existing pattern already
used for `window_days` in `climatology.py:89`. Added
`test_heatwave_event_min_consecutive_days_zero_is_not_overridden_by_config`,
which calls `detect_heatwave_events(flagged, min_consecutive_days=0)` on the
existing 14-day verified fixture and asserts `event_id == run_id` exactly
(every run, including the 2-day run that config.yaml's default of 3 would
otherwise demote to -1, now qualifies) -- this test fails against the old
`or`-based code (which would silently apply the config default of 3) and
passes against the fix.

### WR-02: `ward_id_property` is not safely configurable across `climatology.py`/`heatwave.py`

**Files modified:** `heatwave/science/climatology.py`, `tests/test_heatwave_detection.py`
**Commit:** 9eef7f7
**Applied fix:** Changed `compute_climatology_thresholds`'s output feature
dictionary key from the hardcoded literal `"ward_id"` to the
`ward_id_property` argument itself (`ward_id_property: ee.Dictionary(g).get(ward_id_property)`),
so the output property key now always matches what was passed in. Also
updated the function's docstring to describe the output schema in terms of
`ward_id_property` rather than a hardcoded `ward_id` name. Added
`test_climatology_and_heatwave_honor_non_default_ward_id_property`, an
end-to-end test that builds a synthetic ward-daily table keyed on
`"wardcode"` (matching the real ward asset's property, per REWORK-05), runs
it through `compute_climatology_thresholds(..., ward_id_property="wardcode")`,
confirms the output row's key is literally `"wardcode"`, then feeds that
output into `flag_heatwave_days(..., ward_id_property="wardcode")` and
asserts the join actually matches (non-null threshold, correct `is_hot`) --
this test fails against the old hardcoded-`"ward_id"` code (the join would
find no matching climatology row, surfacing as a null threshold thanks to
CR-01's already-applied outer join) and passes against the fix.

### WR-03: `ClimatologyConfig` performs no runtime validation despite being described as "validated config"

**Files modified:** `heatwave/config.py`, `tests/test_heatwave_detection.py`
**Commit:** 3a4c806
**Applied fix:** Added the `__post_init__` validator to `ClimatologyConfig`
exactly as suggested in the review: percentile must be in `(0, 100)`,
`baseline_start_year <= baseline_end_year`, `pooling_window_days >= 0`, and
`min_consecutive_days >= 1`, each raising `ValueError` on violation. Added
`test_climatology_config_accepts_the_real_config_yaml_values` (proves the
real, valid `config.yaml` values still construct successfully) and a
parametrized `test_climatology_config_rejects_malformed_values` covering six
malformed cases (percentile 150, percentile 0, percentile 100,
`baseline_start_year > baseline_end_year`, negative `pooling_window_days`,
`min_consecutive_days=0`), each asserting `ValueError` is raised. These
tests require no Earth Engine credentials (pure Python dataclass
construction) and run unconditionally, unlike the credential-gated tests
elsewhere in the file.

## Skipped Issues

None — all four in-scope findings (CR-01, WR-01, WR-02, WR-03) were fixed.
IN-01 and IN-02 were out of scope by explicit instruction and were not
attempted.

## Verification

Full test suite run after each fix inside an isolated git worktree
(`.venv/Scripts/python.exe -m pytest -q`), following the existing
skip-gated pattern (no mocking introduced; new tests exercise real Earth
Engine calls via `_REQUIRES_CREDENTIALS`, except the WR-03 config-validation
tests, which are pure Python and need no credentials):

- Baseline (before any fix): 5 passed, 34 skipped
- After CR-01: 5 passed, 35 skipped
- After WR-01: 5 passed, 36 skipped
- After WR-02: 5 passed, 37 skipped
- After WR-03: 12 passed, 37 skipped (7 new credential-free config tests ran and passed)

No test regressions at any step. Live-credential-gated tests remain skipped
in this environment (no `keys/service_account.json` or `EE_SA_JSON`) and
will exercise the fixes' logic once run with real GCP credentials.

---

_Fixed: 2026-09-13T15:51:05Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
