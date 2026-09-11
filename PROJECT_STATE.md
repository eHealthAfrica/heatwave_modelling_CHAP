# Heatwave Modelling (CHAP) — Project State / Continuity Doc

**Last updated:** 2026-09-11
**Purpose of this file:** if conversation history is lost (system crash, new session), read this file first to reconstruct full context and continue exactly where work left off. Written for Claude, but readable by anyone.

---

## 1. What this project is

A ward-level heatwave-detection pipeline for Nigeria, whose output is a weekly covariate table for downstream disease-forecasting platforms like **CHAP** (chap-core / dhis2-chap). It does **not** forecast disease itself — it produces an upstream climate covariate.

Full methodology and phased plan are in the repo's own docs (see §5), originally prepared by Claude for the user (Adedo Lukmon) on 2026-09-07:
- `outputs/01_Heatwave_Methodology.docx` — the science: heatwave definition (WMO/ETCCDI percentile-exceedance, 90th percentile of 1991–2020 calendar-day climatology, ±5-day pooling, ≥3 consecutive days = event), Heat Index (NOAA/NWS Rothfusz regression), output schema.
- `outputs/02_Implementation_Roadmap.docx` — the original 9-phase plan (Phase A + Phases 0–8).
- `outputs/03_Implementation_Phases_Status.docx` / `.pdf` — same phases, expanded with actual status/detail as of 2026-09-10 (superset of this file's phase summary, in the user's branded-documents house style).

**Output schema (target, not yet built — Phase 5):**
| column | meaning |
|---|---|
| `time_period` | ISO week, e.g. `2020-W23` |
| `location` | ward ID |
| `heatwave_days` | count of heatwave days that week |
| `mean_heat_index` / `max_heat_index` | Heat Index (°F) stats |
| `heatwave_event_count` | number of ≥3-day events starting that week |

---

## 2. Repo / folder situation (important, easy to get wrong)

Two local folders exist under `C:\Users\Adedo.lukmon\Adedo\Heatwave\`:

- **`heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main\`** — **this is the active working folder.** All code changes described below live here. This is where you should `cd` to continue work.
- **`heatwave_modelling_CHAP-architectural-design\heatwave_modelling_CHAP-architectural-design\`** — an older, separate branch snapshot. Only touched once, to publish `architecture-design.html` as a Claude Artifact (a design/architecture diagram — see published link, may have been lost if not bookmarked; regenerate from that file if needed). **Not part of ongoing work.**

Both were originally plain zip extracts with **no git history** (`.git` folder absent, confirmed by fresh environment checks). Neither is a git repo today; the *working folder* (`heatwave_modelling_CHAP-main\...`) still has no `.git` — see §4 for why, and see §7 for the actual git-tracked copy of the work.

**Real upstream repo:** `https://github.com/eHealthAfrica/heatwave_modelling_CHAP.git` (default branch `main`). Its actual `main` branch, when checked, still only had the **original prototype** (`gee.py` present, no `heatwave/` package, no `build/`, no `outputs/`) — the roadmap docs and `build/` tooling that exist in the local working folder were never pushed until PR #1 (§7).

---

## 3. Cloud infrastructure (fresh-start setup, done)

- **GCP project:** `heatwave-508110`, registered for Earth Engine.
- **Service account:** `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`
- **Service account key:** stored locally at `keys/service_account.json` inside the working folder (gitignored, never committed — verified via diff scan before every commit). **If this file is lost, the user must re-download a key from GCP Console → IAM & Admin → Service Accounts → heatwave-pipeline → Keys.**
- **Ward boundary asset:** `projects/heatwave-508110/assets/shp` — uploaded by the user from a GRID3 NGA Operational Wards shapefile. **4,841 wards nationwide**, verified live. Feature properties: `wardname`, `wardcode`, `lganame`, `statename`, `geozone`, plus GIS metadata (`ogc_fid`, `area`, etc.).
- **Data source:** `ECMWF/ERA5_LAND/DAILY_AGGR` (~11.1km, daily, from 1950-01-02). Bands in use: `temperature_2m_max`, `temperature_2m`, `dewpoint_temperature_2m`.

---

## 4. Code changes made (Phases 0–2 — DONE, verified)

All in the working folder. Summary (full detail in `outputs/03_Implementation_Phases_Status.docx`):

