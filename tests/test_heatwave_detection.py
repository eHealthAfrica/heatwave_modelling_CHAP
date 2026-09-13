"""Live, skip-gated tests verifying zonal reduction, climatology and heatwave detection
against synthetic time series (CLIM-01 through CLIM-06)."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

# NOTE: This gate is intentionally applied per-test (via `_REQUIRES_CREDENTIALS`) rather
# than as a module-level `pytestmark`. A module-level `pytestmark` would also skip
# `test_zonal_module_exports`, which 03-VALIDATION.md requires to be runnable without
# live GCP credentials (`pytest tests/test_heatwave_detection.py -k export`). Do not
# "restore" the module-level form.
_REQUIRES_CREDENTIALS = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)


def _make_ward_fc(specs) -> ee.FeatureCollection:
    """Build a synthetic ward FeatureCollection from (ward_id, lon, lat, buffer_m) tuples.

    Property key is `"wardcode"` — matches `reduce_to_ward_daily`'s default
    `ward_id_property` and the real ward asset's verified property set (REWORK-05).
    """
    features = [
        ee.Feature(ee.Geometry.Point([lon, lat]).buffer(buffer_m), {"wardcode": ward_id})
        for ward_id, lon, lat, buffer_m in specs
    ]
    return ee.FeatureCollection(features)


def _make_heat_index_collection(date_offsets) -> ee.ImageCollection:
    """Build a synthetic Heat Index ImageCollection from (date_string, offset) pairs.

    Each image's `heat_index` band is longitude-valued (`ee.Image.pixelLonLat()`'s
    `longitude` band plus `offset`) so spatially separated wards reduce to different,
    hand-predictable values — a constant image cannot distinguish wards at all.
    """
    images = [
        ee.Image.pixelLonLat()
        .select("longitude")
        .add(offset)
        .rename("heat_index")
        .set("system:time_start", ee.Date(date_string).millis())
        for date_string, offset in date_offsets
    ]
    return ee.ImageCollection(images)


def _props(fc: ee.FeatureCollection, keys):
    """Materialise a FeatureCollection's properties via a single `.getInfo()` call.

    Returns a plain Python list of dicts, one per feature, containing only the
    requested property keys. An absent property surfaces as `None` rather than
    raising, via `.get(key)`.
    """
    info = fc.getInfo()
    return [
        {key: feature["properties"].get(key) for key in keys}
        for feature in info["features"]
    ]


def test_zonal_module_exports():
    """CLIM-05: heatwave.zonal exports reduce_to_ward_daily, no credentials required."""
    from heatwave.zonal import reduce_to_ward_daily

    assert callable(reduce_to_ward_daily)


@_REQUIRES_CREDENTIALS
def test_zonal_reduction_produces_one_row_per_ward_per_day():
    """CLIM-05: 2 wards x 3 days -> exactly 6 rows, correct ward_id/doy sets."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
    ])
    collection = _make_heat_index_collection([
        ("2020-01-01", 0),
        ("2020-01-02", 10),
        ("2020-01-03", 20),
    ])

    result = reduce_to_ward_daily(collection, wards)
    rows = _props(result, ["ward_id", "doy"])

    assert len(rows) == 6
    assert {row["ward_id"] for row in rows} == {"W-A", "W-B"}
    assert {row["doy"] for row in rows} == {1, 2, 3}


@_REQUIRES_CREDENTIALS
def test_zonal_reduction_assigns_each_ward_its_own_value():
    """CLIM-05: each ward's row carries its own spatially-reduced value, not a shared one."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
    ])
    collection = _make_heat_index_collection([
        ("2020-01-01", 0),
        ("2020-01-02", 10),
        ("2020-01-03", 20),
    ])

    result = reduce_to_ward_daily(collection, wards)
    rows = _props(result, ["ward_id", "doy", "value"])

    offset_by_doy = {1: 0, 2: 10, 3: 20}
    for row in rows:
        expected_lon = 3.0 if row["ward_id"] == "W-A" else 8.0
        expected = expected_lon + offset_by_doy[row["doy"]]
        assert row["value"] == pytest.approx(expected, abs=0.2)


@_REQUIRES_CREDENTIALS
def test_zonal_output_supports_calendarrange_filter():
    """CLIM-05 / Pitfall 1: calendarRange filter works without a timestamp error."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
    ])
    collection = _make_heat_index_collection([
        ("2020-01-01", 0),
        ("2020-01-02", 10),
        ("2020-01-03", 20),
    ])

    result = reduce_to_ward_daily(collection, wards)
    filtered = result.filter(ee.Filter.calendarRange(2, 2, "day_of_year"))

    assert filtered.size().getInfo() == 2


