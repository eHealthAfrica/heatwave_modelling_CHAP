---
phase: 10-baselines-evaluation-harness-and-test-lock
reviewed: 2026-10-08T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - heatwave/forecast/testlock.py
  - heatwave/forecast/baselines.py
  - heatwave/forecast/evaluation/metrics.py
  - heatwave/forecast/evaluation/bootstrap.py
  - heatwave/forecast/evaluation/slices.py
  - heatwave/forecast/evaluation/predictions.py
  - heatwave/forecast/evaluation/harness.py
  - heatwave/forecast/evaluation/baselines_report.py
  - heatwave/forecast/dataset.py
  - heatwave/forecast/config.py
  - scripts/forecast_baselines.py
  - forecast.yaml
  - docs/forecast/PREREGISTRATION.template.md
  - tests/forecast/conftest.py
  - tests/forecast/test_forecast_testlock.py
  - tests/forecast/test_forecast_baselines.py
  - tests/forecast/test_forecast_harness.py
  - tests/forecast/test_forecast_metrics.py
  - tests/forecast/test_forecast_bootstrap.py
  - tests/forecast/test_forecast_predictions.py
  - tests/forecast/test_forecast_slices.py
  - tests/forecast/test_forecast_baselines_script.py
  - tests/forecast/test_forecast_baselines_report.py
  - tests/forecast/test_forecast_leakage.py
findings:
  critical: 0
  warning: 9
  info: 11
  total: 20
status: warnings_fixed
fix_report: 10-REVIEW-FIX.md
---

# Phase 10: Code Review Report

**Reviewed:** 2026-10-08
**Depth:** standard (cross-file tracing for the lock and loaders)
**Files Reviewed:** 24
**Status:** warnings fixed (see 10-REVIEW-FIX.md); info items open

## Summary

Overall the design is sound. The test lock is recomputed on every access. It binds the config hash, the bundle sha256 and the git HEAD blob. `hash-object` with a path applies the clean filter, so CRLF is handled. The baselines fit on `train_index` rows only. `recent_climatology` reads only anchors at least about 50 weeks before the target. The paired bootstrap shares one multiplicity matrix per lead across predictors and slices. The BSS and dBS sign conventions are consistent between point estimates and replicates. The histogram AUC and the discrete-predictor Murphy edge change are correct on tracing (each distinct value lands in its own bin, and ties count 1/2).

No BLOCKER was found. The weaknesses are mostly places where the "lock closed" guarantee depends on the caller behaving, or where the audit trail does not actually audit. The most important are:

- WR-01: the script accepts an arbitrary `--config`, which bypasses the lock.
- WR-02: the loader trusts the `split` label instead of the target weeks.
- WR-03: F1 is NaN instead of 0 when tp = 0.
- WR-04: the log hash chain is never verified.
- WR-05: the pre-registration binding is weak.

## Warnings

### WR-01: `--config` lets the script relabel test years as "validate" and bypass the lock

**File:** `scripts/forecast_baselines.py:106,118,185` (root cause `heatwave/forecast/config.py:104-145`)
**Issue:** The lock keys on the split name `"test"`, but the split boundaries come from whatever config is loaded. `SplitsConfig` only checks that the ranges are contiguous. It does not pin `test_years` to 2021-2026. `--config alt.yaml` with `validate_years: [2015, 2026]` makes `lead_row_index(..., "validate")` return 2021-2026 rows. `build_frame` and `load_predictions` then treat them as validation, and the report and `LOCKED_NOTE` still say "test locked and unscored". The docstring claim "Only the train and validate splits are ever requested" is only true for the shipped config.
**Fix:** In the script (and ideally `load_forecast_config`), refuse a config whose `validate_years[1] >= 2021` or whose `test_years != (2021, 2026)`. Alternatively, drop `--config` or require it to equal `FORECAST_CONFIG_PATH`.
```python
if cfg.splits.validate_years[1] >= cfg.splits.test_years[0] or cfg.splits.test_years != (2021, 2026):
    return _bad("config splits must keep 2021-2026 as the test years")
```

