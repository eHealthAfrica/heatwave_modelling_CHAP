---
phase: 10-baselines-evaluation-harness-and-test-lock
fixed_at: 2026-10-12
review_path: .planning/phases/10-baselines-evaluation-harness-and-test-lock/10-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 8
documented: 1
skipped: 0
status: all_fixed
---

# Phase 10: Code Review Fix Report

Branch gsd/phase-10-baselines. Nothing was pushed.

## Findings

| ID | Status | Commit |
|---|---|---|
| WR-01 | fixed | 95d56e3 |
| WR-02 | fixed | 43f5b7a |
| WR-03 | fixed | a71966c |
| WR-04 | fixed | 1aae38c |
| WR-05 | fixed | c75d57d |
| WR-06 | fixed | 5e65ad3 |
| WR-07 | fixed | 27ebc89 |
| WR-08 | documented, no behaviour change | 0cc918a |
| WR-09 | fixed | 779d75b |
| regenerated BASELINES_VALIDATION.md | docs | d42a420 |

Logic-level fixes (WR-01, 02, 04, 05, 07, 09) pass tests that exercise them but the semantics deserve human confirmation: the date-based test-window guard, the lock/log head binding, the one-shot rule.

Info items touched on the way: IN-05 (n_valid shown, via WR-03), IN-07 (tail-truncation test, drive-relative bundle path), IN-10 (lock/log files cannot be the bundle). Not done: IN-01..04, IN-06, IN-08, IN-09, IN-11 (files not otherwise edited).

## Design notes

- WR-01: `config.PINNED_TEST_START = 2021-01-04`; `SplitsConfig` requires `validate_end` equal to it and `test_years[0] == 2021`. `splits.protected_mask` is date-based; `dataset.lead_row_index` (non-test splits) and `predictions.build_frame` call `testlock.require_open` for any protected target week.
- WR-02: `load_predictions` reads only `target_week_index` and `split` first, requires the lock for protected rows before loading labels, and raises when the label disagrees with the derived split. `write_predictions(cfg=...)` does the same check.
- WR-03: `F1 = 2TP/(2TP+FP+FN)`, precision 0 when nothing is predicted positive, recall NaN only without positives; `*_n_valid` columns and a 'valid replicates' report column.
- WR-04: `TEST_LOCK.json` gains `log_head_sha256` (hash of the `lock_opened` record). `lock_status` closes the lock on a missing log, broken chain or missing head. `count_test_runs` raises on a broken chain.
- WR-05: text check on `git show HEAD:docs/forecast/PREREGISTRATION.md`, labelled `config sha256:` and `model bundle sha256:` lines, HTML comments ignored.
- WR-06: `score_lead` compares config hash, data hash across files and against `ScoringContext.data_sha256`.
- WR-07: `test_evaluation_opened` event, `open_test_evaluation` (second evaluation by another run and repeat lead scoring refused), `count_test_runs` counts those events, `baselines_report.locked_note(meta)` derives the report sentence from the verified log (chain, opened evaluations, test scores for this run).
- WR-09: `week_block_indices`/`week_block_multiplicity` are moving blocks starting in `[0, W - block]`; default block stays 4. `LeadResult.block_sensitivity` holds BSS CIs at 8 and 13 week blocks; the report has a 'Block-length sensitivity' section.

## Test results

- Quick loop `pytest tests/forecast -q -m "not frozen and not slow"`: 531 passed, 94 deselected in 49.18 s (51.7 s wall). It was about 59 s before.
- Full forecast suite `pytest tests/forecast -q`: 625 passed, 1 warning in 503.52 s.
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py -q`: 59 passed.
- `scripts/verify_frozen.py --outputs-only`: 4 checked, 0 mismatches, 0 missing, 0 bad keys.

## Real run and manifest finding

The coordinator saw run folder `20261009T075938Z_b82dc7bd` without `RUN_MANIFEST.json`. That was an observation while the script was still running: `run_folder` writes the final manifest only when the run finishes. The run exited 0, and the manifest is present with `status: completed` (started 2026-10-09T07:59:38Z, finished 08:17:17Z), the same as the earlier run `20261008T214852Z_b82dc7bd`. WR-04/WR-07 did not affect manifest writing. No re-run was needed, no run folder or log line was deleted.

Real evaluation log after the run: 95 records (55 + 40 new validate/train score records), hash chain intact, `count_test_runs` = 0, no `TEST_LOCK.json`, no `docs/forecast/PREREGISTRATION.md`.

## Before and after (validation 2015-2020, B=1000, previous = 53e4d38)

Points are unchanged: Brier lead 1 damped_persistence 0.1249, lead 2 damped_persistence 0.1322, leads 3-6 trend_season 0.1331/0.1331/0.1331/0.1332, climatology 0.1376, recent_climatology 0.1365. BSS points vs recent_climatology are unchanged (lead 1 damped_persistence 0.0852, trend_season 0.0254). Year-block intervals are unchanged. Only week-block intervals moved (non-circular blocks), mostly slightly wider at the lower end.

| Quantity | Before week CI | After week CI |
|---|---|---|
| Brier lead 1 climatology | [0.1120, 0.1638] | [0.1124, 0.1667] |
| Brier lead 1 damped_persistence | [0.1034, 0.1462] | [0.1038, 0.1472] |
| BSS lead 1 damped_persistence vs recent_clim | [0.0418, 0.1290] | [0.0385, 0.1292] |
| BSS lead 1 trend_season | [0.0105, 0.0400] | [0.0092, 0.0356] |
| BSS lead 2 damped_persistence | [0.0083, 0.0555] | [0.0059, 0.0548] |
| BSS lead 2 trend_season | [0.0109, 0.0388] | [0.0091, 0.0362] |
| BSS lead 3 trend_season | [0.0109, 0.0390] | [0.0087, 0.0360] |
| BSS lead 3 damped_persistence | [-0.0102, 0.0406] | [-0.0124, 0.0334] |

No interval changed sign: trend_season stays above 0 at every lead; damped_persistence is above 0 at leads 1-2 only. The sensitivity table (8 and 13 week blocks) gives similar intervals, e.g. lead 1 damped_persistence [0.0402, 0.1295] and [0.0349, 0.1333], lead 2 [0.0037, 0.0529] and [0.0036, 0.0539]; the lower bound at lead 2 stays above 0 but gets close.
