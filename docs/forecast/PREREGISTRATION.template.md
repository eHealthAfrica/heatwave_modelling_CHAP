# Pre-registration (TEMPLATE)

## Instructions

This is a template. In Phase 14, copy it to `docs/forecast/PREREGISTRATION.md`, replace every
`<<FILL>>` token, commit the file, and only then call `heatwave.forecast.testlock.open_lock`.
The lock re-closes if this file or `forecast.yaml` changes after opening. A file that still
contains a placeholder token is refused. Do not commit hashes into this template.

## Primary metric

Brier skill score (`gate.metric`) against the best baseline per lead (`gate.reference`).

## Primary leads

Leads 1 and 2 (`gate.primary_leads`).

## Reference forecasts

The best baseline per lead, taken from `docs/forecast/BASELINES_VALIDATION.md`. At the time of
writing this is damped_persistence at leads 1-2. Reference choice per lead: <<FILL>>

## Confidence interval method

Paired week-block bootstrap: block length `evaluation.block_weeks` weeks, `evaluation.bootstrap_b`
replicates, the global `seed`, level `gate.ci_level`. A year-block bootstrap is reported as a coarse
check. Wards are never resampled.

## Go / no-go rule

Go when BSS > `gate.threshold` against the best baseline on every primary lead and the CI excludes
the threshold. Otherwise no-go. Thresholds as registered: <<FILL>>

## Confirmatory slices

Only these slices are confirmatory: <<FILL>>. All other slices are exploratory and are labelled so
in the report (PITFALLS M5).

## Frozen identifiers

- config sha256: <<FILL>>
- model bundle sha256: <<FILL>>

## Retrain policy

As in the `retrain_policy` block of `forecast.yaml`: refit on 1991-2020 with frozen
hyperparameters before the single test; the operational model is refit on all years and labelled
"not independently tested".

## Test years

2021-2026, scored once.