**Status: fixed** (95d56e3). `SplitsConfig` pins the test window (`validate_end == 2021-01-04`, `test_years[0] == 2021`); `lead_row_index` and `build_frame` also require the lock for any row whose target week is on or after the pinned date, whatever the split label. The script reports an invalid `--config` as exit 2. Regression tests: pinned-window validation, tampered-config guards in `test_forecast_predictions.py`, script test with an extended `validate_years`.

### WR-02: `load_predictions` trusts the `split` label, not the target weeks

**File:** `heatwave/forecast/evaluation/predictions.py:211-233` (also `write_predictions:167-189`)
**Issue:** The lock check fires only if `meta.split == "test"` or the `split` column contains `"test"`. Neither the writer nor the loader recomputes the split from `target_week_index` via `splits.assign_split`. Only `build_frame` does that, and the writer does not require `build_frame`. A file labelled `validate` whose rows have 2021+ target weeks, labels included, is loaded and scored with no lock check and no log entry. This is the one loader in the stack that could enforce the invariant cheaply.
**Fix:** After reading, derive the split from the data:
```python
derived = splits.assign_split(df["target_week_index"].to_numpy(np.int64), cfg.splits, strict=False)
if (derived == "test").any() or (derived == "beyond_test").any():
    testlock.require_open(...)   # and require df["split"] == "test" for those rows
if (derived != df["split"].astype(str).to_numpy()).any():
    raise ValueError("split column disagrees with target_week_index")
```
Also call `require_open` before `pq.read_table` whenever `read_schema` shows test-range rows are possible, so the data is never in memory while the lock is closed.

**Status: fixed** (43f5b7a). `load_predictions` reads only the key columns first, derives the split from `target_week_index`, requires the lock before any label is loaded when protected rows exist, and rejects a label that disagrees with the derived split. `write_predictions(cfg=...)` enforces the same. Tests use a mislabelled file.

### WR-03: F1 is NaN rather than 0 when tp = 0 but both fp+fn > 0, and bootstrap drops those replicates

**File:** `heatwave/forecast/evaluation/metrics.py:194-199,354-358`; `bootstrap.py:69-79`
**Issue:** `_prf` computes `2*prec*rec/(prec+rec)`. With tp = 0, fp > 0 and fn > 0, prec = rec = 0, so F1 = 0/0 = NaN. The correct value is 0. This hits `prf_at_threshold` and every bootstrap replicate in which a resampled set of weeks has no true positive. `percentile_ci` silently ignores NaN replicates, so the F1 interval is truncated and biased upward for low-skill predictors at long leads. The `n_valid` count is discarded for P/R/F1 at `harness.py:215-217`, so the user never sees this.
**Fix:** Compute F1 as `2*tp / (2*tp + fp + fn)`, which is 0 when tp = 0 and fp+fn > 0 and NaN only when everything is zero. Keep NaN for precision when tp+fp = 0, but surface `n_valid` in the P/R/F1 tables.

**Status: fixed** (a71966c). F1 = 2TP/(2TP+FP+FN), precision = 0 when nothing is predicted positive (documented in `_prf`), recall NaN only without positives. `*_n_valid` is stored per P/R/F1 interval and shown as 'valid replicates' in the report (also closes IN-05).

### WR-04: The log hash chain is never verified and cannot detect tail truncation

**File:** `heatwave/forecast/testlock.py:166-183`, `log_event:109-150`; callers (none) in `heatwave/` and `scripts/`
**Issue:** `verify_log_chain` is referenced only by tests. Neither `lock_status`, `require_open`, `count_test_runs` nor the script calls it. A broken chain therefore does not close the lock, and `test_runs` in the report is read from a log whose integrity nobody checked. The chain also has no external anchor. Deleting the last N lines, or the whole log (`log_event` restarts at GENESIS), leaves a valid chain, and `count_test_runs` then reports 0 test runs. `test_log_chain_detects_edit_and_deletion` covers only edit and middle deletion.
**Fix:** Call `verify_log_chain` in `scripts/forecast_baselines.py` before using `count_test_runs` (fail loudly). Write the log head hash into `TEST_LOCK.json` or the run manifest at open time so truncation shows up. Record the head hash in each run manifest. Add a tail-truncation test.

