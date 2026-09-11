"""Build the phase-details status document in house style."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import doctheme as T
import docx

OUT = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUT, exist_ok=True)

META = ["Heatwave modelling pipeline (heatwave_modelling_CHAP) · Status report",
        "Prepared for Adedo Lukmon · 10 September 2026"]

doc = docx.Document()
T.docx_setup(doc)
T.cover(doc, "Implementation Phases",
        "heatwave_modelling_CHAP rework — full phase breakdown and current status",
        META, kicker="Status as of PR #1")

# ---------------------------------------------------------------------------
doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Nine phases take the repository from a single-file heat-index viewer to "
    "a modular, tested, ward-level heatwave-detection pipeline whose output is "
    "shaped as a covariate table usable downstream by CHAP. Phase A produced "
    "the review documents; Phases 0–8 are code implementation. Phases 0–2 are "
    "complete, verified against the live heatwave-508110 project, and shipped "
    "as pull request #1 (feature/heatwave-508110-phase-0-2 → main) on "
    "eHealthAfrica/heatwave_modelling_CHAP. Phases 3–8 have not started."
)

T.add_table(doc,
    ["Phase", "Name", "Status"],
    [["A", "Review documents", "Done"],
     ["0", "Packaging scaffold", "Done"],
     ["1", "Config + auth consolidation", "Done"],
     ["2", "Ward boundary + ERA5-Land switch", "Done"],
     ["3", "Heat Index relocated + tested", "Not started"],
     ["4", "Climatology + heatwave detection", "Not started"],
     ["5", "Batch export + covariate table", "Not started"],
     ["6", "Presentation layer rewrite", "Not started"],
     ["7", "Documentation", "Not started"],
     ["8", "Optional polish (not required)", "Not started"]],
    widths=[0.6, 3.0, 2.9], size=10)

# ---------------------------------------------------------------------------
doc.add_heading("Phase A — Review documents", level=1)
T.kicker_para(doc, "Done")
doc.add_paragraph(
    "Produced the methodology and roadmap document pair in house style, for "
    "approval before any code changes."
)
T.rich_bullet(doc, "**Delivers**: `01_Heatwave_Methodology.docx`, "
              "`02_Implementation_Roadmap.docx`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 0 — Packaging scaffold", level=1)
T.kicker_para(doc, "Done")
doc.add_paragraph(
    "Establishes the project as an installable package rather than a loose "
    "pair of scripts, and adds the test runner used from Phase 3 onward."
)
T.rich_bullet(doc, "**Delivers**: `pyproject.toml` (Python ≥3.11); `pytest` "
              "and `PyYAML` added to `requirements.txt`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 1 — Config + auth consolidation", level=1)
T.kicker_para(doc, "Done")
doc.add_paragraph(
    "Replaces the credential-resolution logic that was duplicated between "
    "`nigeria_heat_index.py` and `gee.py` with a single `init_ee()`, still "
    "supporting the same three credential sources in the same priority order: "
    "Streamlit secrets, then the `EE_SA_JSON` environment variable, then a "
    "local `keys/service_account.json`. `config.yaml` centralises the GCP "
    "project id, ward asset id, ERA5-Land band names, and the climatology "
    "constants fixed by the methodology document, so later phases read one "
    "source of truth instead of hardcoded values."
)
T.rich_bullet(doc, "**Delivers**: `heatwave/config.py`, `config.yaml`, "
              "`heatwave/auth.py`. `gee.py` removed.")
T.callout(doc, "Bug found and fixed during implementation",
    "Reading `st.secrets` when no secrets.toml exists at all raised "
    "StreamlitSecretNotFoundError instead of the intended not-configured "
    "fallback to the next credential source. This affected the original "
    "prototype too — it just never surfaced because it always ran with "
    "Streamlit Cloud secrets configured.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 2 — Ward boundary + ERA5-Land switch", level=1)
T.kicker_para(doc, "Done")
doc.add_paragraph(
    "Moves the app off the old, now-inaccessible ee-victoridakwo/"
    "Northern_Nigeria state-level boundary and the coarser ECMWF/ERA5/DAILY "
    "collection, onto the new nationwide ward-level asset and "
    "ECMWF/ERA5_LAND/DAILY_AGGR (~11.1 km resolution, daily record from "
    "1950-01-02)."
)
T.rich_bullet(doc, "**Delivers**: `heatwave/data/boundary.py`, "
              "`heatwave/data/ingest.py`.")
T.rich_bullet(doc, "**Boundary asset**: `projects/heatwave-508110/assets/shp` "
              "— 4,841 wards nationwide (GRID3 schema: wardname, wardcode, "
              "lganame, statename).")
T.callout(doc, "Verified against the live project",
    "Earth Engine authentication succeeds; the ward boundary loads with the "
    "expected feature count and properties; ERA5-Land ingestion returns the "
    "correct band names for a sample date range; the Streamlit app boots "
    "cleanly and serves over HTTP against real data.")

doc.add_paragraph(
    "Phases 1 and 2 were implemented together in one pass rather than "
    "sequentially: Phase 1's own checkpoint — the app still runs after this "
    "phase — was only achievable once the app pointed at the new asset and "
    "collection from Phase 2, since starting fresh meant no inherited access "
    "to the old project's boundary."
)

# ---------------------------------------------------------------------------
doc.add_heading("Phase 3 — Heat Index relocated + tested", level=1)
T.kicker_para(doc, "Not started")
doc.add_paragraph(
    "Moves the existing relative-humidity approximation "
    "(RH = 100 − 5×(T − D)) and the NOAA/NWS Rothfusz 9-coefficient Heat "
    "Index regression out of `nigeria_heat_index.py` into a tested module — "
    "relocated, not rewritten, per the methodology document."
)
T.rich_bullet(doc, "**Delivers**: `heatwave/science/heat_index.py`, "
              "`tests/test_heat_index.py`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 4 — Climatology + heatwave detection", level=1)
T.kicker_para(doc, "Not started")
doc.add_paragraph(
    "The core new capability: computes each ward's 1991–2020 calendar-day "
    "90th-percentile climatology (±5-day pooling window) and flags heatwave "
    "days and events (≥3 consecutive days exceeding the local percentile) via "
    "per-ward zonal reduction. The constants this phase needs are already in "
    "`config.yaml` from Phase 1."
)
T.rich_bullet(doc, "**Delivers**: `heatwave/science/climatology.py`, "
              "`heatwave/science/heatwave.py`, `heatwave/zonal.py`, "
              "`tests/test_heatwave_detection.py`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 5 — Batch export + covariate table", level=1)
T.kicker_para(doc, "Not started")
doc.add_paragraph(
    "Produces the weekly time_period × location covariate table — this "
    "pipeline's actual deliverable to CHAP: time_period, location, "
    "heatwave_days, mean_heat_index, max_heat_index, heatwave_event_count."
)
T.rich_bullet(doc, "**Delivers**: `scripts/run_batch_export.py`, "
              "`scripts/build_covariate_table.py`, `heatwave/export.py`, "
              "`tests/test_export.py`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 6 — Presentation layer rewrite", level=1)
T.kicker_para(doc, "Not started")
doc.add_paragraph(
    "Replaces the current live, per-date Earth Engine query pattern with a "
    "viewer that reads the precomputed covariate table from Phase 5, "
    "matching the pipeline's shift from a demo viewer to a covariate-"
    "producing pipeline."
)
T.rich_bullet(doc, "**Delivers**: `heatwave/app/streamlit_app.py`. "
              "`nigeria_heat_index.py` retired.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 7 — Documentation", level=1)
T.kicker_para(doc, "Not started")
T.rich_bullet(doc, "**Delivers**: `docs/METHODOLOGY.md`, rewritten "
              "`README.md`.")

# ---------------------------------------------------------------------------
doc.add_heading("Phase 8 — Optional polish", level=1)
T.kicker_para(doc, "Not started")
T.rich_bullet(doc, "**Delivers**: `tests/test_config.py`; optional CI "
              "workflow. Not required for the pipeline to function.")

# ---------------------------------------------------------------------------
doc.add_heading("Verification checkpoints", level=1)
T.rich_bullet(doc, "**After Phase 2 (passed)** — confirmed the uploaded ward "
              "asset loads with the expected ward count, and ERA5-Land "
              "images clip to it correctly.")
T.rich_bullet(doc, "**After Phases 3, 4, 5** — pytest passes for Heat "
              "Index/RH, heatwave detection, and covariate export.")
T.rich_bullet(doc, "**After Phase 5** — run the batch export on a short "
              "date range first; inspect the covariate CSV for one row per "
              "ward per week, plausible ranges, no missing periods.")
T.rich_bullet(doc, "**After Phase 5/6** — sanity-check detected heatwave "
              "events against known historical hot spells for Northern "
              "Nigeria.")

doc.save(os.path.join(OUT, "03_Implementation_Phases_Status.docx"))
print("Saved 03_Implementation_Phases_Status.docx")
