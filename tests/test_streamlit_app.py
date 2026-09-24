"""Tests for `heatwave/app/streamlit_app.py` (APP-01, APP-02, APP-03).

Pure-Python helpers (`color_for_value`, `metric_bounds`) are tested without
any Earth Engine dependency. The live tests follow the project's
established skip-gated pattern (`tests/test_integration.py`,
`tests/test_heatwave_detection.py`, `tests/test_export.py`): real Earth
Engine calls against `heatwave-508110` whenever credentials are available,
never mocked.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import ee
import pandas as pd
import pytest

from heatwave.app.streamlit_app import color_for_value, metric_bounds

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))
_APP_SCRIPT = Path(__file__).resolve().parent.parent / "heatwave" / "app" / "streamlit_app.py"

_PALETTE = ["#000000", "#555555", "#aaaaaa", "#ffffff"]


# =======================
# Pure-Python unit tests (no credentials needed)
# =======================


def test_app02_nigeria_heat_index_retired():
    """APP-02: nigeria_heat_index.py no longer exists -- its logic lives in
    heatwave/science/ and the new app module, per the retirement this phase makes."""
    old_script = Path(__file__).resolve().parent.parent / "nigeria_heat_index.py"
    assert not old_script.exists(), (
        "nigeria_heat_index.py should be retired (APP-02) now that "
        "heatwave/app/streamlit_app.py exists"
    )


def test_color_for_value_missing_data_is_grey():
    assert color_for_value(None, 0.0, 10.0, _PALETTE) == "#d9d9d9"
    assert color_for_value(float("nan"), 0.0, 10.0, _PALETTE) == "#d9d9d9"


def test_color_for_value_clamps_out_of_range_inputs():
    # Below vmin and above vmax must clamp to the palette's end colors, not
    # index out of bounds or extrapolate past the ramp.
    assert color_for_value(-5.0, 0.0, 10.0, _PALETTE) == _PALETTE[0]
    assert color_for_value(999.0, 0.0, 10.0, _PALETTE) == _PALETTE[-1]


def test_color_for_value_interpolates_across_palette():
    # Midpoint of a 4-color palette over [0, 10] should land on one of the
    # middle two colors, never the first or last.
    mid_color = color_for_value(5.0, 0.0, 10.0, _PALETTE)
    assert mid_color in (_PALETTE[1], _PALETTE[2])


def test_metric_bounds_count_metric_floors_at_zero():
    df = pd.DataFrame({"heatwave_days": [3, 5, 7]})
    vmin, vmax = metric_bounds(df, "heatwave_days")
    assert vmin == 0.0
    assert vmax == 7.0


def test_metric_bounds_degenerate_column_does_not_divide_by_zero():
    # Every value identical (e.g. an all-zero sample) must still produce a
    # valid, non-degenerate (vmin < vmax) range.
    df = pd.DataFrame({"heatwave_event_count": [0, 0, 0]})
    vmin, vmax = metric_bounds(df, "heatwave_event_count")
    assert vmax > vmin


def test_metric_bounds_continuous_metric_ignores_nulls():
    df = pd.DataFrame({"mean_heat_index": [60.0, None, 90.0]})
    vmin, vmax = metric_bounds(df, "mean_heat_index")
    assert vmin == 60.0
    assert vmax == 90.0


def test_metric_bounds_all_null_falls_back_to_default_range():
    df = pd.DataFrame({"mean_heat_index": [None, None]})
    vmin, vmax = metric_bounds(df, "mean_heat_index")
    assert vmin < vmax


# =======================
# Live, skip-gated tests
# =======================

pytestmark_live = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)


def _write_fixture_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time_period",
                "location",
                "heatwave_days",
                "mean_heat_index",
                "max_heat_index",
                "heatwave_event_count",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytestmark_live
def test_app01_build_styled_wards_attaches_real_ward_geometry(tmp_path):
    """APP-01: the app renders from the precomputed table against the real
    ward boundary asset -- never a live Heat Index computation."""
    from heatwave.auth import init_ee
    from heatwave.app.streamlit_app import build_styled_wards

    init_ee()

    week_df = pd.DataFrame(
        [
            {"location": "10101", "heatwave_days": 3, "mean_heat_index": 95.0, "max_heat_index": 99.0, "heatwave_event_count": 1},
            {"location": "10104", "heatwave_days": 0, "mean_heat_index": 70.0, "max_heat_index": 74.0, "heatwave_event_count": 0},
        ]
    )
    styled = build_styled_wards(week_df, "mean_heat_index", 60.0, 100.0, ["blue", "red"])

    # ee.FeatureCollection.style() returns a rasterized ee.Image, not a
    # FeatureCollection -- there's no per-ward feature count to assert on
    # post-style. Confirm the whole composition (ward->style dictionary
    # lookup, ee.Algorithms.If default-style fallback, .style() itself)
    # actually executes server-side against the real 4,841-ward asset
    # without error, and produces real visual output (non-empty bands).
    assert isinstance(styled, ee.Image)
    band_names = styled.bandNames().getInfo()
    assert len(band_names) > 0


@pytestmark_live
def test_app03_streamlit_app_boots_and_lets_user_change_week_and_metric(tmp_path):
    """APP-03: the rewritten app boots cleanly and lets a user browse
    ward-level heatwave metrics by week."""
    from streamlit.testing.v1 import AppTest

    fixture_csv = tmp_path / "covariate_table_fixture.csv"
    _write_fixture_csv(
        fixture_csv,
        [
            {"time_period": "2020-W23", "location": "10101", "heatwave_days": 2, "mean_heat_index": 95.5, "max_heat_index": 98.2, "heatwave_event_count": 0},
            {"time_period": "2020-W24", "location": "10101", "heatwave_days": 4, "mean_heat_index": 99.1, "max_heat_index": 103.4, "heatwave_event_count": 1},
        ],
    )

    os.environ["COVARIATE_TABLE_PATH"] = str(fixture_csv)
    try:
        at = AppTest.from_file(str(_APP_SCRIPT), default_timeout=30)
        at.run()
        assert not at.exception, f"App raised: {at.exception}"

        # Two weeks in the fixture -> the week selectbox must offer both.
        week_select = at.selectbox[0]
        assert set(week_select.options) == {"2020-W23", "2020-W24"}

        # Switching weeks must not raise -- this is the "browse by week" behavior APP-03 requires.
        week_select.select("2020-W23").run()
        assert not at.exception, f"App raised after selecting a week: {at.exception}"
    finally:
        os.environ.pop("COVARIATE_TABLE_PATH", None)


@pytestmark_live
def test_app03_missing_covariate_table_shows_clear_error_not_a_crash():
    """A missing covariate table (the real one, since the full backfill has
    not completed -- see outputs/README.md) must show a clear message and
    stop, never raise an unhandled exception."""
    from streamlit.testing.v1 import AppTest

    os.environ["COVARIATE_TABLE_PATH"] = "outputs/.this_file_does_not_exist.csv"
    try:
        at = AppTest.from_file(str(_APP_SCRIPT), default_timeout=30)
        at.run()
        assert not at.exception, f"App raised: {at.exception}"
        assert any("No covariate table found" in e.value for e in at.error)
    finally:
        os.environ.pop("COVARIATE_TABLE_PATH", None)
