# Phase 8: Forecast Foundation - Research

**Researched:** 2026-10-02
**Domain:** Python data-access/config/reproducibility foundation (pandas/pyarrow, PyYAML dataclasses, pytest, GitHub Actions)
**Confidence:** HIGH (most claims verified hands-on in this repo/venv)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- New sibling package `heatwave/forecast/`; never imports `ee`, `geemap`, `heatwave.auth` or any Earth Engine module; an import-isolation test enforces this.
- Settings in separate repo-root `forecast.yaml`, loaded into frozen dataclasses with `__post_init__` validation (style of `ClimatologyConfig`). `config.yaml`, `heatwave/config.py` and the 35 `tests/test_config.py` tests unchanged. `local_data_dir` reused from `heatwave.config.settings`.
- `forecast.yaml` sections: data (`version`=`covariates-v1.0`, frozen folder); splits (train 1991-2014, validate 2015-2020, test 2021-2026; cutoffs by `week_start` date; embargo weeks); leads [1..6]; latency_days default 8 (placeholder until Phase 9); gate (primary leads [2,3]; BSS > 0 vs best baseline with CI excluding 0); retrain_policy (refit 1991-2020 with frozen hyperparameters before the single test; operational model refit on all years, marked "not independently tested"); seed; model hyperparameter placeholders.
- Frozen data at `<local_data_dir>/frozen/covariates-v1.0/`; read `covariate_table.parquet`; verify SHA-256 against `MANIFEST.json` `outputs_sha256` before use. Fail loudly on mismatch, missing file, wrong columns. Reject live `outputs/covariate_table.csv`. Check schema vs MANIFEST `table.columns` (10 cols) plus rows/wards/weeks (9,018,783 / 4,841 / 1,863). Load into dense float32 panel (ward x week x variable) with ward index and week index.
- `scripts/verify_frozen.py` re-hashes frozen outputs and all 361 inputs against MANIFEST and reports mismatches.
- Week index: ISO label `YYYY-Www` <-> contiguous integer index <-> `week_start` Monday date; no label-string arithmetic; correct across 53-week years (1992, 1998, 2004, 2009, 2015, 2020, 2026), e.g. 2020-W53 = 2020-12-28..2021-01-03. Index 0 = 1991-W02.
- Run folders under `<local_data_dir>/forecast_runs/<run_id>/`, `run_id` = UTC timestamp + short config hash; contain `config.yaml` snapshot and `RUN_MANIFEST.json` (data version + parquet sha256, git commit + dirty flag, Python and library versions numpy/pandas/pyarrow/scikit-learn/lightgbm/shap, seed, start/end time). Nothing committed.
- Add to `requirements.txt`: `scikit-learn==1.9.1`, `lightgbm==4.7.0`, `shap==0.52.0`; keep numpy 2.3.3, pandas 2.3.2, pyarrow 21. Verify with `pip install --dry-run` first. Import smoke test (sklearn, lightgbm, shap). If shap cannot install with pins, fall back to LightGBM `pred_contrib`.
- CI -> Python 3.12; `pyproject.toml` `requires-python >=3.12`. CI must pass without frozen data: synthetic-panel fixture under `tests/forecast/` (few wards x few years incl. a 53-week year). pytest marker `frozen` auto-skipped when data absent. Existing 166 tests still pass (local: 166 passed, 2 skipped).

### Claude's Discretion
- Internal module names (suggested `config.py`, `data.py`, `weeks.py`, `artifacts.py`, `fixtures`); dataclass layout and error messages; whether `verify_frozen.py` also checks read-only flags; synthetic fixture size (must include a 53-week year and at least 2 states).

