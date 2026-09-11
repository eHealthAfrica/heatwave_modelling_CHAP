---
phase: 1
slug: foundation-rework
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-11
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 [verified: local .venv] |
| **Config file** | none — `pyproject.toml` has no `[tool.pytest.ini_options]` section (Wave 0 gap) |
| **Quick run command** | `pytest tests/test_integration.py -x -q` |
| **Full suite command** | `pytest -q` (only file will be `tests/test_integration.py` after this phase) |
| **Estimated runtime** | ~10-30s with live credentials; near-instant if all-skipped without them |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_integration.py -x -q`
- **After every plan wave:** Run `pytest -q` (same command — this phase has one test file)
- **Before `/gsd:verify-work`:** Full suite must be green, or all-skipped if run without live GCP credentials
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-TBD | TBD | 0 | REWORK-03 | — | N/A | static check | `grep -q "^ee==" requirements.txt && exit 1 \|\| exit 0` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-01 | — | N/A | integration (manual + inspection) | `pytest tests/test_integration.py::test_init_ee_idempotent -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-02 | — | N/A | unit/integration | `pytest tests/test_integration.py::test_era5_land_bands_aligned -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-04 | — | N/A | integration | `pytest tests/test_integration.py::test_auth_resolves_from_any_cwd -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-05 | — | N/A | integration (live) | `pytest tests/test_integration.py::test_load_ward_boundary -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-06 | — | N/A | integration (live) | `pytest tests/test_integration.py::test_load_era5_land -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-07 | — | N/A | unit | `pytest tests/test_integration.py::test_settings_loaded -x` | ❌ W0 | ⬜ pending |
| 01-01-TBD | TBD | 1+ | REWORK-08 | — | N/A | integration (live) | `pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -x` | ❌ W0 | ⬜ pending |

*Task IDs are placeholders (TBD) — the planner fills in real plan/task IDs when PLAN.md files are created; this map's requirement→command mapping stays fixed.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_integration.py` — does not exist yet; covers REWORK-01, REWORK-02, REWORK-04, REWORK-05, REWORK-06, REWORK-07, REWORK-08
- [ ] Confirm `pytest` discovers `tests/` from repo root without needing a `testpaths` entry added to `pyproject.toml` (default discovery should work; verify once the directory exists)
- [ ] No shared `conftest.py` required — the credential-skip condition and key-file path resolution are small enough to inline directly in `test_integration.py` per CONTEXT.md's discretion note on test structure

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Earth Engine re-auth does not occur on Streamlit rerun/interaction | REWORK-01 | Caching behavior across a live Streamlit rerun cycle is hard to assert reliably via pytest; automated test only confirms `init_ee()` is idempotent (no error on repeat call), not that Streamlit skipped re-execution | Run `streamlit run nigeria_heat_index.py`, interact with a slider/widget several times, confirm no added latency or repeated auth log lines |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
