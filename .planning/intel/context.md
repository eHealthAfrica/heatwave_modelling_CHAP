# Context (from DOCs)

Source for all entries below: `PROJECT_STATE.md` (C:\Users\Adedo.lukmon\Adedo\Heatwave\heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main\PROJECT_STATE.md), last updated 2026-09-11. This is a continuity/status doc written by Claude for the user (Adedo Lukmon), not a formal ADR/PRD/SPEC.

**Note on missing sources:** This doc references three fuller planning documents that could not be parsed in this environment: `outputs/01_Heatwave_Methodology.docx`, `outputs/02_Implementation_Roadmap.docx`, `outputs/03_Implementation_Phases_Status.docx` / `.pdf`. The doc itself states `03_Implementation_Phases_Status` is a "superset of this file's phase summary, in the user's branded-documents house style." If those become available in text form, re-ingest — they likely contain the authoritative methodology and phase detail this file only summarizes.

## Topic: Project purpose

A ward-level heatwave-detection pipeline for Nigeria. Output is a weekly covariate table for downstream disease-forecasting platforms like CHAP (chap-core / dhis2-chap). It does **not** forecast disease itself — it produces an upstream climate covariate.

Heatwave definition basis: WMO/ETCCDI percentile-exceedance method — 90th percentile of 1991-2020 calendar-day climatology, ±5-day pooling, ≥3 consecutive days = event. Heat Index basis: NOAA/NWS Rothfusz regression.

**Source:** `PROJECT_STATE.md` §1

## Topic: Target output schema (Phase 5, not yet built)

| column | meaning |
|---|---|
| `time_period` | ISO week, e.g. `2020-W23` |
| `location` | ward ID |
| `heatwave_days` | count of heatwave days that week |
| `mean_heat_index` / `max_heat_index` | Heat Index (°F) stats |
| `heatwave_event_count` | number of >=3-day events starting that week |

**Source:** `PROJECT_STATE.md` §1

## Topic: Repo / folder situation

Two local folders exist under `C:\Users\Adedo.lukmon\Adedo\Heatwave\`:
- `heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main\` — the active working folder; all code changes live here.
- `heatwave_modelling_CHAP-architectural-design\heatwave_modelling_CHAP-architectural-design\` — older, separate branch snapshot, touched once to publish `architecture-design.html` as a Claude Artifact. Not part of ongoing work.

Both were originally plain zip extracts with no git history. Neither is a git repo locally today (as of doc date); the working folder still has no `.git` (see §7/GitHub topic below for the actual git-tracked copy of the work, via PR #1).

Real upstream repo: `https://github.com/eHealthAfrica/heatwave_modelling_CHAP.git` (default branch `main`). At last check, `main` only had the original prototype (`gee.py` present, no `heatwave/` package, no `build/`, no `outputs/`) — the roadmap docs and `build/` tooling in the local working folder were never pushed until PR #1.

**Source:** `PROJECT_STATE.md` §2

## Topic: Cloud infrastructure (fresh-start setup, done)

- GCP project: `heatwave-508110`, registered for Earth Engine.
- Service account: `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`.
- Service account key stored locally at `keys/service_account.json` inside the working folder (gitignored, never committed, diff-scanned before every commit). If lost, re-download from GCP Console -> IAM & Admin -> Service Accounts -> heatwave-pipeline -> Keys.
- Ward boundary asset: `projects/heatwave-508110/assets/shp`, uploaded by the user from a GRID3 NGA Operational Wards shapefile. 4,841 wards nationwide, verified live. Feature properties: `wardname`, `wardcode`, `lganame`, `statename`, `geozone`, plus GIS metadata (`ogc_fid`, `area`, etc.).
- Data source: `ECMWF/ERA5_LAND/DAILY_AGGR` (~11.1km, daily, from 1950-01-02). Bands in use: `temperature_2m_max`, `temperature_2m`, `dewpoint_temperature_2m`.

**Source:** `PROJECT_STATE.md` §3

## Topic: Code changes made — Phases 0-2 (DONE, verified)

All in the working folder; full detail in `outputs/03_Implementation_Phases_Status.docx` (not parsed in this environment).

**Added:**
- `pyproject.toml` — Python >=3.11 packaging.
- `config.yaml` — non-secret settings: `gcp_project_id`, `ward_asset_id`, `era5_land_collection`, band names, default date range, and climatology constants (`baseline_start_year: 1991`, `baseline_end_year: 2020`, `percentile: 90`, `pooling_window_days: 5`, `min_consecutive_days: 3`) — stored for Phase 4 to read later.
- `heatwave/` package:
  - `config.py` — loads `config.yaml` into a dataclass (`settings`).
  - `auth.py` — single `init_ee()`. Tries, in order: Streamlit secrets (`st.secrets["earthengine"]`) -> `EE_SA_JSON` env var -> local `keys/service_account.json`. Calls `ee.Initialize(credentials, project=settings.gcp_project_id)`.
  - `data/boundary.py` — `load_ward_boundary()` returns the ward `ee.FeatureCollection`.
  - `data/ingest.py` — `load_era5_land(boundary, start_date, end_date)` returns an `Era5LandBands` dataclass (`.tmax`, `.tmean`, `.dewpoint`), each a date-filtered, boundary-clipped `ee.ImageCollection`.
- `requirements.txt` — added `pytest`, `PyYAML`.

**Modified:**
- `nigeria_heat_index.py` — now imports `heatwave.auth`/`heatwave.data.*` instead of inline credential code; boundary/ERA5 loading retargeted to the new asset/collection; RH/Heat-Index band references renamed from ERA5 (`mean_2m_air_temperature`, `dewpoint_2m_temperature`) to ERA5-Land (`temperature_2m`, `dewpoint_temperature_2m`). Map layer label changed from "Northern Nigeria" to "Ward Boundaries" (now nationwide). All other UI/map code unchanged. The Heat Index/RH math is still inline here — relocating it is Phase 3, not done yet.

