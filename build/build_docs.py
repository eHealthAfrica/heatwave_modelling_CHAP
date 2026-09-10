"""Build the two review documents (methodology, phased roadmap) in house style."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import doctheme as T
import docx

OUT = os.path.join(os.path.dirname(__file__), "..", "outputs")
os.makedirs(OUT, exist_ok=True)

META = ["Heatwave modelling pipeline (heatwave_modelling_CHAP) · Review draft",
        "Prepared for Adedo Lukmon · 7 September 2026"]

# ---------------------------------------------------------------------------
# Document 1: Methodology
# ---------------------------------------------------------------------------

doc = docx.Document()
T.docx_setup(doc)
T.cover(doc, "Heatwave Detection Methodology",
        "Northern Nigeria / nationwide ward-level pipeline",
        META, kicker="For review before implementation")

doc.add_heading("1. Purpose", level=1)
doc.add_paragraph(
    "Detect and characterise heatwave events at ward (admin-3) level across "
    "Nigeria, producing a weekly time_period × location covariate table "
    "suitable for later use as a climate covariate in disease-forecasting "
    "platforms such as CHAP (chap-core / dhis2-chap). This pipeline does not "
    "forecast disease outcomes itself — it produces an upstream covariate."
)

doc.add_heading("2. Data sources", level=1)
T.add_table(doc,
    ["Source", "Role", "Detail"],
    [["ECMWF/ERA5_LAND/DAILY_AGGR\n(Google Earth Engine)", "Climate data",
      "~11.1 km resolution, daily, record from 1950-01-02. Bands used: "
      "temperature_2m_max (heatwave detection), temperature_2m, "
      "dewpoint_temperature_2m (Heat Index / RH)."],
     ["Ward boundaries (admin-3)", "Spatial units",
      "Supplied by the project team, nationwide coverage, uploaded as an "
      "Earth Engine FeatureCollection asset."],
     ["Google Earth Engine service account", "Access",
      "Authenticates all data pulls; no raw climate data is stored locally "
      "except pipeline outputs (the covariate table)."]],
    widths=[1.4, 1.0, 3.2], size=9)

doc.add_heading("3. Heatwave definition", level=1)
doc.add_paragraph(
    "A WMO/ETCCDI-style percentile-exceedance definition is used, matching "
    "the Warm Spell Duration Index (WSDI) construct standard in the climate "
    "extremes literature."
)
T.rich_bullet(doc, "**Heatwave day** — daily maximum 2 m air temperature "
              "exceeds the ward's local 90th percentile of a 1991–2020 "
              "calendar-day climatology (±5-day pooling window).")
T.rich_bullet(doc, "**Heatwave event** — ≥ 3 consecutive heatwave days.")
T.rich_bullet(doc, "**Baseline period** — 1991–2020 (current WMO climate "
              "normal), fully covered by the ERA5-Land record.")
T.callout(doc, "Why percentile-based, not a fixed °C threshold",
    "A percentile-relative, duration-gated definition is climate-adaptive: it "
    "accounts for Northern Nigeria's already-hot baseline, avoiding a fixed "
    "threshold that would either trigger constantly or almost never.")

doc.add_heading("4. Heat Index and relative humidity", level=1)
doc.add_paragraph(
    "Retained from the existing prototype, relocated into a tested module "
    "rather than rewritten:"
)
T.rich_bullet(doc, "**Relative humidity approximation**: RH = 100 − 5×(T − D) "
              "— a linear dewpoint-depression approximation, not a full "
              "psychrometric formula.")
T.rich_bullet(doc, "**Heat Index**: the standard NOAA/NWS Rothfusz 9-coefficient "
              "regression, applied to temperature in °F.")
T.callout(doc, "Documented limitation",
    "The Rothfusz regression is only validated for T ≥ 80°F and RH ≥ 40%. "
    "Values outside that range are extrapolated and less reliable. This is "
    "stated here rather than silently corrected.")

doc.add_heading("5. Spatial and temporal aggregation", level=1)
doc.add_paragraph(
    "Per-ward daily series (via Earth Engine zonal reduction over the ward "
    "boundary asset) are aggregated to ISO week (YYYY-Www) per ward, matching "
    "typical disease-surveillance reporting cadence and CHAP's own supported "
    "time_period formats."
)

doc.add_heading("6. Output schema", level=1)
T.add_table(doc,
    ["Column", "Description"],
    [["time_period", "ISO week, e.g. 2020-W23"],
     ["location", "Ward identifier matching the ward boundary asset's feature IDs"],
     ["heatwave_days", "Count of heatwave days in the week"],
     ["mean_heat_index", "Mean Heat Index (°F) across the week"],
     ["max_heat_index", "Maximum Heat Index (°F) across the week"],
     ["heatwave_event_count", "Number of distinct ≥ 3-day heatwave events starting that week"]],
    widths=[1.6, 4.0], size=9)

doc.add_heading("7. Known limitations", level=1)
T.rich_bullet(doc, "**Resolution mismatch** — ERA5-Land's ~11 km grid is "
              "coarser than many wards; neighbouring small wards may share "
              "near-identical values. Documented, not corrected.")
T.rich_bullet(doc, "**No health outcome data** — this is a covariate-only "
              "pipeline, not a disease-forecasting model. No CHAP model "
              "packaging (train/predict/MLproject) is included.")
T.rich_bullet(doc, "**No independent ground truth** — validation is by "
              "plausibility check against known historical hot spells only; "
              "there is no labelled heatwave dataset for this region to "
              "validate against directly.")

doc.add_heading("8. References", level=1)
for ref in [
    "WMO (2018). Guidelines on the Definition and Monitoring of Extreme "
    "Weather and Climate Events.",
    "Perkins, S.E. & Alexander, L.V. (2013). On the measurement of heat "
    "waves. Journal of Climate, 26(13), 4500–4517.",
    "Rothfusz, L.P. (1990). The heat index equation. NWS Technical "
    "Attachment SR 90-23.",
    "Hersbach, H. et al. (2020). The ERA5 global reanalysis. Quarterly "
    "Journal of the Royal Meteorological Society, 146(730), 1999–2049.",
]:
    T.bullet(doc, ref)

doc.save(os.path.join(OUT, "01_Heatwave_Methodology.docx"))
print("Saved 01_Heatwave_Methodology.docx")

# ---------------------------------------------------------------------------
# Document 2: Phased roadmap
# ---------------------------------------------------------------------------

doc2 = docx.Document()
T.docx_setup(doc2)
T.cover(doc2, "Implementation Roadmap",
        "heatwave_modelling_CHAP rework — phased deliverables",
        META, kicker="For review before implementation")

doc2.add_heading("Overview", level=1)
doc2.add_paragraph(
    "Nine phases take the repo from a single-file heat-index viewer to a "
    "modular, tested, ward-level heatwave-detection pipeline whose output is "
    "shaped as a covariate table usable downstream by CHAP. Phase A produces "
    "this pair of review documents; Phases 0–8 are code implementation."
)

rows = [
    ["A", "Review documents", "Produce this methodology and roadmap document "
     "pair in house style, for approval before any code changes."],
    ["0", "Packaging scaffold", "pyproject.toml; add pytest to requirements."],
    ["1", "Config + auth consolidation", "heatwave/config.py, config.yaml, "
     "heatwave/auth.py; remove gee.py; app still runs after this phase."],
    ["2", "Ward boundary + ERA5-Land switch", "Ingest the user-supplied ward "
     "asset; heatwave/data/boundary.py, heatwave/data/ingest.py targeting "
     "ECMWF/ERA5_LAND/DAILY_AGGR."],
    ["3", "Heat Index relocated + tested", "heatwave/science/heat_index.py, "
     "tests/test_heat_index.py."],
    ["4", "Climatology + heatwave detection", "heatwave/science/climatology.py, "
     "heatwave/science/heatwave.py, heatwave/zonal.py, "
     "tests/test_heatwave_detection.py — the core new capability."],
    ["5", "Batch export + covariate table", "scripts/run_batch_export.py, "
     "scripts/build_covariate_table.py, heatwave/export.py, "
     "tests/test_export.py."],
    ["6", "Presentation layer rewrite", "heatwave/app/streamlit_app.py reading "
     "the precomputed covariate table; retire nigeria_heat_index.py."],
    ["7", "Documentation", "docs/METHODOLOGY.md; rewritten README.md."],
    ["8", "Optional polish", "tests/test_config.py; optional CI workflow."],
]
T.add_table(doc2, ["Phase", "Name", "What it delivers"], rows,
            widths=[0.5, 1.6, 4.4], size=9)

doc2.add_heading("Verification checkpoints", level=1)
T.rich_bullet(doc2, "**After Phase 2** — confirm the uploaded ward asset "
              "loads with the expected ward count, and ERA5-Land images clip "
              "to it correctly.")
T.rich_bullet(doc2, "**After Phases 3, 4, 5** — pytest passes for Heat "
              "Index/RH, heatwave detection, and covariate export.")
T.rich_bullet(doc2, "**After Phase 5** — run the batch export on a short "
              "date range first; inspect the covariate CSV for one row per "
              "ward per week, plausible ranges, no missing periods.")
T.rich_bullet(doc2, "**After Phase 5/6** — sanity-check detected heatwave "
              "events against known historical hot spells for Northern "
              "Nigeria.")

doc2.save(os.path.join(OUT, "02_Implementation_Roadmap.docx"))
print("Saved 02_Implementation_Roadmap.docx")