### Deferred Ideas (OUT OF SCOPE)
- Feature store, targets, splits, leakage suite (Phase 9). Measuring real ERA5-Land latency (Phase 9).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | Load frozen covariates-v1.0; refuse SHA mismatch and live CSV | Parquet verified: hash 82583fbf..., complete sorted panel, 0.65 s read, 1.6 GB as pandas; reshape recipe below |
| DATA-02 | ISO label <-> int index <-> week_start, 53-week safe | `datetime.date.fromisocalendar` / `isocalendar`; frozen weeks verified contiguous (all gaps = 7 days) incl. 6 W53 labels |
| DATA-03 | Validated `forecast.yaml` | Mirror `ClimatologyConfig` pattern; PyYAML 6.0.2 `safe_load` |
| DATA-04 | Run folders with provenance | `git` available (2.55); repo is a git repo; use `subprocess` (GitPython is also in requirements but unnecessary) |
| DATA-05 | Deps + CI 3.12 + no-ee import | Dry-run resolves cleanly; pytest/CI structure below |
</phase_requirements>

## Summary

Everything in the phase is low-risk plain Python. Hands-on checks show: (1) `pip install --dry-run scikit-learn==1.9.1 lightgbm==4.7.0 shap==0.52.0` resolves in `.venv` on Windows with cp312 win_amd64 wheels and does NOT change numpy (2.3.3 stays), pandas or pyarrow; new packages: cloudpickle 3.1.2, joblib 1.6.0, llvmlite 0.50.0, numba 0.68.0, scipy 1.18.1, slicer 0.0.8, threadpoolctl 3.7.0, tqdm 4.70.1. So the shap fallback is not needed locally. (2) The frozen parquet is a perfect dense panel: 9,018,783 rows = 4,841 x 1,863, no nulls per MANIFEST, sorted by (time_period, location), every ward has exactly 1,863 rows, week labels are contiguous at 7-day steps, and it contains six W53 labels (1992, 1998, 2004, 2009, 2015, 2020; 2026-W53 is a 53-week year but the data ends 2026-W38). (3) `import heatwave` only stubs `blessings`; `heatwave.config` imports only yaml, so `heatwave.forecast` can avoid `ee` trivially if it never imports `heatwave.auth`, `heatwave.batch`, `heatwave.zonal`, `heatwave.export`, or `heatwave.local` modules that pull ee.

Parquet read via `pd.read_parquet` takes ~0.65 s (warm) and ~1.6 GB as pandas object-string frame; SHA-256 of the 90 MB file takes ~0.11 s warm. Convert to float32 panel (4841 x 1863 x 9 vars = ~324 MB) and drop the object frame immediately.

**Primary recommendation:** Build `heatwave/forecast/{config,weeks,data,artifacts}.py` as stdlib+numpy+pandas+yaml only; verify hash from the raw bytes BEFORE parquet parsing; derive the week axis from labels once (via `date.fromisocalendar`) and assert it equals `1991-W02 + 7*i`; run all tests on a synthetic fixture plus `@pytest.mark.frozen` tests for the real data.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Frozen data verification and loading | Local Python library (`heatwave.forecast.data`) | scripts/verify_frozen.py (CLI) | Offline analysis layer; no server tiers exist |
| Week arithmetic | Library (`weeks.py`) | — | Pure functions, shared by every later phase |
| Config validation | Library (`config.py`) + repo-root `forecast.yaml` | — | Fail-fast at load |
| Run provenance | Library (`artifacts.py`) writing to `<local_data_dir>/forecast_runs/` | git CLI | Artifacts outside repo |
| CI | GitHub Actions `tests.yml` | — | No frozen data in CI |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | 1.9.1 | ML (later phases); import smoke now | Locked in CONTEXT [VERIFIED: pip dry-run, cp312 win wheel resolved] |
| lightgbm | 4.7.0 | GBM (later) | Locked [VERIFIED: pip dry-run] |
| shap | 0.52.0 | Explainability (later) | Locked [VERIFIED: dry-run resolves with numba 0.68.0 / llvmlite 0.50.0 cp312 win_amd64, numpy stays 2.3.3] |
| numpy / pandas / pyarrow / PyYAML | 2.3.3 / 2.3.2 / 21.0.0 / 6.0.2 | Existing pins | Installed [VERIFIED: pip list] |

