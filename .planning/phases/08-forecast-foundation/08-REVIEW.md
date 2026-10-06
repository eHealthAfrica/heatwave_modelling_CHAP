---
phase: 08-forecast-foundation
reviewed: 2026-10-06T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - heatwave/forecast/__init__.py
  - heatwave/forecast/weeks.py
  - heatwave/forecast/config.py
  - heatwave/forecast/data.py
  - heatwave/forecast/fixtures.py
  - heatwave/forecast/artifacts.py
  - scripts/verify_frozen.py
  - forecast.yaml
  - pyproject.toml
  - requirements.txt
  - .github/workflows/tests.yml
  - tests/conftest.py
  - tests/forecast/test_forecast_artifacts.py
  - tests/forecast/test_forecast_config.py
  - tests/forecast/test_forecast_data.py
  - tests/forecast/test_forecast_deps.py
  - tests/forecast/test_forecast_frozen.py
  - tests/forecast/test_forecast_isolation.py
  - tests/forecast/test_forecast_verify_script.py
  - tests/forecast/test_forecast_weeks.py
findings:
  critical: 3
  warning: 11
  info: 6
  total: 20
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-10-06
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Overall the phase is carefully built. ISO-week arithmetic is correct (index 0 = 1991-W02, 53-week years, negative indices). Only `yaml.safe_load` is used, and no `shell=True` appears anywhere. `data.version` and `frozen_subdir` are regex-constrained, so they cannot traverse. Run folders are refused inside the repo, and the MANIFEST write goes through a tmp file plus `os.replace`.

Real defects remain in four areas:
- the hash-then-parse path in `data.py` is not atomic (TOCTOU);
- `verify_frozen.py` applies containment to `inputs_sha256` keys but not to `outputs_sha256` keys, and crashes on malformed keys;
- config validation accepts values that silently corrupt the frozen protocol (string-typed hyperparameters from `1e-5`, duplicate YAML keys);
- several tests cannot fail or do not exercise what they claim.

## Critical Issues

### CR-01: TOCTOU between hash verification and parquet parse (data.py)

**File:** `heatwave/forecast/data.py:225-240, 284`
**Issue:** `verify_frozen_parquet` hashes the file with one open (`sha256_file`). It then opens it again with `pq.ParquetFile(path)` (line 240), and `load_panel` opens it a third time with `pd.read_parquet(path)` (line 284). Nothing pins the bytes between those opens. The module's central guarantee is that training sees only the byte-exact hashed file. A file replaced or modified after the hash (a concurrent writer, a sync client, or an attacker with write access to the data dir) is parsed unverified. `test_byte_flip_refused_before_parse` only proves the hash runs before the parse. It does not cover swap-after-hash. The `ParquetFile` handle at line 240 is also never closed, which on Windows keeps the file locked.
**Fix:** Read the bytes once, hash them, and parse from the same buffer:
```python
raw = Path(path).read_bytes()
sha = hashlib.sha256(raw).hexdigest()
# ... compare sha to manifest / yaml anchor ...
pf = pq.ParquetFile(io.BytesIO(raw))
df = pq.read_table(io.BytesIO(raw), columns=list(EXPECTED_COLUMNS)).to_pandas()
```
Alternatively return the bytes from `verify_frozen_parquet` and have `load_panel` reuse them. If memory is a concern, hash and parse from a single open handle (`with open(path,"rb") as fh:` hash, then `fh.seek(0)`, then `pq.read_table(fh)`).

### CR-02: Non-finite values pass the Panel NaN check (data.py)

**File:** `heatwave/forecast/data.py:285-312`
**Issue:** Only NaN and null are rejected. A float64 `inf` in the parquet survives `df.isna()` and `np.isnan(values)`. A finite float64 larger than about 3.4e38 silently overflows to `inf` in the `dtype=np.float32` cast (confirmed: `np.float32(1e39)` gives `inf`, with only a RuntimeWarning). The hash anchor reduces the practical risk for v1.0. The loader is documented as validating the frozen table, though, and this gap lets non-finite values into every downstream model and metric.
**Fix:** After building `values`, enforce finiteness and fail loudly:
```python
if not np.isfinite(values).all():
    raise FrozenDataError("non-finite values in frozen table (inf or float32 overflow)")
```
Also run `np.isfinite(df[v].to_numpy())` on the float64 source, so overflow is distinguishable from source `inf`.

