---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Heat Forecasting
status: in_progress
stopped_at: Phase 12 complete except reliability tolerance (direct, no GSD)
last_updated: "2026-10-13T11:10:00.000Z"
last_activity: 2026-10-13
progress:
  total_phases: 9
  completed_phases: 5
  total_plans: 24
  completed_plans: 23
  percent: 56
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-02)

**Core value:** A correct, complete weekly covariate table for all 4,841 wards in 19 northern states and the FCT, handed off to CHAP, plus honest, calibrated forecasts of its heat indicators that demonstrably beat simple baselines.
**Current focus:** Phase 12 calibration decision, then Phase 14 (Phase 13 deferred)

## Current Position

Milestone: v2.0 Heat Forecasting (Phases 8-16)
Phase: 12 (LightGBM, Calibration and Selection) — COMPLETE except criterion 3 (reliability tolerance)
Status: Phase 12 committed on `gsd/phase-12-lightgbm` (stacked on Phase 11, PR #14 open); waiting for the user's calibration decision
Last activity: 2026-10-13

Progress: [██████████] 96%

## Performance Metrics

v1.0: 7 phases shipped (archived in .planning/milestones/). v2.0: no plans completed yet.

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. v2.0 roadmap-level decisions:

- Phase numbering continues from v1.0 (Phases 8-16).
- Phase 14 go/no-go (leads 2-3) gates Phases 15-16; on a no-go, the next step is the ECMWF S2S benchmark.
- Phase 13 (secondary targets) is deferred if Phase 12 shows no skill over the best baseline.
- EVAL-06 (negative controls) is assigned to Phase 11, where the first model exists to test.
- Training uses only frozen `covariates-v1.0`, never the live `outputs/covariate_table.csv`.
- Test years 2021-2026 stay locked until pre-registration is committed (Phase 10 builds the lock, Phase 14 uses it once).
- [Phase 08]: shap fallback not needed; shap 0.52.0 works with numpy 2.3.3
- [Phase 08]: 08-02: week index 0 = 1991-W02; time arithmetic uses index/week_start, never label strings
- [Phase 11]: From Phase 11 on, phases run directly without GSD agents; `.planning` is updated by hand.
- [Phase 11]: Logistic (57 features) does not beat damped persistence at leads 1-2; mean p 0.117 vs observed 0.154 (prevalence shift). Negative control and decay check pass.
- [Phase 12]: LightGBM ties damped persistence at leads 1-2 (BSS -0.002 and -0.005) and beats logistic at leads 2-6. OOF calibration on folds 2010-2014 worsens under-prediction; reliability tolerance fails everywhere. Phase 13 deferred (no skill over best baseline).

### Pending Todos

None yet.

### Blockers/Concerns

- CHAP forecast-covariate column names (`heatwave_prob`, `heatwave_week`) are provisional; confirm with the CHAP team before Phase 15.
- Phase 16: ATL3 source not located; PSL parsing and BoM user-agent need checking.
- Phase 12 may need a design spike on real validation predictions (calibration fit set). Phase 11 shows the prevalence shift makes trained models under-predict; calibration must address it.
- Skill at leads 3-6 is unknown; the no-go branch is planned up front.
- PR #1 status and the potentially compromised GitHub PAT (from v1.0) remain as noted: use `gh auth login --web`.

## Deferred Items

| Category | Item | Status |
|----------|------|--------|
| Future | FUT-01 ECMWF S2S benchmark (triggered by a Phase 14 no-go) | Deferred |
| Future | FUT-02 ordinal heatwave-days target, FUT-03 Streamlit forecast page, FUT-04 station re-validation | Deferred |
| Phase 08 P02 | 10min | 2 tasks | 5 files |
| Phase 08 P06 | 25min | 2 tasks | 3 files |
| Phase 09 P07 | 40min | 2 tasks | 4 files |
| Phase 10 P01 | 25min | 3 tasks | 7 files |
| Phase 10 P09 | ~3h | 2 tasks | 2 files |

## Session Continuity

Last session: 2026-10-13
Stopped at: Phase 12 done; PR #14 (Phase 11) open; calibration decision pending
Resume file: None

## Operator Next Steps

- Review and approve the roadmap, then run `/gsd:plan-phase 8`