**Status: fixed** (1aae38c). `TEST_LOCK.json` records `log_head_sha256` at open; `lock_status` re-closes the lock when the log is missing, its chain is broken or the head is gone (tail truncation, deletion, edit). `count_test_runs` and `open_lock` refuse a broken chain. The real 55-record log verifies intact (read-only check, frozen test). Also rejects drive/anchor bundle paths (part of IN-07).

### WR-05: Pre-registration binding is a substring check and ignores the bundle hash

**File:** `heatwave/forecast/testlock.py:229-239,289-295`
**Issue:**
- `config_hash(cfg) in text` is satisfied by the hash appearing anywhere, including inside a comment or HTML comment. It does not have to be the "config sha256:" frozen identifier.
- The template has a "model bundle sha256" frozen identifier, but the lock never checks that the pre-registration contains the bundle hash it opens with. `open_lock` accepts any bundle under `forecast_runs`, so the model scored can differ from the one pre-registered, and nothing notices.
- The text is read from the working tree after the blob comparison (`_preregistration_text_ok` does a separate `read_text`). That is a TOCTOU gap, and it also means the audited bytes are not the committed bytes (CRLF or filters).
- Only the literal `<<FILL>>` is rejected.
**Fix:** Read the committed blob (`git show HEAD:docs/forecast/PREREGISTRATION.md`) once, and test that blob. Require both `config sha256: <hash>` and `model bundle sha256: <hash>` lines via a regex anchored on those labels.

**Status: fixed** (c75d57d). The text check reads `git show HEAD:docs/forecast/PREREGISTRATION.md` and requires labelled lines `config sha256: <hash>` and `model bundle sha256: <hash>` (HTML comments ignored). The lock and log files cannot be the bundle (part of IN-10).

### WR-06: Stored predictions are not tied to the current config or data

**File:** `heatwave/forecast/evaluation/predictions.py:211-233`; `harness.py:118-147`
**Issue:** `PredictionMeta` stores `config_sha256` and `data_sha256`, but nothing compares them with `config_hash(cfg)` or the loaded panel, or across the predictors being compared. The harness will happily score and compare files produced under different configs, data pins or runs. `align` checks only keys and labels. Stale or mixed-provenance files therefore yield valid-looking comparisons. For the test split this also means the lock's config binding applies to the config passed in, not to the config that produced the predictions.
**Fix:** In `_load_aligned`, require every `meta.config_sha256 == config_hash(ctx.cfg)` and all `data_sha256` equal (or equal to the supplied panel hash). Raise on mismatch.

**Status: fixed** (5e65ad3). `score_lead` raises on a config hash different from the scoring config, on mixed `data_sha256` values, and on a mismatch with `ScoringContext.data_sha256` (the script passes the panel hash).

### WR-07: "Test run" accounting overcounts and single-shot scoring is not enforced

**File:** `heatwave/forecast/testlock.py:186-191`; `harness.py:254-258`; `evaluation/baselines_report.py:22-25`
**Issue:** The pre-registration says "Test years 2021-2026, scored once", but nothing enforces or even detects a repeat. `count_test_runs` counts every test `granted` and every test `scored` record. One test scoring of 5 predictors x 6 leads yields 30 `granted` (one per `load_predictions`) plus 30 `scored` records, plus any `build_frame` or `lead_rows` grants. The number printed in the report ("evaluation log test runs: N") is therefore not a run count and cannot show "scored once". `LOCKED_NOTE` also asserts "no test-split row was loaded or scored in this run" unconditionally, independent of what the log says.
**Fix:** Count distinct `run_id` values with a `scored` test record. Make `score_lead` for the test split refuse when a test `scored` record for the same config hash already exists, unless an explicit, logged override is given. Derive the LOCKED_NOTE text from the log instead of asserting it.

**Status: fixed** (27ebc89). One `test_evaluation_opened` event per evaluation; `count_test_runs` counts those. `open_test_evaluation` (called by `score_lead` on the test split) refuses a second evaluation by another run and a repeat scoring of a lead. The report sentence comes from `locked_note(meta)`, built from the verified log, not asserted.

