---
phase: 2
slug: heat-index-relocation
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-13
updated: 2026-09-13
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 [verified: local .venv] |
| **Config file** | none — no `pytest.ini`/`[tool.pytest.ini_options]` in `pyproject.toml`; discovery relies on default `test_*.py` naming |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_heat_index.py -v` |
| **Full suite command** | `.venv/Scripts/python -m pytest -v` |
| **Estimated runtime** | ~10-30s with live credentials |

---

## Sampling Rate

- **After every task commit:** `.venv/Scripts/python -m pytest tests/test_heat_index.py -v`
- **After every plan wave:** `.venv/Scripts/python -m pytest -v` (full suite, includes live-EE `test_integration.py` boot regression check)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-T1 | 02-01 | 1 | HIDX-02 | T-02-01, T-02-02 | RH clamp boundaries encoded as executable assertions before implementation exists | unit/live-EE (RED gate) | `.venv/Scripts/python -m pytest tests/test_heat_index.py -v` (expect ModuleNotFoundError) | ❌ created by this task | ⬜ pending |
| 02-01-T2 | 02-01 | 1 | HIDX-01, HIDX-02 | T-02-01, T-02-02 | `.clamp(0, 100)` applied to single-band RH result, never the multi-band composite | unit/live-EE (GREEN gate) | `.venv/Scripts/python -m pytest tests/test_heat_index.py -v` | ❌ created by 02-01-T1 | ⬜ pending |
| 02-02-T1 | 02-02 | 2 | HIDX-03 | T-02-06 | No divergent duplicate of the formulas left in the presentation layer | smoke (AppTest, in-process, regression) | `.venv/Scripts/python -m pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -v` | ✅ existing | ⬜ pending |
| 02-02-T2 | 02-02 | 2 | HIDX-01, HIDX-02, HIDX-03 | T-02-06, T-02-07 | NOAA-table values unchanged after the call-site relocation (D-02) | full suite (phase gate) | `.venv/Scripts/python -m pytest -v` | ✅ after 02-01 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is absorbed into plan 02-01 rather than run as a separate wave — the missing test file is the
first task of that plan (test-first), and the missing package marker is the second.

- [ ] `tests/test_heat_index.py` — created by 02-01-T1; covers HIDX-02 (3 NOAA table cases) plus direct D-01 clamp-boundary and source-band-integrity coverage
- [ ] `heatwave/science/__init__.py` — created by 02-01-T2; zero-byte package marker required for `heatwave.science.heat_index` to be importable
- [ ] Framework install: none needed — pytest 8.4.1 already present

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (absorbed into 02-01 tasks 1 and 2)
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved at planning (2026-09-13)
