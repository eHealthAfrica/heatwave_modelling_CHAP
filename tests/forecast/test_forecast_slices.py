"""EVAL-04: seasons, regions, years and ward flags."""

from __future__ import annotations

import numpy as np
import pytest

from heatwave.forecast.evaluation import slices
from heatwave.forecast.fixtures import SYNTHETIC_WARDS, _square, synthetic_static_sources
from heatwave.forecast.static import build_static_table


@pytest.fixture(scope="module")
def syn():
    geo, rows = synthetic_static_sources()
    st = build_static_table(geo, rows, SYNTHETIC_WARDS)
    return geo, st


def test_constants():
    assert slices.HIGHLIGHT_SEASON == "MAM"
    assert slices.SEASONS == ("DJF", "MAM", "JJA", "SON")


@pytest.mark.parametrize(
    "start,expected",
    [("2020-12-28", "DJF"), ("1998-12-28", "DJF"), ("2015-11-30", "DJF"), ("2015-11-23", "SON"),
     ("2015-02-23", "DJF"), ("2015-03-02", "MAM"), ("2015-05-25", "MAM"), ("2015-06-01", "JJA")],
)
def test_season_of_midweek(start, expected):
    assert slices.season_of(np.array([start], dtype="datetime64[D]"))[0] == expected


def test_lat_band_boundaries_and_report_counts(syn):
    _, st = syn
    assert slices.lat_band(np.array([11.5, 11.51, 9.5, 9.49])).tolist() == ["central", "far_north", "central", "middle_belt"]
    from heatwave.forecast.report import LAT_FAR_NORTH, LAT_MIDDLE_BELT

    lat = np.asarray(st.lat, dtype=np.float64)
    band = slices.lat_band(lat)
    assert (band == "far_north").sum() == (lat > LAT_FAR_NORTH).sum()
    assert (band == "middle_belt").sum() == (lat < LAT_MIDDLE_BELT).sum()
    assert (band == "central").sum() == ((lat >= LAT_MIDDLE_BELT) & (lat <= LAT_FAR_NORTH)).sum()


def test_areas_and_small_flag(syn):
    geo, st = syn
    areas = slices.ward_areas_deg2(geo, st.wards)
    assert areas[0] == pytest.approx(0.0004)
    assert np.isnan(areas[SYNTHETIC_WARDS.index("SOCCC002")])
    flags = slices.small_ward_flags(areas)
    assert flags[:5].all() and not flags[5]
    big = {"features": [{"properties": {"wardcode": "X"}, "geometry": _square(0.0, 0.0, 0.2)}]}
    a = slices.ward_areas_deg2(big, ("X", "Y"))
    assert a[0] == pytest.approx(0.04) and np.isnan(a[1])
    assert not slices.small_ward_flags(a).any()


def test_week_attributes():
    wa = slices.week_attributes(
        np.array([5, 5, 6]), np.array(["2020-12-28", "2020-12-28", "2021-01-04"], dtype="datetime64[D]"),
        np.array(["2020-W53", "2020-W53", "2021-W01"]),
    )
    assert wa.loc[5, "year"] == 2020 and wa.loc[5, "season"] == "DJF"
    assert wa.loc[6, "year"] == 2021 and len(wa) == 2


def test_row_slice_masks_partition(syn):
    geo, st = syn
    attrs = slices.ward_attributes(st, slices.ward_areas_deg2(geo, st.wards))
    weeks = np.array([0, 1, 2, 3], dtype=np.int64)
    wk = slices.week_attributes(
        weeks, np.array(["2015-01-05", "2015-04-06", "2015-07-06", "2016-10-05"], dtype="datetime64[D]"),
        np.array(["2015-W02", "2015-W15", "2015-W28", "2016-W40"]),
    )
    codes = np.repeat(np.array(SYNTHETIC_WARDS, dtype=object), 4)
    widx = np.tile(weeks, 6)
    masks = slices.row_slice_masks(codes, widx, attrs, wk)
    n = len(codes)
    for fam in slices.FAMILIES:
        parts = [m for (f, _s, ff), m in masks.items() if f == fam and ff == "all_wards"]
        assert np.array_equal(np.sum(parts, axis=0), np.ones(n)), fam
    large = masks[("all", "all", "large_wards_only")]
    assert not attrs["small"].loc[codes[large]].any()
    assert masks[("season", "MAM", "all_wards")].sum() == 6
    assert ("year", 2016, "all_wards") in masks
    lga_only = masks[("all", "all", "lga_average_only")]
    excl = masks[("all", "all", "exclude_lga_average")]
    assert np.array_equal(lga_only, ~excl)


@pytest.mark.frozen
def test_frozen_small_ward_count(forecast_cfg, frozen_panel):
    areas = slices.load_ward_areas(forecast_cfg.data, frozen_panel.wards)
    assert int(np.isfinite(areas).sum()) == 4835
    assert int(slices.small_ward_flags(areas).sum()) == 3086
