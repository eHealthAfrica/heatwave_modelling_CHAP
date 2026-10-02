---
phase: 3
slug: climatology-heatwave-detection
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-13
finalized: 2026-09-13
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest [assumed unchanged since Phase 2] |
| **Config file** | none — no `pytest.ini`/`setup.cfg`; default discovery |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -x` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests/ -x` |
| **Estimated runtime** | small synthetic live-EE calls per D-01 — each test well under 30s; the two composed/real-data tests in plan 03-04 are explicitly timed with `--durations` against the 30s budget |

---

## Sampling Rate

- **After every task commit:** `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -x`
- **After every plan wave:** `.venv/Scripts/python -m pytest tests/ -x` (full suite, includes Phase 1-2 regression)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

Every task in every plan carries an `<automated>` verify command. Wave 0 (the test file itself) is
created by plan 03-01 Task 1, which is the first task executed in the phase — so no task after it
runs without automated coverage, and there is no run of three consecutive tasks lacking an automated
verify.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 03-01 | 1 | CLIM-05, CLIM-06 | T-03-04, T-03-05 | Credential path existence-checked only, never read or logged; per-test skip gate | live-EE unit (RED) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -v` | ✅ created by this task (Wave 0) | ⬜ pending |
| 03-01-T2 | 03-01 | 1 | CLIM-05 | T-03-01, T-03-02, T-03-03 | Missing zonal result surfaces as explicit null, never 0; `system:time_start` set on every row; scale/band/ward-id parameterised, no hardcoded ward count | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k zonal -x` | ✅ | ⬜ pending |
| 03-02-T1 | 03-02 | 2 | CLIM-01, CLIM-02, CLIM-06 | T-03-09 | EE's own live-verified percentile is the oracle; numpy/pandas/scipy imports forbidden in the test file | live-EE unit (RED) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k "climatology or pooling" -v` | ✅ | ⬜ pending |
| 03-02-T2 | 03-02 | 2 | CLIM-01, CLIM-02 | T-03-07, T-03-08, T-03-10, T-03-11 | ASVS V5: percentile/window/baseline years resolve from `settings.climatology`, zero hardcoded constants; floor-mod prevents negative day values reaching `calendarRange`; baseline year filter blocks out-of-range contamination | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k climatology -x` | ✅ | ⬜ pending |
| 03-03-T1 | 03-03 | 3 | CLIM-03, CLIM-04, CLIM-06 | T-03-14 | Strict greater-than boundary pinned by a value-equals-threshold test | live-EE unit (RED) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k "flag or event" -v` | ✅ | ⬜ pending |
| 03-03-T2 | 03-03 | 3 | CLIM-03, CLIM-04 | T-03-13, T-03-15, T-03-16, T-03-17, T-03-18 | Join keys on ward AND doy; per-ward date-sorted partitioning prevents cross-ward run bleed; ASVS V5 min_consecutive_days from config; null-value coalescing explicitly forbidden | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k "flag or event" -x` | ✅ | ⬜ pending |
| 03-04-T1 | 03-04 | 4 | CLIM-01, CLIM-02, CLIM-03, CLIM-04, CLIM-05, CLIM-06 | T-03-20, T-03-24 | Cross-stage property-name contract verified in one composed run; runtime timed against the 30s budget | live-EE integration | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k end_to_end -v --durations=5` | ✅ | ⬜ pending |
| 03-04-T2 | 03-04 | 4 | CLIM-05, CLIM-06 | T-03-21, T-03-22, T-03-23, T-03-25 | Unit-sanity band catches Kelvin/Celsius leaks; largest-ward selection removes Pitfall 4 as a confounder; `system:time_start` re-verified against real timestamps | live-EE integration + phase gate | `.venv/Scripts/python -m pytest tests/ -v --durations=10` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement coverage cross-check

| Req ID | Covered by | `-k` selector |
|--------|-----------|----------------|
| CLIM-01 | 03-02-T1/T2, 03-04-T1 | `-k climatology` |
| CLIM-02 | 03-02-T1/T2, 03-04-T1 | `-k pooling` |
| CLIM-03 | 03-03-T1/T2, 03-04-T1 | `-k flag` |
| CLIM-04 | 03-03-T1/T2, 03-04-T1 | `-k event` |
| CLIM-05 | 03-01-T1/T2, 03-04-T1/T2 | `-k zonal` |
| CLIM-06 | 03-01-T1, 03-02-T1, 03-03-T1, 03-04-T1/T2 | (whole file) |

---

## Wave 0 Requirements

- [ ] `tests/test_heatwave_detection.py` — new file, this phase's own deliverable (CLIM-06). Created by **plan 03-01, Task 1**, the first task of the phase. Follows the skip-gated, live-EE, `pytest.approx`-tolerance pattern from `tests/test_heat_index.py` (per-test credential guard, not module-level `pytestmark`, per Phase 2 precedent).
- [ ] No shared `conftest.py` — local synthetic-data helpers (`_make_ward_fc`, `_make_heat_index_collection`, `_make_ward_daily_fc`, `_make_climatology_fc`, `_make_constant_heat_index_collection`, `_props`) live in the test file, following the existing `_make_test_image()` pattern. Each plan adds the helper it needs and reuses the earlier ones.
- [ ] Framework install: none needed — pytest and earthengine-api 1.6.8 already present.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (all 8 tasks carry one)
- [x] Wave 0 covers all MISSING references (`tests/test_heatwave_detection.py` created in plan 03-01 Task 1)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (plan 03-04 tasks explicitly measure and carry a documented fallback if exceeded)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved — 2026-09-13, at plan creation (planner), matching the Phase 2 precedent.