### WR-08: Test-year label statistics are exposed unguarded by the Phase 9 report (lock gap)

**File:** `heatwave/forecast/report.py:38-60` (`prevalence_tables`, `ERAS` includes (2021, 2026)); `heatwave/forecast/dataset.py:197` (not in the Phase 10 diff, but the lock claims to cover all loaders)
**Issue:** `prevalence_tables` reads `targets.heatwave_week_matrix(panel)` over all years and publishes per-year and per-era (2021-2026) heatwave prevalence. It does not go through `testlock`. Test-period prevalence and trend are visible before the pre-registration, which informs threshold, reference and slice choices. The lock docstring admits raw arrays are unguarded, but this is a shipped report path, not a raw-array escape hatch.
**Fix:** Route the report's year and era rows with test years through `testlock.labels_unlocked` and blank them (or mask years > `validate_years[1]`) while closed. Add a test that the generated report has no 2021+ prevalence row while the lock is closed.

**Status: documented, no behaviour change** (0cc918a). Decision recorded in 10-CONTEXT and in the data report Caveats (`report.PREVALENCE_DECISION`): test-year descriptive prevalence is published by design and is not model scoring.

### WR-09: Fixed 4-week block length with no autocorrelation sensitivity

**File:** `heatwave/forecast/evaluation/bootstrap.py:19,36-50`; `forecast.yaml` (`block_weeks: 4`)
**Issue:** 4 weeks is the minimum allowed. Heatwave-week labels, and especially model skill differences, are strongly autocorrelated at seasonal scale (the same hot spell, the same MAM season). The gate rests on the week-block CI "excluding the threshold", so the CI is the decisive quantity. A 4-week block understates the variance of a Brier difference over seasonal clusters. The year-block check has only 6 clusters. There is also a wrap-around: the circular block joins the last validation week to the first, six years apart and in a different season. Neither the report nor the gate shows how much the interval widens with longer blocks.
**Fix:** Report a block-length sensitivity (4, 8, 13 weeks) for the primary leads, or choose the block length from the autocorrelation of the paired per-week loss difference. State the choice in the pre-registration.

**Status: fixed** (779d75b). Week blocks are moving and non-circular; the default stays 4 (minimum 4). `score_lead` adds BSS intervals at 8 and 13 week blocks for every reference/candidate pair; the report has a 'Block-length sensitivity' section.

## Info

### IN-01: Log append is not atomic across processes

**File:** `heatwave/forecast/testlock.py:128-149`
**Issue:** `_last_line` and the append are separate operations with no file lock. Two concurrent processes read the same `prev`, both write `prev_sha256 = H(prev)`, and the chain breaks (a false tamper signal). Appends are also O(file) per event.
**Fix:** Use an OS-level advisory lock (for example `msvcrt.locking` / `fcntl`) around read-last-line plus append, or a lock directory.

### IN-02: Hard-coded years and unverifiable claims in a "generated" report

**File:** `heatwave/forecast/evaluation/baselines_report.py:21-25,265,419-423`
**Issue:** "validation 2015-2020", "Test years 2021-2026", "fitted on 1991-2014" and the sentence "a larger m was marginally better on the backtest and on validation by less than the CI half-width" are literals. They would stay wrong if the config changed, and the last claim is not computed from the run. The m sentence also shows validation data informed the m discussion, while the text calls m "chosen a priori".
**Fix:** Format the years from `cfg.splits`. Drop or source the m claim from a stored experiment artifact.

### IN-03: Misleading `p_lo`/`p_hi` for the discrete-predictor edge case

**File:** `heatwave/forecast/evaluation/metrics.py:94-96,147-162`
**Issue:** For discrete predictors the edges are `[d0, d0, d1, ..., d_{m-1}]`. Bin j holds only value `d_j`, but the reliability table shows its range as `[d_{j-1}, d_j]` (bin 0 shows `[d0, d0]`). Mean forecast and observed frequency are right, only the printed "forecast range" is wrong.
**Fix:** For this branch emit `p_lo = p_hi = mean_p` (or the distinct value).

### IN-04: Duplicated week-stats construction