**Removed:**
- `gee.py` (superseded by `heatwave/auth.py`, per roadmap instruction).

**Bug found and fixed:** `heatwave/auth.py`'s original version crashed with `StreamlitSecretNotFoundError` when no `secrets.toml` exists at all (`if "earthengine" in st.secrets:` was unguarded). Fixed by wrapping in try/except. This bug existed in the original prototype too, just never surfaced because it always ran with Streamlit Cloud secrets configured.

**Verification performed (all passed), against the real `heatwave-508110` project:**
1. `heatwave.auth.init_ee()` connects successfully.
2. `heatwave.data.boundary.load_ward_boundary()` -> 4,841 features with correct properties.
3. `heatwave.data.ingest.load_era5_land()` -> correct band names returned for a sample date range (`2020-06-01` to `2020-06-05`).
4. `streamlit run nigeria_heat_index.py` boots cleanly, HTTP 200 on `localhost:8501`, no stderr.

A Python venv with all `requirements.txt` deps installed exists at `.venv/` inside the working folder (not committed; recreate with `python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt` if lost). It also has `python-docx`, `python-pptx`, `pywin32`, `pypdfium2` installed ad hoc (used to build `outputs/03_...`, not in `requirements.txt` — add them there if doc-building becomes routine).

**Source:** `PROJECT_STATE.md` §4

## Topic: Phases 3-8 — NOT STARTED

See `requirements.md` (candidate requirement set) for the full phase table. Full detail in `outputs/02_Implementation_Roadmap.docx` and `outputs/03_Implementation_Phases_Status.docx` (not parsed in this environment). Next immediate step if resuming work: start Phase 3 (lowest risk, unblocks Phase 4), using `EnterPlanMode` first per the established workflow.

**Source:** `PROJECT_STATE.md` §5

## Topic: Side discussion — custom dashboard (not committed to, no action taken)

User asked about feasibility of replacing Streamlit with a custom HTML/JS dashboard (Leaflet.js frontend + FastAPI/Flask backend exposing Earth Engine tile URLs via `image.getMapId()`), reusing the same `heatwave.auth`/`data` modules. Assessed as feasible but a detour from the roadmap (Phase 6 already plans a Streamlit rewrite reading a precomputed table, reducing the need for live per-date tile serving). No decision made — user said "just wanted to know feasibility," not pursuing it now. Revisit only if asked.

**Source:** `PROJECT_STATE.md` §6

## Topic: GitHub state

- PR #1 open: `https://github.com/eHealthAfrica/heatwave_modelling_CHAP/pull/1`. Branch `feature/heatwave-508110-phase-0-2` -> `main`. Contains everything in the Phases 0-2 topic above, plus `outputs/01_...docx`, `outputs/02_...docx`, and `build/` (which existed only locally before this PR). Not yet merged as of last update — check PR status before assuming it's in `main`.
- The branch was pushed from a temporary clone at `_pr_workspace\heatwave_modelling_CHAP` (deleted after push). The working folder itself still has no `.git`. If continuing work and wanting version control locally: (a) `git clone` the real repo fresh into a new folder, check out `feature/heatwave-508110-phase-0-2` (or `main` once merged), and copy the working folder's files in [recommended]; or (b) `git init` the working folder directly and add the remote — messier since it'd have unrelated history.
- GitHub auth: user is `McDoman`, an active member of the `eHealthAfrica` org. Initially had no write access to this repo (`push: false`); access was granted mid-session and confirmed (`push: true, admin: true`). A fork at `McDoman/heatwave_modelling_CHAP` was created as a fallback during the no-access window — has no commits, should be deleted (Settings -> Danger Zone) if not already done.
- **Security note:** a GitHub PAT was pasted directly into chat by the user (twice) to authenticate git/API calls. User was asked to revoke/regenerate it — unknown whether they did. Do not assume it still works; do not reuse the old token value if it appears anywhere in old context. If git/PR operations are needed again, ask for a fresh token.
- Tools installed system-wide during this session (persist across sessions): Git for Windows (was already present, just not on PATH — `C:\Users\Adedo.lukmon\AppData\Local\Programs\Git\cmd\git.exe`), GitHub CLI (`gh`, newly installed via winget, v2.100.0). A fresh PowerShell session does not inherit updated PATH automatically — see constraints.md for the workaround.

**Source:** `PROJECT_STATE.md` §7

## Topic: Working-style notes for continuing this project

- User prefers `EnterPlanMode` for non-trivial multi-file implementation work (used successfully for Phases 0-2) — propose a plan, get approval via `ExitPlanMode`, then implement.
- User wants real verification, not just "should work": actually run `init_ee()`, check real ward counts, boot the Streamlit app, look at rendered output — against the live GCP project, not mocked.
- User uses the `branded-documents` skill (two-color house style, `#0090FC`/`#CCE9FE`) for any deliverable docs — reuse `build/doctheme.py` and `build/to_pdf.py` already in the repo rather than re-deriving.
- User has asked for short, plain KPI-update-style summaries of completed phases on occasion — keep those separate from the full technical doc.

**Source:** `PROJECT_STATE.md` §8

## Topic: If picking this up cold (checklist from doc)

1. `cd` to `C:\Users\Adedo.lukmon\Adedo\Heatwave\heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main`.
2. Check PR #1 status (merged? still open? changes requested?) before assuming what's in upstream `main`.
3. Confirm `keys/service_account.json` still exists locally (gitignored, never pushed — only lives on this machine).
4. Ask the user what they want next: continue to Phase 3, or something else entirely.

**Source:** `PROJECT_STATE.md` §9