Note: the dry-run resolved numba without touching numpy; whether `import shap` actually runs against numpy 2.3.3 can only be proven by real install (not done, per instructions). Keep the CONTEXT fallback (pred_contrib) and make the smoke test for shap the first CI/local check. [ASSUMED] numba 0.68 supports numpy 2.3 (pip resolver accepted it, which is evidence via its metadata, not a runtime test).

**Installation:**
```bash
.venv/Scripts/python.exe -m pip install "scikit-learn==1.9.1" "lightgbm==4.7.0" "shap==0.52.0"
# then append transitive pins (cloudpickle, joblib, llvmlite, numba, scipy, slicer, threadpoolctl, tqdm) to requirements.txt,
# because requirements.txt is a full alphabetised freeze (no ranges), keep that style.
```

## Package Legitimacy Audit

slopcheck was not run (not installed; pip install into the shared environment avoided). All three primary packages were named by the user in CONTEXT and are major, long-established projects; transitive packages came from the pip resolver. Per protocol they are tagged [ASSUMED] for provenance: planner should include a single `checkpoint:human-verify` before the real `pip install`, showing the dry-run output.

| Package | Registry | Age | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-------------|-----------|-------------|
| scikit-learn, lightgbm, shap | PyPI | many years | scikit-learn/scikit-learn, microsoft/LightGBM, shap/shap | not run | Approved by user decision; human-verify gate |
| numba, llvmlite, scipy, joblib, threadpoolctl, tqdm, cloudpickle, slicer | PyPI | many years | well-known | not run | Transitive; human-verify gate |

**Removed:** none. **Flagged [SUS]:** none identified.

## Architecture Patterns

### Data flow
```
forecast.yaml --> ForecastConfig (frozen dataclasses, __post_init__ validation)
                        |
 local_data_dir (heatwave.config.settings) --> frozen/covariates-v1.0/
        MANIFEST.json --(outputs_sha256, table.*)--> expected hash/columns/counts
        covariate_table.parquet --(sha256 of bytes first)--> pd.read_parquet
              --> schema/row/ward/week checks --> dense float32 Panel(values[ward,week,var], wards, weeks, variables)
 weeks.py: label <-> index <-> week_start (used by Panel and later phases)
 artifacts.py: RunFolder(<local_data_dir>/forecast_runs/<run_id>/{config.yaml,RUN_MANIFEST.json})
```

### Recommended structure
```
heatwave/forecast/__init__.py   # empty docstring only; NO imports of heatwave.auth/ee
heatwave/forecast/config.py     # dataclasses + load_forecast_config(path)
heatwave/forecast/weeks.py
heatwave/forecast/data.py       # verify_frozen_dataset, load_panel, Panel, FrozenDataError
heatwave/forecast/artifacts.py  # create_run_folder, write_manifest, git_info
heatwave/forecast/fixtures.py   # synthetic panel builder (importable by tests/forecast and later phases)
forecast.yaml
scripts/verify_frozen.py        # sys.path insert style as run_local_pipeline.py
tests/forecast/{test_weeks,test_config,test_data,test_artifacts,test_imports,test_deps_smoke}.py
```
`pyproject.toml` already uses `packages.find include = ["heatwave*"]`, so the new subpackage is picked up (needs `__init__.py`).

### Pattern: week axis (DATA-02)
```python
from datetime import date, timedelta
EPOCH = date.fromisocalendar(1991, 2, 1)          # 1991-01-07, Monday  [VERIFIED: 1991-01-01 is a Tuesday, W01 starts 1990-12-31]
def label_to_index(label: str) -> int:
    y, w = int(label[:4]), int(label[6:])          # "YYYY-Www"
    return (date.fromisocalendar(y, w, 1) - EPOCH).days // 7   # fromisocalendar raises ValueError for W53 in 52-week years
def index_to_week_start(i): return EPOCH + timedelta(weeks=i)
def index_to_label(i):
    y, w, _ = index_to_week_start(i).isocalendar(); return f"{y}-W{w:02d}"
```
Never compare or subtract label strings. Vectorised variant for 9M-row column: build the 1,863-entry label->index dict once from `unique()` labels, then map (do not call fromisocalendar 9M times). Pipeline writes labels via isocalendar (`heatwave/local/pipeline.py` line ~129) so labels use ISO year, matching `isocalendar()`. Parity test: round-trip every index 0..1862 and the frozen label set.