**File:** `heatwave/forecast/evaluation/harness.py:90-114` vs `metrics.py:259-290`
**Issue:** `_week_stats_from_bins` copies `week_stats` field by field. A new field added to one will silently diverge. `test_helper_equals_week_stats` guards today's field list only.
**Fix:** Have `metrics.week_stats` accept optional precomputed bin ids and mask, and delete the copy.

### IN-05: `n_valid` discarded for precision, recall and F1 intervals

**File:** `heatwave/forecast/evaluation/harness.py:215-217`
**Issue:** Precision is undefined in replicates with no predicted positives. The interval is computed from the surviving replicates and the report shows it with no indication that some were dropped.
**Fix:** Store `n_valid` per metric and print it, or flag any interval with `n_valid < B`.

### IN-06: Empty-geometry wards count as "large wards"

**File:** `heatwave/forecast/evaluation/slices.py:74-91`; `tests/forecast/test_forecast_harness.py` (comment on "synthetic empty-geometry ward counts as large")
**Issue:** NaN area gives `small = False`. The empty-geometry flag is computed in `ward_attributes` but no slice filter uses it, so those wards (which have no real geometry-derived signal) are included in "large wards only" and in the all-wards results.
**Fix:** Add an `exclude_empty_geometry` filter, or make `large_wards_only` also require `~empty_geometry`.

### IN-07: Test gaps

**File:** `tests/forecast/test_forecast_testlock.py`
**Issue:**
- Tail truncation of the log is not tested (see WR-04).
- `test_forecast_runs_dir_refuses_repo_and_frozen` only exercises the repo branch, not the frozen branch.
- `test_phase10_has_no_real_preregistration` asserts that a file is absent. It is repo-state-coupled and will fail as soon as Phase 14 commits the file, and it can never catch a regression.
- There is no test for a lock whose `model_bundle_path` is a Windows drive-relative path such as `C:foo`. `Path(root) / "C:foo"` on Windows discards `root`, and `_read_lock` accepts it.
**Fix:** Add the missing tests. Reject any bundle path with a drive or anchor (`Path(bundle).drive or Path(bundle).anchor`).

### IN-08: Best baseline is chosen and reported on the same validation data

**File:** `scripts/forecast_baselines.py:207-210`; `baselines_report.py` (BSS best vs recent_climatology)
**Issue:** The best baseline per lead is selected by validation Brier, and its BSS and CI against recent_climatology is then reported on the same validation years. That is selection bias in favour of the chosen baseline (small with 5 candidates, but unstated). The report should say that this skill is not an out-of-sample estimate.
**Fix:** Add one sentence to the report notes.

### IN-09: `recent_climatology` as-of property depends on the lead being short

**File:** `heatwave/forecast/baselines.py:106-124`; `features.base_rate`
**Issue:** Anchors are prior years +/- pool, about 50 weeks before the target column. Origin = target - lead, so anchors are before the origin only when lead < about 50 - pool. The docstring states "about 50 weeks" but nothing asserts `max(cfg.leads) < 48`. Also `pos = br * cnt` goes through float32 (`br` is float32), so `pos` is not an exact integer count.
**Fix:** Assert the lead bound in `fit`, and recompute counts in float64 from the integer sums if exactness matters.

### IN-10: Bundle path may be any file under forecast_runs

**File:** `heatwave/forecast/testlock.py:322-328`
**Issue:** `open_lock` accepts any file in `forecast_runs` as the "model bundle", including `evaluation_log.jsonl` (its hash changes with every log append, so the lock would re-close itself) or `TEST_LOCK.json`. This is harmless but confusing.
**Fix:** Require the bundle to sit in a run folder (`RUN_ID_PATTERN` directory) and exclude the lock and log names.

### IN-11: P/R/F1 threshold computed in float32

**File:** `heatwave/forecast/baselines.py:274-277`
**Issue:** `lead_label` is float32, so `.mean()` returns a float32 (pairwise-summed) value. The reported threshold has about 1e-7 error and is later compared in float64 against float32 predictions. That is only relevant if a predictor emits exactly the base rate.
**Fix:** `.mean(dtype=np.float64)`.

---

_Reviewed: 2026-10-08_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