@_REQUIRES_CREDENTIALS
def test_zonal_reduction_tiny_ward_row_is_null_not_dropped():
    """CLIM-05 / Pitfall 4: a sub-pixel-weight ward still produces a row, value is None."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    collection = _make_heat_index_collection([
        ("2020-01-01", 0),
    ])

    result = reduce_to_ward_daily(collection, wards)
    rows = _props(result, ["ward_id", "doy", "value"])

    tiny_rows = [row for row in rows if row["ward_id"] == "W-TINY"]
    assert len(tiny_rows) == 1
    assert tiny_rows[0]["doy"] == 1
    assert tiny_rows[0]["value"] is None


def _make_ward_daily_fc(rows) -> ee.FeatureCollection:
    """Build a synthetic per-ward-daily FeatureCollection from (ward_id, date_string, value) tuples.

    Reproduces exactly the row schema `heatwave/zonal.py`'s `reduce_to_ward_daily`
    emits (`ward_id`, `value`, `doy`, `system:time_start`), so climatology tests
    exercise the real downstream contract without paying for a zonal reduction.
    `doy` is computed server-side from the date string, the same way
    `heatwave/zonal.py` computes it (`ee.Date(...).getRelative("day", "year").add(1)`),
    which guarantees this helper agrees with zonal.py's convention by construction
    rather than by a hand-copied duplicate rule. `system:time_start` is mandatory:
    every `calendarRange` filter under test (baseline-year filter, pooling window)
    reads day-of-year and year from it, not from the `doy` property
    (03-RESEARCH.md Pitfall 1).
    """
    features = []
    for ward_id, date_string, value in rows:
        date = ee.Date(date_string)
        doy = date.getRelative("day", "year").add(1)
        features.append(
            ee.Feature(
                None,
                {
                    "ward_id": ward_id,
                    "value": value,
                    "doy": doy,
                    "system:time_start": date.millis(),
                },
            )
        )
    return ee.FeatureCollection(features)


def test_climatology_module_exports():
    """CLIM-01: heatwave.science.climatology exports the four public functions, no credentials required."""
    from heatwave.science.climatology import (
        compute_climatology_thresholds,
        floor_mod,
        pooling_window_filter,
        wrapped_day,
    )

    assert callable(floor_mod)
    assert callable(wrapped_day)
    assert callable(pooling_window_filter)
    assert callable(compute_climatology_thresholds)


@_REQUIRES_CREDENTIALS
def test_pooling_window_floor_mod_handles_negatives():
    """D-06 / Pitfall 2: floor_mod/wrapped_day floor negative inputs instead of
    returning raw ee.Number.mod()'s truncated (sign-follows-dividend) result.

    Raw `ee.Number(-3).mod(366)` returns -3, not 363 -- verified live in
    03-RESEARCH.md Pitfall 2. Feeding -3 into ee.Filter.calendarRange raises
    'Start and end date values must be >= 0'. These are the negative cases
    that matter for D-06's bidirectional wraparound.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import floor_mod, wrapped_day

    init_ee()

    assert floor_mod(-3, 366).getInfo() == 363
    assert floor_mod(-1, 366).getInfo() == 365
    assert floor_mod(370, 366).getInfo() == 4

    assert wrapped_day(-3).getInfo() == 363
    assert wrapped_day(0).getInfo() == 366
    assert wrapped_day(1).getInfo() == 1
    assert wrapped_day(367).getInfo() == 1
    assert wrapped_day(730).getInfo() == 364
    assert wrapped_day(366).getInfo() == 366


