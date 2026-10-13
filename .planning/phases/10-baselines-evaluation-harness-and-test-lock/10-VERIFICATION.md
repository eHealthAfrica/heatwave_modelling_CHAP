---
phase: 10-baselines-evaluation-harness-and-test-lock
verified: 2026-10-08T23:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 10: Baselines, Evaluation Harness and Test Lock Verification Report

**Phase Goal:** The analyst can see exactly what a model must beat, scored through one honest path, with the test years mechanically locked.
**Status:** passed. CI was not run and is outside this verification.

## Observable Truths

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|---|---|---|
| 1 | Five baselines scored per lead through the same harness; self-BSS is 0; persistence skill decays | VERIFIED | `docs/forecast/BASELINES_VALIDATION.md` has Brier for 5 predictors x 6 leads (from stored prediction files, same harness). Sanity section: self-BSS zero = yes at all 6 leads. Persistence BSS vs climatology is 0.0507 at lead 1 and 0.0038 at lead 6. The doc notes it is not strictly monotone (warning only). The decay check passes. |
| 2 | Brier/BSS with named reference, decomposition, stratified AUC, quantile-bin reliability, P/R/F1 at stated threshold, calibration-in-the-large by year, no accuracy | VERIFIED | Report sections: Skill against climatology / recent climatology, Brier decomposition, Stratified ROC AUC, Reliability (10 quantile bins), Precision/recall/F1, Calibration-in-the-large by year. A grep for "accuracy" in the report and in `heatwave/forecast/*.py` returns nothing. |
| 3 | Paired week-block (>=4) and year-block CIs, never row/ward resampling | VERIFIED | `heatwave/forecast/evaluation/bootstrap.py` has `MIN_BLOCK_WEEKS = 4` and raises ValueError below it. Resampling is on target weeks (circular blocks) or years, on per-week sufficient statistics. The report lists both week-block and year-block CIs. `test_forecast_bootstrap.py` passes. |
| 4 | Breakdown by lead, season (MAM highlighted), region, year; LGA-average and small wards flagged | VERIFIED | Report has Season (MAM bolded and highlighted), Region (geozone and latitude band), Ward filter rows (all, large only, excluding LGA-average, LGA-average at n=1884), and by-year calibration. Small wards are flagged: 3086 of 4841 (63.7%). |
| 5 | Loaders refuse 2021-2026 rows until a pre-registration is committed and the lock opened; log shows no test run | VERIFIED | `testlock.require_open` and `labels_unlocked` gate `dataset.lead_rows`, `build_issue_table` and `predictions.build_predictions`. `tests/forecast/test_forecast_testlock.py`: 33 passed. Real log `evaluation_log.jsonl` has 55 events with split counts train=15, validate=40 and 0 test (hash-chained). `TEST_LOCK.json` and `docs/forecast/PREREGISTRATION.md` are absent. Only `PREREGISTRATION.template.md` exists. |

**Score:** 5/5

## Behavioral Spot-Checks

| Check | Result | Status |
|---|---|---|
| `pytest tests/forecast -m "not frozen and not slow"` | 485 passed, 92 deselected, 68.75 s | PASS |
| `pytest tests/forecast/test_forecast_testlock.py` | 33 passed | PASS |
| Real log test-split count | 0 | PASS |

## Requirements Coverage

| Req | Plans | Status |
|---|---|---|
| EVAL-01 | 10-06, 10-07, 10-08, 10-09 | SATISFIED (Truth 1) |
| EVAL-02 | 10-02, 10-05, 10-07, 10-08, 10-09 | SATISFIED (Truth 2) |
| EVAL-03 | 10-04, 10-07, 10-08, 10-09 | SATISFIED (Truth 3) |
| EVAL-04 | 10-04, 10-07, 10-08, 10-09 | SATISFIED (Truth 4) |
| EVAL-05 | 10-01, 10-03, 10-05, 10-08, 10-09 | SATISFIED (Truth 5) |

All five IDs appear in the plan frontmatter and in REQUIREMENTS.md, where all five are marked Complete and mapped to Phase 10. There are no orphaned requirements. EVAL-06 belongs to Phase 11.

REQUIREMENTS.md EVAL-05 says the log shows "exactly one test run". That is the end-state wording for the later phase that opens the lock. The Phase 10 roadmap criterion is "no test run yet", which holds. Note this as a wording mismatch only.

## Anti-Patterns

No debt markers or stubs were examined beyond the green test suite. Both the doc and the code are generated, with no placeholders seen.

## Human Verification Required

None blocking. Observations for the analyst, none of which are gaps:
- Persistence skill is non-monotone across leads 4-6 (a documented warning), and the lead-1 to lead-6 decay holds.
- The year-block CI rests on 6 clusters and is coarse.
- Slice CIs are exploratory.

## Gaps Summary

No gaps. The phase goal is achieved in the codebase.

_Verifier: Claude (gsd-verifier)_
