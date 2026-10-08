---
phase: 9
slug: features-targets-splits-and-leakage-suite
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-10-06
---

# Phase 9 — Validation Strategy

> Per-phase validation contract. Derived from `09-RESEARCH.md` § Validation Architecture, updated for the 2026-10-06 framing decision (latency 0; no live Earth Engine query in this phase).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.1 (`pyproject.toml`, marker `frozen`; `tests/conftest.py` auto-skips `frozen` tests when the data is absent) |
| **Quick run command** | `.venv/Scripts/python.exe -m pytest tests/forecast -q -m "not frozen and not slow"` (CI and the full local gate run without the `slow` filter: `pytest -v` / `-m "not frozen"`) |
| **Full suite command** | `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q` |
| **Frozen-data command (local only)** | `.venv/Scripts/python.exe -m pytest tests/forecast -q -m frozen` (the session-scoped `load_panel` takes about 20 s) |
| **Estimated runtime** | quick < 60 s; frozen ~1-2 min |

---

## Sampling Rate

- **After every task commit:** run the quick run command.
- **After every plan wave:** run the full suite command.
- **Before `/gsd:verify-work`:** the full suite and the frozen command are green, and CI is green.
- **Max feedback latency:** 60 seconds, for the quick `-m "not frozen and not slow"` suite only (about 50 s; the `slow` marker covers the subprocess-heavy Phase 8 script/git/ML-import tests, which are not skipped by default or in CI). Frozen (`-m frozen`) runs are local only: once per plan, for the tasks that have a @frozen test, and in full at the 09-08 gate. They are not bound by the 60 s limit (the session panel load alone takes about 20 s).

---

## Per-Task Verification Map

