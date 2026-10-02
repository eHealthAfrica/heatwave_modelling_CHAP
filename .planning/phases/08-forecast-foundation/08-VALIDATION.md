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

To be filled by the planner and executor: one row per task, mapped to the tests below.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 8-xx | — | — | DATA-01 | T-8-01 | Hash checked before parse; byte-flipped copy, wrong columns/counts, missing file and the live CSV are all refused | unit | `pytest tests/forecast/test_forecast_data.py -x` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-01 | T-8-01 | Real frozen parquet loads as (4841, 1863, 8) with no NaN and sha `82583fbf…`; a modified copy is rejected | integration `@frozen` | `pytest -m frozen tests/forecast/test_forecast_frozen.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-02 | N/A | label↔index↔date round-trips for all 1,863 indices; the 53-week years are correct; 2020-W53 = 2020-12-28..2021-01-03; index 0 = 1991-W02 = 1991-01-07; an invalid `2021-W53` raises | unit | `pytest tests/forecast/test_forecast_weeks.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-02 | N/A | Frozen label set equals the generated labels 0..1862 | `@frozen` | `pytest -m frozen tests/forecast/test_forecast_frozen.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-03 | T-8-02, T-8-03 | Valid `forecast.yaml` loads; every bad value raises (duplicate/zero leads, overlapping splits, non-Monday cutoff, negative or boolean latency, gate leads not in leads, unknown key, wrong version or path-like version); uses `safe_load` only; `config.yaml` and `tests/test_config.py` unchanged | unit | `pytest tests/forecast/test_forecast_config.py tests/test_config.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-04 | T-8-04 | Run folder is written under the data root with config.yaml and a complete RUN_MANIFEST.json; a base inside the repo is refused; ids are unique; works without git | unit | `pytest tests/forecast/test_forecast_artifacts.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-05 | N/A | sklearn, lightgbm and shap import at the pinned versions; the forecast package never imports `ee`/`geemap`/`heatwave.auth` (subprocess + AST scan) | unit | `pytest tests/forecast/test_forecast_deps.py` | ❌ W0 | ⬜ pending |
| 8-xx | — | — | DATA-05 | N/A | Existing suite intact; CI green on 3.12 | full suite / CI | `pytest -q`, then push and check Actions | ✅ | ⬜ pending |
| 8-xx | — | — | DATA-01 | T-8-01 | `verify_frozen.py --outputs-only` exits 0 on real data and non-zero on a tampered copy | `@frozen` / subprocess | `python scripts/verify_frozen.py --outputs-only` | ❌ W0 | ⬜ pending |

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
