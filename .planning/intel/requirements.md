# Requirements (from PRDs)

No PRD-type documents were present in this ingest. No formal requirements with acceptance criteria exist yet.

`PROJECT_STATE.md` (type DOC) does describe a target output and an implementation phase breakdown that function as informal, unratified requirements. These are captured in `context.md` and summarized here for visibility — they are **not** REQ-IDs backed by a PRD and should be treated as candidate requirements for the roadmapper to formalize, not as locked scope.

## Candidate requirement: weekly ward-level covariate table (Phase 5, not yet built)

- **Description:** Produce a weekly covariate table per ward for downstream disease-forecasting platforms (CHAP / chap-core / dhis2-chap). This is the project's primary deliverable.
- **Target schema (from doc, "not yet built"):**
  | column | meaning |
  |---|---|
  | `time_period` | ISO week, e.g. `2020-W23` |
  | `location` | ward ID |
  | `heatwave_days` | count of heatwave days that week |
  | `mean_heat_index` / `max_heat_index` | Heat Index (°F) stats |
  | `heatwave_event_count` | number of ≥3-day events starting that week |
- **Source:** `PROJECT_STATE.md` §1, §5 (Phase 5)

## Candidate requirement set: Phase 3-8 implementation roadmap (not started)

| Phase | Name | Delivers |
|---|---|---|
| 3 | Heat Index relocated + tested | `heatwave/science/heat_index.py`, `tests/test_heat_index.py` — move RH/Heat-Index math out of `nigeria_heat_index.py`, relocate not rewrite, add tests |
| 4 | Climatology + heatwave detection | `heatwave/science/climatology.py`, `heatwave/science/heatwave.py`, `heatwave/zonal.py`, `tests/test_heatwave_detection.py` — per-ward 90th-percentile climatology + heatwave day/event flagging (core new capability) |
| 5 | Batch export + covariate table | `scripts/run_batch_export.py`, `scripts/build_covariate_table.py`, `heatwave/export.py`, `tests/test_export.py` — produces the CHAP-facing output table (see schema above) |
| 6 | Presentation layer rewrite | `heatwave/app/streamlit_app.py` reading the precomputed table; retire `nigeria_heat_index.py` |
| 7 | Documentation | `docs/METHODOLOGY.md`, rewritten `README.md` |
| 8 | Optional polish | `tests/test_config.py`, optional CI — not required |

Next immediate step per the doc: start Phase 3 (lowest risk, unblocks Phase 4).

**Source:** `PROJECT_STATE.md` §5

## Already delivered (Phases 0-2 — DONE, verified; not "requirements" going forward but establish current baseline)

- `pyproject.toml`, `config.yaml`, `heatwave/` package (`config.py`, `auth.py`, `data/boundary.py`, `data/ingest.py`), `requirements.txt` additions (`pytest`, `PyYAML`).
- `nigeria_heat_index.py` retargeted to new ward asset + ERA5-Land bands; `gee.py` removed (superseded by `heatwave/auth.py`).
- Verified live against `heatwave-508110`: EE init, 4,841-ward boundary load, ERA5-Land band ingestion, Streamlit app boot (HTTP 200).

**Source:** `PROJECT_STATE.md` §4
