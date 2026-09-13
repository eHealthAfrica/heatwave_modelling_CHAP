"""Live, skip-gated tests verifying zonal reduction, climatology and heatwave detection
against synthetic time series (CLIM-01 through CLIM-06)."""
from __future__ import annotations

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