@_REQUIRES_CREDENTIALS
def test_pooling_window_wraps_across_new_year():
    """CLIM-02 / D-06: the ±5-day window for doy=3 wraps back into late December.

    Fixture: 2019-12-27..2019-12-31 (doy 361-365, 2019 is not a leap year) plus
    2020-01-01..2020-01-10 (doy 1-10). window = doy 364 through doy 8 (wrapping),
    which should match 2019-12-30, 2019-12-31, and 2020-01-01 through 2020-01-08
    -- exactly 10 rows. Values are irrelevant to this test; only row counts
    matter, so every row uses a constant value of 1.0.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import pooling_window_filter

    init_ee()
    dates = [
        "2019-12-27", "2019-12-28", "2019-12-29", "2019-12-30", "2019-12-31",
        "2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05",
        "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
    ]
    fc = _make_ward_daily_fc([("W-A", d, 1.0) for d in dates])

    filtered = fc.filter(pooling_window_filter(3, 5))

    assert filtered.size().getInfo() == 10


@_REQUIRES_CREDENTIALS
def test_pooling_window_wraps_at_day_366():
    """CLIM-02 / D-05 / D-06: the ±5-day window for doy=366 wraps forward into early January.

    Same fixture as the new-year wraparound test. window = doy 361 through
    doy 5 (wrapping), which should match all five December rows (361-365) and
    2020-01-01 through 2020-01-05 -- exactly 10 rows.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import pooling_window_filter

    init_ee()
    dates = [
        "2019-12-27", "2019-12-28", "2019-12-29", "2019-12-30", "2019-12-31",
        "2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05",
        "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10",
    ]
    fc = _make_ward_daily_fc([("W-A", d, 1.0) for d in dates])

    filtered = fc.filter(pooling_window_filter(366, 5))

    assert filtered.size().getInfo() == 10


@_REQUIRES_CREDENTIALS
def test_climatology_threshold_matches_live_verified_ee_percentile():
    """CLIM-01 / D-02: p90 of [1..10] pooled around doy 6 is EE's own live-computed 9.5.

    03-RESEARCH.md Pitfall 3 verified this live: ee.Reducer.percentile([90]) on
    the sample 1..10 returns 9.5, while numpy.percentile's default 'linear'
    method returns 9.1. 9.1 would be the WRONG oracle here -- asserting it
    would mean the test measures numpy's math, not the EE engine actually
    used in production (D-02). No parallel Python percentile implementation
    exists in this test file or in production code.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds

    init_ee()
    dates = [
        "2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05",
        "2000-01-06", "2000-01-07", "2000-01-08", "2000-01-09", "2000-01-10",
    ]
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    fc = _make_ward_daily_fc(list(zip(["W-A"] * 10, dates, values)))

    thresholds = compute_climatology_thresholds(
        fc, percentile=90, window_days=5, baseline_start_year=2000, baseline_end_year=2000
    )
    row = thresholds.filter(
        ee.Filter.And(ee.Filter.eq("doy", 6), ee.Filter.eq("ward_id", "W-A"))
    )
    rows = _props(row, ["ward_id", "doy", "threshold"])

    assert len(rows) == 1
    assert rows[0]["threshold"] == pytest.approx(9.5, abs=1e-6)


@_REQUIRES_CREDENTIALS
def test_climatology_baseline_year_filter_excludes_outside_years():
    """CLIM-01: a 999.0 outlier in 1999 or 2021 cannot move a 2000-2000 baseline threshold.

    Both outlier dates (1999-01-05, 2021-01-05) fall inside doy 6's ±5-day
    pooling window, so the baseline-year filter -- not the pooling window --
    is what must exclude them.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds

    init_ee()
    dates = [
        "2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05",
        "2000-01-06", "2000-01-07", "2000-01-08", "2000-01-09", "2000-01-10",
    ]
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    rows = list(zip(["W-A"] * 10, dates, values))
    rows.append(("W-A", "1999-01-05", 999.0))
    rows.append(("W-A", "2021-01-05", 999.0))
    fc = _make_ward_daily_fc(rows)

    thresholds = compute_climatology_thresholds(
        fc, percentile=90, window_days=5, baseline_start_year=2000, baseline_end_year=2000
    )
    row = thresholds.filter(
        ee.Filter.And(ee.Filter.eq("doy", 6), ee.Filter.eq("ward_id", "W-A"))
    )
    result_rows = _props(row, ["ward_id", "doy", "threshold"])

    assert len(result_rows) == 1
    assert result_rows[0]["threshold"] == pytest.approx(9.5, abs=1e-6)


