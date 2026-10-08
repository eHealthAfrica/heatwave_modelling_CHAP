---
phase: 10-baselines-evaluation-harness-and-test-lock
plan: 01
subsystem: forecast-evaluation
tags: [test-lock, evaluation-log, config, pre-registration, EVAL-05]
requires: [forecast config (Phase 8), artifacts._git/RUNS_SUBDIR (Phase 8)]
provides: [testlock module, evaluation config keys, test isolation fixtures, pre-registration template]
affects: [10-03 dataset guards, 10-05 prediction loader, 10-07 harness, 10-08 script, Phase 14]
tech-stack:
  added: []
  patterns: [hash-chained JSONL audit log, closed-by-default lock, private injectable git runner]
key-files:
  created:
    - heatwave/forecast/testlock.py
    - tests/forecast/test_forecast_testlock.py
    - docs/forecast/PREREGISTRATION.template.md
  modified:
    - heatwave/forecast/config.py
    - forecast.yaml
    - tests/forecast/test_forecast_config.py
    - tests/forecast/conftest.py
key-decisions:
  - "Lock API has no git parameter and no bypass flag; tests patch the private testlock._git_runner"
  - "Closed-lock path never calls git (lock file existence checked first)"
  - "Only the template exists in the repo; docs/forecast/PREREGISTRATION.md is Phase 14"
requirements-completed: []
duration: ~25 min
completed: 2026-10-08
---

# Phase 10 Plan 01: Test lock, evaluation log and config keys Summary

Closed-by-default test-split lock with a hash-chained append-only evaluation log, strict new config keys (shrinkage pseudo-count 50 and an evaluation section), tmp-root test isolation, and a pre-registration template only (lock never opened).

## Public APIs

config (`heatwave/forecast/config.py`, `forecast.yaml`):
- `BaselinesConfig.shrinkage_pseudo_count` (int >= 0, 50)
- `EvaluationConfig(bootstrap_b=1000, block_weeks=4 (min 4), reliability_bins=10 (min 2), auc_hist_bins=1000 (min 10))`, exposed as `ForecastConfig.evaluation` (after `gate`); strict, unknown or missing keys rejected.

`heatwave.forecast.testlock`:
- `TestLockError` (`__test__ = False`)
- `open_lock(cfg, *, model_bundle_path, opened_by, data_root=None, repo_root=REPO_ROOT) -> dict`
- `lock_status(cfg, *, data_root=None, repo_root=...) -> (bool, reason)` (no logging; no git call while closed)
- `require_open(cfg, purpose, *, predictor, lead, n_rows, run_id, data_root, repo_root) -> dict` (logs granted/refused, raises `TestLockError`)
- `labels_unlocked(cfg, purpose, *, n_rows, data_root, repo_root) -> bool` (never raises; logs granted or refused/"blanked")
- `log_event(event, *, outcome, split, predictor, lead, n_rows, run_id, config_sha256, purpose, reason, data_root) -> dict`, `read_log`, `verify_log_chain`, `count_test_runs`
- `preregistration_status`, `forecast_runs_dir`, `lock_path`, `log_path`, `_default_data_root` (single patch point), `_git_runner` (private)
- constants `PREREG_RELPATH`, `TEMPLATE_RELPATH`, `LOCK_NAME`, `LOG_NAME`, `PLACEHOLDER`, `EVENTS`, `OUTCOMES`

tests/forecast/conftest.py fixtures: `_testlock_isolated_root` (session autouse), `testlock_root`, `allow_test_rows` (stubs `testlock.require_open` / `labels_unlocked`; reference via the module), `make_git_repo(path, *, autocrlf=False)`.

## Tasks and commits

1. Config keys: b813ee2
2. testlock module, fixtures, quick tests: f1128e5
3. Template and real-git slow tests: e119bf7

## Verification

- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 396 passed in 42.5 s.
- Full testlock module including slow: 33 passed in 12.9 s. Config tests: 113 passed.
- `config.yaml`, `heatwave/config.py`, `tests/test_config.py` untouched (blob pin tests pass).
- Real `<local_data_dir>/forecast_runs/` holds only two run folders: no TEST_LOCK.json, no evaluation_log.jsonl. `docs/forecast/PREREGISTRATION.md` does not exist.

## Deviations from Plan

None. The log chain cannot detect deletion of the final line (inherent to a prev-hash chain); the check covers edits and middle deletions as specified.

## EVAL-05 status

Not marked complete: this plan delivers the lock mechanism only. The loader guards (10-03, 10-05) and the real-log check at the phase gate (10-09) remain.

## Known Stubs

None.

## Self-Check: PASSED
