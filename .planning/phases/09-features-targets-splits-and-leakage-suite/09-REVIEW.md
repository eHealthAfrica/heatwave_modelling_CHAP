---
phase: 09-features-targets-splits-and-leakage-suite
reviewed: 2026-10-07T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - heatwave/forecast/static.py
  - heatwave/forecast/climatology.py
  - heatwave/forecast/targets.py
  - heatwave/forecast/splits.py
  - heatwave/forecast/registry.py
  - heatwave/forecast/features.py
  - heatwave/forecast/dataset.py
  - heatwave/forecast/leakage.py
  - heatwave/forecast/report.py
  - heatwave/forecast/config.py
  - heatwave/forecast/fixtures.py
  - scripts/forecast_data_report.py
  - forecast.yaml
  - tests/forecast/conftest.py
  - tests/forecast/test_forecast_leakage.py
  - tests/forecast/test_forecast_leakage_frozen.py
  - tests/forecast/test_forecast_splits.py
  - tests/forecast/test_forecast_dataset.py
  - tests/forecast/test_forecast_features.py
  - tests/forecast/test_forecast_climatology.py
  - tests/forecast/test_forecast_targets.py
  - tests/forecast/test_forecast_report.py
  - tests/forecast/test_forecast_static.py
  - tests/forecast/test_forecast_registry.py
findings:
  critical: 0
  warning: 8
  info: 9
  total: 17
status: warnings_fixed
fixes: 09-REVIEW-FIX.md
---

# Phase 9: Code Review Report

**Reviewed:** 2026-10-07
**Depth:** standard (with cross-file tracing of the leakage paths)
**Files Reviewed:** 24 (source files read in full; the leakage, leakage_frozen, splits, dataset and features tests read in full; the climatology, targets, report, static, registry, config and fixtures tests were only skimmed or not opened, so conclusions about them are limited)
**Status:** issues_found

## Summary

I found no target-week or validation/test-year leakage into features or fitted statistics. I specifically traced these paths:

- **Rolling windows and lags** (`features.lag`, `trail_mean`, `trail_sum`): these read positions <= t only. Windows are full-or-NaN, and the shift direction is correct.
- **Base-rate anchors** (`features.base_rate`): anchors are at least about 50 weeks before t, and the `idx <= t` mask is a second guard. W53 origins map to W52 of 52-week years and stay <= t.
- **Spatial means** (`features.group_mean`): they use the same week t only.
- **Climatology fit range** (`Climatology.fit`): it uses `week_start < end`. The main fit therefore covers 1991-W02 to 2014-W52, and each CV fold fits through the week before its validation year.
- **Cache reuse** (`dataset._check_store`): it compares the store's recorded `fit_end` with `train_end`, or with the fold's `climatology_end`.
- **Labels** (`targets.lead_label`): the gather is `out[:, :T-k] = base[:, k:]`. The tail is NaN and is never filled. The frozen loader rejects NaN, so `NaN >= 3 -> 0` cannot happen on real data.
- **Split and embargo arithmetic**: cutoffs are Mondays. 2020-W53 (2020-12-28) falls before 2021-01-04, so it lands in validate and in CV fold 2020. `effective_days_ahead` = 7k - 6 - latency is correct.

The defects below are about guard completeness, a latent operational failure, the issue-table split column, memory on the real panel, cache robustness and test quality. None of them is a present leak.

## Warnings

### WR-01: `_check_store` does not bind the store to the panel

**Status:** FIXED d51b2b0 (data_sha256, week axis and array shapes checked; the clim-sha comparison from the suggested fix was left out because the row-level truncation test legitimately reuses one train_end climatology across truncated panels)

**File:** `heatwave/forecast/dataset.py:384-393` (also used by `build_issue_table`, line 487)
**Issue:** The guard checks only the ward tuple and the climatology `fit_end`. It never checks `store.data_sha256 == panel.sha256`, `store.week_index` against `panel.week_index`, or array shapes. `lead_rows` and `build_issue_table` then index `store[nm][ward_pos, origin_pos]` by panel positions. A store built from a different panel with the same wards and the same `fit_end` is silently accepted. Examples are a truncated, poisoned or older-version panel, or a store loaded from the wrong cache. If T matches, rows are misaligned with no error. If T is smaller, the result is an IndexError. This is exactly the stale-cache scenario the guard exists for.
**Fix:**
```python
if store.data_sha256 != panel.sha256:
    raise ValueError("store was built from a different panel (data_sha256 mismatch)")
if not np.array_equal(store.week_index, panel.week_index):
    raise ValueError("store week axis differs from panel")
if store.clim_fit_range.get("data_sha256") != panel.sha256:
    raise ValueError("store climatology was fitted on different data")
```

