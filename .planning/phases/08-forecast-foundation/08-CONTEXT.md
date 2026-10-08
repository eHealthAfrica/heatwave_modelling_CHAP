# Phase 8: Forecast Foundation - Context

**Gathered:** 2026-10-02
**Status:** Ready for planning
**Source:** These decisions were already agreed with the user during milestone v2.0 setup (PROJECT.md Key Decisions, research/SUMMARY.md adjustments adopted 2026-10-02, and the approved ROADMAP phase overview). There was no separate discuss-phase session.

<domain>
## Phase Boundary

This phase builds the foundation that every later forecasting phase reads through:
- a checksum-verified loader for the frozen `covariates-v1.0` dataset;
- an ISO-week index that's safe for 53-week years;
- a validated `forecast.yaml`;
- reproducible run folders;
- the new ML dependencies;
- CI on Python 3.12.

No features, targets, baselines or models are built here (those are Phases 9-12).

Requirements: DATA-01, DATA-02, DATA-03, DATA-04, DATA-05.
</domain>

<decisions>
## Implementation Decisions

### Package and config
- New sibling package `heatwave/forecast/`. It must never import `ee`, `geemap`, `heatwave.auth` or any Earth Engine module, and an import-isolation test enforces this.
- Forecast settings live in a separate repo-root `forecast.yaml`, loaded into frozen dataclasses with `__post_init__` validation (same style as `heatwave/config.py`'s `ClimatologyConfig`). `config.yaml`, `heatwave/config.py` and the 35 `tests/test_config.py` tests stay unchanged. `local_data_dir` is reused from `heatwave.config.settings`.
- `forecast.yaml` holds these sections (later phases fill in values; Phase 8 defines and validates them):
  - **data:** `version` = `covariates-v1.0` and the frozen folder.
  - **splits:** train 1991-2014, validate 2015-2020, test 2021-2026; cutoffs by `week_start` date; embargo weeks.
  - **leads:** [1, 2, 3, 4, 5, 6].
  - **latency_days:** default 8. It is a placeholder until it's measured in Phase 9.
  - **gate:** primary leads [2, 3]; BSS > 0 vs the best baseline with a CI excluding 0.
  - **retrain_policy:** refit on 1991-2020 with frozen hyperparameters before the single test; the operational model is refit on all years and marked "not independently tested".
  - **seed**.
  - **model hyperparameter placeholders**.

### Frozen data access (DATA-01)
- Training data is the frozen `covariates-v1.0` only, at `<local_data_dir>/frozen/covariates-v1.0/`. Read `covariate_table.parquet`, and verify its SHA-256 against `MANIFEST.json` `outputs_sha256` before use.
- On a mismatch, a missing file or the wrong columns, fail loudly. The training loader must reject the live `outputs/covariate_table.csv`.
- Check the schema against the MANIFEST `table.columns` (10 columns), plus the row and ward counts (9,018,783 rows; 4,841 wards; 1,863 weeks).
- Load into a dense float32 panel (ward x week x variable), with a ward index and a week index. This is faster than 9M-row groupby shifts, and later lag building depends on it.
- Provide `scripts/verify_frozen.py`, which re-hashes the frozen outputs and all 361 inputs against the MANIFEST and reports mismatches.

### Week index (DATA-02)
- Convert between ISO labels `YYYY-Www`, a contiguous integer week index and the `week_start` (Monday) date.
- Time arithmetic never uses label strings.
- It must be correct across 53-week ISO years (1992, 1998, 2004, 2009, 2015, 2020, 2026); for example, 2020-W53 starts 2020-12-28 and runs to 2021-01-03.
- The frozen table starts at 1991-W02, so index 0 = 1991-W02.

### Run folders (DATA-04)
- Run folders go outside the repo, under `<local_data_dir>/forecast_runs/<run_id>/`. `run_id` = UTC timestamp + short config hash.
- Each folder contains:
  - `config.yaml` snapshot;
  - `RUN_MANIFEST.json`: data version + MANIFEST sha256 of the parquet, git commit (+ dirty flag), Python and library versions (numpy, pandas, pyarrow, scikit-learn, lightgbm, shap), seed, start/end time.
- Nothing from run folders is committed.

### Dependencies and CI (DATA-05)
- Add to `requirements.txt`: `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `shap==0.52.0`. Keep numpy 2.3.3, pandas 2.3.2 and pyarrow 21 pinned.
- Verify Windows wheels with `pip install --dry-run` before installing into `.venv`.
- Add an import smoke test (sklearn, lightgbm, shap).
- If shap can't be installed alongside the pins, fall back to LightGBM's native `pred_contrib`, keep shap out, and document why.
- Move `.github/workflows/tests.yml` to Python 3.12 (the user chose this, because shap 0.52 and scipy 1.18 need ≥ 3.12; the local venv is 3.12.10). Update `pyproject.toml` `requires-python` to `>=3.12`.
- CI must pass without the frozen data. Add a synthetic-panel fixture (a few wards x a few years, including a 53-week year) under `tests/forecast/`. Add a pytest marker `frozen` for tests that need the real frozen data, skipped automatically when it's absent.
- The existing 166 tests must still pass (local result: 166 passed, 2 skipped).

### Resolved after phase research (2026-10-02)
- **Split cutoffs:** expressed as exclusive upper-bound Monday dates (`week_start < cutoff`), documented once and tested. Each boundary is the Monday of ISO week 1 of the next split's first year:
- **Train:** `week_start < 2014-12-29` (2015-W01 Monday).
- **Validate:** `2014-12-29 <= week_start < 2021-01-04` (2021-W01 Monday). This includes 2020-W53, 28 Dec 2020 to 3 Jan 2021.
- **Test:** `week_start >= 2021-01-04`, to the end (2026-W38). Default `embargo_weeks` = max(leads) = 6. Phase 9 may raise it once lag lengths are known.
- **`verify_frozen.py` read-only flags:** report only, not a failure.
- **Parquet sha256:** pinned in `forecast.yaml` (`data.expected_parquet_sha256`) as a second anchor beside MANIFEST.json, so a tampered MANIFEST can't pass silently.
- **MANIFEST `inputs_sha256` keys** are relative to `local_data_dir`, not to the frozen `inputs/` folder: `wards.geojson` and `era5_land_daily_gee/<band>/<year>.nc` (verified by whoever built the MANIFEST). Only `wards.geojson` and each band's `2026.nc` are copied into `frozen/covariates-v1.0/inputs/`. `verify_frozen.py` hashes the files under `local_data_dir` and also checks that the copied `inputs/` files match. It gets an `--outputs-only` flag, because hashing 361 .nc files (about 3 GB) is slow.
- **Test naming:** use unique file names under `tests/forecast/` (for example `test_forecast_config.py`) to avoid colliding with `tests/test_config.py`. Add a `tests/conftest.py` that auto-skips `@pytest.mark.frozen` when the frozen data is absent, and register the marker in `pyproject.toml`.
- **Dependency install:** dry-run resolution succeeded (cp312 win_amd64 wheels; numpy stays 2.3.3). Install for real during execution, then import-smoke-test shap. Append the new transitive pins to `requirements.txt` (it's a full freeze).

### Claude's Discretion
- Internal module names within `heatwave/forecast/`. The suggested ones are `config.py`, `data.py`, `weeks.py`, `artifacts.py`, `fixtures`.
- The exact dataclass layout and error messages.
- Whether `verify_frozen.py` also checks the read-only flags.
- Synthetic fixture size, as long as it includes a 53-week year and at least 2 states.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design and research
- `.planning/research/SUMMARY.md` — agreed adjustments, Phase 8 delivers/avoids/exit
- `.planning/research/ARCHITECTURE.md` — package layout, artifact layout, config approach, CI considerations
- `.planning/research/STACK.md` — package versions, Windows wheel notes, shap fallback
- `.planning/research/PITFALLS.md` — M2 (week 53), m1 (live vs frozen)

### Existing code patterns
- `heatwave/config.py` — dataclass and validation style; `local_data_dir` resolution
- `heatwave/local/pipeline.py` — `COVARIATE_COLUMNS`, ISO week labelling
- `scripts/run_local_pipeline.py` — script style (`sys.path` insert, logging)
- `.github/workflows/tests.yml`, `pyproject.toml`, `requirements.txt`

### Frozen data
- `<local_data_dir>/frozen/covariates-v1.0/MANIFEST.json` — checksums, table shape, columns (`local_data_dir` = `../../Heatwave Data` relative to the repo)
</canonical_refs>

<specifics>
## Specific Ideas

- The frozen files are read-only on disk. The loader must only read them.
- The CSV sha256 starts `c7437cd0`; the parquet sha256 starts `82583fbf`.
- `docs/METHODOLOGY.md` sections 8-9 describe the data's caveats. No doc changes are needed in this phase, beyond a short README note on the new dependencies and Python 3.12.
</specifics>

<deferred>
## Deferred Ideas

- Feature store, targets, splits and leakage suite: Phase 9.
- Measuring the real ERA5-Land latency: Phase 9. `latency_days` = 8 stays a placeholder until then.
</deferred>

---

*Phase: 08-forecast-foundation*
*Context gathered: 2026-10-02 from agreed milestone decisions*