### Pattern: panel build
Data are sorted by (time_period, location) with identical ward set in every week, so: assert `groupby`-free completeness (`len == W*N`), map labels->week idx and wards->ward idx via `pd.factorize`/`Categorical`, then `arr = np.full((N, W, V), np.nan, float32); arr[w_idx, t_idx, :] = df[vars].to_numpy(float32)`; assert no NaN remains (MANIFEST nulls=0). Do not trust sort order; index explicitly. Ward order: sorted ward codes for determinism. Variables: 8 numeric columns (`heatwave_days, mean_heat_index, max_heat_index, heatwave_event_count, hot_nights, total_precipitation_mm, mean_relative_humidity, mean_soil_moisture`) = ~1.3 GB? Compute: 4841*1863*8*4 B = 289 MB. Read only the columns needed (`columns=`) and release the DataFrame.
float32 caveat: values like `max_heat_index` at 3-decimal rounding lose nothing material; integer counts exact. Test with the frozen marker that `panel.values` round-trips to float32(df).

### Pattern: loader refusal of live CSV (DATA-01)
Loader takes only a dataset *version name/folder*, not an arbitrary path; it resolves `<local_data_dir>/frozen/<version>/covariate_table.parquet`. Additionally reject: any path whose resolved parent is not under `frozen/`, any `.csv` suffix, and any file whose sha256 is not `MANIFEST.outputs_sha256[name]`. The live CSV in `outputs/` will fail on at least one of those; test with a tmp copy of the synthetic fixture.
Order: (1) MANIFEST present and `version` matches config; (2) file exists; (3) stream-hash in 1 MiB chunks; (4) only then parse parquet; (5) schema via `pq.ParquetFile(p).schema_arrow.names == table.columns` (cheap, no data read); (6) counts. Hash cost ~0.1-0.5 s, acceptable every load.
The MANIFEST itself is not self-authenticating (it sits beside the data); note that and optionally pin the expected parquet hash prefix `82583fbf` in `forecast.yaml data.expected_sha256` as a second anchor (recommended, cheap, defeats a tampered MANIFEST+parquet pair). [Discretion]

### Pattern: config (DATA-03)
Frozen dataclasses: `DataConfig, SplitsConfig, GateConfig, RetrainPolicy, ModelConfig, ForecastConfig`. Validate in `__post_init__`: leads non-empty, unique, ascending ints >= 1; primary leads subset of leads; years ordered and non-overlapping train<validate<test; split cutoffs parsed as `date` and each must be a Monday; embargo_weeks >= 0 int; latency_days int >= 0 (bool rejected: `isinstance(x, bool)` check because `True` is an int); seed int >= 0; `data.version` matches `^covariates-v\d+\.\d+$`; unknown keys rejected (`ForecastConfig(**raw)` raises TypeError on extras -> wrap with clear ValueError); loader uses `yaml.safe_load`. Tuples not lists in frozen dataclasses (hashable, for the config hash). Cutoffs by `week_start` date: store e.g. `train_end: 2014-12-29` ... decide inclusive/exclusive semantics once and document; derive from week_start Mondays since years straddle ISO boundaries (e.g. 2014 last ISO week starts 2014-12-29; 2021-W01 starts 2021-01-04; 2020-W53 starts 2020-12-28 so "validate through 2020" includes W53). Note PyYAML parses unquoted `2014-12-29` as `datetime.date` already. [VERIFIED: PyYAML timestamp implicit resolver - standard behaviour]
`local_data_dir`: `heatwave.config.settings.local_data_dir = _REPO_ROOT / os.getenv("HEATWAVE_DATA_DIR", "../../Heatwave Data")` [VERIFIED in code; config.yaml line 16 `"../../Heatwave Data"`]. Resolves to a non-normalised path with `..`; call `.resolve()`. Note: `_REPO_ROOT / absolute_env_value` yields the absolute value (pathlib semantics), so env override with an absolute path works. Tests must monkeypatch by passing `data_root` explicitly to loader functions (default argument = settings value) instead of editing settings.

