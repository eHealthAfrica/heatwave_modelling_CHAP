# Constraints (from SPECs)

No SPEC-type documents were present in this ingest. No formal api-contract/schema/nfr/protocol constraints have been ratified.

`PROJECT_STATE.md` (type DOC) records several parameter and environment constraints informally. Captured here for visibility as DOC-sourced context, not binding SPEC constraints:

## Climatology / detection parameters (config.yaml, type: nfr-like config)
- `baseline_start_year: 1991`, `baseline_end_year: 2020` — climatology baseline period.
- `percentile: 90` — heatwave threshold (90th percentile of calendar-day climatology).
- `pooling_window_days: 5` — ±5-day pooling window.
- `min_consecutive_days: 3` — minimum consecutive days to qualify as a heatwave event.
- **Source:** `PROJECT_STATE.md` §4, referencing `config.yaml`

## Infrastructure constraints (type: protocol/environment)
- Python `>=3.11` (per `pyproject.toml`).
- GCP project `heatwave-508110` must be registered for Earth Engine; service account `heatwave-pipeline@heatwave-508110.iam.gserviceaccount.com`.
- Service account key must never be committed (`keys/service_account.json`, gitignored, diff-scanned before every commit).
- `heatwave/auth.py` credential resolution order: Streamlit secrets (`st.secrets["earthengine"]`) → `EE_SA_JSON` env var → local `keys/service_account.json`.
- Data source fixed to `ECMWF/ERA5_LAND/DAILY_AGGR` (~11.1km, daily, from 1950-01-02); bands in use: `temperature_2m_max`, `temperature_2m`, `dewpoint_temperature_2m`.
- Ward boundary asset fixed to `projects/heatwave-508110/assets/shp` (GRID3 NGA Operational Wards, 4,841 wards nationwide).
- **Source:** `PROJECT_STATE.md` §3, §4

## Environment/tooling constraints (Windows-specific, type: protocol)
- PowerShell: each tool call is a fresh shell — PATH changes and `cd` do not persist across calls; must re-set PATH (via `[System.Environment]::GetEnvironmentVariable`) every time `git`/`gh` are needed.
- Multi-line git commit messages with embedded double quotes break `git commit -m` parsing on Windows — use `git commit -F <file>` instead.
- `robocopy` does not delete files absent from source — deleted files must be removed explicitly.
- Word COM PDF export needs `pywin32` installed in the venv even when Word is present.
- **Source:** `PROJECT_STATE.md` §8
