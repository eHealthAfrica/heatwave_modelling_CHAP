# Pre-registration: single test evaluation of the heatwave-week forecast

Written 2026-10-13, before the test years 2021-2026 were opened. Once this file is committed and
the test lock is opened against it, nothing below may change: any change re-closes the lock.

## Primary metric

Brier skill score (`gate.metric`) of the candidate against the reference forecast per lead
(`gate.reference`: the best baseline).

## Candidate forecast

The predictor `forecast` from the frozen model bundle. Per lead it is the model selected in Phase 12
by CV Brier: LightGBM at leads 1-4 and logistic regression at leads 5-6. Its Phase 12 settings come
from `docs/forecast/MODEL_SELECTION.json` (run `20261013T124205Z_b82dc7bd`). It is refitted on target
weeks 1991-2020 (up to the test start minus the 14-week embargo; at most 1,500,000 sampled rows per
lead, seed 20261002), and calibrated with the method chosen in `docs/forecast/RECALIBRATION.json`
(isotonic at lead 1, Platt at leads 2-6). The calibrator is fitted on expanding-window out-of-fold
predictions for 2015-2020. The summary is in `docs/forecast/MODEL_BUNDLE.json`.

## Primary leads

Leads 1 and 2 (`gate.primary_leads`).

## Reference forecasts

Reference choice per lead: the best baseline per lead from `docs/forecast/BASELINES_VALIDATION.md`
(damped_persistence at leads 1-2; trend_season at leads 3-6), refitted on 1991-2020 and recalibrated
on 2015-2020 out-of-fold predictions exactly like the candidate. In the outputs this is the predictor
`damped_persistence_recal` at leads 1-2 and `trend_season_recal` at leads 3-6. The uncalibrated best
baseline and recent_climatology are reported as secondary comparisons; they do not decide anything.

## Confidence interval method

Paired week-block bootstrap: block length `evaluation.block_weeks` (4) weeks,
`evaluation.bootstrap_b` (1000) replicates, the global `seed` (20261002), level `gate.ci_level`
(0.95). A year-block bootstrap is reported as a coarse check and does not decide anything. Wards are
never resampled.

## Go / no-go rule

Go when, on every primary lead, the BSS of `forecast` against the reference is greater than
`gate.threshold` and the lower end of its week-block CI is also greater than `gate.threshold`.
Otherwise no-go. Thresholds as registered: `gate.threshold` = 0.0 on leads 1 and 2.

Leads 3-6 are judged with the same rule for the skill mask. They do not change the go/no-go.

## Confirmatory slices

Only these slices are confirmatory: none (the per-lead result on all wards is the only confirmatory
result). Season, geopolitical-zone, latitude-band and ward-size slices are exploratory and are
labelled so in the report (PITFALLS M5).

## Expectation stated in advance

On validation the selected models tied the equally recalibrated best baseline (BSS -0.003 at lead 1
and -0.004 at lead 2, CIs spanning 0). The expected outcome is therefore no-go. On a no-go, the
report names the leads without skill and recommends the ECMWF S2S benchmark. Phases 15-16 then run
only for leads that passed.

## Frozen identifiers

- config sha256: b82dc7bdc42485fafb369e36828d3adefe1e2ca5264c47161918c5ebdf542def
- model bundle sha256: f27f9bafc986d136aff9c5dac6d4961d164239f11ee972130b7cd890ccb79190

The bundle lies at `forecast_runs/20261013T160730Z_b82dc7bd/model_bundle.joblib` under the local
data root.

## Retrain policy

As in the `retrain_policy` block of `forecast.yaml`: refit on 1991-2020 with frozen
hyperparameters before the single test (done: the bundle above). The operational model is refit on
all years and labelled "not independently tested".

## Test years

2021-2026, scored once by `scripts/forecast_test.py`.