### Pattern: run folder (DATA-04)
`run_id = f"{utc:%Y%m%dT%H%M%SZ}_{cfg_hash[:8]}"` where `cfg_hash = sha256(canonical json/yaml dump of dataclasses.asdict(cfg))`. Create with `mkdir(parents=True, exist_ok=False)`; collision (same second, same config) -> raise or add suffix. Refuse a base dir inside the repo (resolve and check `repo_root not in path.parents`). Write snapshot as the validated config re-dumped (and optionally a byte copy of forecast.yaml). RUN_MANIFEST: data version, parquet sha256, `git rev-parse HEAD`, dirty = `git status --porcelain` non-empty, python version, `importlib.metadata.version(pkg)` for numpy/pandas/pyarrow/scikit-learn/lightgbm/shap (store `null`/"not installed" if missing rather than crash - shap fallback case), seed, start/end ISO UTC. Write `RUN_MANIFEST.json` at start (status "running") and rewrite at end (atomic: write tmp then `os.replace`), so crashes leave evidence. Use `subprocess.run(["git", ...], cwd=repo_root, capture_output=True, text=True, timeout=10)`; if git absent/not a repo -> commit `null`, not an exception. Do NOT use `git status` on Windows with huge untracked dirs unguarded (outputs/ and build/ exist) - use `git status --porcelain --untracked-files=no` for speed and to avoid flagging data files. Seed handling: `numpy.random.default_rng(seed)`; record, don't set global state.

### Anti-Patterns to Avoid
- Parsing labels with string sort/`int(label[-2:])` arithmetic across years (W53 -> breaks).
- `pd.to_datetime(label + "-1", format="%G-W%V-%u")` in hot loops - correct but slow; use dict over unique labels.
- Importing from `heatwave.local` modules in forecast (check what they import before reusing `COVARIATE_COLUMNS`; safer to read the column list from MANIFEST and cross-check against a constant in forecast code). Verify with the import-isolation test rather than assumption.
- Reading the 517 MB CSV anywhere in the forecast package.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ISO calendar math | Own week-count rules | `datetime.date.fromisocalendar` / `.isocalendar()` (stdlib, 3.8+) | Handles W53 and ISO-year boundaries |
| Hashing | Custom | `hashlib.sha256` chunked | Stdlib |
| Package versions | Parse `pip freeze` | `importlib.metadata.version` | Reliable |
| YAML | Custom parser | `yaml.safe_load` | Already pinned |
| Parquet schema peek | Read data to see columns | `pyarrow.parquet.ParquetFile(...).schema_arrow` | Metadata only |

## Runtime State Inventory
Not a rename/migration phase - omitted. (`pyproject requires-python` and CI Python bump are config edits only.)

## Common Pitfalls

### 1. Label vs ISO-year mismatch (W53)
`2020-W53` is valid, `2021-W53` is not (`fromisocalendar` raises ValueError - useful as validation). Calendar year != ISO year: `2021-01-03` is `2020-W53`; `2018-12-31` is `2019-W01`. Test fixed vectors: 2020-W53 -> 2020-12-28; index of 2021-W01 = index(2020-W53)+1; 1992/1998/2004/2009/2015/2020/2026 have W53, and 2026-W53 starts 2026-12-28 (beyond data, so only the pure function test covers it). Derive the 53-week set in a test from `date(y,12,28).isocalendar()[1] == 53` and compare to the user's list.

### 2. Frozen data window vs "year" splits
Table spans 1991-W02..2026-W38 (last_day 2026-09-23 but week 38 ends 2026-09-20; days 09-21..23 are dropped). 1991-01-01..06 days are in 1990-W53/1991-W01 and excluded, so "train 1991-2014" really begins 1991-W02. Config split semantics should be by `week_start` date, defined once.