One row per task (filled by the planner, 2026-10-06). Wave 0 = plan 09-01 (fixtures + config); every later task has its own automated test.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 9-01-01 | 09-01 | 1 | FEAT-05 | T-9-02 | cv_first_year 2005 validated (int, train start < Y <= validate end); embargo_weeks 14; 5 rejection cases | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_config.py -q` | modify | ✅ green |
| 9-01-02 | 09-01 | 1 | FEAT-04 | T-9-04, T-9-07 | synthetic_panel (1991-W02..2003-W20, W53 1992/1998), truncate/poison/subset return new Panels; static fixture hashes match MANIFEST; session frozen_panel | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_fixtures.py tests/forecast/test_forecast_data.py tests/forecast/test_forecast_verify_script.py -q` | ❌ W0 | ✅ green |
| 9-02-01 | 09-02 | 2 | FEAT-03 | T-9-03, T-9-04 | static table from hash-verified geojson + LGA-average csv; 6 empty geometries take LGA-union centroid; 6 wards flagged; @frozen 4841 wards, geozones NWZ 2004 / NCZ 1518 / NEZ 1319 | unit + @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_static.py -q -m "not frozen"` (frozen: same file with `-m frozen`, local) | ❌ W0 | ✅ green |
| 9-02-02 | 09-02 | 2 | FEAT-03, FEAT-04 | T-9-02 | climatology fit only on week_start < end; W53 pools with W52 and W01; std floor 0.1 x median; bit-identical under poisoned held-out weeks; @frozen fit range 1991-W02..2014-W52 (1251 weeks) | unit + @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_climatology.py -q` | ❌ W0 | ✅ green |
| 9-03-01 | 09-03 | 2 | FEAT-01, FEAT-02 | T-9-01 | label_k[:, t] == heatwave_days[:, t+k] >= 3 (independent date join); tail masked; label differs from heatwave_event_count; effective days +1/+8/+15/+22/+29/+36 at latency 0 (and -8..27 at 9); W53/year-end boundaries; @frozen 2026-W38 -> 2026-W39 | unit + @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_targets.py -q` | ❌ W0 | ✅ green |
| 9-03-02 | 09-03 | 2 | FEAT-05 | T-9-02 | assign by target week start; 2020-W53 validate; embargo 14 = max(leads)+8, last train target 2014-W38; 16 CV folds 2005-2020 with max(train) < min(validate) - embargo; index-only (no data values) | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_splits.py -q` | ❌ W0 | ✅ green |
| 9-04-01 | 09-04 | 3 | FEAT-03, FEAT-04 | T-9-01 | registry rejects max_lookahead != 0 and duplicates; FORBIDDEN_NAME_PATTERN rejects ward_id/wardcode/location/year but accepts lga_average_ward; lag/trailing windows full-window-or-NaN hand-checked; recent-heat (35) and land/humidity (6) families | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_registry.py tests/forecast/test_forecast_features.py -q -m "not frozen"` | ❌ W0 | ✅ green |
| 9-04-02 | 09-04 | 3 | FEAT-03 | T-9-01, T-9-07 | 10-year base rate vectorised over t, using prior-year anchors only (first valid 1994-W04 = position 159; matches an independent reference; W53 anchors fall back to W52); LGA/state same-week means | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_features.py -q -m "not frozen"` | ❌ W0 | ✅ green |
| 9-04-03 | 09-04 | 3 | FEAT-03, FEAT-04 | T-9-01, T-9-02, T-9-07 | static (incl. lga_average_ward, accepted by FORBIDDEN_NAME_PATTERN) and season (target-week doy/365.25) features; 58 specs; never refits the climatology; @frozen full build float32, no NaN after position 159 | unit + @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_features.py tests/forecast/test_forecast_registry.py -q -m "not frozen"` (frozen: features file with `-m frozen`, local) | ❌ W0 | ✅ green |
| 9-05-01 | 09-05 | 4 | FEAT-01, FEAT-02, FEAT-05 | T-9-01, T-9-02 | lead rows carry all timing fields, label and split; embargo and warm-up applied; issue table has one row per (ward, origin) with 6 lead label columns; store fitted on the wrong range rejected | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_dataset.py -q` | ❌ W0 | ✅ green |
| 9-05-02 | 09-05 | 4 | FEAT-05, FEAT-03 | T-9-02, T-9-04, T-9-08 | per-fold climatology refit (fit_end = fold year start) unchanged by fold validation values; cache under <local_data_dir>/forecast_cache/<sha8>/<cfg8> only, refuses repo/frozen paths, meta mismatch = miss, allow_pickle=False | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_dataset.py -q` | ❌ W0 | ✅ green |
| 9-06-01 | 09-06 | 5 | FEAT-04, FEAT-05, FEAT-01 | T-9-01, T-9-02 | (a) truncation, (b) poison (garbage + NaN), (c) train-only stats incl. folds, (d) registry, (e) mutation: lead shift / centred / full-mean / past-end climatology all caught, (f) split + fold integrity, (g) target alignment | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_leakage.py -q` | ❌ W0 | ✅ green |
| 9-06-02 | 09-06 | 5 | FEAT-04 | T-9-01, T-9-02, T-9-07 | @frozen (a)/(b) on a 200-ward subset x ~10 origins (incl. 2014-W52, 2020-W53, 2026-W38); real climatology train-only; real split cutoffs and label alignment | @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_leakage_frozen.py -q -m frozen` | ❌ W0 | ✅ green |
| 9-07-01 | 09-07 | 5 | FEAT-06, FEAT-02 | T-9-09 | prevalence by year (partial flagged), region (geozone + far north / central / middle belt), era, split; effective-days table; row counts per lead x split; caption twice; operational-delay note (about 9 days, 2026-10-06); no 'accuracy' | unit | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_report.py -q -m "not frozen"` | ❌ W0 | ✅ green |
| 9-07-02 | 09-07 | 5 | FEAT-06 | T-9-04, T-9-05 | script writes run folder (manifest completed, 6 CSVs, markdown) and docs/forecast/DATA_REPORT.md; refuses frozen/outputs/keys/non-.md paths; no ee import; @frozen overall prevalence 10-13%, eras within 1 pp of 6.6/11.2/11.6/21.5 | subprocess + @frozen | `.venv/Scripts/python.exe -m pytest tests/forecast/test_forecast_report.py -q` | ❌ W0 | ✅ green |
| 9-08-01 | 09-08 | 6 | FEAT-01..06 | T-9-01, T-9-02, T-9-04 | full suite + frozen suite green; isolation test; no outputs/keys/cache/run paths tracked; verify_frozen --outputs-only 0 mismatches | regression | `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py tests/forecast -q` | ✅ | ✅ green |
| 9-08-02 | 09-08 | 6 | FEAT-01..06 | T-9-05, T-9-10 | CI green on the branch after user-approved push | manual checkpoint | `gh run list --branch gsd/phase-09-features --limit 1` | N/A | ⏳ pending user-approved push |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Threat refs:**
- T-9-01: target or future information leaking into features (silent optimism).
- T-9-02: held-out (validation or test) data influencing training statistics or split membership.
- T-9-03: tampered ward metadata (wards.geojson / wards_lga_average.csv) parsed without a MANIFEST hash check.
- T-9-04: writes into the frozen folder, outputs/ or keys/, or cache/run folders inside the repo.
- T-9-05: credential disclosure (no Earth Engine use in this phase; explicit staging; push only on approval).
- T-9-07: memory exhaustion on the real panel (float32, family-by-family, session-scoped load).
- T-9-08: stale or crafted feature cache served as features.
- T-9-09: report misread (label definition, reanalysis caveat, regime shift).
- T-9-10: compromised GitHub credentials (use `gh auth login --web`).

---

## Wave 0 Requirements

- [x] `heatwave/forecast/fixtures.py`:
  - `synthetic_panel(n_wards=6, first_week="1991-W02", last_week="2003-W20", seed)`, an in-memory Panel covering the 1992 and 1998 W53 weeks and more than 10 years of history;
  - a static fixture (wards.geojson with geometries, including one empty geometry, plus `wards_lga_average.csv` and MANIFEST entries).
- [x] `config.py`, `forecast.yaml` and `test_forecast_config.py`: add `cv_first_year` (2005) and set `embargo_weeks: 14`, with updated assertions and rejection cases. `latency_days: 0` and `gate.primary_leads: [1, 2]` are already done (commit c2d4d50).
- [x] New test modules: `test_forecast_{targets,features,climatology,static,splits,leakage,report}.py`.
- [x] `scripts/forecast_data_report.py` and the `docs/forecast/` directory.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI green on the branch | FEAT-01-06 | GitHub Actions | Push only with user approval, then check the Actions run |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] nyquist_compliant flag set in frontmatter

**Approval:** passed (local and CI, run 37684002080, 2026-10-07)
