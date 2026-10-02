# Architecture Research: v2.0 Forecast Layer

**Domain:** Ward-level weekly heat-indicator forecasting bolted onto a rule-based detection pipeline
**Researched:** 2026-10-02
**Confidence:** HIGH for integration points (grounded in the repo code and the frozen MANIFEST); MEDIUM for library-specific details (not re-verified here, see STACK.md)

## Grounding Facts From the Existing Code

- `heatwave/local/pipeline.py::weekly_table` is the only producer of the covariate table. Columns are fixed by `COVARIATE_COLUMNS`: `time_period` ("1991-W02", ISO label string), `location` (ward id), `heatwave_days`, `mean_heat_index`, `max_heat_index`, `heatwave_event_count`, `hot_nights`, `total_precipitation_mm`, `mean_relative_humidity`, `mean_soil_moisture`. Only complete 7-day ISO weeks are kept.
- The table is a tidy long panel of 9,018,783 rows (4,841 wards x 1,863 weeks, 1991-W02 to 2026-W38), no nulls. Frozen copy is `<local_data_dir>/frozen/covariates-v1.0/covariate_table.parquet` plus `MANIFEST.json`. The manifest has `outputs_sha256` for the parquet, so checksum verification is a ~10-line function.
- `heatwave_days` and `hot_nights` are produced by thresholds computed from the 1991-2020 baseline (`ClimatologyConfig`). That baseline overlaps the validation (2015-2020) years. This is the label DEFINITION (WMO/ETCCDI), not a model feature, so it is acceptable, but it must be stated in the report as a known, small, shared-by-all-models label property. Do NOT re-derive labels from daily data (the frozen table has no daily series). Do NOT reuse these thresholds for feature anomalies (see Leakage section).
- `heatwave/config.py` has a module-level singleton `settings = load_settings()`, frozen dataclasses with `__post_init__` validation, and `local_data_dir` (env override `HEATWAVE_DATA_DIR`). `config.yaml` currently has no forecast section. Note `load_settings` does `Settings(...)` with explicit keys, so a new section must be added without breaking `tests/test_config.py` (35 tests; missing-key tests assume the listed top-level keys are required). A new optional section must default when absent.
- `scripts/run_local_pipeline.py` writes to `--output` (default `outputs/covariate_table.csv`, gitignored via `outputs/*.csv`), with `.part` atomic write, and calls `sys.path.insert` for repo-root imports. New scripts should mimic this style (argparse, logging, `main(argv)`, `if __name__ == "__main__"`).
- CI (`.github/workflows/tests.yml`) runs `pip install -r requirements.txt` then `pytest -v` on ubuntu, Python 3.11, with no data. requirements.txt is a full pinned freeze with no scikit-learn/LightGBM/SHAP/matplotlib yet. pyarrow 21.0.0 and pandas 2.3.2 are already pinned.
- Frozen manifest records the dataset was built on Python 3.12.10; CI uses 3.11. Pinned wheels must exist for both (check at install time).

## Recommended Architecture

### System Overview

```
 EXISTING (unchanged)                         NEW (heatwave/forecast/)
┌────────────────────────────┐
│ ERA5-Land NetCDF           │
│ scripts/run_local_pipeline │
│ local/pipeline.weekly_table│
└─────────────┬──────────────┘
              │ covariate_table.csv (live, overwritten)       frozen copy (read-only, sha256)
              │                                               covariates-v1.0/covariate_table.parquet
              │                                                         │
              │                    ┌────────────────────────────────────┤
              │                    │ TRAINING / EVALUATION PATH         │
              │                    ▼                                    │
              │            data.py  load_frozen() + verify_checksum()   │
              │                    │ panel (week_idx int, ward cat)     │
              │                    ▼                                    │
              │            weeks.py  ISO label <-> week index, leads    │
              │                    ▼                                    │
              │            climatology.py  fit on train years only      │
              │                    ▼                                    │
              │            features.py  lagged feats @ issue week t     │
              │            targets.py   y(t+lead) per lead              │
              │                    ▼                                    │
              │            dataset.py   (X, y, meta) per lead  ──► leakage test (tests/)
              │                    ▼                                    │
              │            splits.py    train/val/test + expanding CV   │
              │                    ▼                                    │
              │   baselines.py   models/{logistic,lgbm,quantile}.py     │
              │                    ▼        calibration.py              │
              │            evaluation/{metrics,bootstrap,slices}.py     │
              │            explain.py (SHAP, ablations)                  │
              │                    ▼                                    │
              │            report.py + gate.py  ──► go/no-go            │
              │                    ▼                                    │
              │            artifacts.py  runs/<run_id>/ (model, metrics)│
              │                                                         │
              │ OPERATIONAL PATH (weekly)                               │
              ▼                                                         │
   fresh covariate table (run_local_pipeline output, same schema)      │
              │   + registered model bundle (from artifacts)            │
              ▼                                                         │
        operational.py  build features for latest issue week ONLY       │
              ▼              predict leads 1-6, calibrate, quantiles    │
        forecast_table.csv/parquet  (CHAP schema) + FORECAST_MANIFEST   │
```

