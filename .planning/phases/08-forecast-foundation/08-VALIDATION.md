---
phase: 8
slug: forecast-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-02
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from `08-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 (`[tool.pytest.ini_options] pythonpath=["."]` in `pyproject.toml`) |
| **Config file** | `pyproject.toml` (register the `frozen` marker); new `tests/conftest.py` (auto-skips `frozen` tests, synthetic fixture helpers) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/forecast -x -q` |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest -q` (166 existing tests plus the new ones; 2 existing opt-in skips) |
| **Frozen-data command (local only)** | `.venv/Scripts/python.exe -m pytest -m frozen -q` |
| **Estimated runtime** | quick < 10 s; full ~3 min (live Earth Engine tests); frozen ~10 s |

---

## Sampling Rate

- **After every task commit:** run the quick run command.
- **After every plan wave:** run the full suite command.
- **Before `/gsd:verify-work`:** the full suite and the frozen-data command must be green locally, and CI must be green on Python 3.12.
- **Max feedback latency:** 10 seconds (quick run).

---

## Per-Task Verification Map

Filled by the planner (2026-10-02); the executor updates Status.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 8-01-01 | 01 | 1 | DATA-05 | T-8-SC | Dry-run list human-approved before any install (blocking-human) | checkpoint | `pip install --dry-run scikit-learn==1.9.1 lightgbm==4.7.0 shap==0.52.0` | n/a | ⬜ pending |
| 8-01-02 | 01 | 1 | DATA-05 | T-8-SC, T-8-05 | sklearn/lightgbm/shap at pins; numpy/pandas/pyarrow unchanged; pred_contrib works | unit | `pytest tests/forecast/test_forecast_deps.py tests/test_requirements.py` | ❌ W0 | ⬜ pending |
| 8-02-01 | 02 | 1 | DATA-02 | T-8-07 | label<->index<->date round-trips 0..1862; 53-week years; 2020-W53 = 2020-12-28..2021-01-03; index 0 = 1991-W02; invalid `2021-W53` raises | unit | `pytest tests/forecast/test_forecast_weeks.py` | ❌ W0 | ⬜ pending |
| 8-02-02 | 02 | 1 | DATA-05 | T-8-09 | frozen marker registered and auto-skipped without data; requires-python >=3.12; test_config untouched | unit | `pytest tests/forecast tests/test_config.py` | ❌ W0 | ⬜ pending |
| 8-03-01 | 03 | 2 | DATA-03 | T-8-02 | forecast.yaml loads to frozen ForecastConfig; canonical hash; snapshot round-trip | unit | `pytest tests/forecast/test_forecast_config.py` | ❌ W0 | ⬜ pending |
| 8-03-02 | 03 | 2 | DATA-03 | T-8-02, T-8-03, T-8-10 | Every bad value raises; safe_load refuses python tags; path-like version refused; config.yaml/tests unchanged | unit | `pytest tests/forecast/test_forecast_config.py tests/test_config.py` | ❌ W0 | ⬜ pending |
| 8-04-01 | 04 | 3 | DATA-01, DATA-05 | T-8-12 | Synthetic frozen dataset (6 wards, 3 states, 1991-W02..1993-W05 incl. 1992-W53) matches real schema; chunked sha256 | unit | `pytest tests/forecast/test_forecast_data.py` | ❌ W0 | ⬜ pending |
| 8-04-02 | 04 | 3 | DATA-01, DATA-02 | T-8-01, T-8-03, T-8-13 | Hash checked before parse (MANIFEST + forecast.yaml anchor); byte flip, schema, counts, contiguity, duplicates, missing file, live CSV refused | unit | `pytest tests/forecast/test_forecast_data.py` | ❌ W0 | ⬜ pending |
| 8-05-01 | 05 | 3 | DATA-04 | T-8-15 | run_id format; git info tolerant of missing git; library versions incl. None | unit | `pytest tests/forecast/test_forecast_artifacts.py` | ❌ W0 | ⬜ pending |
| 8-05-02 | 05 | 3 | DATA-04 | T-8-04, T-8-14 | Run folder under data root with config.yaml + complete RUN_MANIFEST.json; in-repo base refused; unique ids; atomic manifest | unit | `pytest tests/forecast/test_forecast_artifacts.py` | ❌ W0 | ⬜ pending |
| 8-06-01 | 06 | 4 | DATA-01 | T-8-01, T-8-17 | verify_frozen.py exit 0/1/2; tamper, missing, BAD-KEY, copied-input checks; never writes | subprocess (synthetic) | `pytest tests/forecast/test_forecast_verify_script.py` | ❌ W0 | ⬜ pending |
| 8-06-02 | 06 | 4 | DATA-01, DATA-02, DATA-04 | T-8-01, T-8-12 | Real parquet loads (4841, 1863, 8), sha 82583fbf…; frozen labels == generated 0..1862; modified copy rejected; `verify_frozen.py --outputs-only` 0/1; run folder with real hash | integration `@frozen` | `pytest -m frozen tests/forecast/test_forecast_frozen.py` | ❌ W0 | ⬜ pending |
| 8-07-01 | 07 | 5 | DATA-05 | T-8-19 | Forecast package never imports ee/geemap/heatwave.auth (subprocess + AST, scanner self-test); CI on 3.12 | unit | `pytest tests/forecast/test_forecast_isolation.py` | ❌ W0 | ⬜ pending |
| 8-07-02 | 07 | 5 | DATA-05 | T-8-09 | Existing 166 tests + forecast tests green; frozen suite green; CI simulation skips frozen | full suite | `pytest -q`; `pytest -m frozen -q` | ✅ | ⬜ pending |
| 8-07-03 | 07 | 5 | DATA-05 | T-8-20, T-8-21 | User-approved push; CI green on Python 3.12 | CI / checkpoint | `gh run list --branch milestone/v2.0-heat-forecasting --workflow tests.yml --limit 1` | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Threat refs:**
- T-8-01: tampered or stale data used for training.
- T-8-02: YAML arbitrary object construction.
- T-8-03: path traversal via `data.version`.
- T-8-04: run artifacts written into the repo or outside the data root.

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — frozen auto-skip, `frozen_root` fixture, synthetic fixture helpers
- [ ] `heatwave/forecast/fixtures.py` — synthetic panel builder (e.g. 6 wards across 2-3 states; weeks covering 1992 with W53 through at least 1993-W05). It writes a parquet and MANIFEST matching the real schema and dtypes (strings for time_period/location, int64 counts, float64 others).
- [ ] `pyproject.toml` — register the `frozen` marker. Test files under `tests/forecast/` use unique names, `test_forecast_*.py`.
- [ ] Dependency install (scikit-learn 1.9.1, lightgbm 4.7.0, shap 0.52.0 plus transitive pins) after a human-verify checkpoint.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI green on Python 3.12 | DATA-05 | Runs on GitHub Actions | Push the branch, open a PR or check the Actions run for `tests.yml` |
| Package install approval | DATA-05 | Supply-chain checkpoint before installing new packages into `.venv` | Review the dry-run resolution list, then approve the install |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