@_REQUIRES_CREDENTIALS
def test_climatology_thresholds_are_computed_per_ward():
    """CLIM-01 / D-04: a single call separates two wards' thresholds via the grouped reducer.

    W-A (1.0..10.0) and W-B (101.0..110.0) over the same ten dates should
    produce two independent doy-6 rows: W-A -> 9.5, W-B -> 109.5 (percentile
    is shift-equivariant, so the same EE rule that gives [1..10] p90=9.5 gives
    [101..110] p90=109.5). Proves the grouped reducer separates wards rather
    than pooling all rows together.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds

    init_ee()
    dates = [
        "2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05",
        "2000-01-06", "2000-01-07", "2000-01-08", "2000-01-09", "2000-01-10",
    ]
    rows = list(zip(["W-A"] * 10, dates, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]))
    rows += list(zip(["W-B"] * 10, dates, [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0]))
    fc = _make_ward_daily_fc(rows)

    thresholds = compute_climatology_thresholds(
        fc, percentile=90, window_days=5, baseline_start_year=2000, baseline_end_year=2000
    )
    doy6 = thresholds.filter(ee.Filter.eq("doy", 6))
    result_rows = {row["ward_id"]: row["threshold"] for row in _props(doy6, ["ward_id", "threshold"])}

    assert result_rows["W-A"] == pytest.approx(9.5, abs=1e-6)
    assert result_rows["W-B"] == pytest.approx(109.5, abs=1e-6)


@_REQUIRES_CREDENTIALS
def test_climatology_feb29_is_its_own_calendar_day_slot():
    """CLIM-01 / D-05: Feb 29 (doy 60) gets its own threshold, never merged with Feb 28 (doy 59).

    Live-verified day-of-year values (03-RESEARCH.md Pattern 2):
    ee.Date('2020-02-29').getRelative('day','year') == 59 -> doy 60,
    ee.Date('2020-02-28').getRelative('day','year') == 58 -> doy 59.
    With window_days=0 (no pooling), a collection holding 2020-02-28 value 1.0
    and 2020-02-29 value 99.0 (baseline 2020-2020) must yield doy 59 -> 1.0
    and doy 60 -> 99.0.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds

    init_ee()
    assert ee.Date("2020-02-29").getRelative("day", "year").add(1).getInfo() == 60
    assert ee.Date("2020-02-28").getRelative("day", "year").add(1).getInfo() == 59

    fc = _make_ward_daily_fc([
        ("W-A", "2020-02-28", 1.0),
        ("W-A", "2020-02-29", 99.0),
    ])

    thresholds = compute_climatology_thresholds(
        fc, percentile=90, window_days=0, baseline_start_year=2020, baseline_end_year=2020
    )
    result_rows = {
        row["doy"]: row["threshold"]
        for row in _props(thresholds.filter(ee.Filter.eq("ward_id", "W-A")), ["doy", "threshold"])
    }

    assert result_rows[59] == pytest.approx(1.0, abs=1e-6)
    assert result_rows[60] == pytest.approx(99.0, abs=1e-6)


@_REQUIRES_CREDENTIALS
def test_climatology_defaults_read_from_settings():
    """CLIM-01 / CLIM-02 / security V5: all four tuning parameters default to None
    and resolve from heatwave.config.settings.climatology.

    Calling compute_climatology_thresholds with only ward_daily_fc must produce
    the same 9.5 threshold for doy 6 as the explicit-args test above -- true
    only if the None defaults resolved to percentile 90, window 5, and a
    baseline range containing year 2000 (settings.climatology's configured
    1991-2020 baseline).
    """
    from heatwave.science.climatology import compute_climatology_thresholds

    sig = inspect.signature(compute_climatology_thresholds)
    assert sig.parameters["percentile"].default is None
    assert sig.parameters["window_days"].default is None
    assert sig.parameters["baseline_start_year"].default is None
    assert sig.parameters["baseline_end_year"].default is None

    from heatwave.auth import init_ee

    init_ee()
    dates = [
        "2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05",
        "2000-01-06", "2000-01-07", "2000-01-08", "2000-01-09", "2000-01-10",
    ]
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    fc = _make_ward_daily_fc(list(zip(["W-A"] * 10, dates, values)))

    thresholds = compute_climatology_thresholds(fc)
    row = thresholds.filter(
        ee.Filter.And(ee.Filter.eq("doy", 6), ee.Filter.eq("ward_id", "W-A"))
    )
    result_rows = _props(row, ["ward_id", "doy", "threshold"])

    assert len(result_rows) == 1
    assert result_rows[0]["threshold"] == pytest.approx(9.5, abs=1e-6)