### Component Responsibilities

| Component | Responsibility | Notes |
|-----------|----------------|-------|
| `forecast/config.py` | Typed `ForecastConfig` (leads, split years, lags, model params, seeds, paths, thresholds for go/no-go) | Separate dataclass, loaded from its own YAML (see Config) |
| `forecast/data.py` | `load_frozen(version)`, `verify_checksum`, `load_live(path)`, schema check against `COVARIATE_COLUMNS`, convert to dense panel | Single entry point for all data; refuses to train on anything not under `frozen/` |
| `forecast/weeks.py` | Parse "YYYY-Www" to a monotonically increasing integer week index and a (year, week, week_of_year) tuple; gap check; `add_weeks(idx, k)` | ISO years have 52 or 53 weeks, so never do arithmetic on the label string |
| `forecast/climatology.py` | Fit week-of-year (smoothed) mean/std/quantile per ward using TRAIN weeks only; `anomaly(x)` | Object with `fit(panel, years)` and `transform`; stored in the model bundle |
| `forecast/features.py` | Pure functions: panel + issue-week index -> feature frame. Lag 0..L of anomalies, rolling means, recent hot-day counts, season (sin/cos week), ward static (lat/lon, state, region), seasonal-lag climate state | Only ever reads rows with week_idx <= issue week |
| `forecast/targets.py` | `y_hw(t, lead) = heatwave_days[t+lead] >= 3`; `hi_anom(t, lead)`; `hot_nights(t, lead)`; drops rows whose target week is missing | The only module allowed to look forward in time |
| `forecast/dataset.py` | Joins features and targets for one lead; returns `LeadDataset(X, y, meta)` where meta carries issue_week, target_week, ward, year, region, split | Meta is not fed to models |
| `forecast/splits.py` | `assign_split(target_week or issue_week)`, expanding-window CV folds with an embargo gap | Split key is the TARGET year for labels; training rows must have target week inside the train period (no label bleeding across the boundary) |
| `forecast/baselines.py` | Climatology, 10-yr recent climatology, persistence as the same `Predictor` interface as models | Evaluated by the same harness |
| `forecast/models/` | `logistic.py`, `lgbm.py`, `quantile.py`; common `fit/predict_proba/predict_quantiles/save/load` | One fitted object per (target, lead) |
| `forecast/calibration.py` | Isotonic fit on validation predictions, applied at test and operational time | Fit on validation never on test; for final model refit see Retrain Policy |
| `forecast/evaluation/` | `metrics.py` (BSS, AUC, P/R/F1, MAE, pinball, coverage), `bootstrap.py` (week-block), `slices.py` (lead, season, region), `reliability.py` | Pure numpy/pandas functions, heavily unit-tested on synthetic data |
| `forecast/explain.py` | SHAP summary, ablation runner (drop feature group, retrain, re-score) | Ablations are config-driven feature-group lists |
| `forecast/gate.py` | Encodes go/no-go criteria from config (e.g. BSS vs best baseline with CI lower bound > 0 at leads X) | Returns structured decision, so the report cannot disagree with it |
| `forecast/report.py` | Renders metrics.json + plots into `report.md` (+ PNG figures) | Reads only artifacts; no recompute |
| `forecast/artifacts.py` | Run directory creation, run_id, writes config snapshot, git commit, data_version, library versions, model bundle, metrics | Single place that knows the layout |
| `forecast/operational.py` | `make_forecast(live_table, bundle_dir, issue_week)` -> CHAP forecast table | Reuses `features.py` verbatim (train/serve parity) |
| `forecast/drivers.py` (later phase) | Load ENSO/Atlantic SST/MJO monthly or daily indices, lag them to the issue week, expose as a feature group | Needs its own frozen/versioned input and publication-lag handling |

### Package Layout