**Added:**
- `pyproject.toml` — Python ≥3.11 packaging.
- `config.yaml` — non-secret settings: `gcp_project_id`, `ward_asset_id`, `era5_land_collection`, band names, default date range, and climatology constants (`baseline_start_year: 1991`, `baseline_end_year: 2020`, `percentile: 90`, `pooling_window_days: 5`, `min_consecutive_days: 3`) — stored now for Phase 4 to read later.
- `heatwave/` package:
  - `config.py` — loads `config.yaml` into a dataclass (`settings`).
  - `auth.py` — single `init_ee()`. Tries, in order: Streamlit secrets (`st.secrets["earthengine"]`) → `EE_SA_JSON` env var → local `keys/service_account.json`. Calls `ee.Initialize(credentials, project=settings.gcp_project_id)`.
  - `data/boundary.py` — `load_ward_boundary()` returns the ward `ee.FeatureCollection`.
  - `data/ingest.py` — `load_era5_land(boundary, start_date, end_date)` returns an `Era5LandBands` dataclass (`.tmax`, `.tmean`, `.dewpoint`), each a date-filtered, boundary-clipped `ee.ImageCollection`.
- `requirements.txt` — added `pytest`, `PyYAML`.

**Modified:**
- `nigeria_heat_index.py` — now imports `heatwave.auth`/`heatwave.data.*` instead of inline credential code; boundary/ERA5 loading retargeted to the new asset/collection; RH/Heat-Index band references renamed from ERA5 (`mean_2m_air_temperature`, `dewpoint_2m_temperature`) to ERA5-Land (`temperature_2m`, `dewpoint_temperature_2m`). Map layer label changed from "Northern Nigeria" to "Ward Boundaries" (now nationwide). All other UI/map code unchanged. The actual Heat Index/RH math is **still inline here** — relocating it is Phase 3, not done yet.

**Removed:**
- `gee.py` (superseded by `heatwave/auth.py`, per roadmap instruction).

**Bug found and fixed:** `heatwave/auth.py`'s original version crashed with `StreamlitSecretNotFoundError` when no `secrets.toml` exists at all (was `if "earthengine" in st.secrets:` unguarded). Fixed by wrapping in try/except. This bug existed in the *original* prototype too, just never surfaced because it always ran with Streamlit Cloud secrets configured.

**Verification performed (all passed), against the real `heatwave-508110` project:**
1. `heatwave.auth.init_ee()` connects successfully.
2. `heatwave.data.boundary.load_ward_boundary()` → 4,841 features with correct properties.
3. `heatwave.data.ingest.load_era5_land()` → correct band names returned for a sample date range (`2020-06-01` to `2020-06-05`).
4. `streamlit run nigeria_heat_index.py` boots cleanly, HTTP 200 on `localhost:8501`, no stderr.

A Python venv with all `requirements.txt` deps installed exists at `.venv/` inside the working folder (not committed — recreate with `python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt` if lost). It also has `python-docx`, `python-pptx`, `pywin32`, `pypdfium2` installed ad hoc (used to build `outputs/03_...` — not in `requirements.txt`, add them there if doc-building becomes routine).

---

## 5. Phases 3–8 — NOT STARTED

Full detail in `outputs/02_Implementation_Roadmap.docx` and `outputs/03_Implementation_Phases_Status.docx`. Short version:

