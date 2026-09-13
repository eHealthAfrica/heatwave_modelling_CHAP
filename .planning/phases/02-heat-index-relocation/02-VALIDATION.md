---
phase: 2
slug: heat-index-relocation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-13
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
| 02-01-TBD | TBD | 0 | HIDX-01 | — | N/A | unit (import-level) | `pytest tests/test_heat_index.py -k import -x` | ❌ W0 | ⬜ pending |
| 02-01-TBD | TBD | 0 | HIDX-02 | — | N/A | live-EE, skip-gated | `pytest tests/test_heat_index.py -v` | ❌ W0 | ⬜ pending |
| 02-01-TBD | TBD | 0 | HIDX-03 | — | N/A | smoke (AppTest, in-process, regression) | `pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -v` | ✅ existing | ⬜ pending |

*Task IDs are placeholders (TBD) — the planner fills in real plan/task IDs when PLAN.md files are created.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_heat_index.py` — new file, covers HIDX-02 (and optionally direct RH-clamp boundary coverage per Research Open Question 1)
- [ ] `heatwave/science/__init__.py` — new empty package file, required for `heatwave/science/heat_index.py` to be importable
- [ ] Framework install: none needed — pytest already present

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
