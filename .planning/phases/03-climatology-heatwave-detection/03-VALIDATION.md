---
phase: 3
slug: climatology-heatwave-detection
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-13
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest [assumed unchanged since Phase 2] |
| **Config file** | none — no `pytest.ini`/`setup.cfg`; default discovery |
| **Quick run command** | `pytest tests/test_heatwave_detection.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | small synthetic live-EE calls per D-01 — should stay well under 30s |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_heatwave_detection.py -x`
- **After every plan wave:** `pytest tests/ -x` (full suite, includes Phase 1-2 regression)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-TBD | TBD | 0 | CLIM-05 | — | N/A | live-EE unit | `pytest tests/test_heatwave_detection.py -k zonal -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | TBD | 0 | CLIM-01 | — | N/A | live-EE unit | `pytest tests/test_heatwave_detection.py -k climatology -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | TBD | 0 | CLIM-02 | — | N/A | live-EE unit | `pytest tests/test_heatwave_detection.py -k pooling -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | TBD | 0 | CLIM-03 | — | N/A | live-EE unit | `pytest tests/test_heatwave_detection.py -k flag -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | TBD | 0 | CLIM-04 | — | N/A | live-EE unit | `pytest tests/test_heatwave_detection.py -k event -x` | ❌ W0 | ⬜ pending |
| 03-01-TBD | TBD | 0 | CLIM-06 | — | N/A | (this file itself) | `pytest tests/test_heatwave_detection.py -x` | ❌ W0 | ⬜ pending |

*Task IDs are placeholders (TBD) — the planner fills in real plan/task IDs when PLAN.md files are created.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_heatwave_detection.py` — new file, this phase's own deliverable (CLIM-06). Follow the skip-gated, live-EE, `pytest.approx`-tolerance pattern from `tests/test_heat_index.py` (per-test credential guard, not module-level `pytestmark`, per Phase 2 precedent).
- [ ] No shared `conftest.py` needed — a local synthetic-data helper (e.g. `_make_synthetic_ward_daily_fc(...)`) in the new test file follows the existing `_make_test_image()` pattern.
- [ ] Framework install: none needed — pytest and earthengine-api already present.

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
