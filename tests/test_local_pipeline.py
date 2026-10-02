"""Offline tests for the local (numpy) pipeline: science, ward weights, weekly table.

No Earth Engine credentials or downloaded data needed; everything runs on synthetic arrays.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import MultiPoint, box

from heatwave.config import ClimatologyConfig
from heatwave.local import science
from heatwave.local.grid import build_weights, fill_empty_from_lga
from heatwave.local.pipeline import COVARIATE_COLUMNS, WardDaily, weekly_table
from test_heat_index import _dewpoint_k, _f_to_k, _nws_heat_index

# --- RH and Heat Index ------------------------------------------------------


@pytest.mark.parametrize(("t_f", "rh", "noaa_hi"), [(96, 50, 108), (100, 40, 109), (90, 70, 105)])
def test_heat_index_matches_noaa_table(t_f, rh, noaa_hi):
    t_k, d_k = np.array([_f_to_k(t_f)]), np.array([_dewpoint_k(t_f, rh)])
    hi = science.heat_index_f(t_k, science.relative_humidity(t_k, d_k))
    assert hi[0] == pytest.approx(noaa_hi, abs=1.5)


def test_heat_index_matches_nws_reference_on_a_grid():
    """Every branch (simple, Rothfusz, dry and humid adjustments) matches the reference."""
    t_f = np.arange(50, 115, 1.5)
    rh = np.arange(2, 100, 3.5)
    tt, rr = np.meshgrid(t_f, rh)
    got = science.heat_index_f(np.vectorize(_f_to_k)(tt), rr)
    want = np.vectorize(_nws_heat_index)(tt, rr)
    np.testing.assert_allclose(got, want, atol=1e-6)


def test_relative_humidity_magnus_and_clamp():
    t_k = np.array([_f_to_k(95), 290.0])
    d_k = np.array([_dewpoint_k(95, 20), 300.0])  # second: dewpoint above air temperature
    np.testing.assert_allclose(science.relative_humidity(t_k, d_k), [20, 100], atol=1e-6)


# --- thresholds, exceedance and events ---------------------------------------


def test_doy_thresholds_pool_and_wrap_year_end():
    doy = np.tile(np.arange(1, 367), 3)
    values = doy.astype("float64")[:, None]  # each day's value is its own day of year
    thr = science.doy_thresholds(values, doy, np.ones(len(doy), bool), percentile=100, window=5)
    assert thr[100 - 1, 0] == 105             # pools doy 95..105
    assert thr[366 - 1, 0] == 366             # pools 361..366 and 1..5
    assert thr[1 - 1, 0] == 366               # pools 362..366 and 1..6
    lo = science.doy_thresholds(values, doy, np.ones(len(doy), bool), percentile=0, window=5)
    assert lo[1 - 1, 0] == 1 and lo[366 - 1, 0] == 1


def test_doy_thresholds_use_only_baseline_days():
    doy = np.tile(np.arange(1, 367), 2)
    values = np.r_[np.zeros(366), np.full(366, 50.0)][:, None]
    in_base = np.r_[np.ones(366, bool), np.zeros(366, bool)]
    thr = science.doy_thresholds(values, doy, in_base, percentile=90, window=5)
    assert (thr == 0).all()


def test_exceeds_is_strict():
    thr = np.full((366, 1), 10.0, dtype="float32")
    hot = science.exceeds(np.array([[9.9], [10.0], [10.1]]), thr, np.array([1, 2, 3]))
    assert hot[:, 0].tolist() == [False, False, True]


@pytest.mark.parametrize(
    ("pattern", "expected_starts"),
    [
        ("0110", []),                 # 2-day spell is not an event
        ("0111000", [1]),             # exactly 3 days
        ("1111100111", [0, 7]),       # runs at both edges
        ("1101110111", [3, 7]),
    ],
)
def test_event_starts(pattern, expected_starts):
    hot = np.array([c == "1" for c in pattern])[:, None]
    assert np.flatnonzero(science.event_starts(hot, 3)[:, 0]).tolist() == expected_starts


# --- ward weights ------------------------------------------------------------

LATS = np.round(np.arange(14.0, 3.95, -0.1), 2)
LONS = np.round(np.arange(2.5, 15.05, 0.1), 2)
VALID = np.ones((len(LATS), len(LONS)), bool)


def _cell(lat, lon):
    return int(np.argmin(abs(LATS - lat))) * len(LONS) + int(np.argmin(abs(LONS - lon)))


def test_ward_matching_one_cell_gets_that_cell():
    w = build_weights([box(7.95, 9.95, 8.05, 10.05)], LATS, LONS, VALID)
    assert w.cells.tolist() == [_cell(10.0, 8.0)]
    assert w.weights.tolist() == [1.0]


def test_ward_split_over_two_cells_is_area_weighted():
    # 3/4 of the ward in the 8.0E cell, 1/4 in the 8.1E cell
    w = build_weights([box(7.96, 9.97, 8.08, 10.03)], LATS, LONS, VALID)
    got = dict(zip(w.cells.tolist(), w.weights.tolist()))
    assert got[_cell(10.0, 8.0)] == pytest.approx(0.75, abs=1e-6)
    assert got[_cell(10.0, 8.1)] == pytest.approx(0.25, abs=1e-6)


def test_point_ward_uses_containing_cell():
    w = build_weights([MultiPoint([(8.01, 10.02)])], LATS, LONS, VALID)
    assert w.cells.tolist() == [_cell(10.0, 8.0)] and w.n_point_wards == 1


def test_ward_over_no_data_falls_back_to_nearest_valid_cell():
    valid = VALID.copy()
    i, j = int(np.argmin(abs(LATS - 10.0))), int(np.argmin(abs(LONS - 8.0)))
    valid[i, j] = False
    w = build_weights([box(7.97, 9.97, 8.03, 10.03)], LATS, LONS, valid)
    assert w.n_nearest_wards == 1
    assert len(w.cells) == 1 and valid.ravel()[w.cells[0]]


def test_empty_ward_geometry_is_rejected():
    with pytest.raises(ValueError, match="empty geometry"):
        build_weights([MultiPoint()], LATS, LONS, VALID)


def test_empty_ward_takes_area_weighted_lga_average():
    # LGA "1": a 1-cell ward at 8.0E and a 3-cell ward at 8.1-8.3E; ward 2 has no geometry
    geoms = [box(7.95, 9.95, 8.05, 10.05), box(8.05, 9.95, 8.35, 10.05), MultiPoint(),
             box(9.95, 11.95, 10.05, 12.05)]
    filled, which = fill_empty_from_lga(geoms, ["1", "1", "1", "2"])
    assert which == [2]
    w = build_weights(filled, LATS, LONS, VALID)
    grid = np.zeros((1, len(LATS) * len(LONS)), dtype="float32")
    for lon, v in [(8.0, 4), (8.1, 8), (8.2, 8), (8.3, 8)]:
        grid[0, _cell(10.0, lon)] = v
    np.testing.assert_allclose(w.reduce(grid)[0, 2], 7.0, atol=1e-4)  # (4 + 3*8) / 4


def test_empty_ward_without_lga_siblings_is_rejected():
    with pytest.raises(ValueError, match="no other ward"):
        fill_empty_from_lga([MultiPoint(), box(7.95, 9.95, 8.05, 10.05)], ["1", "2"])


def test_reduce_gives_weighted_means_per_ward():
    geoms = [box(7.96, 9.97, 8.08, 10.03), box(9.95, 11.95, 10.05, 12.05)]
    w = build_weights(geoms, LATS, LONS, VALID)
    grid = np.zeros((1, len(LATS) * len(LONS)), dtype="float32")
    grid[0, _cell(10.0, 8.0)], grid[0, _cell(10.0, 8.1)], grid[0, _cell(12.0, 10.0)] = 4, 8, 7
    np.testing.assert_allclose(w.reduce(grid), [[5.0, 7.0]], atol=1e-5)


# --- weekly table ------------------------------------------------------------

CLIM = ClimatologyConfig(baseline_start_year=2001, baseline_end_year=2001, percentile=90,
                         pooling_window_days=5, min_consecutive_days=3)


def _daily(dates, hi, tmin, precip=None, rh=None, soil=None):
    col = lambda x, fill: np.asarray(x if x is not None else np.full(len(hi), fill), "float32")[:, None]  # noqa: E731
    return WardDaily(pd.DatetimeIndex(dates), ["A"], col(hi, 0), col(tmin, 0),
                     col(precip, 0.0), col(rh, 50.0), col(soil, 0.3))


def test_weekly_table_schema_complete_weeks_and_iso_labels():
    dates = pd.date_range("2001-01-01", "2003-01-01")  # Mon 2001-W01 .. Wed 2003-W01 (partial)
    daily = _daily(dates, np.full(len(dates), 90.0), np.full(len(dates), 295.0))
    t = weekly_table(daily, CLIM)
    assert list(t.columns) == COVARIATE_COLUMNS
    assert t.time_period.iloc[0] == "2001-W01" and t.time_period.iloc[-1] == "2002-W52"
    assert "2003-W01" not in set(t.time_period)  # partial final week dropped
    assert (t.heatwave_days == 0).all() and (t.hot_nights == 0).all()  # flat series: nothing exceeds


def test_weekly_table_counts_hot_days_events_and_nights():
    dates = pd.date_range("2001-01-01", "2002-12-29")  # whole ISO weeks
    rng = np.random.default_rng(0)
    hi = rng.normal(90, 1, len(dates))
    tmin = rng.normal(295, 1, len(dates))
    spike = (dates >= "2002-06-06") & (dates <= "2002-06-12")  # Thu..Wed: spans two ISO weeks
    hi[spike] = 200
    tmin[spike] = 400
    t = weekly_table(_daily(dates, hi, tmin), CLIM).set_index("time_period")
    w1, w2 = "2002-W23", "2002-W24"  # Jun 6-9 are in W23, Jun 10-12 in W24
    assert t.loc[w1, "heatwave_days"] >= 4 and t.loc[w2, "heatwave_days"] >= 3
    assert t.loc[w1, "heatwave_event_count"] == 1  # counted in the week the event starts
    assert t.loc[w2, "heatwave_event_count"] == 0
    assert t.loc[w1, "hot_nights"] >= 4
    assert t.loc[w1, "max_heat_index"] == pytest.approx(200)
    week_vals = hi[(dates >= "2002-06-03") & (dates <= "2002-06-09")]
    assert t.loc[w1, "mean_heat_index"] == pytest.approx(week_vals.mean(), rel=1e-5)


def test_weekly_table_sums_rain_and_averages_humidity_and_soil():
    dates = pd.date_range("2001-01-01", "2001-12-30")  # a full baseline year of whole ISO weeks
    n = len(dates)
    precip = np.r_[np.full(7, 2.0), np.arange(7.0), np.zeros(n - 14)]
    rh = np.r_[np.full(7, 40.0), np.linspace(20, 80, 7), np.full(n - 14, 50.0)]
    soil = np.r_[np.full(7, 0.1), np.full(n - 7, 0.3)]
    clim = ClimatologyConfig(baseline_start_year=2001, baseline_end_year=2001, percentile=90,
                             pooling_window_days=5, min_consecutive_days=3)
    t = weekly_table(_daily(dates, np.full(n, 90.0), np.full(n, 295.0), precip, rh, soil), clim)
    t = t.set_index("time_period")
    assert t.loc["2001-W01", "total_precipitation_mm"] == pytest.approx(14.0)
    assert t.loc["2001-W02", "total_precipitation_mm"] == pytest.approx(21.0)
    assert t.loc["2001-W02", "mean_relative_humidity"] == pytest.approx(50.0, abs=1e-4)
    assert t.loc["2001-W01", "mean_soil_moisture"] == pytest.approx(0.1, abs=1e-6)