### CR-03: verify_frozen.py hashes arbitrary paths from `outputs_sha256` keys (no containment)

**File:** `scripts/verify_frozen.py:468-471`
**Issue:** `inputs_sha256` keys are contained (lines 484-486). `outputs_sha256` keys are not: `path = dataset_dir / name` with `name` taken verbatim from the MANIFEST. An absolute key (`C:\...`) replaces `dataset_dir` entirely, and `../..` keys escape it. The script then hashes and reports OK/MISMATCH/MISSING for any file on disk. A MANIFEST is data that may be copied or edited. The user's brief called out MANIFEST key containment explicitly, and this path was missed. It is a file-existence and content-hash oracle outside the frozen dir, and it also means a poisoned MANIFEST can make verification pass by pointing an output key at an attacker-controlled file.
**Fix:** Apply the same containment check to output keys, resolved against `dataset_dir`:
```python
target = (dataset_dir / name).resolve()
if dataset_dir != target and dataset_dir not in target.parents:
    tally.report("BAD-KEY", name); continue
```
Also require `isinstance(name, str)` and `isinstance(want, str)`.

## Warnings

### WR-01: Malformed MANIFEST keys crash verify_frozen with a traceback instead of exit 1 or 2

**File:** `scripts/verify_frozen.py:483-488`
**Issue:** `(data_root / key).resolve()` raises `ValueError` for a key containing a NUL byte (confirmed). It raises `TypeError` for a non-string key (JSON object keys are always str, but `outputs_sha256` could be a non-dict of lists and so on). It can raise `OSError` for reserved Windows names or invalid characters such as `a:b`. This code is outside the `try` at lines 445-463, so the script exits with a Python traceback (rc 1 by accident, or an unhandled exception) rather than a `BAD-KEY` report.
**Fix:** Wrap the resolve and containment check in `try/except (ValueError, OSError, TypeError)` and report `BAD-KEY`. Do the same around `sha256_file` in `_check_hash`, because a `PermissionError` on a locked file currently aborts the whole run.

### WR-02: Missing or empty `inputs_sha256` silently passes full verification

**File:** `scripts/verify_frozen.py:458`
**Issue:** `manifest.get("inputs_sha256", {})` makes a MANIFEST that lacks the section (or has `{}`) pass the "full" (non `--outputs-only`) check with 0 inputs verified. The final summary line does not make clear that nothing was checked. A full verify that checks no inputs should not return 0.
**Fix:** In full mode, require the key to exist and be a non-empty dict (exit 1 or 2 otherwise), or at minimum print `0 inputs listed` and return non-zero.

### WR-03: Hyperparameters like `1e-5` silently load as strings; string params are accepted

**File:** `heatwave/forecast/config.py:208-212`, `forecast.yaml:560-575`
**Issue:** PyYAML (YAML 1.1) parses `1e-5` and `5e-1` as `str`, and only `1.0e-5` as float (confirmed). `ModelsConfig` accepts any `str`, so `learning_rate: 1e-5` validates, is hashed into `config_sha256` as a string, and only blows up later inside LightGBM (or, worse, is coerced). Parameter names are never checked against the model's known set, so a typo (`num_leafs`) or a determinism-breaking key (`seed`, `n_jobs`, `num_threads`, `deterministic: false`) is accepted. The `deterministic` and `force_row_wise` settings that the project depends on for reproducibility are not enforced.
**Fix:** Keep an allow-list per model with expected types (str only for `penalty`, `solver`, and similar). Reject str values for numeric params. Require `deterministic is True` for lightgbm, and reject `seed`/`random_state` keys, which would override the global seed.

### WR-04: Duplicate YAML keys silently take the last value

**File:** `heatwave/forecast/config.py:312`
**Issue:** `yaml.safe_load` keeps the last duplicate key (confirmed). For a file that is supposed to freeze the evaluation protocol (splits, gate, threshold), an accidentally duplicated `threshold:` or `train_end:` is silently resolved, and the hash then covers only the surviving value.
**Fix:** Use a `SafeLoader` subclass whose `construct_mapping` raises on duplicate keys, and keep `yaml.safe_load` semantics otherwise.

