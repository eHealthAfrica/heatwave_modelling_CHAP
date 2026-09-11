# Decisions (from ADRs)

No ADR-type documents were present in this ingest (only one document was classified: `PROJECT_STATE.md`, type DOC). No formal, locked architectural decisions exist yet.

The source `.docx`/`.pdf` planning documents referenced by `PROJECT_STATE.md` (methodology, roadmap, phase-status docs) could not be parsed in this environment and were not classified or synthesized. If those are made available as text/markdown, re-run ingestion — they may contain the project's actual ADR-equivalent decisions in full.

In the meantime, `context.md` (topic: "Cloud Infrastructure" and "Config / Climatology Constants") captures several de-facto infrastructure and parameter choices that read like decisions but were only ever recorded informally in a status doc:

- GCP project `heatwave-508110`, Earth Engine data source `ECMWF/ERA5_LAND/DAILY_AGGR`, ward boundary asset `projects/heatwave-508110/assets/shp` (GRID3 NGA Operational Wards).
- Climatology parameters: baseline period 1991-2020, 90th percentile threshold, ±5-day pooling window, ≥3 consecutive days = heatwave event.

None of these are marked `locked` and none originate from an ADR — treat them as strong precedent, not binding decisions, until formalized (e.g., via an ADR) in a future ingest.

**Source:** `PROJECT_STATE.md`
