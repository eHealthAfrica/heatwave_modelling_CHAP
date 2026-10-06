---
phase: 08-forecast-foundation
fixed_at: 2026-10-06
review_path: .planning/phases/08-forecast-foundation/08-REVIEW.md
iteration: 1
findings_in_scope: 14
fixed: 14
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

Scope: CR-01..CR-03 and WR-01..WR-11. Each fix has a regression test that failed before the fix.

## Fixed Issues

### CR-01

**Commit:** 607bbb0
**Applied fix:** data.py reads the parquet bytes once, hashes them, and parses (ParquetFile and read_table) from the same BytesIO; no open handle remains. Test swaps the file on disk between hash and parse and asserts the panel still holds the hashed values. Logic change, human verification advised.

### CR-02

**Commit:** 62f7020
**Applied fix:** Panel build rejects inf in source columns and float32 overflow after the cast (np.isfinite, FrozenDataError). Tests: inf, -inf, 1e39.

### CR-03

**Commit:** 2131cee
**Applied fix:** verify_frozen resolves outputs_sha256 keys under the dataset dir (shared _contained helper), requires str key and str hash; escaping or absolute keys report BAD-KEY.

### WR-01

**Commit:** 1931aff
**Applied fix:** NUL / invalid-name keys give BAD-KEY; OSError while hashing reports UNREADABLE (counted as failure) instead of aborting.

### WR-02

**Commit:** 66a1274
**Applied fix:** Full mode exits 2 if inputs_sha256 is missing, empty or not an object; --outputs-only is unaffected.

### WR-03

**Commit:** e159dd8
**Applied fix:** Per-model allow-list with kinds; numeric strings such as 1e-5 normalised to float, non-numeric strings and wrong types rejected; seed/random_state/n_jobs/num_threads and typos rejected; lightgbm deterministic must be true. Also removed the unused EPOCH_WEEK_START import (IN-02). Config hash of the real forecast.yaml is unchanged. Logic change, human verification advised.

### WR-04

**Commit:** 07fc686
**Applied fix:** SafeLoader subclass raising on duplicate mapping keys (still no python tags).

### WR-05

**Commit:** bdeb800
**Applied fix:** Panel arrays (values, week_index, week_start) set non-writeable in __post_init__.

### WR-06

**Commit:** d5f4605
**Applied fix:** MANIFEST table section validated up front (rows/wards/weeks ints, first/last_week valid labels, columns list), raising FrozenDataError.

### WR-07

**Commit:** 8a676c2
**Applied fix:** git_info counts untracked files (excluding outputs/ and keys/ pathspecs) and returns None values unless git toplevel is repo_root. Design choice: the exclusions keep the repo's untracked report files from always marking runs dirty.

### WR-08

**Commit:** c7bd656
**Applied fix:** Failure-path finish_run errors (OSError) are logged, original exception propagates; transitions out of completed/failed raise ValueError (the old test that did completed then failed was rewritten); start_run removes its folder if setup fails after mkdir.

### WR-09

**Commit:** 0580c58
**Applied fix:** Label regex is now [0-9]{4}-W[0-9]{2} with fullmatch; tests for trailing/leading newline, trailing space, fullwidth and Arabic-Indic digits.

### WR-10

**Commit:** 2465f74
**Applied fix:** test_existing_config_untouched compares git blob ids (computed in pure Python, CRLF-normalised) with ids recorded from base 7ed8d1c; independent of index/history/git binary; parametrised per file with a helper sanity test.

### WR-11

**Commit:** 272def3
**Applied fix:** test_library_versions compares with importlib.metadata instead of a hard-coded pin; never-writes test is an AST scan; shuffle test asserts >90% of weeks unsorted; test_full_ok checks exact OK lines and no failure lines. Missing negative tests were added with CR-01..03, WR-02, WR-05, WR-09.

## Not addressed (out of scope)

IN-01, IN-03, IN-04, IN-05, IN-06 (Info). IN-02 was fixed incidentally in the WR-03 commit.

## Test results

- `pytest tests/forecast -q`: 261 passed
- `pytest -m frozen -q`: 8 passed, 421 deselected
- `scripts/verify_frozen.py` (full): 376 checked, 0 mismatches, 0 missing, 0 bad keys
- `pytest tests/test_config.py tests/test_requirements.py tests/test_local_pipeline.py -q`: 59 passed

No locked decision from 08-CONTEXT.md was changed. The frozen data directory was only read.

---

_Fixer: Claude (gsd-code-fixer), iteration 1_
