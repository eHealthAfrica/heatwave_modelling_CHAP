"""Presentation layer: browse the precomputed weekly covariate table on a
ward map (APP-01, APP-02, APP-03).

Reads the covariate CSV (`heatwave.export.COVARIATE_COLUMNS` schema) that
`scripts/run_batch_export.py` produces and NEVER computes Heat Index,
climatology, or heatwave detection live -- all of that math already lives
in `heatwave/science/` and `heatwave/zonal.py`. This module retires
`nigeria_heat_index.py` (APP-02): it is presentation only, reading a
precomputed table instead of a live per-date Earth Engine computation.

The table path defaults to `outputs/covariate_table.csv` (the real
production output) but is overridable via the `COVARIATE_TABLE_PATH`
environment variable -- e.g. pointed at `outputs/covariate_table_SAMPLE.csv`
during development, since the full historical backfill has not yet
completed (see `outputs/README.md`).
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
import ee
from heatwave.auth import init_ee  # triggers heatwave package's blessings stub before geemap loads
import geemap.foliumap as geemap  # noqa: E402  (import order is load-bearing, see above)

from heatwave.data.boundary import load_ward_boundary

WARD_ID_PROPERTY = "wardcode"
NO_DATA_COLOR = "#d9d9d9"

# One sequential palette per metric. Reuses the old app's blue->purple hot
# scale for the two Heat Index metrics so returning users see a familiar
# ramp; heatwave_days/heatwave_event_count are small integer counts, so a
# shorter white->red ramp reads more like "how much", less like "how hot".
METRICS: dict[str, dict] = {
    "heatwave_days": {
        "label": "Heatwave days (per week)",
        "palette": ["#ffffcc", "#fd8d3c", "#e31a1c", "#800026"],
    },
    "mean_heat_index": {
        "label": "Mean Heat Index (°F)",
        "palette": ["blue", "cyan", "green", "yellow", "orange", "red", "purple"],
    },
    "max_heat_index": {
        "label": "Max Heat Index (°F)",
        "palette": ["blue", "cyan", "green", "yellow", "orange", "red", "purple"],
    },
    "heatwave_event_count": {
        "label": "Heatwave events (starting that week)",
        "palette": ["#ffffcc", "#fd8d3c", "#e31a1c", "#800026"],
    },
}


@st.cache_resource
def _cached_init_ee() -> None:
    init_ee()


@st.cache_data
def load_covariate_table(csv_path: str) -> pd.DataFrame:
    """Load the covariate CSV, keeping `location` (a ward code) as a string
    so it isn't mangled to an int/float and can join cleanly against
    `heatwave.data.boundary.load_ward_boundary()`'s `wardcode` property.
    """
    return pd.read_csv(csv_path, dtype={"location": str})


def metric_bounds(df: pd.DataFrame, metric: str) -> tuple[float, float]:
    """Return a (min, max) color-scale range for `metric` across the whole
    loaded table (not just the selected week), so a ward's color means the
    same thing regardless of which week is being viewed.

    Count-based metrics are always floored at 0 (a week with no heatwave
    days is meaningfully "zero", not "the lowest observed value"); a
    degenerate all-equal column still produces a valid (if single-color)
    range rather than a division by zero.
    """
    series = df[metric].dropna()
    if metric in ("heatwave_days", "heatwave_event_count"):
        vmin = 0.0
        vmax = float(series.max()) if not series.empty else 1.0
    else:
        vmin = float(series.min()) if not series.empty else 60.0
        vmax = float(series.max()) if not series.empty else 130.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax


def color_for_value(value: float | None, vmin: float, vmax: float, palette: list[str]) -> str:
    """Map a metric value to a palette color; missing data gets `NO_DATA_COLOR`
    (grey), never a fabricated position on the scale."""
    if value is None or pd.isna(value):
        return NO_DATA_COLOR
    fraction = 0.0 if vmax == vmin else (value - vmin) / (vmax - vmin)
    fraction = min(1.0, max(0.0, fraction))
    index = min(int(fraction * (len(palette) - 1)), len(palette) - 1)
    return palette[index]


def build_styled_wards(
    week_df: pd.DataFrame, metric: str, vmin: float, vmax: float, palette: list[str]
) -> ee.Image:
    """Attach a per-ward fill color for `metric` server-side and return the
    rasterized, styled `ee.Image` ready to add as a map layer.

    `ee.FeatureCollection.style()` returns an `ee.Image` (a rendering), not
    a `FeatureCollection` -- there is no post-style feature count to assert
    on; verify correctness via `.getInfo()`/`.bandNames()` instead.

    The ward->style lookup is built once, client-side, from `week_df`
    (at most 4,841 rows) and passed to Earth Engine as a single
    `ee.Dictionary` -- the boundary's ~4,841 polygons themselves are never
    pulled down into Python; only their rendered map tiles are, same as the
    retired app's `boundary.style()` call.
    """
    style_by_ward = {
        str(row["location"]): {
            "color": "black",
            "width": 1,
            "fillColor": color_for_value(row[metric], vmin, vmax, palette),
        }
        for _, row in week_df.iterrows()
    }
    style_dict = ee.Dictionary(style_by_ward)
    default_style = {"color": "black", "width": 1, "fillColor": NO_DATA_COLOR}

    def _attach_style(feature: ee.Feature) -> ee.Feature:
        ward_id = feature.get(WARD_ID_PROPERTY)
        style = ee.Dictionary(
            ee.Algorithms.If(style_dict.contains(ward_id), style_dict.get(ward_id), default_style)
        )
        return feature.set("style", style)

    return load_ward_boundary().map(_attach_style).style(styleProperty="style")


# =======================
# Streamlit UI
# =======================
# Guarded by `__name__ == "__main__"` so the pure helper functions above stay
# safely importable for unit testing (`from heatwave.app.streamlit_app import
# color_for_value`) without executing the UI. Both `streamlit run` and
# `streamlit.testing.v1.AppTest.from_file()` execute this file with
# `__name__` set to `"__main__"`, so the app behaves identically under both.
def _run_app() -> None:
    st.set_page_config(page_title="Heatwave Covariate Explorer", layout="wide")
    st.title("🌍 Nigeria Heatwave Covariate Explorer")
    st.caption(
        "Reads the precomputed weekly covariate table -- no live Heat Index or "
        "climatology computation happens in this app."
    )

    covariate_csv_path = os.getenv("COVARIATE_TABLE_PATH", "outputs/covariate_table.csv")

    if not Path(covariate_csv_path).exists():
        st.error(
            f"No covariate table found at `{covariate_csv_path}`.\n\n"
            "Run `python scripts/run_batch_export.py` to produce the real table "
            "(the full 1991-present historical backfill has not yet completed -- "
            "see `outputs/README.md`), or set the `COVARIATE_TABLE_PATH` "
            "environment variable to point at a sample CSV for development, e.g. "
            "`outputs/covariate_table_SAMPLE.csv`."
        )
        st.stop()

    df = load_covariate_table(covariate_csv_path)

    weeks = sorted(df["time_period"].unique())
    metric_keys = list(METRICS.keys())

    col1, col2 = st.columns(2)
    selected_week = col1.selectbox("Week", weeks, index=len(weeks) - 1)
    selected_metric = col2.selectbox(
        "Metric", metric_keys, format_func=lambda key: METRICS[key]["label"]
    )

    week_df = df[df["time_period"] == selected_week]
    vmin, vmax = metric_bounds(df, selected_metric)
    palette = METRICS[selected_metric]["palette"]

    st.write(
        f"📅 **{selected_week}** — {METRICS[selected_metric]['label']} "
        f"(scale: {vmin:g} to {vmax:g}; grey = no data for this ward/week)"
    )

    _cached_init_ee()

    ward_map = geemap.Map(center=[9.0820, 8.6753], zoom=6)
    ward_map.addLayer(
        build_styled_wards(week_df, selected_metric, vmin, vmax, palette),
        {},
        METRICS[selected_metric]["label"],
    )
    ward_map.to_streamlit(height=650)

    st.subheader(f"Ward data for {selected_week}")
    st.dataframe(
        week_df[
            ["location", "heatwave_days", "mean_heat_index", "max_heat_index", "heatwave_event_count"]
        ].sort_values("location"),
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    _run_app()