### WR-05: Panel arrays are mutable; the "frozen" dataclass does not freeze the data

**File:** `heatwave/forecast/data.py:255-326`
**Issue:** `Panel` is `frozen=True` but `values`, `week_index` and `week_start` are ordinary writable ndarrays. An in-place edit by any later phase (imputation, normalisation) corrupts the shared panel and breaks reproducibility, with `Panel.sha256` still claiming byte-exact provenance. `eq=False` also means two panels cannot be compared.
**Fix:** After construction, set `values.flags.writeable = False` (and the same for the index arrays). Document that consumers must copy.

### WR-06: Manifest `table` keys accessed unguarded in `load_panel`, raising `KeyError` instead of `FrozenDataError`

**File:** `heatwave/forecast/data.py:283-293`
**Issue:** `verify_frozen_parquet` uses `table.get(...)` defensively. `load_panel` then does `table["wards"]`, `table["first_week"]`, `table["last_week"]` and `table["weeks"]` directly. A truncated MANIFEST gives a bare `KeyError` (and `label_to_index(None)` gives `ValueError`). Callers catching `FrozenDataError` will miss it.
**Fix:** Validate `table` once (required keys and types) in `verify_frozen_parquet` and raise `FrozenDataError`.

### WR-07: `git_info` ignores untracked files, so `git_dirty` can claim a clean tree for unreproducible code

**File:** `heatwave/forecast/artifacts.py:392`
**Issue:** `git status --porcelain --untracked-files=no` reports clean when new, uncommitted `.py` files exist (for example a new feature module imported by the run). The RUN_MANIFEST then records a commit that cannot reproduce the run. `_git` also cannot tell "repo_root is not itself a repo but sits inside a parent repo", and would record the parent's HEAD.
**Fix:** Drop `--untracked-files=no` (or use `normal`, optionally excluding the data and run dirs via pathspec). Verify `git rev-parse --show-toplevel` equals `repo_root`.

### WR-08: `run_folder` can mask the original exception, and `finish_run` can downgrade a completed run

**File:** `heatwave/forecast/artifacts.py:483-500`
**Issue:**
- If `finish_run(ctx, "failed")` itself raises (disk full, antivirus lock on `os.replace` on Windows), the original training exception is replaced by the I/O error.
- `except BaseException` also marks `KeyboardInterrupt` and `SystemExit` as `failed`, which is acceptable, but there is no guard against calling `finish_run` twice. The test even does `completed` then `failed`, so a completed run can be silently overwritten.
- A run folder created in `start_run` is left orphaned (no manifest) if the yaml dump or git call fails between `mkdir` (line 440) and `_write_manifest` (line 479).

**Fix:** Wrap the failure-path `finish_run` in `try/except OSError: pass` (with logging) so the original exception propagates. Refuse transitions out of a terminal status. Write a provisional manifest immediately after `mkdir`, or remove the folder on early failure.

### WR-09: Week label regex accepts a trailing newline and non-ASCII digits

**File:** `heatwave/forecast/weeks.py:21, 34`
**Issue:** `^(\d{4})-W(\d{2})$` with `re.match` lets `"1991-W02\n"` through (`$` matches before a trailing newline), and `\d` matches Unicode digits (`"１９９１-W０２"` parses to index 0; both confirmed). The docstring says labels are only parsed at the boundary, yet `label_to_index`, `labels_to_indices` and `split_for_week_start` callers get non-canonical labels accepted. `load_panel` happens to catch this afterwards via the canonical-label check, but the other entry points do not.
**Fix:** `re.compile(r"[0-9]{4}-W[0-9]{2}").fullmatch(label)`. Add the two inputs to `test_invalid_labels`.

### WR-10: `test_existing_config_untouched` cannot fail once changes are committed

**File:** `tests/forecast/test_forecast_config.py:369-381`
**Issue:** `git diff --exit-code -- config.yaml heatwave/config.py tests/test_config.py` compares the working tree to the index. After a commit (or in CI at a clean checkout) it always returns 0 regardless of what the phase changed. It also skips silently when git is missing. It guards nothing in CI.
**Fix:** Diff against the base ref (`git diff --exit-code origin/main -- ...`), or assert a pinned sha256 of `config.yaml`, or delete the test.

