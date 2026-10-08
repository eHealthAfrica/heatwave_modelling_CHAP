---
phase: 10
slug: baselines-evaluation-harness-and-test-lock
status: draft
nyquist_compliant: false
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

To be filled in by the planner.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|

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

## Wave 0 Requirements

- [ ] New test modules: `test_forecast_{baselines,metrics,bootstrap,slices,predictions,testlock,baselines_frozen,baselines_script}.py`
- [ ] `tests/forecast/conftest.py`:
  - autouse tmp data root for the test lock and evaluation log;
  - a test-lock-open fixture;
  - a tmp git repo helper (`user.name`/`user.email`, `core.autocrlf` configurable)
- [ ] Config: `baselines.shrinkage_pseudo_count` (50) and a new `evaluation` section, plus config tests
- [ ] Update the three existing `lead_rows(..., "test")` call sites (`test_forecast_dataset.py` 103/262, `test_forecast_leakage.py` 197)

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Quick-loop latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
