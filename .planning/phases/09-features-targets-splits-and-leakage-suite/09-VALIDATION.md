---
phase: 9
slug: features-targets-splits-and-leakage-suite
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-06
---

# Phase 9 — Validation Strategy

> Per-phase validation contract. Derived from `09-RESEARCH.md` § Validation Architecture, updated for the 2026-10-06 framing decision (latency 0; no live Earth Engine query in this phase).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 (`pyproject.toml`, marker `frozen`; `tests/conftest.py` auto-skips `frozen` tests when the data is absent) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/forecast -q -m "not frozen"` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q` |
| **Frozen-data command (local only)** | `.venv/Scripts/python.exe -m pytest tests/forecast -q -m frozen` (the session-scoped `load_panel` takes about 20 s) |
| **Estimated runtime** | quick < 60 s; frozen ~1-2 min |

---

## Sampling Rate

- **After every task commit:** run the quick run command.
- **After every plan wave:** run the full suite command.
- **Before `/gsd:verify-work`:** the full suite and the frozen command are green, and CI is green.
- **Max feedback latency:** 60 seconds.

---

## Per-Task Verification Map

To be filled in by the planner: one row per task.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 9-xx | — | — | FEAT-01 | T-9-01 | label_k[:, t] == (heatwave_days[:, t+k] >= 3); rows past the end of the data are masked; the label differs from `heatwave_event_count`; an independent date-join check agrees | unit (synthetic) | `pytest tests/forecast/test_forecast_targets.py -q` | ❌ W0 | ⬜ pending |
| 9-xx | — | — | FEAT-02 | N/A | issue_date = Sunday of t + latency_days (0); effective_days_ahead = 7k − 6 − latency gives +1, +8, +15, +22, +29, +36 at latency 0; correct across year-end and W53 boundaries | unit | same file | ❌ W0 | ⬜ pending |
| 9-xx | — | — | FEAT-03 | T-9-01 | each feature family matches hand-computed values on a tiny panel; anomalies are zero-mean on train; W53 pooling; the base rate excludes current-year weeks; group means; warm-up NaN counts; no raw year or ward id in the registry | unit | `test_forecast_features.py`, `test_forecast_climatology.py`, `test_forecast_static.py` | ❌ W0 | ⬜ pending |
| 9-xx | — | — | FEAT-04 | T-9-01, T-9-02 | (a) truncation, (b) poison the future, (c) train-only statistics, (d) registry, (e) mutation check, on synthetic data; a `@frozen` variant of (a) and (b) on ~10 origins × a 200-ward subset of the real panel | unit + `@frozen` | `test_forecast_leakage.py` | ❌ W0 | ⬜ pending |
| 9-xx | — | — | FEAT-05 | T-9-02 | (f) no overlap between splits; embargo 14 respected; cutoffs on Mondays; 2020-W53 in validate; CV folds 2005-2020 with max(train target) < min(validate target) − embargo, refitting the per-fold climatology; test rows labelled; `cv_first_year` validation | unit | `test_forecast_splits.py`, `test_forecast_config.py` | ❌ W0 / modify | ⬜ pending |
| 9-xx | — | — | FEAT-06 | N/A | the report builder returns its tables from a synthetic panel; caption present; the operational-delay note (9 days, measured 2026-10-06) is shown; the script on `@frozen` writes a run folder and `docs/forecast/DATA_REPORT.md`; overall real prevalence is within 0.10-0.13 | unit + `@frozen` | `test_forecast_report.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Threat refs:**
- T-9-01: target or future information leaking into features (silent optimism).
- T-9-02: held-out (validation or test) data influencing training statistics or split membership.

---

## Wave 0 Requirements

- [ ] `heatwave/forecast/fixtures.py`:
  - `synthetic_panel(n_wards=6, first_week="1991-W02", last_week="2003-W20", seed)`, an in-memory Panel covering the 1992 and 1998 W53 weeks and more than 10 years of history;
  - a static fixture (wards.geojson with geometries, including one empty geometry, plus `wards_lga_average.csv` and MANIFEST entries).
- [ ] `config.py`, `forecast.yaml` and `test_forecast_config.py`: add `cv_first_year` (2005) and set `embargo_weeks: 14`, with updated assertions and rejection cases. `latency_days: 0` and `gate.primary_leads: [1, 2]` are already done (commit c2d4d50).
- [ ] New test modules: `test_forecast_{targets,features,climatology,static,splits,leakage,report}.py`.
- [ ] `scripts/forecast_data_report.py` and the `docs/forecast/` directory.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI green on the branch | FEAT-01-06 | GitHub Actions | Push only with user approval, then check the Actions run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