### WR-11: Hard-coded and tautological test assertions

**File:** `tests/forecast/test_forecast_artifacts.py:64`, `tests/forecast/test_forecast_data.py:245,407-409`, `tests/forecast/test_forecast_verify_script.py:610-615`
**Issue:**
- `test_library_versions` hard-codes `numpy == "2.3.3"`, so any routine pin bump fails an unrelated test.
- `test_data_module_never_writes` only asserts the substring `"chmod"` is absent from the source. It would pass for `open(p, "wb")`, and a comment containing the word would fail it.
- `test_synthetic_rows_shuffled_within_week` first assertion uses `or` such that it is nearly always true.
- `test_full_ok` asserts `"OK" in out`, which is also satisfied by `"NOTE ... OK"` text.
- There is no test for: `inf` or overflow in the parquet, mutated Panel values, a trailing-newline label, `outputs_sha256` key traversal, a missing or empty `inputs_sha256`, or a TOCTOU swap.

**Fix:** Tighten or remove the above, and add the missing negative tests alongside the fixes for CR-01 to CR-03 and WR-09.

## Info

### IN-01: `test_escaping_key_is_bad_key` writes outside its tmp_path

**File:** `tests/forecast/test_forecast_verify_script.py:676-680`
**Issue:** `tmp_path.parent / "escape.nc"` lands in the shared pytest basetemp and is never cleaned up. It can collide under xdist.
**Fix:** Use `tmp_path / "root"` as the data root and `tmp_path / "escape.nc"` as the outside file.

### IN-02: Unused import kept with a noqa

**File:** `heatwave/forecast/config.py:20`
**Issue:** `EPOCH_WEEK_START` is imported "for the week index contract" and never used. It also makes `config` depend on `weeks` for no functional reason.
**Fix:** Remove it.

### IN-03: `verify_frozen` tally is inconsistent

**File:** `scripts/verify_frozen.py:472-478`
**Issue:** The anchor MISMATCH branch does not increment `tally.checked`, while the OK branch does. The "N checked" figure therefore under-counts on failure. Copied inputs under `dataset_dir/inputs` are hashed a second time against the same MANIFEST entry, doubling the work for the large inputs. `_note_writable` is advisory only, so the "read-only" freeze is never enforced.
**Fix:** Increment `checked` in all branches. De-duplicate hashing. Optionally make writable frozen files a warning exit code.

### IN-04: Atomic write lacks fsync and the config snapshot is not atomic

**File:** `heatwave/forecast/artifacts.py:411-414, 457-460`
**Issue:** `_write_manifest` does tmp + `os.replace` but never flushes or fsyncs. A power loss can leave a zero-length manifest after rename. `config.yaml` is written non-atomically. A fixed `.tmp` name also collides if two writers share a folder.
**Fix:** Open the tmp file, write, `flush()`, `os.fsync()`, then `os.replace`. Use the same helper for the config snapshot.

### IN-05: Config year and range bounds are not validated

**File:** `heatwave/forecast/config.py:53-59, 237-251`
**Issue:**
- Years only need to be at least 1, and an absurd year such as 99999 surfaces as a raw `date.fromisocalendar` ValueError from the splits validator.
- `train_years[0]` is not checked against the dataset epoch (1991), and `latency_days` and `recent_climatology_years` have no upper bounds or cross-checks against the train span.
- `test_years` ends 2026 although the data ends 2026-W38, so the final test year is partial. This is a design note, not a bug.

**Fix:** Bound years to a sensible range, for example `1991 <= y <= 2100`, and cross-check `recent_climatology_years` against the train span.

### IN-06: conftest silently skips every frozen test when data is absent

**File:** `tests/conftest.py:30-35`
**Issue:** There is no signal in CI or locally that the real-data tests (`test_forecast_frozen.py`) never ran. If the data dir moves, the integration suite reports green with all tests skipped. `"frozen" in item.keywords` also matches any test or node literally named "frozen".
**Fix:** Print a loud summary (`pytest_report_header`) of skipped frozen tests. Optionally add an env var (for example `REQUIRE_FROZEN=1`) that turns the skip into a failure.

---

_Reviewed: 2026-10-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
