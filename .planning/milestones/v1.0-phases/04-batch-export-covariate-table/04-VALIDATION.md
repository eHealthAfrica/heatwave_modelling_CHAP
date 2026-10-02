---
phase: 4
slug: batch-export-covariate-table
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-15
finalized: 2026-09-15
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 [verified: requirements.txt] |
| **Config file** | none — no `pytest.ini`/`setup.cfg`; default discovery |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_export.py -x` |
| **Full suite command** | `.venv/Scripts/python -m pytest tests/ -x` |
| **Estimated runtime** | default (ungated) run: small-sample live-EE and credential-free calls only, under 30s for `tests/test_export.py`. Two opt-in env-gated tests sit outside that budget by design (see below). The real full-scale production export (hours) runs separately, outside the test loop entirely |

### Opt-in gates (deliberately outside the fast loop)

| Env var | Test | Why gated | Run deliberately in |
|---------|------|-----------|---------------------|
| `RUN_EE_BATCH_ROUNDTRIP=1` | `test_batch_export_asset_round_trip` | Submits a real Earth Engine batch task; queue + run time is minutes, blowing the 30s budget. Still a real (not mocked) verification | 04-01-T3 |
| `RUN_EE_PIPELINE_SMOKE=1` | `test_batch_export_small_sample_pipeline_produces_export_02_rows` | A full-pipeline graph; Phase 3 measured 65.81s for a comparable 60-row composed graph | 04-04-T2 |

Both are real live tests, not skipped work: each is executed once, deliberately, by a named task whose
acceptance criteria require it to pass. Gating keeps the per-task feedback loop inside 30 seconds for
every other task in the phase.

---

## Sampling Rate

- **After every task commit:** `.venv/Scripts/python -m pytest tests/test_export.py -x` (plans 04-01, 04-03, 04-04) or `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k zonal -x` (plan 04-02)
- **After every plan wave:** `.venv/Scripts/python -m pytest tests/ -x` (full suite, includes Phase 1-3 regression)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds (ungated tests)

Every task in every plan carries an `<automated>` verify command. Wave 0's test files are created by
the first task of the first plan in each Wave-1 lane (04-01-T1 creates `tests/test_export.py`;
04-02-T1 extends the existing `tests/test_heatwave_detection.py`), so no task after them runs without
automated coverage, and there is no run of three consecutive tasks lacking an automated verify.

**Scope note (load-bearing for the verifier):** the actual full-scale production run — EXPORT-01's real
1991-present, 4,841-ward invocation — is a separate, manually-triggered, hours-long operation. It is
never exercised inline in the per-task or per-wave loop, and `outputs/covariate_table.csv` at full scale
is NOT a completion criterion for this phase. See "Manual-Only Verifications" below.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-T1 | 04-01 | 1 | EXPORT-01, EXPORT-04 | T-04-08, T-04-11, T-04-12, T-04-13 | Credential path existence-checked only, never read or logged; asset-prefix guard test written before the guard exists; round-trip test deletes its own asset | unit (RED) | `.venv/Scripts/python -m pytest tests/test_export.py -v` | ✅ created by this task (Wave 0) | ⬜ pending |
| 04-01-T2 | 04-01 | 1 | EXPORT-01, EXPORT-04 | T-04-03, T-04-11, T-04-13 | D-07 destination fixed to the project's own asset namespace (`toDrive`/`toCloudStorage` absent); asset-id prefix guard raises before any EE call; paginated read-back instead of unbounded `getInfo()`; run artefacts gitignored | credential-free unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_export.py -v` | ✅ | ⬜ pending |
| 04-01-T3 | 04-01 | 1 | EXPORT-01 | T-04-09, T-04-12 | Real asset-write permission proven rather than assumed; quota-consuming test is opt-in; no artefact left in the live project | live-EE integration (opt-in) | `RUN_EE_BATCH_ROUNDTRIP=1 .venv/Scripts/python -m pytest tests/test_export.py -k round_trip -v --durations=3` | ✅ | ⬜ pending |
| 04-02-T1 | 04-02 | 1 | EXPORT-03 | T-04-06, T-04-14, T-04-15 | D-08 non-zero fallback value and D-09 provenance flag pinned before implementation; pre-existing null-not-dropped assertion preserved byte-identical | live-EE unit (RED) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k zonal -v` | ✅ | ⬜ pending |
| 04-02-T2 | 04-02 | 1 | EXPORT-03 | T-04-06, T-04-07, T-04-14, T-04-15, T-04-16 | Centroid fallback yields a genuine value, never a fabricated 0; `ee.Filter.Not(inList)` complement prevents double-reduction; small-ward detection structurally cannot run per-day; `used_fallback_reducer` set on both paths | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_heatwave_detection.py -k zonal -v` | ✅ | ⬜ pending |
| 04-03-T1 | 04-03 | 2 | EXPORT-02, EXPORT-03, EXPORT-04 | T-04-04, T-04-05, T-04-06, T-04-17, T-04-18, T-04-19 | Dec/Jan ISO boundary, hand-computed group values, exact schema set-equality, event-start counting and the null-vs-zero split all pinned before implementation | live-EE unit (RED) | `.venv/Scripts/python -m pytest tests/test_export.py -v` | ✅ | ⬜ pending |
| 04-03-T2 | 04-03 | 2 | EXPORT-02 | T-04-04 | ISO week-year derived from the Thursday-of-week formula, never `ee.Date.get('year')`; zero-padded week number | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_export.py -k "module_exports or iso_time_period" -v` | ✅ | ⬜ pending |
| 04-03-T3 | 04-03 | 2 | EXPORT-02, EXPORT-03 | T-04-05, T-04-06, T-04-17, T-04-18, T-04-19 | Single composite-key `.group()` only; canonical ward-week key backbone with outer joins so no row is lost; nulls preserved for heat-index columns while counts get genuine zeros; final row rebuilt as a fresh `ee.Feature` so no internal property leaks | live-EE unit (GREEN) | `.venv/Scripts/python -m pytest tests/test_export.py -v --durations=5` | ✅ | ⬜ pending |
| 04-04-T1 | 04-04 | 3 | EXPORT-01, EXPORT-03, EXPORT-04 | T-04-01, T-04-02, T-04-03 | ASVS V5 date rejection, deterministic loss-free chunking and the two-directional coverage gate pinned before implementation | credential-free unit (RED) | `.venv/Scripts/python -m pytest tests/test_export.py -k batch_export -v` | ✅ | ⬜ pending |
| 04-04-T2 | 04-04 | 3 | EXPORT-01, EXPORT-02, EXPORT-03 | T-04-01, T-04-02, T-04-03, T-04-07, T-04-20, T-04-21 | `date.fromisoformat` validation wired as argparse `type=` so it cannot be bypassed; coverage gate + atomic `os.replace` so the output is absent-or-complete; per-chunk ward ids bound as defaults, not captured; chunk header schema verified before merge; `find_small_wards` called exactly once | credential-free unit (GREEN) + opt-in live pipeline smoke | `.venv/Scripts/python -m pytest tests/test_export.py -v --durations=5` | ✅ | ⬜ pending |
| 04-04-T3 | 04-04 | 3 | EXPORT-01, EXPORT-02, EXPORT-03 | T-04-22, T-04-11 | `--stage plan` shows ward/chunk/small-ward counts and the quota-and-hours warning without submitting; blocking human go/no-go with a measured per-chunk runtime before the full backfill | checkpoint (human-verify) + CLI | `.venv/Scripts/python scripts/run_batch_export.py --stage plan` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Requirement coverage cross-check

| Req ID | Covered by | `-k` selector |
|--------|------------|----------------|
| EXPORT-01 | 04-01-T1/T2/T3, 04-04-T1/T2/T3 | `-k batch_export`, `-k round_trip` (opt-in), `--stage plan` CLI |
| EXPORT-02 | 04-03-T1/T2/T3, 04-04-T2 | `-k schema`, `-k iso_time_period` |
| EXPORT-03 | 04-02-T1/T2, 04-03-T1/T3, 04-04-T1/T2 | `-k completeness`, `-k zonal`, `-k batch_export` |
| EXPORT-04 | 04-01-T1, 04-03-T1, 04-04-T1 | `pytest tests/test_export.py -x` (the file itself) |

### Decision coverage cross-check

| Decision | Cited in |
|----------|----------|
| D-01 (full 1991-present backfill) | 04-04 (default export range derived from `settings.climatology.baseline_start_year`) |
| D-02 (hours, real quota) | 04-04 (`--stage plan` warning, T-04-22, blocking operator checkpoint) |
| D-03 (async batch export, not `getInfo`) | 04-01 (`Export.table.toAsset(...).start()`) |
| D-04 (submit then poll, process not held open) | 04-01 (`submit_or_resume` / `poll_until_complete` are separate calls) |
| D-05 (chunking, one final table) | 04-01 (resumable task-state file), 04-04 (chunk planner + re-concatenation) |
| D-06 (CSV to `outputs/`, exact schema) | 04-03 (`COVARIATE_COLUMNS`), 04-04 (`outputs/covariate_table.csv`) |
| D-07 (no new cloud infrastructure) | 04-01 (asset-namespace destination only), 04-04 (no Drive/GCS/BigQuery reference) |
| D-08 (small-ward fallback, never null-to-zero) | 04-02 (centroid fallback), 04-03 (null preserved through aggregation) |
| D-09 (fallback use detectable/loggable) | 04-02 (`used_fallback_reducer` per row, `find_small_wards`), 04-04 (`outputs/small_wards_report.csv` + stderr count) |

---

## Wave 0 Requirements

- [ ] `tests/test_export.py` — new file, this phase's own deliverable (EXPORT-04). Created by **04-01-T1**, the first task of the phase. Follows the skip-gated, live-EE pattern from `tests/test_heatwave_detection.py`.
- [ ] `heatwave/batch.py` — new file, Earth Engine async export harness (toAsset submission, resumable task-state file, polling, paginated read-back, CSV writing). Created by **04-01-T2**.
- [ ] `heatwave/export.py` — new file, weekly-aggregation logic (ISO-week keying, composite-key group-by, event-start-week counting). Created by **04-03-T2** and **04-03-T3**.
- [ ] `scripts/run_batch_export.py` — new file, chunk planner + task submission/polling + coverage-gated CSV concatenation. Created by **04-04-T2**. A production entry point, not exercised at full scale by the test suite.
- [ ] A real (not purely synthetic) `Export.table.toAsset()` round-trip — submit a tiny real task, poll to `COMPLETED`, read back via pagination, delete. Executed by **04-01-T3**, early in Wave 1, to close 04-RESEARCH.md's `[ASSUMED]` asset-write-permission row and Open Question 3 before later plans build on them.
- [ ] A live proof of Pattern 4's two-stage event-start-week composition (04-RESEARCH.md Assumption A4). Closed by **04-03-T1/T3**'s `test_heatwave_event_count_counts_event_starts_not_touched_weeks`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full 1991-present production export completes and produces a complete, correct CSV for all 4,841 wards | EXPORT-01, EXPORT-03 | Genuinely large (~hours), chunked across ~10-25 Earth Engine batch tasks, consuming real quota — cannot run inside the fast per-task/per-wave test loop | Run `.venv/Scripts/python scripts/run_batch_export.py` for the full default date range as a deliberate, monitored, one-time (or occasional) invocation. The script's own coverage gate enforces EXPORT-03 completeness before writing `outputs/covariate_table.csv`; verify row counts and the header against EXPORT-02 afterward |
| Operator go/no-go on launching that full backfill | D-01, D-02 | A cost and runtime decision that belongs to the human, not the executor | Blocking checkpoint **04-04-T3**: review the real chunk plan, the D-09 small-ward report, a real small-sample CSV, and the measured per-chunk wall-clock time, then approve or defer |

**Explicitly NOT a completion criterion for this phase:** the existence of a full-scale
`outputs/covariate_table.csv`. Phase 4 is complete when the script is verified correct on small samples
and its chunk plan for the real 4,841-ward asset is sound.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 11 tasks carry an `<automated>` command
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — zero tasks lack one
- [x] Wave 0 covers all MISSING references — `tests/test_export.py`, `heatwave/batch.py`, `heatwave/export.py`, `scripts/run_batch_export.py`, the live toAsset round-trip and the Assumption A4 proof are each owned by a named task
- [x] No watch-mode flags — every command is a single-shot `pytest` or CLI invocation
- [x] Feedback latency < 30s — for all ungated tests; the two opt-in live tests are documented above with their owning tasks and rationale
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner, 2026-09-15)