### WR-02: Issue table `split_l{k}` ignores the embargo and warm-up

**Status:** FIXED d57f67a (split_l{k} now train/embargoed/validate/test/beyond_test/warmup)

**File:** `heatwave/forecast/dataset.py:508`
**Issue:** `split_l{k}` comes from `assign_split` alone. Rows whose target falls in the 14-week embargo before 2014-12-29 are labelled "train", and so are warm-up origins whose features are NaN. `lead_rows` and `lead_row_index` apply `split_masks`, `has_label` and the warm-up drop. A Phase 10-12 consumer who filters `split_l3 == "train"` on the issue table gets embargoed rows, which is a C4 violation. The issue table also exposes no "embargoed" state.
**Fix:** Derive the column from `split_masks` and emit "embargoed" for `is_train & ~keep`. Alternatively, add `train_ok_l{k}` (embargo, has_label and warm-up combined) and document that `split_l{k}` is the raw target-week split.

### WR-03: Memory blow-up in `build_issue_table` and `lead_rows` on the real 4841x1863 panel

**Status:** FIXED d7f9e07 (categorical ward/week/split columns, DataFrame(copy=False), max_rows guard 3M on issue tables)

**File:** `heatwave/forecast/dataset.py:484-512`, `480` (`pd.DataFrame(cols)`)
**Issue:** With all origins, `build_issue_table` creates about 9.0M rows. The columns are:
- 6 `split_l{k}` columns as `<U8`. UCS4 costs 32 bytes per cell, so about 288 MB each and 1.7 GB in total.
- 6 object columns `target_week_l{k}` plus `last_obs_week`.
- 18 int64 or datetime64 timing columns, about 1.3 GB.
- 49 float32 features, about 1.8 GB.
- 6 float32 labels.

`pd.DataFrame(dict)` then consolidates and copies the blocks, so the peak is about twice the total (roughly 10 GB or more), on top of the roughly 1.8 GB feature store. `lead_rows` for lead 1 train has about 5.3M rows x 58 features, which is about 1.2 GB doubled by the copy, and it also builds `ward` and `target_week` as object columns. Neither function chunks or uses categoricals.
**Fix:**
- Store `split` as `int8` or `pd.Categorical`. Store `ward` and the week labels as categoricals, or drop the string columns and keep only the indices.
- Require or encourage an `origin_positions` subset in `build_issue_table`.
- Build the DataFrame from a pre-allocated float32 block (`pd.DataFrame(matrix, columns=...)`) to avoid consolidation copies.
- Add a guard that raises above a row-count threshold.

### WR-04: `assign_split` raises when the data extends past the configured test years (latent operational failure)

**Status:** FIXED 2471edf (assign_split(strict=False) labels beyond_test; split_masks and report tolerate it)

**File:** `heatwave/forecast/dataset.py:508`; `heatwave/forecast/splits.py:294-298`; `heatwave/forecast/report.py:81`
**Issue:** `build_issue_table` calls `assign_split` on the target index of every origin, including origins whose target lies beyond the data (the operational rows). `assign_split` raises when `t.max() >= hi`, where `hi` is the start of ISO year `test_years[1] + 1`. The panel currently ends at 2026-W38, so lead 6 reaches 2026-W44 and nothing breaks. After the next data refresh past about 2026-W46, or for any `test_years` that ends earlier, the operational issue table and the data report fail with an unhelpful ValueError. `lead_row_index` avoids this only by pre-filtering on `has_label`.
**Fix:** For unlabelled targets, assign "future" or "unassigned" instead of raising. For example, add `assign_split(..., strict=False)` that maps `t >= hi` to "test" or "future", and use it in `build_issue_table`. Also make `report.prevalence_tables` tolerate weeks past `hi`.

### WR-05: Feature cache can be stale, partial or unverified

**Status:** FIXED 0a44f7f (feature_code_version, required registry_names, atomic array writes, per-array sha256)

**File:** `heatwave/forecast/dataset.py:567-624`
**Issue:**
- `_meta` and the cache key contain data sha, ward sha, names, climatology fit range and registry names, but nothing identifies the feature code or its constants. Examples are windows, `BASE_RATE_*`, the `POOL_WEEKS` effect on the features, and the anomaly formula. Editing a feature function without renaming it, or changing `LONGEST_FIXED_WINDOW_WEEKS`, still gives a cache hit with stale arrays. `config_hash(cfg)` does not cover these code constants either.
- `registry_names` is optional on load. When it is omitted (the default), that check is skipped.
- `.npy` files are written in place, and `store_meta.json` is replaced only at the end. A crash mid-save over an existing cache leaves old meta with a mix of new and old arrays. The load path validates dtype and shape only, with no content hash, so truncated or corrupted arrays that still parse are accepted.
- Security positives: `allow_pickle=False` is used on both save and load, and names are regex-validated. Path containment is also handled (hex-only key components, the repo and frozen folders rejected).