```
heatwave/
  forecast/                      NEW
    __init__.py
    config.py
    data.py
    weeks.py
    climatology.py
    features.py
    targets.py
    dataset.py
    splits.py
    baselines.py
    calibration.py
    explain.py
    gate.py
    report.py
    artifacts.py
    operational.py
    drivers.py                   (later phase)
    models/
      __init__.py                (registry + Predictor protocol)
      logistic.py
      lgbm.py
      quantile.py
    evaluation/
      __init__.py
      metrics.py
      bootstrap.py
      slices.py
      reliability.py
scripts/
  forecast_train.py              NEW  (fit + validate; --lead, --model, --stage dev|final)
  forecast_evaluate.py           NEW  (score a run on validation, or on test with --final lock)
  forecast_report.py             NEW  (artifacts -> report.md, gate decision)
  forecast_run.py                NEW  (operational weekly forecast)
  verify_frozen.py               NEW  (optional: checksum a frozen version; also used by CI-less local checks)
config/forecast.yaml             NEW  (or repo-root forecast.yaml; see Config)
tests/forecast/                  NEW
  conftest.py                    (synthetic panel factory)
  test_leakage.py
  test_weeks.py  test_features.py  test_targets.py  test_splits.py
  test_metrics.py  test_bootstrap.py  test_baselines.py
  test_models_smoke.py  test_calibration.py  test_operational.py  test_data_checksum.py
```

Rationale for a sibling package `heatwave/forecast/` rather than extending `heatwave/local/`: `local/` is the detection/production table builder, and the PROJECT.md constraint says reports must keep the rule-based detection layer separate from the trained forecast layer. The forecast package depends on the covariate table schema only (via `COVARIATE_COLUMNS` import), never on `local.science`, `grid`, or Earth Engine. It must be importable without `ee`, `geemap`, `xarray`, or credentials. Note `heatwave/__init__.py` has the `blessings` stub; verify `import heatwave.forecast` does not drag in `heatwave.auth`/geemap (add an import-isolation test).

## Config

**Recommendation: a separate `forecast.yaml` loaded by `heatwave/forecast/config.py`, not a new section in `config.yaml`.**

Why: `load_settings` builds `Settings` from required keys and `tests/test_config.py` has 35 tests keyed on that structure, so adding a section to the shared file forces edits to a stable, validated module and risks the v1 test suite. The forecast settings are large (lags, model hyperparameters, thresholds) and change on every experiment; one run snapshots exactly the YAML used. Shared values are read, not duplicated: `ForecastConfig` takes `local_data_dir` from `heatwave.config.settings` (honours `HEATWAVE_DATA_DIR`) and the climatology baseline is NOT reused for features.

Minimal modification to existing code: none required. Optionally add one line `forecast_config: forecast.yaml` later; not needed.

```yaml
# forecast.yaml
data_version: covariates-v1.0
leads: [1, 2, 3, 4, 5, 6]
target: {heatwave_week_min_days: 3}
split: {train: [1991, 2014], validation: [2015, 2020], test: [2021, 2026]}
cv: {scheme: expanding, first_train_end: 2005, step_years: 3, embargo_weeks: 6}
features: {lags_weeks: 8, rolling_windows: [2, 4, 8], groups: [heat, humidity, rain_soil, season, static]}
climatology: {fit_years: train, smoothing_days_of_year: 3}   # train-only, never 1991-2020
models: {logistic: {C: 1.0}, lgbm: {...}, quantile: {alphas: [0.1, 0.5, 0.9]}}
calibration: {method: isotonic, fit_on: validation}
bootstrap: {block: week, n_boot: 1000, seed: 42}
gate: {metric: bss, vs: best_baseline, ci_lower_gt: 0.0, min_leads_passing: 3}
seed: 42
```

Frozen dataclasses with `__post_init__` validation, matching `ClimatologyConfig` style (e.g. train < validation < test, leads >= 1, test_year_start > validation_end).

## Artifact Layout (outside the repo, versioned, gitignored)

Store under `<local_data_dir>/forecast_runs/` (same root as `frozen/` so one `HEATWAVE_DATA_DIR` moves everything; a ~9M-row panel and model files do not belong in git). In-repo, add `forecast_runs/` and `*.joblib` to `.gitignore` as a guard, and commit only the small, human-readable decision artefacts (see below).

