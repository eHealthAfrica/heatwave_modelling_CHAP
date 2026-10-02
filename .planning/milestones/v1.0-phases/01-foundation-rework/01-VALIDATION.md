---
phase: 1
slug: foundation-rework
status: approved
nyquist_compliant: true
wave_0_complete: true
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
  - Exception: Plan 01-03 Task 3's `test_streamlit_app_boots_cleanly` boots the full Streamlit app
    in-process against live Earth Engine calls and, combined with live-network latency, risks
    exceeding the 30s feedback-latency target. Per Plan 01-03 Task 3's `<verify>` note, that
    specific test is excluded from the fast per-task command (`pytest tests/test_requirements.py
    -x -q` is used instead for that task's commit loop) and is run at the wave/phase gate below.
- **After every plan wave:** Run `pytest -q` (same command — this phase has one test file; this is
  where `test_streamlit_app_boots_cleanly` executes)
- **Before `/gsd:verify-work`:** Full suite must be green, or all-skipped if run without live GCP credentials
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-T2 | 01-01 | 1 | REWORK-03 | T-1-01 | mitigate | static check | `grep -v '^#' requirements.txt \| grep -c '^ee==' \| grep -qx 0 && echo OK` | ✅ planned (01-01) | ⬜ pending |
| 01-03-T1 | 01-03 | 2 | REWORK-01 | T-1-05 | mitigate | integration (live, idempotency proxy) | `pytest tests/test_integration.py::test_init_ee_idempotent -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T2 | 01-03 | 2 | REWORK-02 | T-1-06 | accept | unit/integration | `pytest tests/test_integration.py::test_era5_land_bands_aligned -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T1 | 01-03 | 2 | REWORK-04 | T-1-02 | mitigate | integration | `pytest tests/test_integration.py::test_auth_resolves_from_any_cwd -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T2 | 01-03 | 2 | REWORK-05 | — | N/A | integration (live) | `pytest tests/test_integration.py::test_load_ward_boundary -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T2 | 01-03 | 2 | REWORK-06 | — | N/A | integration (live) | `pytest tests/test_integration.py::test_load_era5_land -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T1 | 01-03 | 2 | REWORK-07 | — | N/A | unit | `pytest tests/test_integration.py::test_settings_loaded -x` | ✅ planned (01-03) | ⬜ pending |
| 01-03-T3 | 01-03 | 2 | REWORK-08 | — | N/A | integration (live, run at wave/phase gate — see Sampling Rate exception) | `pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -x` | ✅ planned (01-03) | ⬜ pending |

*Task IDs reference `{phase}-{plan}-T{task}` once PLAN.md files exist (01-01, 01-02, 01-03 all
exist as of this revision); `File Exists` reflects planning-time coverage (a plan/task now creates
or verifies this file/behavior), not yet-executed code state — `Status` tracks actual execution
and stays pending until `/gsd:execute-phase` runs.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_integration.py` — created by Plan 01-03 Task 1 (skeleton) and extended by Tasks 2-3; covers REWORK-01, REWORK-02, REWORK-04, REWORK-05, REWORK-06, REWORK-07, REWORK-08
- [x] Confirm `pytest` discovers `tests/` from repo root without needing a `testpaths` entry added to `pyproject.toml` — verified via Plan 01-03 Task 3's acceptance criterion `pytest -q --collect-only` (default rootdir discovery)
- [x] No shared `conftest.py` required — the credential-skip condition and key-file path resolution are inlined directly in `tests/test_integration.py` per Plan 01-03 Task 1, per CONTEXT.md's discretion note on test structure

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Earth Engine re-auth does not occur on Streamlit rerun/interaction | REWORK-01 | Caching behavior across a live Streamlit rerun cycle is hard to assert reliably via pytest; automated test only confirms `init_ee()` is idempotent (no error on repeat call), not that Streamlit skipped re-execution | Run `streamlit run nigeria_heat_index.py`, interact with a slider/widget several times, confirm no added latency or repeated auth log lines |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-11
