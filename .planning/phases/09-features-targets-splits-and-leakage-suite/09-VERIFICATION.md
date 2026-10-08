---
phase: 09-features-targets-splits-and-leakage-suite
verified: 2026-10-07T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 9 Verification Report

**Goal:** Leakage-safe features, lead-aligned targets and time-honest splits exist and are proven leak-free before any model is trained.
**Re-verification:** No. CI not run (outside scope).

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Lead 1-6 target aligned; rows carry last_obs_week, issue_date, target_week, lead_weeks, effective_days_ahead | VERIFIED | `heatwave/forecast/targets.py`: `lead_label` gathers by integer shift k and never fills past the end; `timing_fields` computes issue_date = Sunday + latency and effective_days_ahead = 7k-6-latency. `dataset.py` writes all columns. `test_g_target_alignment` merges rows to the raw panel for every lead and asserts target_week_index - last_obs_week_index == lead. |
| 2 | As-of features use data up to the last observed week; fit range recorded; no raw year index | VERIFIED | `registry.py` forbids year/ward-id/location names by regex and `check_registry` enforces it. Climatology exposes `fit_range()`. `test_d_registry_guard` passes. Truncation and poison tests pass on real registry features. |
| 3 | Leakage suite passes on real features and fails on injected leaks | VERIFIED | `leakage.py` has truncation, poison, row-level truncation, train-only statistics and registry checks. `test_forecast_leakage.py` mutation tests inject lead-1, centered window, full mean, climatology fit past end (also by one year) and `max_lookahead=1`, and assert LeakageError. 394 non-frozen tests pass. The 6 frozen leakage tests pass on real data (60 s). |
| 4 | Target-week splits with embargo; expanding CV folds by week_start cutoffs | VERIFIED | `splits.py` assigns splits by target-week index from Monday week_start cutoffs. `forecast.yaml` sets embargo_weeks 14. `cv_folds` uses train_max_target_exclusive = start - embargo and climatology_end = fold start. `test_f_split_integrity` and `test_f_cv_fold_integrity` pass, including week 2020-W53 landing in validate. |
| 5 | Pre-model report: prevalence by year/region/era plus measured ERA5-Land delay note | VERIFIED | `docs/forecast/DATA_REPORT.md` has provenance (parquet sha256, run id), prevalence by split, era, region and year, and the regime-shift warning (8.4% / 15.4% / 21.5%). It also has the operational note of about 9 days delay, stated as informational with no live query and latency_days = 0. `report.py` and `test_forecast_report.py` pass. |

## Requirements Coverage

| Req | Status | Evidence |
|-----|--------|----------|
| FEAT-01 | SATISFIED | Truth 1 |
| FEAT-02 | SATISFIED | Truth 1 (issue_date uses latency_days) |
| FEAT-03 | SATISFIED | Truth 2 |
| FEAT-04 | SATISFIED | Truth 3 |
| FEAT-05 | SATISFIED | Truth 4 |
| FEAT-06 | SATISFIED | Truth 5 |

No orphaned requirements. REQUIREMENTS.md maps FEAT-01..06 to Phase 9 only.

## Behavioral Spot-Checks

| Check | Result |
|-------|--------|
| `pytest tests/forecast -q -m "not frozen"` | 394 passed, 19 deselected (94 s) |
| `pytest tests/forecast/test_forecast_leakage_frozen.py -m frozen` | 6 passed (61 s) |

## Anti-Patterns

No TBD/FIXME/XXX debt markers or stub returns were observed in the files read (targets, splits, leakage). I did not run a full-file grep.

## Notes (non-blocking)

- The report shows a large regime shift (prevalence 8.4% train, 15.4% validate, 21.5% test). It is documented for later phases and is not a Phase 9 defect.
- The remaining frozen tests (about 13) were not re-run. The leakage-frozen set was run.
- CI is untested, as agreed.

## Human Verification Required

None.
