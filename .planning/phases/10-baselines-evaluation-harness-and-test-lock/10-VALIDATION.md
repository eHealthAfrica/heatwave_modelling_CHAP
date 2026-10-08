---
phase: 10
slug: baselines-evaluation-harness-and-test-lock
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-10-08
---

# Phase 10 — Validation Strategy

> Per-phase validation contract. Derived from `10-RESEARCH.md` § Validation Architecture and `10-CONTEXT.md` "Resolved after phase research".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 (`pyproject.toml`, markers `frozen` and `slow`) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/forecast -q -m "not frozen and not slow"` (target < 60 s: no real git subprocesses, no real-panel loading) |
| **Full forecast suite** | `.venv/Scripts/python.exe -m pytest tests/forecast -q` (frozen + slow, local) |
| **Phase gate** | full forecast suite green; then `scripts/forecast_baselines.py` on the real data; then a read-only check that the real `evaluation_log.jsonl` has zero test runs and no `PREREGISTRATION.md` is committed |

---

## Sampling Rate

- **After every task commit:** run the task's new test module with `-m "not frozen and not slow"`.
- **After every plan wave:** run the quick command plus the edited Phase 9 modules.
- **Before verify:** the phase gate is green, and CI is green after a user-approved push.
- **Max feedback latency:** 60 s, for the quick loop only.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-T1 | 10-01 | 1 | EVAL-05 | T-10-08 | strict validator rejects bad/unknown/missing evaluation keys, block_weeks < 4 | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_config.py -q -m "not frozen and not slow"` | exists, edit | ⬜ pending |
| 10-01-T2 | 10-01 | 1 | EVAL-05 | T-10-01..06 | lock closed by default (no git call), refusals logged, tamper re-closes, hash-chained log, tests isolated from real log | unit (stub git) | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_testlock.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-01-T3 | 10-01 | 1 | EVAL-05 | T-10-02, T-10-07 | real git: modified/untracked/staged-only/placeholder/config-drift refused; CRLF clean; template only; real log 0 test runs | slow + frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_testlock.py -q` | W0 new | ⬜ pending |
| 10-02-T1 | 10-02 | 1 | EVAL-02 | T-10-09, T-10-10 | Brier/BSS vs sklearn, tie-safe Murphy, AUC stratified only, P/R/F1 with threshold, CITL by year, no accuracy | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_metrics.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-02-T2 | 10-02 | 1 | EVAL-02 | T-10-09 | week sufficient stats equal point metrics at unit weights; empty replicate -> NaN | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_metrics.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-03-T1 | 10-03 | 2 | EVAL-05 | T-10-12..14 | lead_rows(test) raises + logs; issue table blanks test labels + logs; no bypass param | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_dataset.py -q -m "not frozen and not slow"` | exists, edit | ⬜ pending |
| 10-03-T2 | 10-03 | 2 | EVAL-05 | T-10-12 | Phase 9 regression with allow_test_rows fixture | unit + frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_dataset.py tests/forecast/test_forecast_leakage.py tests/forecast/test_forecast_report.py -q -m "not slow"` | exists, edit | ⬜ pending |
| 10-04-T1 | 10-04 | 2 | EVAL-03 | T-10-17, T-10-18 | week/year resampling only, block >= 4, paired self-CI {0}, spatial-correlation invariant, brute-force equality, seed reproducible | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_bootstrap.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-04-T2 | 10-04 | 2 | EVAL-04 | T-10-16 | season boundaries (W53/Dec), MAM highlight, lat bands = report, year, LGA-average + small flags; real small-ward count 3,086 | unit + frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_slices.py -q -m "not slow"` | W0 new | ⬜ pending |
| 10-05-T1 | 10-05 | 2 | EVAL-02 | T-10-19, T-10-21, T-10-22 | schema/dtypes/metadata round trip, safe run-folder paths, atomic write, no pickle | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_predictions.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-05-T2 | 10-05 | 2 | EVAL-05, EVAL-02 | T-10-20, T-10-23 | test-split prediction load refused + logged (incl. tampered metadata); strict alignment | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_predictions.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-06-T1 | 10-06 | 3 | EVAL-01 | T-10-24, T-10-25 | climatology/recent/persistence: p in [0,1] no NaN on lead_row_index rows; train-only (poison) and as-of (poison_future); hand-computed persistence | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_baselines.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-06-T2 | 10-06 | 3 | EVAL-01 | T-10-24, T-10-26 | damped/trend train-only fits; aggregated trend fit == row-level; registry == config names | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_baselines.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-07-T1 | 10-07 | 3 | EVAL-02, EVAL-03 | T-10-28..30 | harness Brier == metrics, BSS(ref,ref)=0 CI {0}, AUC stratified only, threshold reported, one score log record per predictor | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_harness.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-07-T2 | 10-07 | 3 | EVAL-01, EVAL-04 | T-10-30, T-10-31 | slice tables + flags + MAM highlight, empty slice NaN, best baseline argmin, decay check, import isolation; Wave 3 quick-loop timing < 60 s | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_harness.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-08-T1 | 10-08 | 4 | EVAL-01..04 | T-10-10 | caption line, locked note, all CONTEXT tables, no accuracy, marker last | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_baselines_report.py -q -m "not frozen and not slow"` | W0 new | ⬜ pending |
| 10-08-T2 | 10-08 | 4 | EVAL-01..05 | T-10-32..35 | synthetic end-to-end run; zero test runs/refusals in log; path refusals | slow (subprocess) | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_baselines_script.py -q` | W0 new | ⬜ pending |
| 10-09-T1 | 10-09 | 5 | EVAL-01, EVAL-03 | T-10-24 | real Brier within +-0.002 of research; best baseline damped (L1) / trend (L6); lead-1 BSS CI ~[0.04, 0.13] | frozen + slow | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_baselines_frozen.py -q` | W0 new | ⬜ pending |
| 10-09-T2 | 10-09 | 5 | EVAL-01..05 | T-10-36, T-10-37, T-10-39 | real run committed; full suite green; quick loop < 60 s; real log 0 test runs; no PREREGISTRATION.md / TEST_LOCK.json | phase gate | `.venv/Scripts/python.exe -m pytest tests/forecast -q` | n/a | ⬜ pending |
| 10-09-T3 | 10-09 | 5 | - | T-10-38 | push/CI only after user approval | checkpoint | `manual decision` | n/a | ⬜ pending |

**Requirement → test map (from research):**
- **EVAL-01:**
  - p in [0, 1] with no NaN on scored rows, and row keys equal `lead_row_index`;
  - train-only fits are unchanged when validation labels are poisoned;
  - `recent_climatology` is invariant under `poison_future` after the origin;
  - persistence equals a hand-computed conditional frequency;
  - the trend aggregated fit equals the row-level fit;
  - the best baseline is the argmin Brier, BSS(ref, ref) = 0, and persistence skill at lead 1 > lead 6;
  - `@frozen @slow`: real Brier within tolerance (for example damped persistence at lead 1 in [0.123, 0.127]), best baseline is damped persistence at lead 1 and trend_season at lead 6.
- **EVAL-02:**
  - Brier and BSS against hand cases and `sklearn.brier_score_loss`;
  - Murphy identity is exact for a 2-valued predictor, with residual < 1e-3 for a continuous one, and tie-safe bins;
  - AUC is stratified only, with no pooled field;
  - the string "accuracy" appears nowhere in the module or the report;
  - P/R/F1 carry their threshold;
  - the predictions parquet round-trips with dtypes and metadata;
  - the harness imports no baseline or model.
- **EVAL-03:**
  - the resampling unit is weeks or years, and a block < 4 is rejected;
  - a perfectly correlated synthetic panel gives the same CI as a single site;
  - paired BSS(ref, ref) CI is exactly {0};
  - results are seed-reproducible;
  - the sufficient-statistics replicate equals a brute-force replicate;
  - `@frozen @slow`: the lead-1 BSS CI of damped persistence vs recent climatology is roughly [0.04, 0.13] at B = 200.
- **EVAL-04:**
  - season masks are correct at W53 and December boundaries, with MAM highlighted;
  - region and latitude bands match the `report` constants;
  - year slice;
  - LGA-average and small-ward flags, with a "large wards only" row;
  - `@frozen`: the small-ward count is 3,086.
- **EVAL-05:**
  - with the lock closed, `lead_rows(split="test")` and the prediction loader raise `TestLockError` and log the attempt;
  - `build_issue_table` blanks test labels;
  - with the lock open (tmp git repo, committed pre-registration, tmp data root), access is granted and logged;
  - a modified, uncommitted or staged-only pre-registration, a config-hash mismatch, a template placeholder, or a config change after opening is refused (`@slow`);
  - a CRLF working copy counts as clean;
  - the log is append-only JSONL;
  - the real log shows zero test runs;
  - Phase 9 regression tests pass with the test-lock fixture.
- **Script:** `scripts/forecast_baselines.py` runs end-to-end on a synthetic data root (small B) and refuses repo or frozen output paths (`@slow`).

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Quick-Loop Budget (plan checker W1)

- Per new module, quick subset: about 2 s (testlock, metrics, bootstrap, slices, predictions, baselines_report); about 3 s (baselines, harness); dataset guard tests add about 1 s or less.
- Bootstrap, harness and baselines quick tests use the 6-ward synthetic panel and B <= 50.
- Measured in Wave 3 (10-07 Task 2 acceptance) with `--durations=15`; if the quick loop exceeds 60 s, the slowest new tests are marked `@slow` there. 10-09 re-measures at the phase gate.

## Wave 0 Requirements

- [ ] New test modules: `test_forecast_{baselines,metrics,bootstrap,slices,predictions,testlock,harness,baselines_report,baselines_frozen,baselines_script}.py` (each created by the task that owns it; see map)
- [ ] `tests/forecast/conftest.py`:
  - autouse tmp data root for the test lock and evaluation log;
  - a test-lock-open fixture;
  - a tmp git repo helper (`user.name`/`user.email`, `core.autocrlf` configurable)
- [ ] Config: `baselines.shrinkage_pseudo_count` (50) and a new `evaluation` section, plus config tests
- [ ] Update the three existing `lead_rows(..., "test")` call sites (`test_forecast_dataset.py` 103/262, `test_forecast_leakage.py` 197)

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (10-09-T3 is the approval checkpoint)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [ ] Quick-loop latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

## Orchestrator notes from plan check (iteration 2, 2026-10-08)
- **N1:** the quick-loop timing and slow-marking step written into 10-07 T2 is **moved to the start of 10-08**, which runs in wave 4 after 10-06 and 10-07. Plans run one at a time on the main tree, so there's no race. Moving the step keeps file ownership clean: 10-07 must not edit 10-06's test files.
- **N2 (10-06 T1):** the persistence hand-count test builds its tiny case from slices of the synthetic panel and reuses the module's single fitted `Climatology`, or a minimal stub with `fit_end = cfg.splits.train_end`. The gate `grep -c "Climatology.fit" tests/forecast/test_forecast_baselines.py == 1` still holds.