```
<local_data_dir>/
  frozen/covariates-v1.0/...                       (existing, read-only)
  frozen/covariates-v1.0/inputs/...               (existing)
  forecast_cache/<data_version>/<feature_hash>/    NEW  feature store (parquet per lead or per split)
  forecast_runs/<run_id>/                          NEW  run_id = YYYYMMDDTHHMMSS_<git7>_<cfg_hash6>
    config.snapshot.yaml
    RUN_MANIFEST.json            (data_version, parquet sha256, git commit + dirty flag, lib versions, seed, python)
    models/<target>/lead<k>/model.joblib (+ calibrator.joblib, climatology.joblib)
    predictions/<split>/<target>_lead<k>.parquet   (issue_week, target_week, ward, y_true, p_raw, p_cal, baseline preds)
    metrics/metrics.json         (full tables incl. bootstrap CIs)
    figures/*.png                (reliability, BSS by lead/season/region, SHAP)
    report.md
    GATE.json                    (decision + inputs)
  forecast_releases/<model_version>/                NEW  promoted bundle used operationally
    bundle/ (models + calibrators + climatology + feature spec + config snapshot)
    MODEL_CARD.md
  forecast_output/<issue_week>/                     NEW  operational outputs
    forecast_table.parquet + .csv
    FORECAST_MANIFEST.json       (model_version, data_version of training, live table sha256, issue_week)
```