### 3. Hash then parse, not parse then hash
Parsing untrusted parquet before verification wastes time and widens attack surface; verify bytes first. Also avoid TOCTOU: read file once if possible (hash chunked then re-open is fine for local analysis; note it).

### 4. Read-only files on Windows
Frozen files are `-r--r--r--`. Open with mode `"rb"` only; never `os.chmod`/replace. Tests that corrupt a copy must copy to `tmp_path` (copy of a read-only file is writable? `shutil.copy` copies mode bits -> copy is read-only; call `os.chmod(copy, 0o600)` before modifying, or write fixture bytes fresh).

### 5. Test discovery collisions
`tests/` has no `__init__.py` and no conftest; pytest default `prepend` import mode uses basenames, so `tests/forecast/test_config.py` COLLIDES with `tests/test_config.py` ("import file mismatch"). Fix: give new tests unique names (`test_forecast_config.py`) or add `tests/forecast/__init__.py` (then the dir becomes package `forecast`; and `tests/__init__.py` is still absent - works since rootdir of package is `tests/`; note package name `forecast` is fine). Recommended: unique filenames AND `__init__.py`-free; pick one and keep it. `pythonpath = ["."]` already makes `import heatwave` work.

### 6. Marker registration
Unregistered `frozen` marker only warns, but register in `[tool.pytest.ini_options] markers = ["frozen: needs real covariates-v1.0 data (skipped if absent)"]`. Auto-skip via a `tests/conftest.py` (new, harmless to existing tests) `pytest_collection_modifyitems` that adds `skip` to `frozen` items when `<local_data_dir>/frozen/covariates-v1.0/covariate_table.parquet` is missing. Do not use `--strict-markers` globally unless all existing markers are registered (existing opt-in tests skip via env/credentials - check `grep -rn "pytest.mark" tests`).

### 7. CI platform differences
CI is ubuntu-latest; `requirements.txt` is a Windows-origin freeze but already installs there today (colorama is harmless). The new packages have manylinux cp312 wheels (lightgbm needs libgomp, preinstalled on ubuntu runners) [ASSUMED - standard practice, not verified]. numba/llvmlite increase install time (~tens of seconds) - acceptable. Use `actions/setup-python@v5` `python-version: "3.12"` and optionally `cache: pip`.

### 8. `requires-python` bump
Changing to `>=3.12` is metadata only. Local venv is 3.12.10 so no impact; README should mention Python 3.12.

## Code Examples

### Chunked hash
```python
import hashlib
def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()
```

### Import-isolation test (DATA-05)
Run in a subprocess to get a clean interpreter (other tests in-process may have imported ee):
```python
import subprocess, sys, textwrap
def test_forecast_never_imports_ee():
    code = textwrap.dedent("""
        import sys, importlib, pkgutil
        import heatwave.forecast as pkg
        for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            importlib.import_module(m.name)
        bad = [n for n in sys.modules if n.split(".")[0] in {"ee", "geemap"} or n == "heatwave.auth"]
        assert not bad, bad
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
```
Plus a static AST scan of `heatwave/forecast/**/*.py` for `import ee|geemap|heatwave.auth` (catches lazy imports inside functions). `heatwave.auth` evidently imports ee/credentials (it is gated on `_HAS_CREDENTIALS`) [CITED: workflow comment in tests.yml]. Verified baseline: `import heatwave` leaves `ee` and `geemap` out of `sys.modules` [VERIFIED: ran].

### CI workflow edit
Only `python-version: "3.12"` changes (line `python-version: "3.11"`); the install step stays `pip install -r requirements.txt`; the `pytest -v` run excludes nothing (frozen tests self-skip). Optionally add a step `python -c "import sklearn, lightgbm, shap"` for fast failure (the pytest smoke test already covers it).