**Fix:**
- Add a `feature_code_version` to meta, or hash `inspect.getsource` of `features.py` and `climatology.py` plus the constants.
- Make `registry_names` required.
- Delete `store_meta.json` before writing the arrays, or write the arrays to a temp directory and rename it.
- Store a per-array sha256 in meta and verify it on load.

### WR-06: `dataset` is hard-wired to the global `REGISTRY`, though `build_feature_store` accepts a registry

**Status:** FIXED 5874cae (registry argument on lead_rows/build_issue_table, threaded through)

**File:** `heatwave/forecast/dataset.py:396-401, 429-450, 510-527`
**Issue:** `_feature_names`, `_gather_features` and `_issue_features` all call `REGISTRY.get(nm)` and `REGISTRY.names()`. A store built with a custom registry fails at row assembly with KeyError, or silently omits features. Phase 16 (climate-driver features) will hit this. The row-level leakage check (`check_row_truncation_invariance`) also cannot be mutation-tested for an injected leaky feature, because the injected feature never reaches the rows. Only the store-level (a)/(b) mutation tests cover that case.
**Fix:** Add a `registry=REGISTRY` parameter to `lead_rows`, `build_issue_table` and `_feature_names`, and thread it through to `_gather_features` and `_issue_features`.

### WR-07: Report script path safety is incomplete

**Status:** FIXED 7c96227 (--docs-out limited to docs/ unless --force, generated-by marker, pin override recorded in report and manifest)

**File:** `scripts/forecast_data_report.py:293-301, 282-289`
**Issue:**
- `--docs-out` only requires a `.md` suffix and exclusion from frozen, `outputs/` and `keys/`. Any other Markdown file the user can write can be overwritten by `os.replace`, for example `README.md`, `CLAUDE.md`, `docs/METHODOLOGY.md` or `.planning/*.md`. A typo or a hostile argument is enough.
- `--expected-parquet-sha256` replaces the pinned anchor from `forecast.yaml`. A report committed to `docs/forecast/DATA_REPORT.md` can therefore be generated from unpinned data, and the committed text does not record that the pin was overridden.

**Fix:**
- Restrict `--docs-out` to a path under `REPO_ROOT / "docs"` (or require `--force` for anything else), and refuse to overwrite an existing file that was not produced by this script. A header marker such as `<!-- generated by forecast_data_report.py -->` would let the script check this.
- Print a warning and add a "pin overridden" line to the report provenance when the override is used.

### WR-08: Wall-clock assertion makes a test flaky

**Status:** FIXED 2a9f227 (0.5 s assertion replaced by a 30 s complexity bound plus shape checks)

**File:** `tests/forecast/test_forecast_features.py:176-183` (`test_base_rate_speed`)
**Issue:** The test asserts `time.perf_counter() - t0 < 0.5` for a small panel. On a loaded CI runner or a Windows machine it will fail intermittently. It also tests performance, which is not a correctness property of this phase.
**Fix:** Delete the test, or mark it as a benchmark and relax it to a generous bound (for example 10 s) to catch only complexity regressions.

## Info

### IN-01: Frozen real-data leakage tests are silently skipped when data is absent

**File:** `tests/forecast/conftest.py:18-23`
**Issue:** The `frozen_panel` fixture skips when the parquet or MANIFEST is missing. If CI never has the data, the real-data variant of the leakage suite (FEAT-04) never runs, and the skip is silent. The path also hard-codes `"frozen"` instead of `forecast_cfg.data.frozen_subdir`, which diverges from `load_panel` if the config changes.
**Fix:** Use `forecast_cfg.data.frozen_subdir`. Print a skip reason that names the lost FEAT-04 coverage, or add a CI check that fails when `-m frozen` runs with zero executed tests.

### IN-02: Base rate is keyed on the origin's season, not the target week's

**File:** `heatwave/forecast/features.py:72-103`
**Issue:** `hw_base_rate_10y` is computed for the ISO week of origin t, with a +-2 week pool. For lead 6 the target is six weeks later, so the same-season anchor and the target season differ by more than the pool. The target season is known at issue time, so using it would not leak. The spec says "up to t", so this is acceptable as written, but the feature is weaker for long leads and the same value is reused for all leads.
**Fix:** If wanted, compute a per-lead base rate anchored on the target week's ISO week, still using only anchors <= t. Otherwise document the mismatch.

### IN-03: Precipitation anomaly is unbounded where climatological variance is near zero

