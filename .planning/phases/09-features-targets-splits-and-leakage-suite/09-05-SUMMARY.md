---
phase: 09-features-targets-splits-and-leakage-suite
plan: 05
subsystem: forecast
tags: [dataset, issue-rows, embargo, cv-folds, cache]
requires: [09-02, 09-03, 09-04]
provides:
  - heatwave.forecast.dataset (row assembly, fold stores, feature cache)
affects: [09-06, 09-07, 09-08]
key-files:
  created:
    - heatwave/forecast/dataset.py
    - tests/forecast/test_forecast_dataset.py
key-decisions:
  - "Fit-end guard normalises both the store's ISO-string fit_end and cfg.splits.train_end / fold.climatology_end to datetime.date before comparing"
  - "lead_weeks is one column (in TIMING_COLUMNS and the calendar registry); season sin/cos are per-lead and only in lead_rows"
  - "Cache format: one float32 .npy per feature plus store_meta.json, under <local_data_dir>/forecast_cache/<data_sha8>/<config_hash8>/clim_<YYYYMMDD>/"
requirements-completed: []
duration: ~20 min
completed: 2026-10-06
---

# Phase 9 Plan 05: Dataset assembly Summary

Per-lead and wide issue-row tables carrying all timing fields, labels and splits, with warm-up drop, 14-week embargo, date-normalised fit-range guards, per-fold climatology refits and an optional out-of-repo feature cache.

## Commits
- c74e522: `feat(09-05): issue-row and per-lead dataset assembly, fold stores, feature cache` (both tasks in one commit; tests and implementation written together)

## Public APIs (`heatwave.forecast.dataset`)
- Constants: `TIMING_COLUMNS` (8 fields), `LABEL_COLUMN="heatwave_week"`, `SPLIT_COLUMN="split"`, `CACHE_SUBDIR="forecast_cache"`
- `warmup_first_position(panel) -> int` (159 = 1994-W04 on synthetic and real calendars)
- `lead_row_index(panel, cfg, lead, split, *, fold=None, drop_warmup=True) -> (ward_pos, origin_pos)` ordered by origin then ward; labelled origins only; embargo via `split_masks` / `fold_masks`
- `lead_rows(panel, store, static, cfg, lead, split, *, fold=None, drop_warmup=True, feature_names=None) -> DataFrame`: `ward`, timing columns, `heatwave_week` (int8), `split`, then float32 features (panel, static, season sin/cos, `lead_weeks`); ValueError if store fit end != train_end (or fold.climatology_end), KeyError on unknown feature, ValueError on lead not in cfg.leads
- `build_issue_table(panel, store, static, cfg, *, origin_positions, ward_positions=None, feature_names=None)`: one row per (ward, origin); `target_week_index_l{k}`, `target_week_l{k}`, `target_week_start_l{k}`, `effective_days_ahead_l{k}`, `heatwave_week_l{k}` (NaN if unlabelled), `has_label_l{k}`, `split_l{k}`, plus panel and static features. Origins limited to panel positions 0..T-1 (last origin is the operational row)
- `build_fold_store(panel, static, fold, *, registry, names) -> (Climatology, FeatureStore)` per-fold refit
- `feature_cache_dir(cfg, panel, data_root=None)`, `save_feature_store(store, clim, directory, *, registry_names)`, `load_feature_store(directory, panel, clim, *, names, registry_names=None) -> FeatureStore | None`

## Verification
- `pytest tests/forecast -q -m "not frozen"`: 363 passed, 12 deselected (98 s, dominated by Phase 8 subprocess tests); dataset tests run in ~1 s
- Grep gates: no ffill/bfill/fillna/interpolate; `allow_pickle=False` x2; no forecast_cache path in git status

## Deviations from Plan
- `load_feature_store` accepts an optional extra `registry_names` keyword (compared against meta when given); otherwise as planned.
- Issue-table origins beyond the panel end are rejected (features do not exist there); the last panel origin serves as the operational row.

## Requirements
FEAT-01/02/03/05 each have remaining parts (leakage suite, reporting); left pending.

## Self-Check: PASSED