Committed to the repo (small, reviewable): `docs/FORECAST_REPORT.md` (copied from the final run's `report.md` with figures), `docs/forecast/gate_decision.json`, `forecast.yaml`. This mirrors how `covariates-v1.0` is handled: heavy data external, tagged, with a MANIFEST.

Feature cache is optional but worthwhile: 9M panel rows x ~50 features x 6 leads is large in pandas. Key the cache by hash of (data sha256, feature-config, climatology-config) so a config change can never serve a stale cache (the exact failure class Phase 4 hit with resumable state).

## Data Flow

### Training / Evaluation

```
frozen parquet --verify sha256--> panel (week_idx, ward_idx, 9 value cols) float32
   --> climatology.fit(train weeks only) --> anomaly columns
   --> features(issue week t) ; targets(t+lead)
   --> LeadDataset[lead] --> split by TARGET week year
        train (fit) -> validate (select, calibrate, tune) -> [test LOCKED]
   --> predictions parquet --> metrics (+week-block bootstrap) --> report + gate
```

Practical notes: represent the panel as a dense array (weeks x wards x variables) or as a pandas frame sorted by (ward, week_idx) so lags are `groupby(ward).shift(k)` with a verified no-gap guarantee (`weeks.py` asserts a contiguous index; the frozen table starts 1991-W02, so week 1 of 1991 is absent and lag features for early 1991 weeks are NaN, drop them). Use float32 and per-lead processing to keep memory within a laptop. Subsample ward-weeks for logistic/LightGBM tuning only if needed, and say so in the report.

### Operational (weekly)

```
run_local_pipeline.py (existing, unchanged)  -> fresh covariate_table.csv
   --> forecast_run.py:
        data.load_live(path): schema check == COVARIATE_COLUMNS, nulls == 0, contiguous weeks
        issue_week = last COMPLETE week in table (explicit arg allowed)
        features.build(panel, issue_week)  # same function as training
        for lead in 1..6: p = calibrator(model.predict_proba) ; q = quantile models
   --> forecast_table (CHAP schema) + FORECAST_MANIFEST.json
```

Key point: the operational path consumes the table file `run_local_pipeline` already writes, with no code change to the pipeline. The only coupling is the schema, protected by a test that imports `COVARIATE_COLUMNS` from `heatwave.local.pipeline` and asserts the forecast loader accepts a table produced by `weekly_table` on synthetic `WardDaily` (an integration test using the existing test helpers; no frozen data needed).

Important: the live table's thresholds are recomputed from the 1991-2020 baseline and the live code may drift from v1.0 (e.g. future corrections). `FORECAST_MANIFEST` must record the live table checksum, and `operational.py` must compare the live table's overlapping history (e.g. last 52 weeks present in both frozen and live where years overlap, or a hash of 1991-2020 weeks) with the frozen data and WARN/FAIL when the covariate definition has drifted, since models trained on v1.0 semantics would silently degrade. Cheap check: compare the live table's weeks inside the frozen range to the frozen values.

Forecast output schema (as agreed): `issue_week, target_week, lead, location, p_heatwave_week, hi_anomaly_p10, hi_anomaly_p50, hi_anomaly_p90, model_version, data_version`. Recommendation: also emit `hi_p50_abs`-style absolute values? No, keep the agreed schema; document that `hi_anomaly` units are deg F relative to the train-only weekly climatology (ship the climatology table so CHAP/users can reconstruct absolutes). `time_period` labels use the same "YYYY-Www" format as the covariate table so CHAP can join; also provide `target_week` in that same format. Compute target_week via `weeks.add_weeks`, respecting 52/53-week years.

## Leakage Test Structure

Three layers, all in `tests/forecast/test_leakage.py`, running on synthetic panels so CI needs no frozen data.

1. **Truncation invariance (the core test).** For a random synthetic panel and an issue week t, `features.build(panel, t)` must equal `features.build(panel.truncate(week_idx <= t), t)` (bitwise/allclose). If any feature peeks at weeks > t, truncation changes it. Run for several t and for every feature group. This catches shifts in the wrong direction, centered rolling windows, and any global statistic (e.g. full-panel mean scaling).
2. **Perturbation test.** Replace all values at weeks > t with random garbage (NaN/huge numbers); features at t must be unchanged. Complementary to 1 and catches aggregates computed over the whole frame before slicing.
3. **Train-only statistics test.** Fit `climatology`/scalers/imputers on a panel, then change values only in validation/test years; fitted parameters must be identical. Also assert the fitted climatology object stores the year range it used, and that `assert_train_only(fit_years, split)` raises when it includes any year >= validation start.
4. **Split integrity test.** For each split and lead, max(target_week) of train rows < min(target_week) of the next split (with embargo), and no (issue_week, ward) appears in two splits. Test labels: assert rows whose target week is in the validation/test period never occur in the training set even if their issue week is earlier (the classic boundary leak).
5. **Target-alignment test.** On a tiny hand-built panel, assert `y(t, lead)` equals `heatwave_days[t+lead] >= 3` exactly, including across a 53-week year boundary.
6. **Registry-wide guard.** Every feature must be registered with a declared `max_lookahead = 0`; the test iterates the registry so a newly added feature without a declaration (or a driver feature without a publication lag) fails CI. Climate driver features (later phase) get a declared `availability_lag_weeks`.
7. **Model-level canary (can run on real data locally, marked opt-in):** a model trained with shuffled-time targets should score BSS about 0; a model fed the future target as a feature must be caught by the harness. Cheap smoke that the harness would detect leakage.

Operational parity test: `features.build(panel, t)` on the full panel equals the features `operational.py` computes from a panel that ends at t (this is test 1 applied to the serve path).

## Evaluation to Report Flow

```
predictions/<split>/*.parquet  (every model AND baseline writes identical columns)
      │
      ▼
evaluation.metrics   -> per (model, target, lead, slice) table
evaluation.bootstrap -> week-block resampling (resample whole target weeks across all wards, so spatial correlation is kept) -> CIs, and CI of BSS difference vs best baseline
evaluation.slices    -> lead x season (DJF/MAM/JJA/SON or Nigerian seasons) x region (state / agro-ecological zone)
      │
      ▼
metrics.json  ──►  gate.py (reads gate thresholds from forecast.yaml) ──► GATE.json
      │                                     │
      └────────────► report.py ◄────────────┘   report.md + figures
```

Design rules: (a) models never compute their own metrics; the harness scores stored predictions, so baselines and models are scored identically. (b) BSS reference is selectable and the report states which baseline (climatology vs recent climatology vs persistence, and the best of them per lead) is used. (c) The report template has a fixed section stating the detection layer is rule-based and the study area is "4,841 wards in 19 northern states and the FCT", per project constraints. (d) The test split is scored by `forecast_evaluate.py --final`, which requires a lock file (`TEST_LOCK.json` written on first use with config hash and model bundle hash) and refuses to run twice for different models: this enforces "test 2021-2026 once" mechanically instead of by discipline. (e) The report generator is a pure function of artifacts, so re-rendering never changes numbers.

Note on week-block bootstrap: resample target weeks (blocks of 1 week, or consecutive 2-4 weeks given autocorrelation: say so and make block length configurable), and also because 6 leads share target weeks across issue weeks.

## Retrain Policy and Final Model

Selection and calibration happen on validation (2015-2020). Before the single test evaluation, decide in advance (write in config) whether the final model is (A) the train-only model scored on test as is, or (B) refit on train+validation with frozen hyperparameters and calibrator fit by cross-fitted predictions. Recommendation: (A) for the go/no-go test (cleanest, matches the agreed split), then for the operational release refit on all data up to the latest year with the same hyperparameters and record it as a new `model_version` (documented as not independently tested; honest in the model card). This keeps the test number honest and the operational model fresh.

## Scripts (CLI)

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `scripts/forecast_train.py` | Build/cached features, fit models + calibrators for given leads/models, write predictions for train/validation | `--config forecast.yaml --models logistic lgbm --leads 1 2 --run-id` |
| `scripts/forecast_evaluate.py` | Score stored predictions: metrics, bootstrap, slices, ablations; `--final` scores test once under the lock | `--run <id> --split validation|test --final` |
| `scripts/forecast_report.py` | Render report.md + figures + GATE.json | `--run <id> --out docs/` |
| `scripts/forecast_run.py` | Operational forecast from live table | `--table outputs/covariate_table.csv --release <model_version> --issue-week auto` |
| `scripts/verify_frozen.py` | Checksum a frozen version against MANIFEST | `--version covariates-v1.0` |

Each uses the existing script conventions (`sys.path.insert`, argparse, logging, atomic `.part` write). Keep scripts thin; logic lives in the package so tests cover it.

## New vs Modified

| Item | Status | Detail |
|------|--------|--------|
| `heatwave/forecast/**` | NEW | Entire package above |
| `scripts/forecast_*.py`, `verify_frozen.py` | NEW | Thin CLIs |
| `forecast.yaml` | NEW | Separate from `config.yaml` |
| `tests/forecast/**` | NEW | Synthetic fixtures; no frozen data |
| `requirements.txt` | MODIFIED | Add pinned scikit-learn, lightgbm, shap, matplotlib (and joblib via sklearn); keep pins in the existing frozen style. Verify wheels for py3.11 and 3.12 on Linux and Windows. SHAP pulls numba/llvmlite: consider an optional `requirements-forecast.txt` or extras so the CI install stays light; but CI must install whatever the forecast tests import. |
| `.gitignore` | MODIFIED | Add `forecast_runs/`, `forecast_cache/`, `*.joblib`, `*.parquet` outside docs guard |
| `pyproject.toml` | MODIFIED (small) | Register a pytest marker, e.g. `frozen` (opt-in tests that need the real data, skipped by default like the existing opt-in tests) |
| `.github/workflows/tests.yml` | UNCHANGED (probably) | Works as is if deps are in requirements.txt; optionally add a cache for pip |
| `docs/METHODOLOGY.md` | MODIFIED | New section for the forecast layer, clearly separated from the rule-based detection layer; plus `docs/FORECAST_REPORT.md`, `MODEL_CARD.md`, forecast table schema doc |
| `README.md` | MODIFIED | Architecture diagram, commands |
| `heatwave/config.py` | UNCHANGED | `forecast/config.py` imports `settings.local_data_dir` only |
| `heatwave/local/*`, `scripts/run_local_pipeline.py`, `app/`, EE modules | UNCHANGED | Forecast reads their output; zero coupling in the reverse direction |
| Streamlit app | OPTIONAL later | Could add a forecast-map page reading `forecast_table.parquet`; defer, dev tool only |

One small optional modification worth considering to `run_local_pipeline.py`: nothing is required. Do not add forecast calls to it (keeps v1 delivery path independent).

## CI Considerations

- All forecast tests run on synthetic data: a `conftest.py` factory `make_panel(n_wards=6, years=1991..2026, seed)` producing the exact `COVARIATE_COLUMNS` schema with a seasonal cycle plus noise and some persistence, so LightGBM/logistic can learn a little (smoke tests assert shape/finite/determinism, not skill, except one planted-signal test that checks the model beats climatology on a series where the signal is known).
- Small sizes: 6 wards x 36 years x 52 weeks is about 11k rows; the full forecast test file should run in seconds. Use `n_estimators` of 5-20 in test configs, `n_jobs=1` and fixed seeds for determinism across Windows and Linux.
- Tests needing the real frozen data are marked `frozen` and skipped when `<local_data_dir>/frozen/covariates-v1.0` is absent (same pattern as the existing credential-gated skips). Locally they verify checksum, schema, row count (9,018,783), and run the leakage canary on a real ward sample.
- Checksum logic is itself tested with a tiny fake frozen dir (write parquet + MANIFEST in `tmp_path`, flip a byte, expect failure).
- Import isolation test: `import heatwave.forecast` must not import `ee`/`geemap` (CI has no credentials; `heatwave.auth` is import-order sensitive).
- Existing 166 tests must stay green; run them in the same job. Watch CI install time (full freeze plus lightgbm/shap).
- Reproducibility: pin `random_state`, `deterministic=True`/`force_row_wise=True` in LightGBM to avoid thread-count-dependent results; record versions in RUN_MANIFEST.
- Floating-point cross-platform: use `allclose` with tolerances in tests, never exact equality across OSs for model outputs.

## Patterns to Follow

### Pattern 1: Single `Predictor` interface for baselines and models
**What:** Baselines, logistic, LightGBM expose `fit(ds_train)`, `predict_proba(ds)`, `save/load`. The harness is oblivious to type.
**When:** Always; it guarantees apples-to-apples scoring and makes ablations trivial.
**Example:**
```python
class Predictor(Protocol):
    name: str
    def fit(self, train: LeadDataset) -> "Predictor": ...
    def predict_proba(self, ds: LeadDataset) -> np.ndarray: ...
```

### Pattern 2: Time as an integer index, labels only at the edges
**What:** Convert "YYYY-Www" to `week_idx` once in `data.py`; everything else uses ints; convert back only for output.
**When:** Always. ISO 53-week years make string arithmetic wrong.

### Pattern 3: As-of feature function (`build(panel, issue_week)`)
**What:** Features are a pure function of data up to the issue week. The same function is used for training (all issue weeks vectorized) and serving (one issue week).
**Why:** Gives train/serve parity and makes the truncation leakage test possible.

### Pattern 4: Manifest-everything
**What:** Every run, release and forecast output carries a MANIFEST with data checksum, git commit, config hash, and versions, mirroring `MANIFEST.json` for covariates-v1.0.

### Pattern 5: Fit-on-train objects stored with their fit range
**What:** Climatology, scalers, calibrators save the years/rows they were fit on; `assert_train_only` guards.

## Anti-Patterns

### Anti-Pattern 1: Reusing the 1991-2020 detection climatology for anomalies
**What people do:** Subtract `percentile`/baseline thresholds already used by `weekly_table`.
**Why wrong:** The baseline spans validation years (2015-2020), so validation anomalies carry information fit on those years.
**Instead:** Fit a separate train-years-only (1991-2014) weekly climatology inside `forecast/climatology.py`. Only the label definition stays on the 1991-2020 baseline, documented.

### Anti-Pattern 2: Random K-fold or shuffled splits on a space-time panel
**Instead:** Expanding-window CV by year with an embargo of at least max-lead + feature-lag weeks; evaluate grouped by target week.

### Anti-Pattern 3: Training on `outputs/covariate_table.csv`
**Why wrong:** Overwritten each run; breaks reproducibility (project constraint). **Instead:** `data.py` only accepts the frozen path for training; the live loader is used only in `operational.py`.

### Anti-Pattern 4: Tuning or calibrating on test, or peeking at test during development
**Instead:** Test lock file; report validation numbers during development, test number exactly once.

### Anti-Pattern 5: Treating ward-weeks as i.i.d. for confidence intervals
**Instead:** Week-block bootstrap; ward-level CIs are overconfident because neighbouring wards share 11 km ERA5 cells.

### Anti-Pattern 6: Putting forecast code in `heatwave/local/` or importing EE
**Instead:** Separate package, no EE import.

### Anti-Pattern 7: Evaluating only pooled metrics
**Why wrong:** Heatwave weeks are rare (about 10% of days exceed threshold, so maybe 5-10% of weeks are heatwave weeks), AUC/accuracy look fine while skill is nil. **Instead:** BSS vs best baseline per lead/season/region, with reliability diagrams.

### Anti-Pattern 8: Independent models per lead without a shared feature store
**Instead:** Build features once per issue week; each lead only changes the target and row filter.

## Scalability Considerations

| Concern | Laptop (now) | If expanded |
|---------|--------------|-------------|
| Panel size 9M rows x ~50 float32 features | ~2 GB per lead if materialized; build per lead, parquet cache, process by year chunks | Subsample wards for tuning; train on all wards for final |
| LightGBM training 6 leads x 3 quantiles x CV folds | Minutes to tens of minutes with `n_jobs`; use histogram-based defaults, early stopping on validation | Cache fold predictions |
| SHAP | Compute on a stratified subsample (e.g. 50k rows) | n/a |
| Operational run | One issue week x 4,841 wards x 6 leads = trivial seconds | n/a |

## Suggested Build Order

Each phase has a verifiable exit criterion; nothing downstream starts until upstream leakage and harness tests pass.

1. **Foundation: data access, week index, config, artifact skeleton.** `config.py`, `data.py` (frozen load + sha256 verify), `weeks.py`, `artifacts.py`, `forecast.yaml`, synthetic-panel fixture, import-isolation test, requirements update. Exit: loads frozen parquet locally, rejects a corrupted copy, CI green with new deps.
2. **Feature store + targets + splits + leakage test.** `climatology.py` (train-only), `features.py`, `targets.py`, `dataset.py`, `splits.py`, and the full leakage suite (truncation, perturbation, train-only, split integrity, registry guard). Exit: leakage tests pass and fail when a deliberate leak is injected (mutation check).
3. **Baselines + evaluation harness.** `baselines.py`, `evaluation/*` (BSS, AUC, P/R/F1, MAE, pinball, coverage, reliability, week-block bootstrap, slices), predictions parquet format, a first metrics table. Exit: baseline scores per lead on validation; known sanity (climatology BSS vs itself = 0; persistence decays with lead). This also tells you early how much skill there is to gain.
4. **Logistic regression (per lead).** First trained model, `models/logistic.py`, standardization fit on train. Exit: validation BSS vs baselines with CIs; tests for determinism; first ablation scaffold.
5. **LightGBM + isotonic calibration.** `models/lgbm.py`, `calibration.py` (fit on validation), expanding-window CV for hyperparameters, reliability plots. Exit: calibrated probabilities, reliability within tolerance, comparison vs logistic.
6. **Quantile models and hot-nights target.** `models/quantile.py` (p10/p50/p90 HI anomaly, monotone/non-crossing fix), coverage and pinball metrics, hot-night classifier reusing step 5. Exit: coverage near nominal on validation.
7. **Explainability + ablations + final test + report + go/no-go.** `explain.py` (SHAP, feature-group ablations), `gate.py`, `report.py`, test lock, single test evaluation, `docs/FORECAST_REPORT.md`. Exit: GATE.json decision recorded; if NO-GO, stop (project fallback: ECMWF S2S benchmark per Out of Scope) and skip step 8 to 9 or re-scope.
8. **Operational forecast table.** `operational.py`, `scripts/forecast_run.py`, retrain-on-all release (`forecast_releases/<model_version>`), MODEL_CARD, FORECAST_MANIFEST, drift check against frozen values, CHAP schema doc. Exit: forecast generated from the output of `run_local_pipeline.py` end-to-end; parity test passes.
9. **Climate drivers (ENSO, Atlantic SST, MJO).** `drivers.py` plus its own frozen/versioned input dataset with checksum, publication-lag-aware features, ablation measuring added skill vs the step 7 baseline model on validation (and test only if the one-shot rule is respected: pre-register that driver evaluation uses a fresh protocol, such as expanding-window CV on 2015-2026, since the test years are spent). Exit: skill gain with CI, or documented no gain.

Why operational (8) before drivers (9) rather than after: it delivers value to CHAP with the already-validated model; drivers are an upgrade that creates a new `model_version`. If you prefer drivers before operational, the architecture does not change, but the test-set-already-spent problem must be handled either way (see below). Roadmapper may reorder, but 1-2 must come first and 7 gates 8.

## Integration Risks Specific to This Repo

1. **Test set is spent once.** Climate drivers added after the test is read cannot be honestly evaluated on 2021-2026 again. Mitigation: evaluate drivers with expanding-window CV and the validation period, or accept that driver value is reported as CV evidence only and the operational model with drivers is flagged as not independently tested.
2. **Label baseline overlaps validation years** (1991-2020 thresholds). Small, shared by all models, but declare it in the report.
3. **The ERA5-Land data ends 2026-09-23 and the test period 2021-2026 is partial:** 2026 has about 38 weeks (seasonal composition differs). Report seasonal slices and do not average by year naively.
4. **Heatwave week is a count over a rule-defined target already in the table** (`heatwave_days`), so the target is deterministic from the covariate table with no extra data. Persistence and "recent climatology" baselines are cheap to compute but the 10-year recent climatology must itself be trailing and leak-free (window ends before the issue week).
5. **Adjacent wards are highly spatially correlated** (11 km grid, 4,841 wards, 73 small wards use fallback, 6 wards use LGA average): effective sample size is much smaller than 9M; avoid overfitting to ward id (use coordinates or region as static features, evaluate by region, and consider spatial-block holdout as an extra robustness check on the validation period).
6. **Python 3.11 CI vs 3.12 local:** pin and test wheels for both.
7. **Config singleton import side effect:** `heatwave.config` executes `load_settings()` on import; forecast tests that import it need `config.yaml` present (it is) and should avoid depending on `local_data_dir` existing.

## Sources

- Repo code read: `heatwave/local/pipeline.py`, `heatwave/config.py`, `scripts/run_local_pipeline.py`, `config.yaml`, `.github/workflows/tests.yml`, `requirements.txt`, `.gitignore`, `tests/test_local_pipeline.py` (HIGH)
- `<local_data_dir>/frozen/covariates-v1.0/MANIFEST.json` (schema, row counts, sha256, environment versions) (HIGH)
- `.planning/PROJECT.md` (milestone scope, constraints, agreed forecast design) (HIGH)
- Design patterns (time-index as-of features, truncation leakage tests, block bootstrap for forecast verification, test-lock) reflect standard forecast-verification and ML-engineering practice; not re-verified against external sources in this pass (MEDIUM)

---
*Architecture research for: v2.0 forecast layer, Heatwave Modelling (CHAP)*
*Researched: 2026-10-02*