## State of the Art
| Old | Current | Impact |
|-----|---------|--------|
| `CalibratedClassifierCV(cv="prefit")` | FrozenEstimator | Not this phase |
| Group-by shifts on 9M rows | Dense 3D arrays | Panel built here |

## Assumptions Log
| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `import shap` works at runtime with numpy 2.3.3 / numba 0.68 (only resolution verified) | Standard Stack | Fall back to pred_contrib (already a locked fallback) |
| A2 | manylinux cp312 wheels + libgomp OK on ubuntu-latest | Pitfall 7 | CI red; add `apt-get install libgomp1` |
| A3 | Packages not slopchecked | Audit | Low; user-chosen major libs |
| A4 | Pinning expected parquet sha in forecast.yaml is desirable | Patterns | Discretion; drop if unwanted |

## Open Questions
1. **Split cutoff semantics (inclusive/exclusive, which Monday)**: recommend `train_end_week_start` etc. as exclusive upper bounds = Monday of first week of next period, e.g. validate starts `2015-01-05` (2015-W02? note 2014-12-29 is 2015-W01, ISO year 2015). Decide whether "year" means ISO year (recommended, matches labels) and document; planner should make this an explicit task with a test. Embargo default suggestion: `max(leads)` = 6 weeks (Phase 9 may refine).
2. **Should `verify_frozen.py` check read-only flags?** Discretion; recommend report-only (warn), not fail, because Windows ACL/attribute semantics differ across machines.
3. **Inputs path**: 361 inputs under `frozen/covariates-v1.0/inputs/` (plus `wards.geojson` key resolution relative to `inputs/`); confirm MANIFEST keys are relative to `inputs/` (key `era5_land_daily_gee/.../1991.nc`, `wards.geojson`) - verify at implementation by checking the first key's file exists; hashing ~all inputs is slow-ish (GB of .nc) so script should show progress and support `--outputs-only`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | all | yes | 3.12.10 | — |
| numpy/pandas/pyarrow/PyYAML/pytest | all | yes | 2.3.3/2.3.2/21.0.0/6.0.2/8.4.1 | — |
| scikit-learn/lightgbm/shap | DATA-05 | not yet installed; dry-run OK | 1.9.1/4.7.0/0.52.0 | pred_contrib if shap import fails |
| git | DATA-04 | yes | 2.55.0.windows.3 (repo root confirmed) | commit=null |
| Frozen data | frozen tests | yes | covariates-v1.0, parquet 90 MB, read-only | tests skip |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 (`[tool.pytest.ini_options] pythonpath=["."]`; no conftest today) |
| Config file | `pyproject.toml` (add `markers`) ; new `tests/conftest.py` for frozen auto-skip |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/forecast -x -q` |
| Full suite command | `.venv/Scripts/python.exe -m pytest -q` (expect 166 existing + new; 2 skipped existing) |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | Data needed | File Exists? |
|--------|----------|-----------|-------------------|-------------|--------------|
| DATA-01 | Valid fixture loads; byte-flipped copy -> hash error; wrong columns, wrong counts, missing file, live-CSV path/suffix refused | unit | `pytest tests/forecast/test_forecast_data.py -x` | synthetic (build fixture parquet+MANIFEST in tmp_path) | Wave 0 |
| DATA-01 | Real frozen parquet loads, shape (4841,1863,8), no NaN, hash matches `82583fbf` | integration `@frozen` | `pytest -m frozen tests/forecast/test_forecast_frozen.py` | real | Wave 0 |
| DATA-01 | Modified copy of real parquet rejected | `@frozen` (copy 90 MB to tmp, flip a byte) | same | real | Wave 0 |
| DATA-02 | Round-trip label<->index<->date for all 1,863 indices; 53-week set vs `isocalendar`; 2020-W53 -> 2020-12-28..2021-01-03; index 0 = 1991-W02 = 1991-01-07; invalid `2021-W53` raises | unit | `pytest tests/forecast/test_forecast_weeks.py` | none | Wave 0 |
| DATA-02 | Frozen label set == generated labels for 0..1862 | `@frozen` | in frozen file | real | Wave 0 |
| DATA-03 | Valid `forecast.yaml` loads; each bad value (leads dup/zero, overlapping splits, non-Monday cutoff, negative latency, bool latency, primary leads not in leads, unknown key, wrong version) raises; `config.yaml` and `tests/test_config.py` unchanged | unit | `pytest tests/forecast/test_forecast_config.py` and `pytest tests/test_config.py` | none | Wave 0 |
| DATA-04 | Run folder created under tmp data root, contains config.yaml + RUN_MANIFEST.json with all keys; refuses in-repo base; unique ids; git info tolerant of missing git (monkeypatch) | unit | `pytest tests/forecast/test_forecast_artifacts.py` | none | Wave 0 |
| DATA-05 | `import sklearn, lightgbm, shap` smoke; forecast import isolation (subprocess + AST); versions match pins | unit | `pytest tests/forecast/test_forecast_deps.py` | none | Wave 0 |
| DATA-05 | Existing suite intact; CI green py3.12 | full suite / CI | `pytest -q`; push | none | existing |
| script | `verify_frozen.py --outputs-only` exits 0 on real data, nonzero on tampered copy | `@frozen` / subprocess | `python scripts/verify_frozen.py --outputs-only` | real | Wave 0 |

### Sampling Rate
- Per task commit: quick run command (< 10 s without frozen).
- Per wave merge: full suite.
- Phase gate: full suite green locally, plus `pytest -m frozen` locally with real data (not run in CI), and CI green.

### Wave 0 Gaps
- [ ] `tests/conftest.py` (frozen auto-skip, `frozen_root` fixture, synthetic fixture helpers)
- [ ] `heatwave/forecast/fixtures.py` synthetic panel builder: e.g. 6 wards across 2-3 states x weeks covering 1992 (W53) through at least 1993-W05, writes parquet + MANIFEST matching the real schema/types (strings for time_period/location, int64 counts, float64 others)
- [ ] pyproject marker registration; unique test filenames (see Pitfall 5)
- [ ] Dependency install after human-verify checkpoint

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input validation | yes | `__post_init__` validation; `yaml.safe_load` only (never `yaml.load`) |
| V6 Cryptography | yes (integrity) | `hashlib.sha256` stdlib; no custom crypto |
| V12 Files | yes | read-only open of frozen data; run folder path confined outside repo; no path from untrusted input joined without `resolve()` containment check |
| V2/V3/V4 | no | local analysis tool |

| Threat | STRIDE | Mitigation |
|--------|--------|-----------|
| Tampered/stale data used for training | Tampering | Hash before parse; optional second anchor hash in config |
| YAML arbitrary object construction | Tampering/EoP | `safe_load` |
| Path traversal in `data.version` (`../outputs`) | Tampering | Regex-validate version; resolve and assert under `frozen/` |
| Pickle usage in later phases | EoP | Not in this phase; note for Phase 12+ |

## Sources
### Primary (HIGH) - verified hands-on in this session
- Repo files: `pyproject.toml`, `.github/workflows/tests.yml`, `requirements.txt`, `heatwave/__init__.py`, `heatwave/config.py`, `config.yaml`, MANIFEST.json
- `.venv` Python 3.12.10: `pip install --dry-run` output; parquet schema/row groups (9 row groups), read time, memory, label/gap checks, sha256 prefix
- Planning docs: CONTEXT.md, REQUIREMENTS.md, STACK.md
### Secondary / Tertiary
- Python docs for `date.fromisocalendar` (stdlib behaviour, training knowledge) - MEDIUM
- ARCHITECTURE.md, PITFALLS.md, SUMMARY.md were not re-read in full here; planner should skim PITFALLS M2/m1 per CONTEXT canonical refs.

## Metadata
**Confidence:** stack HIGH (dry-run), architecture HIGH, pitfalls HIGH (test-collision and read-only items derived from observed repo layout), CI-on-ubuntu wheels MEDIUM.
**Research date:** 2026-10-02 **Valid until:** ~30 days (pins are fixed).
