---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 09
subsystem: forecast-evaluation
tags: [real-data, baselines, phase-gate, EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05]
requires: [10-08]
provides: [docs/forecast/BASELINES_VALIDATION.md, tests/forecast/test_forecast_baselines_frozen.py]
key-files:
  created:
    - tests/forecast/test_forecast_baselines_frozen.py
    - docs/forecast/BASELINES_VALIDATION.md
key-decisions:
  - "Real run output is the official bar: damped_persistence is best at leads 1-2, trend_season at leads 3-6"
requirements-completed: [EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05]
status: tasks 1-2 complete; Task 3 (push / PR / CI) PENDING user approval
completed: 2026-10-08
---

# Phase 10 Plan 09: Real-data checks, official baseline scores, phase gate Summary

Real frozen-data magnitude tests pass first time, the real run (B=1000, six leads) produced and committed BASELINES_VALIDATION.md, and the phase gate is green with zero test runs and no lock opened. Push / PR / CI is pending the user checkpoint.

## Commits
- acd2157: test(10-09) real-data frozen magnitude checks (9 tests, all `frozen` + `slow`)
- 0f00d1c: docs(10-09) official BASELINES_VALIDATION.md (run 20261008T214852Z_b82dc7bd)

## Task 1: frozen tests
`pytest tests/forecast/test_forecast_baselines_frozen.py -q`: 9 passed in 272 s (not skipped). No tolerance was changed. Validation rows 1,520,074 at leads 1 and 6; all Briers within 0.002 of research; best baseline damped_persistence (L1) and trend_season (L6); persistence BSS L1 > L6; lead-1 damped vs recent BSS in [0.07, 0.10] with week CI inside the specified bounds; climatology mean p in [0.085, 0.093] vs observed rate in [0.150, 0.158]; small wards 3,086; real log untouched.

## Task 2: real run
Default call `scripts/forecast_baselines.py` (B=1000, leads 1-6, train diagnostics for leads 1 and 6). Doc checks: caption present (1), "locked and unscored" 1, "accuracy" 0, generated marker 1, test runs 0 in the locked note.

### Headline validation Brier (same as research to 4 d.p.)
| lead | climatology | recent | persistence | damped | trend_season | best |
|---|---|---|---|---|---|---|
| 1 | 0.1376 | 0.1365 | 0.1306 | 0.1249 | 0.1330 | damped_persistence |
| 2 | 0.1376 | 0.1365 | 0.1355 | 0.1322 | 0.1331 | damped_persistence |
| 3 | 0.1376 | 0.1365 | 0.1364 | 0.1345 | 0.1331 | trend_season |
| 4 | 0.1376 | 0.1365 | 0.1383 | 0.1369 | 0.1331 | trend_season |
| 5 | 0.1376 | 0.1365 | 0.1376 | 0.1365 | 0.1331 | trend_season |
| 6 | 0.1376 | 0.1365 | 0.1370 | 0.1356 | 0.1332 | trend_season |

Key BSS vs recent_climatology (week-block 95% CI): lead 1 damped 0.0852 [0.0418, 0.1290] (year-block [0.0255, 0.1411]); lead 1 persistence 0.0435 [0.0083, 0.0786]; lead 1 trend 0.0254 [0.0105, 0.0400]; lead 2 damped 0.0313 [0.0083, 0.0555]; lead 2 trend 0.0252 [0.0109, 0.0388]; lead 6 trend 0.0246 [0.0107, 0.0387], lead 6 damped 0.0069 [-0.0144, 0.0303] (CI spans zero). BSS vs climatology lead 1: damped 0.0922 [0.0464, 0.1355]. MAM lead 1: best baseline BSS 0.1661 [0.0864, 0.2373]. Persistence decay check passes (0.0507 at L1 vs 0.0038 at L6); not strictly monotone (warning only).

### Phase gate
1. Full forecast suite: 577 passed, 1 warning, 806 s.
2. Quick loop `-m "not frozen and not slow"`: 485 passed, 92 deselected, 59.12 s pytest time (62.7 s wall with startup). Under 60 s but with about 1 s headroom; the nine new tests are all slow. Next phase must mark new quick tests slow or trim.
3. v1 tests (test_config, test_requirements, test_local_pipeline): 59 passed.
4. Real log: `count_test_runs == 0`; 55 records, all `score` events (40 validate, 15 train), no test split, no refused record; real TEST_LOCK.json absent; docs/forecast/PREREGISTRATION.md absent and untracked (only PREREGISTRATION.template.md exists).
5. `git diff --stat main -- config.yaml heatwave/config.py tests/test_config.py`: empty.

## Deviations from Plan
**1. [Rule 3 - blocking] First real run was killed.** The first launch ran under a 30-minute background limit and was stopped partway (during lead 3 validation). It left an orphan run folder `20261008T212900Z_b82dc7bd` with RUN_MANIFEST status "running" and 15 validate/train `score` records in the real append-only log (the log cannot be edited without breaking its hash chain). I did not delete anything and re-ran from scratch with a 2 h limit; the clean run is `20261008T214852Z_b82dc7bd` (about 20 min). The extra records are only train/validate scores, so the zero-test-run result is unaffected. The orphan folder is outside the repo and can be removed by the user.

## Known Stubs
None.

## Pending: Task 3 (checkpoint:decision)
Push `gsd/phase-10-baselines`, open a PR and watch CI: NOT done, awaiting user choice (push / hold).

## Self-Check: PASSED
Test file, docs file, commits acd2157 and 0f00d1c verified.
