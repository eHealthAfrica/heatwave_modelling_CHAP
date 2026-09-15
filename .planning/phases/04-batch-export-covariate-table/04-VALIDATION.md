---
phase: 4
slug: batch-export-covariate-table
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-15
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 [verified: requirements.txt] |
| **Config file** | none — no `pytest.ini`/`setup.cfg`; default discovery |
| **Quick run command** | `pytest tests/test_export.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | small-sample live-EE calls only — the real full-scale production export (hours) runs separately, outside the fast test loop |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_export.py -x`
- **After every plan wave:** `pytest tests/ -x` (full suite, includes Phase 1-3 regression)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds
- The actual full-scale production run (EXPORT-01's real 1991-present invocation) is a separate, manually-triggered, long-running operation — never exercised inline in the fast per-task/per-wave loop.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-TBD | TBD | 0 | EXPORT-02 | — | N/A | live-EE unit | `pytest tests/test_export.py -k schema -x` | ❌ W0 | ⬜ pending |
| 04-01-TBD | TBD | 0 | EXPORT-03 | — | N/A | live-EE unit | `pytest tests/test_export.py -k completeness -x` | ❌ W0 | ⬜ pending |
| 04-01-TBD | TBD | 0 | EXPORT-01 | — | N/A | live-EE smoke, small sample only | `pytest tests/test_export.py -k batch_export -x` | ❌ W0 | ⬜ pending |
| 04-01-TBD | TBD | 0 | EXPORT-04 | — | N/A | (this file itself) | `pytest tests/test_export.py -x` | ❌ W0 | ⬜ pending |

*Task IDs are placeholders (TBD) — the planner fills in real plan/task IDs when PLAN.md files are created.*

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_export.py` — new file, this phase's own deliverable (EXPORT-04). Follows the skip-gated, live-EE pattern from `tests/test_heatwave_detection.py`.
- [ ] `heatwave/export.py` — new file, weekly-aggregation logic (ISO-week keying, composite-key group-by, event-start-week counting) and the D-08 fallback wiring.
- [ ] `scripts/run_batch_export.py` — new file, chunk planner + Earth Engine task submission/polling + final CSV concatenation. This is a production entry point, not exercised by the fast test suite itself.
- [ ] A real (not purely synthetic) `Export.table.toAsset()` round-trip smoke test — submit a tiny real task, poll to `COMPLETED`, read back via pagination — run once early to de-risk the asset-write-permission assumption before the planner/executor build further on top of it.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full 1991-present production export completes and produces a complete, correct CSV for all 4,841 wards | EXPORT-01, EXPORT-03 | Genuinely large (~hours), chunked, long-running — cannot run inside the fast per-task/per-wave test loop | Run `scripts/run_batch_export.py` for the full date range as a deliberate, monitored, one-time (or occasional) invocation; verify row counts and schema against EXPORT-02/03 afterward |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