**File:** `heatwave/forecast/climatology.py:104, 137`
**Issue:** The std floor is 0.1 x the global median std per variable. For zero-inflated precipitation in dry-season slots the per-ward std is near 0, so a single rain event gives `(x - 0) / floor`. The result is large, heavy-tailed anomalies, and `pr_anom_sum4` and `pr_anom_sum8` then sum them. This is not leakage, but it hurts logistic-regression conditioning and tree splits. Also, the anomalies are in-sample on training years and out-of-sample on validation years, so the variance differs between them. Both are small effects.
**Fix:** Clip anomalies (for example to +-6), or use a per-variable floor tied to a within-slot quantile. Record the choice in the fit range.

### IN-04: Spatial features silently change meaning on a ward subset

**File:** `heatwave/forecast/features.py:106-118, 234-242`
**Issue:** `group_mean` averages over the wards present in the panel. `subset_panel` and `build_feature_store` accept a subset, as in the 200-ward frozen leakage test and `ward_positions` in `build_issue_table`. The LGA and state means then differ from the full-panel values, with no warning.
**Fix:** Compute the spatial features on the full panel and subset afterwards, or log or assert when the panel does not cover each LGA fully.

### IN-05: `warmup_first_position` recomputes a full-size base rate on every call

**Status:** FIXED 246b227 (incidental one-line change)

**File:** `heatwave/forecast/dataset.py:357-365`
**Issue:** It allocates a zero `(n, T)` panel and runs the full base-rate loop only to read the counts, which depend on T alone. It runs on every `lead_row_index` call, which is 18 times in `report.row_count_table`, plus once more. This is a performance issue and out of scope for v1, but the fix is one line.
**Fix:** Pass `np.zeros((1, T), np.float32)`, or cache the result per `panel.week_start`.

### IN-06: Dead and loosely coupled code

**File:** `heatwave/forecast/splits.py:324-327`; `heatwave/forecast/report.py:33`; `heatwave/forecast/leakage.py:195`
**Issue:**
- `refit_train_mask` is unused. `_check_store` always demands a climatology fitted at `train_end`, so rows for the pre-test refit (train+validate) cannot be built with a refit climatology. The refit path is incomplete or undocumented.
- `_row(weeks_mask, label, n_wards)` has an unused `n_wards` parameter.
- The production module `leakage.py` imports test helpers from `fixtures`.

**Fix:** Delete or finish `refit_train_mask` (plan the refit climatology guard in Phase 12). Remove the unused parameter. Consider moving `truncate_panel` and `poison_future` into `leakage.py` or a shared module.

### IN-07: Hard-coded narrative in the generated report

**File:** `heatwave/forecast/report.py:177-182, 239`
**Issue:** The "Regime shift ... Validation is not representative of test" sentence and the "1991 starts at W02" caveat are static text. They stay true only for the current numbers. `OPERATIONAL_DELAY_DAYS = 9` is also a constant, while the operational columns are labelled as real delay. If the data or the measurement changes, the committed report can state something its own tables contradict.
**Fix:** Generate the regime-shift sentence conditionally from the three prevalence values (for example, only when the relative difference exceeds a threshold).

### IN-08: Windows line endings in the committed report and CSVs

**File:** `scripts/forecast_data_report.py:330-335`
**Issue:** `Path.write_text` and `DataFrame.to_csv` use `os.linesep`, so on Windows `docs/forecast/DATA_REPORT.md` is written with CRLF and produces noisy diffs when regenerated on another OS. The tmp-then-`os.replace` write is fine on Windows.
**Fix:** `tmp.write_text(md, encoding="utf-8", newline="\n")` (Python 3.10+) and `to_csv(..., lineterminator="\n")`.

### IN-09: Bit-exact float comparison in leakage checks may depend on summation order

**File:** `heatwave/forecast/features.py:51-65`; `heatwave/forecast/leakage.py:203-210`
**Issue:** `trail_mean` and `trail_sum` reduce over a `sliding_window_view` with `dtype=float64`. Both axes 1 and 2 of that view have stride 4 bytes, and numpy chooses its iteration order from the array shape. A full panel and a truncated panel of a different T could therefore reduce in different orders, giving last-bit float64 differences that the float32 cast usually, but not provably, absorbs. The leakage checks compare with `atol=0.0`. I have not reproduced a failure, and the module docstring already documents the `atol` fallback, so this is a flake risk and not a defect.
**Fix:** If flakes appear, compute rolling sums with a cumulative-sum difference on float64 (order-independent per window) and keep `atol=0`. Alternatively, run the frozen suite with `atol=1e-6`, which still catches O(1) leaks as the docstring notes.

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