| Phase | Name | Delivers |
|---|---|---|
| 3 | Heat Index relocated + tested | `heatwave/science/heat_index.py`, `tests/test_heat_index.py` — move the RH/Heat-Index math out of `nigeria_heat_index.py`, relocate not rewrite, add tests |
| 4 | Climatology + heatwave detection | `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, `heatwave/zonal.py`, `tests/test_heatwave_detection.py` — **the core new capability**: per-ward 90th-percentile climatology + heatwave day/event flagging |
| 5 | Batch export + covariate table | `scripts/run_batch_export.py`, `scripts/build_covariate_table.py`, `heatwave/export.py`, `tests/test_export.py` — produces the actual CHAP-facing output table |
| 6 | Presentation layer rewrite | `heatwave/app/streamlit_app.py` reading the precomputed table; retire `nigeria_heat_index.py` |
| 7 | Documentation | `docs/METHODOLOGY.md`, rewritten `README.md` |
| 8 | Optional polish | `tests/test_config.py`, optional CI — not required |

**Next immediate step if resuming work:** start Phase 3 (lowest risk, unblocks Phase 4). Use `EnterPlanMode` first per the user's established workflow (see §8).

---

## 6. Side discussion — custom dashboard (not committed to, no action taken)

User asked about feasibility of replacing Streamlit with a custom HTML/JS dashboard (Leaflet.js frontend + FastAPI/Flask backend exposing Earth Engine tile URLs via `image.getMapId()`), reusing the same `heatwave.auth`/`data` modules. Assessed as feasible but a detour from the roadmap (Phase 6 already plans a Streamlit rewrite reading a precomputed table, reducing the need for live per-date tile serving). **No decision made — user said "just wanted to know feasibility," not pursuing it now.** Revisit only if asked.

---

## 7. GitHub state

- **PR #1 open:** https://github.com/eHealthAfrica/heatwave_modelling_CHAP/pull/1
  Branch `feature/heatwave-508110-phase-0-2` → `main`. Contains everything in §4, plus `outputs/01_...docx`, `outputs/02_...docx`, and `build/` (which existed only locally before this PR). **Not yet merged** as of last update — check PR status before assuming it's in `main`.
- The branch was pushed from a **temporary clone** at `_pr_workspace\heatwave_modelling_CHAP` (deleted after push — see cleanup in conversation). **The working folder itself (`heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main`) still has no `.git`.** If continuing work and wanting version control locally, either:
  (a) `git clone` the real repo fresh into a new folder, check out `feature/heatwave-508110-phase-0-2` (or `main` once merged), and copy the working folder's files in, or
  (b) `git init` the working folder directly and add the remote — messier since it'd have unrelated history.
  Recommended: (a).
- **GitHub auth:** user is `McDoman`, an active member of the `eHealthAfrica` org. Initially had **no write access** to this specific repo (`push: false`); access was granted mid-session and confirmed (`push: true, admin: true`). A fork at `McDoman/heatwave_modelling_CHAP` was created as a fallback during the no-access window — **it has no commits and should be deleted** (Settings → Danger Zone) if not already done, it's just clutter now.
- **A GitHub PAT was pasted directly into chat** by the user (twice) to authenticate git/API calls. **User was asked to revoke/regenerate it** — unknown whether they did. **Do not assume it still works; do not reuse the old token value if it appears anywhere in old context.** If git/PR operations are needed again, ask for a fresh token.
- Tools installed system-wide during this session (persist across sessions): **Git for Windows** (was already present, just not on PATH — `C:\Users\Adedo.lukmon\AppData\Local\Programs\Git\cmd\git.exe`), **GitHub CLI** (`gh`, newly installed via winget, v2.100.0). Note: **a fresh PowerShell session in this environment does not inherit updated PATH automatically** — every command needing `git`/`gh` must start with:
  ```powershell
  $env:Path = "$([System.Environment]::GetEnvironmentVariable('Path','Machine'));$([System.Environment]::GetEnvironmentVariable('Path','User'))"
  ```

---

## 8. Working-style notes for continuing this project

- User prefers `EnterPlanMode` for non-trivial multi-file implementation work (used successfully for Phases 0–2) — propose a plan, get approval via `ExitPlanMode`, then implement.
- User wants real verification, not just "should work": actually run `init_ee()`, check real ward counts, boot the Streamlit app, look at rendered output — against the live GCP project, not mocked.
- User uses the `branded-documents` skill (two-color house style, `#0090FC`/`#CCE9FE`) for any deliverable docs — reuse `build/doctheme.py` and `build/to_pdf.py` already in the repo rather than re-deriving.
- User has asked for short, plain KPI-update-style summaries of completed phases on occasion — keep those separate from the full technical doc.
- PowerShell gotchas hit this session, worth remembering: (1) each tool call is a fresh shell — PATH changes and `cd`/`Set-Location` don't persist across calls, must re-set every time; (2) multi-line git commit messages with embedded double quotes break `git commit -m` argument parsing on Windows — use `git commit -F <file>` instead; (3) `robocopy` does not delete files absent from source — deleted files (like `gee.py`) must be removed explicitly; (4) Word COM PDF export needs `pywin32` installed in the venv even though Word itself was already present.

---

## 9. If you're picking this up cold

1. `cd` to `C:\Users\Adedo.lukmon\Adedo\Heatwave\heatwave_modelling_CHAP-main\heatwave_modelling_CHAP-main`
2. Check PR #1 status (merged? still open? changes requested?) before assuming what's in upstream `main`.
3. Confirm `keys/service_account.json` still exists locally (it's gitignored, never pushed — only lives on this machine).
4. Ask the user what they want next: continue to Phase 3, or something else entirely.
