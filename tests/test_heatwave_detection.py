"""Live, skip-gated tests verifying zonal reduction, climatology and heatwave detection
against synthetic time series (CLIM-01 through CLIM-06)."""
from __future__ import annotations

import inspect
import os
from datetime import datetime, timezone
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


def test_climatology_config_accepts_the_real_config_yaml_values():
    """WR-03: config.yaml's actual, valid climatology values (percentile 90,
    baseline 1991-2020, pooling window 5, min_consecutive_days 3) must still
    construct successfully now that __post_init__ validates them -- pure
    Python object construction, no EE/credentials required."""
    from heatwave.config import ClimatologyConfig

    config = ClimatologyConfig(
        baseline_start_year=1991,
        baseline_end_year=2020,
        percentile=90,
        pooling_window_days=5,
        min_consecutive_days=3,
    )
    assert config.percentile == 90


@pytest.mark.parametrize(
    "overrides",
    [
        {"percentile": 150},
        {"percentile": 0},
        {"percentile": 100},
        {"baseline_start_year": 2020, "baseline_end_year": 1991},
        {"pooling_window_days": -5},
        {"min_consecutive_days": 0},
    ],
)
def test_climatology_config_rejects_malformed_values(overrides):
    """WR-03: each of these malformed config.yaml-shaped values (a
    percentile outside (0, 100), baseline_start_year after
    baseline_end_year, a negative pooling_window_days, and a
    min_consecutive_days below 1) must raise ValueError from
    __post_init__ rather than silently loading -- no credentials required,
    this is pure Python dataclass construction."""
    from heatwave.config import ClimatologyConfig

    valid_kwargs = {
        "baseline_start_year": 1991,
        "baseline_end_year": 2020,
        "percentile": 90,
        "pooling_window_days": 5,
        "min_consecutive_days": 3,
    }
    valid_kwargs.update(overrides)

    with pytest.raises(ValueError):
        ClimatologyConfig(**valid_kwargs)


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


@_REQUIRES_CREDENTIALS
def test_zonal_find_small_wards_identifies_subpixel_ward():
    """D-08: find_small_wards(image, wards) surfaces exactly the ward ids
    whose primary area-weighted reduction yields no value for a given image
    -- the one-time detection pass Pitfall 5 requires be run once, not per
    day. W-TINY's 250m buffer sits far below ERA5-Land's ~0.4% pixel-weight
    inclusion threshold; W-A and W-B's 20km buffers sit comfortably above
    it, so only W-TINY should appear."""
    from heatwave.auth import init_ee
    from heatwave.zonal import find_small_wards

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    image = _make_heat_index_collection([("2020-01-01", 0)]).first()

    small_ward_ids = find_small_wards(image, wards).getInfo()

    assert small_ward_ids == ["W-TINY"]


@_REQUIRES_CREDENTIALS
def test_zonal_find_small_wards_requires_consensus_across_samples():
    """WR-05: find_small_wards no longer trusts a single sampled image. A
    normal-sized ward (W-A) that has a real `mean` on two sample images but
    shows a missing `mean` on a THIRD sample -- simulating an incidental
    single-day data anomaly: the whole region is nodata that day, not a
    geometric property of W-A's polygon -- must NOT be misclassified as
    small, because it does not agree across every sample. W-TINY, genuinely
    below the pixel-weight inclusion threshold, is missing `mean` on every
    sample regardless of the image's own data (it is a static geometric
    property), and IS classified as small."""
    from heatwave.auth import init_ee
    from heatwave.zonal import find_small_wards

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])

    good_images = _make_heat_index_collection([
        ("2020-01-01", 0),
        ("2020-06-01", 5),
    ]).toList(2)

    # The third sample's whole heat_index band is nodata everywhere,
    # including over W-A and W-B -- an incidental single-day anomaly, not a
    # genuine geometric property of either ward's polygon.
    anomalous_image = (
        ee.Image.pixelLonLat()
        .select("longitude")
        .rename("heat_index")
        .updateMask(ee.Image.constant(0))
        .set("system:time_start", ee.Date("2020-09-01").millis())
    )

    images = [
        ee.Image(good_images.get(0)),
        ee.Image(good_images.get(1)),
        anomalous_image,
    ]

    small_ward_ids = find_small_wards(images, wards).getInfo()

    assert small_ward_ids == ["W-TINY"]


@_REQUIRES_CREDENTIALS
def test_zonal_find_small_wards_still_accepts_a_single_image():
    """WR-05 backward compatibility: passing a lone ee.Image (not a list)
    must keep behaving as a single-sample check, unchanged from before this
    fix -- callers that have not been updated to sample multiple dates
    still get correct results."""
    from heatwave.auth import init_ee
    from heatwave.zonal import find_small_wards

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    image = _make_heat_index_collection([("2020-01-01", 0)]).first()

    small_ward_ids = find_small_wards(image, wards).getInfo()

    assert small_ward_ids == ["W-TINY"]


@_REQUIRES_CREDENTIALS
def test_zonal_fallback_gives_tiny_ward_a_real_value():
    """D-08: reduce_to_ward_daily(..., fallback_ward_ids=["W-TINY"]) samples
    W-TINY at its centroid instead of area-weighting its (too-small) polygon,
    producing a genuine, non-null, non-zero value -- approximately the
    ward's centroid longitude (5.0) plus the day's zero offset -- rather
    than the null the primary area-weighted path would otherwise emit."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    collection = _make_heat_index_collection([("2020-01-01", 0)])

    result = reduce_to_ward_daily(collection, wards, fallback_ward_ids=["W-TINY"])
    rows = _props(result, ["ward_id", "value", "used_fallback_reducer"])

    tiny_rows = [row for row in rows if row["ward_id"] == "W-TINY"]
    assert len(tiny_rows) == 1
    assert tiny_rows[0]["value"] is not None
    assert tiny_rows[0]["value"] == pytest.approx(5.0, abs=0.2)


@_REQUIRES_CREDENTIALS
def test_zonal_fallback_point_lies_inside_its_own_ward_geometry_even_when_concave():
    """WR-04: build_fallback_ward_centroids must use pointOnSurface(), not
    centroid() -- verified against a donut-shaped ward polygon whose raw
    geometric centroid falls in the hole, entirely outside the polygon.
    First confirms (as a sanity check, not a tautology) that the donut's
    raw centroid really is outside its own geometry, then asserts the
    fallback function's output point IS contained by the ward's original
    geometry."""
    from heatwave.auth import init_ee
    from heatwave.zonal import build_fallback_ward_centroids

    init_ee()

    outer_ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    inner_hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    donut_geometry = ee.Geometry.Polygon([outer_ring, inner_hole])

    raw_centroid_is_inside = donut_geometry.contains(donut_geometry.centroid()).getInfo()
    assert raw_centroid_is_inside is False, (
        "test fixture is not a genuine concave-geometry regression case -- "
        "the donut's own centroid must fall in its hole"
    )

    small_wards = ee.FeatureCollection(
        [ee.Feature(donut_geometry, {"wardcode": "W-DONUT"})]
    )

    fallback = build_fallback_ward_centroids(small_wards)
    fallback_point = ee.Feature(fallback.first()).geometry()

    assert donut_geometry.contains(fallback_point).getInfo() is True


@_REQUIRES_CREDENTIALS
def test_zonal_fallback_flags_provenance_per_row():
    """D-09: every row -- from both the fallback centroid path and the
    unchanged primary area-weighted path -- carries a used_fallback_reducer
    boolean, so a downstream CSV consumer can tell which ward-days came from
    the lower-fidelity sample. Asserted by identity against True/False, not
    truthiness, per this plan's acceptance criteria."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    collection = _make_heat_index_collection([("2020-01-01", 0)])

    result = reduce_to_ward_daily(collection, wards, fallback_ward_ids=["W-TINY"])
    rows = _props(result, ["ward_id", "used_fallback_reducer"])

    by_ward = {row["ward_id"]: row["used_fallback_reducer"] for row in rows}
    assert by_ward["W-TINY"] is True
    assert by_ward["W-A"] is False
    assert by_ward["W-B"] is False


@_REQUIRES_CREDENTIALS
def test_zonal_fallback_preserves_row_count_and_ward_uniqueness():
    """D-08: with 3 wards and 2 days and fallback_ward_ids=["W-TINY"], the
    output size is exactly 6 (N*M) and each (ward_id, doy) pair appears
    exactly once -- a ward in the fallback list is removed from the primary
    reduction via the ee.Filter.Not(inList(...)) complement, never reduced
    twice, so no ward can appear in both partitions for the same day."""
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
        ("2020-01-02", 10),
    ])

    result = reduce_to_ward_daily(collection, wards, fallback_ward_ids=["W-TINY"])
    rows = _props(result, ["ward_id", "doy"])

    assert len(rows) == 6
    pairs = [(row["ward_id"], row["doy"]) for row in rows]
    assert len(pairs) == len(set(pairs))


@_REQUIRES_CREDENTIALS
def test_zonal_fallback_does_not_change_primary_ward_values():
    """D-08: adding fallback_ward_ids=["W-TINY"] must not perturb the wards
    that never needed it -- W-A and W-B's values with the fallback active
    must equal their values with fallback_ward_ids=None (Phase 3 behaviour),
    proving the primary reduceRegions(Reducer.mean()) path is untouched."""
    from heatwave.auth import init_ee
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
        ("W-TINY", 5.0, 7.0, 250),
    ])
    collection = _make_heat_index_collection([("2020-01-01", 0)])

    with_fallback = _props(
        reduce_to_ward_daily(collection, wards, fallback_ward_ids=["W-TINY"]),
        ["ward_id", "value"],
    )
    without_fallback = _props(
        reduce_to_ward_daily(collection, wards, fallback_ward_ids=None),
        ["ward_id", "value"],
    )

    with_by_ward = {row["ward_id"]: row["value"] for row in with_fallback}
    without_by_ward = {row["ward_id"]: row["value"] for row in without_fallback}

    for ward_id in ("W-A", "W-B"):
        assert with_by_ward[ward_id] == pytest.approx(without_by_ward[ward_id], abs=0.01)


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


@_REQUIRES_CREDENTIALS
def test_climatology_and_heatwave_honor_non_default_ward_id_property():
    """WR-02: a non-default `ward_id_property` (e.g. `"wardcode"`, matching
    the real ward asset's property per REWORK-05) passed consistently to
    BOTH `compute_climatology_thresholds` and `flag_heatwave_days` must
    still produce a working join, end to end.

    Before the fix, `compute_climatology_thresholds`'s output always used
    the literal key `"ward_id"` regardless of `ward_id_property`, so
    `flag_heatwave_days`'s join filter (which looks for `"wardcode"` on
    BOTH sides) would never find it on `climatology_fc` -- every row would
    join to nothing. Thanks to CR-01's outer join, that failure mode now
    surfaces as every row having a null threshold/is_hot (not as rows
    vanishing), which is exactly what this test asserts is NOT the case.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    dates = [
        "2000-01-01", "2000-01-02", "2000-01-03", "2000-01-04", "2000-01-05",
        "2000-01-06", "2000-01-07", "2000-01-08", "2000-01-09", "2000-01-10",
    ]
    baseline_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    baseline_features = [
        ee.Feature(
            None,
            {
                "wardcode": "W-A",
                "value": value,
                "doy": ee.Date(date).getRelative("day", "year").add(1),
                "system:time_start": ee.Date(date).millis(),
            },
        )
        for date, value in zip(dates, baseline_values)
    ]
    ward_daily_fc = ee.FeatureCollection(baseline_features)

    thresholds = compute_climatology_thresholds(
        ward_daily_fc,
        percentile=90,
        window_days=5,
        baseline_start_year=2000,
        baseline_end_year=2000,
        ward_id_property="wardcode",
    )

    # The output key itself must be "wardcode", not the hardcoded "ward_id".
    threshold_rows = _props(thresholds.filter(ee.Filter.eq("doy", 6)), ["wardcode", "threshold"])
    assert len(threshold_rows) == 1
    assert threshold_rows[0]["wardcode"] == "W-A"
    assert threshold_rows[0]["threshold"] == pytest.approx(9.5, abs=1e-6)

    detection_feature = ee.Feature(
        None,
        {
            "wardcode": "W-A",
            "value": 50.0,
            "doy": 6,
            "system:time_start": ee.Date("2000-01-06").millis(),
        },
    )
    detection_fc = ee.FeatureCollection([detection_feature])

    flagged = flag_heatwave_days(detection_fc, thresholds, ward_id_property="wardcode")
    flagged_rows = _props(flagged, ["wardcode", "threshold", "is_hot"])

    assert len(flagged_rows) == 1
    assert flagged_rows[0]["threshold"] == pytest.approx(9.5, abs=1e-6)
    assert flagged_rows[0]["is_hot"] == 1


def _make_climatology_fc(rows) -> ee.FeatureCollection:
    """Build a synthetic climatology FeatureCollection from (ward_id, doy, threshold) tuples.

    Reproduces `heatwave/science/climatology.py`'s `compute_climatology_thresholds()`
    output row schema exactly (`ward_id`, `doy`, `threshold`). Climatology rows
    deliberately carry no `system:time_start` -- they are joined on
    (`ward_id`, `doy`) by `heatwave/science/heatwave.py` and are never
    `calendarRange`-filtered, so this helper must not invent one.
    """
    features = [
        ee.Feature(None, {"ward_id": ward_id, "doy": doy, "threshold": threshold})
        for ward_id, doy, threshold in rows
    ]
    return ee.FeatureCollection(features)


# Live-verified input/output of the tag_consecutive_runs() .iterate() state
# machine (03-RESEARCH.md Pattern 6) -- these are EE-computed literals used
# as test oracles, not a Python reimplementation of the run-detection math
# (D-02).
_VERIFIED_FLAG_SEQUENCE = [0, 1, 1, 1, 0, 1, 1, 0, 0, 1, 1, 1, 1, 0]
_VERIFIED_RUN_TAGS = [-1, 1, 1, 1, -1, 2, 2, -1, -1, 3, 3, 3, 3, -1]
# Run 2 (the pair of 1s tagged group id 2, length 2) is demoted to -1 in the
# event view because 2 < min_consecutive_days (3, config.yaml). Runs 1
# (length 3) and 3 (length 4) both qualify and keep their run id as event_id.
_VERIFIED_EVENT_IDS = [-1, 1, 1, 1, -1, -1, -1, -1, -1, 3, 3, 3, 3, -1]


def test_heatwave_module_exports():
    """CLIM-03/CLIM-04: heatwave.science.heatwave exports the three public
    functions, no credentials required."""
    from heatwave.science.heatwave import (
        detect_heatwave_events,
        flag_heatwave_days,
        tag_consecutive_runs,
    )

    assert callable(flag_heatwave_days)
    assert callable(tag_consecutive_runs)
    assert callable(detect_heatwave_events)


@_REQUIRES_CREDENTIALS
def test_heatwave_day_flag_marks_values_above_threshold():
    """CLIM-03: values 10/20/30/40/50 against a threshold of 25.0 for every
    doy yield is_hot 0,0,1,1,1 in date order; every row's threshold reads
    25.0."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 5, dates, values)))
    climatology_fc = _make_climatology_fc([("W-A", doy, 25.0) for doy in range(1, 6)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc).sort("system:time_start")

    assert flagged.aggregate_array("is_hot").getInfo() == [0, 0, 1, 1, 1]
    assert flagged.aggregate_array("threshold").getInfo() == [25.0] * 5


@_REQUIRES_CREDENTIALS
def test_heatwave_day_flag_is_strictly_greater_than():
    """CLIM-03: a value exactly equal to the threshold is not a heatwave day
    -- equality is not exceedance."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    ward_daily_fc = _make_ward_daily_fc([("W-A", "2020-01-01", 25.0)])
    climatology_fc = _make_climatology_fc([("W-A", 1, 25.0)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc)

    assert flagged.aggregate_array("is_hot").getInfo() == [0]


@_REQUIRES_CREDENTIALS
def test_heatwave_day_flag_uses_the_matching_calendar_day_threshold():
    """CLIM-03: a constant value of 50.0 against thresholds 5.0/100.0/5.0 for
    doy 1/2/3 yields is_hot 1,0,1 -- proving the join keys on (ward_id, doy)
    rather than applying one ward-wide threshold."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 3, dates, [50.0, 50.0, 50.0])))
    climatology_fc = _make_climatology_fc([("W-A", 1, 5.0), ("W-A", 2, 100.0), ("W-A", 3, 5.0)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc).sort("system:time_start")

    assert flagged.aggregate_array("is_hot").getInfo() == [1, 0, 1]


@_REQUIRES_CREDENTIALS
def test_heatwave_day_flag_keeps_unmatched_ward_day_with_null_threshold():
    """CR-01: a ward-day whose (ward_id, doy) has no matching climatology
    threshold row must still appear in the output -- with `threshold` and
    `is_hot` both null -- rather than being silently dropped by an inner
    join. doy 2 has no climatology row here; the row count must stay 3 (not
    drop to 2), and only doy 2's threshold/is_hot must be null."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 3, dates, [50.0, 50.0, 50.0])))
    # Deliberately omit doy 2's climatology row -- this is the coverage gap
    # (baseline data gap / newly-added ward) CR-01 describes.
    climatology_fc = _make_climatology_fc([("W-A", 1, 5.0), ("W-A", 3, 5.0)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc).sort("system:time_start")
    rows = _props(flagged, ["doy", "threshold", "is_hot"])

    assert len(rows) == 3
    by_doy = {row["doy"]: row for row in rows}
    assert by_doy[1]["threshold"] == 5.0
    assert by_doy[1]["is_hot"] == 1
    assert by_doy[2]["threshold"] is None
    assert by_doy[2]["is_hot"] is None
    assert by_doy[3]["threshold"] == 5.0
    assert by_doy[3]["is_hot"] == 1


@_REQUIRES_CREDENTIALS
def test_heatwave_event_tag_consecutive_runs_matches_verified_sequence():
    """CLIM-04: tag_consecutive_runs reproduces the exact live-verified
    sequence from 03-RESEARCH.md Pattern 6."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import tag_consecutive_runs

    init_ee()
    result = tag_consecutive_runs(ee.List(_VERIFIED_FLAG_SEQUENCE)).getInfo()

    assert result == _VERIFIED_RUN_TAGS


@_REQUIRES_CREDENTIALS
def test_heatwave_event_requires_min_consecutive_days():
    """CLIM-04: the 14-day fixture derived from _VERIFIED_FLAG_SEQUENCE demotes
    the 2-day run to -1 while the 3-day and 4-day runs each keep one event id;
    exactly 2 distinct non-(-1) event ids result."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days

    init_ee()
    dates = [f"2020-01-{day:02d}" for day in range(1, 15)]
    values = [50.0 if flag else 10.0 for flag in _VERIFIED_FLAG_SEQUENCE]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 14, dates, values)))
    climatology_fc = _make_climatology_fc([("W-A", doy, 25.0) for doy in range(1, 15)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc)
    events = detect_heatwave_events(flagged, min_consecutive_days=3).sort("system:time_start")

    run_ids = events.aggregate_array("run_id").getInfo()
    event_ids = events.aggregate_array("event_id").getInfo()

    assert run_ids == _VERIFIED_RUN_TAGS
    assert event_ids == _VERIFIED_EVENT_IDS
    assert len({event_id for event_id in event_ids if event_id != -1}) == 2


@_REQUIRES_CREDENTIALS
def test_heatwave_event_min_consecutive_days_zero_is_not_overridden_by_config():
    """WR-01: an explicit `min_consecutive_days=0` must be respected as-is,
    not silently replaced by config.yaml's default of 3 (a Python `or`
    truthiness bug would swallow 0). With threshold 0 every run -- including
    run 2, the 2-day run that config.yaml's default of 3 demotes to -1 --
    qualifies, so `event_id` must equal `run_id` exactly on this fixture."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days

    init_ee()
    dates = [f"2020-01-{day:02d}" for day in range(1, 15)]
    values = [50.0 if flag else 10.0 for flag in _VERIFIED_FLAG_SEQUENCE]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 14, dates, values)))
    climatology_fc = _make_climatology_fc([("W-A", doy, 25.0) for doy in range(1, 15)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc)
    events = detect_heatwave_events(flagged, min_consecutive_days=0).sort("system:time_start")

    run_ids = events.aggregate_array("run_id").getInfo()
    event_ids = events.aggregate_array("event_id").getInfo()

    assert run_ids == _VERIFIED_RUN_TAGS
    assert event_ids == _VERIFIED_RUN_TAGS
    assert len({event_id for event_id in event_ids if event_id != -1}) == 3


@_REQUIRES_CREDENTIALS
def test_heatwave_event_detection_is_scoped_per_ward():
    """CLIM-04 / D-04: a 2-day run for W-A and a 3-day run for W-B, interleaved
    in one collection, stay two separate, correctly classified runs. A
    cross-ward bleed would merge these five hot days into one qualifying
    5-day event, which is exactly the failure mode this test guards against."""
    from heatwave.auth import init_ee
    from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days

    init_ee()
    dates = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]
    wa_flags = [1, 1, 0, 0, 0]
    wb_flags = [0, 0, 1, 1, 1]
    wa_values = [50.0 if flag else 10.0 for flag in wa_flags]
    wb_values = [50.0 if flag else 10.0 for flag in wb_flags]
    rows = list(zip(["W-A"] * 5, dates, wa_values)) + list(zip(["W-B"] * 5, dates, wb_values))
    ward_daily_fc = _make_ward_daily_fc(rows)
    climatology_fc = _make_climatology_fc(
        [("W-A", doy, 25.0) for doy in range(1, 6)]
        + [("W-B", doy, 25.0) for doy in range(1, 6)]
    )

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc)
    events = detect_heatwave_events(flagged, min_consecutive_days=3)

    wa_events = events.filter(ee.Filter.eq("ward_id", "W-A")).sort("system:time_start")
    wb_events = events.filter(ee.Filter.eq("ward_id", "W-B")).sort("system:time_start")

    wa_event_ids = wa_events.aggregate_array("event_id").getInfo()
    wb_event_ids = wb_events.aggregate_array("event_id").getInfo()

    assert wa_event_ids == [-1, -1, -1, -1, -1]
    non_negative_wb_event_ids = [event_id for event_id in wb_event_ids if event_id != -1]
    assert len(set(non_negative_wb_event_ids)) == 1
    assert len(non_negative_wb_event_ids) == 3


def _make_constant_heat_index_collection(date_values) -> ee.ImageCollection:
    """Build a synthetic Heat Index ImageCollection from (date_string, value) pairs.

    Each image is spatially CONSTANT (`ee.Image.constant(value)`), unlike plan
    03-01's `_make_heat_index_collection`, whose `heat_index` band is
    longitude-valued so spatially separated synthetic wards reduce to
    different, hand-predictable values. A constant image makes every ward's
    zonal mean exactly the stated value regardless of the ward's location --
    that is what makes the entire four-stage chain (zonal reduction ->
    climatology -> flagging -> event detection) hand-computable end to end in
    one test. Ward discrimination (proving `reduce_to_ward_daily` assigns
    each ward its own, distinct value) is already covered by plan 03-01's
    CLIM-05 tests and is not this test's job.
    """
    images = [
        ee.Image.constant(value)
        .rename("heat_index")
        .set("system:time_start", ee.Date(date_string).millis())
        for date_string, value in date_values
    ]
    return ee.ImageCollection(images)


@_REQUIRES_CREDENTIALS
def test_end_to_end_climatology_and_event_pipeline():
    """CLIM-01 through CLIM-06 composed: reduce_to_ward_daily ->
    compute_climatology_thresholds -> flag_heatwave_days ->
    detect_heatwave_events run as one chain, the exact order and default
    parameter shape Phase 4's scripts/run_batch_export.py will call them in.

    Fixture rationale (why this test can assert exact numbers at all): the
    baseline (2001-01-01..2001-01-10 and 2002-01-01..2002-01-10) is
    deliberately a CONSTANT 20.0, so the pooled 90th percentile for every
    baseline calendar day is exactly 20.0 under any interpolation rule --
    the percentile of a constant sample is that constant regardless of which
    undocumented small-N rule EE applies. That sidesteps 03-RESEARCH.md
    Pitfall 3 entirely: a failure here means a composition/wiring bug, never
    a percentile-interpolation surprise. The per-stage percentile behaviour
    itself (EE's 9.5-vs-numpy's-9.1 interpolation) is already pinned by plan
    03-02's test_climatology_threshold_matches_live_verified_ee_percentile.
    Wards W-A and W-B are 20 km buffers (well above 03-RESEARCH.md Pitfall
    4's ~354m x 354m sub-pixel-weight inclusion threshold), so Pitfall 4
    cannot interfere with this test's null-freedom.

    Two independent wards (W-A at lon 3.0, W-B at lon 8.0) are asserted
    identically: matching results across two independent wards is what
    proves the per-ward partitioning holds under composition, not just
    under a single ward's coincidental correctness.
    """
    from heatwave.auth import init_ee
    from heatwave.science.climatology import compute_climatology_thresholds
    from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    wards = _make_ward_fc([
        ("W-A", 3.0, 7.0, 20000),
        ("W-B", 8.0, 7.0, 20000),
    ])

    baseline_2001 = [(f"2001-01-{day:02d}", 20.0) for day in range(1, 11)]
    baseline_2002 = [(f"2002-01-{day:02d}", 20.0) for day in range(1, 11)]
    detection_values = [15.0, 15.0, 25.0, 25.0, 25.0, 15.0, 25.0, 25.0, 15.0, 15.0]
    detection_2003 = [
        (f"2003-01-{day:02d}", value) for day, value in zip(range(1, 11), detection_values)
    ]
    collection = _make_constant_heat_index_collection(
        baseline_2001 + baseline_2002 + detection_2003
    )

    # Stage 1 (CLIM-05): the one zonal reduction Phase 4's pipeline performs.
    # Both the baseline and detection views below are filtered from THIS
    # single table -- no second zonal reduction is built for the detection
    # years, matching 03-RESEARCH.md's diagrammed architecture.
    #
    # Runtime fallback applied (03-VALIDATION.md's 30s budget): an initial
    # single-computation-graph version of this test (zonal reduction feeding
    # climatology feeding flagging feeding event detection, all lazily
    # re-evaluated on every downstream .getInfo() call) measured 65.81s with
    # `--durations=5` -- over budget. Per this task's documented fallback,
    # the zonal output is materialised ONCE here with `.getInfo()`, the
    # 60-row CLIM-05 expectation is asserted on that live payload directly,
    # and an equivalent table is rebuilt from those live-computed values with
    # the existing `_make_ward_daily_fc` helper before feeding the remaining
    # three stages -- breaking one large lazy graph into two smaller ones.
    # Re-measured with the fallback applied: 16.09s with `--durations=5`,
    # inside the 30s budget. Everything below remains live Earth Engine
    # either way (D-01); no value is computed by client-side Python
    # arithmetic (D-02) -- only date strings are reformatted from the
    # already-live-computed `system:time_start` millis.
    ward_daily_fc = reduce_to_ward_daily(collection, wards)
    ward_daily_features = ward_daily_fc.getInfo()["features"]
    assert len(ward_daily_features) == 60  # 2 wards x 30 days

    def _millis_to_date_string(millis: int) -> str:
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    ward_daily_rows = [
        (
            feature["properties"]["ward_id"],
            _millis_to_date_string(feature["properties"]["system:time_start"]),
            feature["properties"]["value"],
        )
        for feature in ward_daily_features
    ]
    ward_daily_fc = _make_ward_daily_fc(ward_daily_rows)

    # Stage 2 (CLIM-01/CLIM-02): pooled 90th-percentile baseline threshold.
    climatology_fc = compute_climatology_thresholds(
        ward_daily_fc,
        percentile=90,
        window_days=5,
        baseline_start_year=2001,
        baseline_end_year=2002,
    )
    doy5 = climatology_fc.filter(ee.Filter.eq("doy", 5))
    doy5_rows = {row["ward_id"]: row["threshold"] for row in _props(doy5, ["ward_id", "threshold"])}
    assert doy5_rows["W-A"] == pytest.approx(20.0, abs=1e-6)
    assert doy5_rows["W-B"] == pytest.approx(20.0, abs=1e-6)

    # Detection view: filter the SAME ward-daily table into the 2003 window.
    detection_fc = ward_daily_fc.filter(ee.Filter.calendarRange(2003, 2003, "year"))
    assert detection_fc.size().getInfo() == 20  # 2 wards x 10 days

    # Stage 3 (CLIM-03): threshold join + exceedance flagging.
    flagged_fc = flag_heatwave_days(detection_fc, climatology_fc)

    expected_is_hot = [0, 0, 1, 1, 1, 0, 1, 1, 0, 0]
    for ward in ("W-A", "W-B"):
        ward_flagged = flagged_fc.filter(ee.Filter.eq("ward_id", ward)).sort("system:time_start")
        assert ward_flagged.aggregate_array("is_hot").getInfo() == expected_is_hot
        assert ward_flagged.aggregate_sum("is_hot").getInfo() == 5

    # Stage 4 (CLIM-04): consecutive-run event detection.
    events_fc = detect_heatwave_events(flagged_fc, min_consecutive_days=3)

    expected_run_id = [-1, -1, 1, 1, 1, -1, 2, 2, -1, -1]
    expected_event_id = [-1, -1, 1, 1, 1, -1, -1, -1, -1, -1]
    for ward in ("W-A", "W-B"):
        ward_events = events_fc.filter(ee.Filter.eq("ward_id", ward)).sort("system:time_start")
        assert ward_events.aggregate_array("run_id").getInfo() == expected_run_id
        event_ids = ward_events.aggregate_array("event_id").getInfo()
        assert event_ids == expected_event_id
        # Aggregate shape Phase 4 actually reads from this pipeline: the CHAP
        # covariate table's heatwave_event_count is the count of distinct
        # non-(-1) event ids, not the count of hot days in qualifying runs.
        assert len({event_id for event_id in event_ids if event_id != -1}) == 1


@_REQUIRES_CREDENTIALS
def test_heatwave_event_min_days_defaults_from_settings():
    """CLIM-04 / security V5: min_consecutive_days defaults to None in the
    signature and resolves from settings.climatology.min_consecutive_days --
    calling without the argument reproduces the explicit min_consecutive_days=3
    result on the same 14-day fixture."""
    from heatwave.science.heatwave import detect_heatwave_events

    sig = inspect.signature(detect_heatwave_events)
    assert sig.parameters["min_consecutive_days"].default is None

    from heatwave.auth import init_ee
    from heatwave.science.heatwave import flag_heatwave_days

    init_ee()
    dates = [f"2020-01-{day:02d}" for day in range(1, 15)]
    values = [50.0 if flag else 10.0 for flag in _VERIFIED_FLAG_SEQUENCE]
    ward_daily_fc = _make_ward_daily_fc(list(zip(["W-A"] * 14, dates, values)))
    climatology_fc = _make_climatology_fc([("W-A", doy, 25.0) for doy in range(1, 15)])

    flagged = flag_heatwave_days(ward_daily_fc, climatology_fc)
    events = detect_heatwave_events(flagged).sort("system:time_start")

    assert events.aggregate_array("event_id").getInfo() == _VERIFIED_EVENT_IDS


@_REQUIRES_CREDENTIALS
def test_real_era5_land_zonal_reduction_smoke():
    """CLIM-05 / D-03: heatwave/zonal.py against the real ERA5-Land collection
    and the real nationwide ward asset, not only synthetic constructions.

    Scope deliberately stays small (D-03): the three largest real ward
    polygons, five real ERA5-Land days (2020-06-01 through 2020-06-05
    inclusive, via a 2020-06-06 exclusive `ee.Filter.date` end). Full-scale
    execution across the full nationwide ward asset or the 1991-2020
    baseline is Phase 4's scripts/run_batch_export.py (EXPORT-01) and must
    not be attempted here.

    Ward selection is sorted by polygon area, largest first, rather than a
    bare `.limit(3)` on the unsorted asset -- feature order on the real asset
    is arbitrary and could otherwise land on a ward below Earth Engine's
    ~0.4%-pixel-weight inclusion threshold (03-RESEARCH.md Pitfall 4, a
    roughly 354m x 354m square), turning a real regression signal into a
    flaky null. Whether any real Nigerian ward is actually that small is
    explicitly Phase 4's question (03-RESEARCH.md Open Question 2), not
    something this test should discover by accident.
    """
    from heatwave.auth import init_ee
    from heatwave.data.boundary import load_ward_boundary
    from heatwave.data.ingest import load_era5_land
    from heatwave.science.heat_index import compute_heat_index, compute_relative_humidity
    from heatwave.zonal import reduce_to_ward_daily

    init_ee()
    all_wards = load_ward_boundary()
    # Measured runtime (`.venv/Scripts/python -m pytest
    # tests/test_heatwave_detection.py -k real_era5 --durations=5`): ~43s,
    # over 03-VALIDATION.md's 30s aspirational per-test budget. Unlike plan
    # 03-04's Task 1, no two-graph fallback applies here: the cost is the
    # mandated area-sort over the full real nationwide ward asset itself (the
    # Pitfall-4-proof largest-ward selection this task requires), not a
    # re-evaluated lazy graph, so splitting computation would not help.
    # D-03 accepts this cost as a bounded, one-time real-data check.
    largest_wards = (
        all_wards.map(lambda feature: feature.set("area_m2", feature.geometry().area(maxError=1000)))
        .sort("area_m2", False)
        .limit(3)
    )

    # load_era5_land uses ee.Filter.date, whose end is exclusive (REWORK-06),
    # so 2020-06-06 yields exactly 2020-06-01 through 2020-06-05.
    hi_collection = (
        load_era5_land(boundary=largest_wards, start_date="2020-06-01", end_date="2020-06-06")
        .map(compute_relative_humidity)
        .map(compute_heat_index)
    )

    # compute_relative_humidity is mapped before compute_heat_index because
    # the latter selects the relative_humidity band the former adds.
    result = reduce_to_ward_daily(hi_collection, largest_wards)

    # Materialise once: every assertion below derives from this one live
    # payload so the 30s latency budget is not spent on repeated real-data
    # recomputation.
    info = result.getInfo()
    rows = [feature["properties"] for feature in info["features"]]

    assert len(rows) == 15  # 3 wards x 5 days

    values = [row["value"] for row in rows]
    assert all(value is not None for value in values)
    assert all(50 <= value <= 200 for value in values)

    assert {row["doy"] for row in rows} == {153, 154, 155, 156, 157}

    ward_ids = [row["ward_id"] for row in rows]
    assert all(ward_id is not None for ward_id in ward_ids)
    assert len(set(ward_ids)) == 3

    # Pitfall 1 timestamp guard, re-verified against real ERA5-Land
    # timestamps rather than synthetic ones -- a cheap, load-bearing second
    # live call.
    filtered = result.filter(ee.Filter.calendarRange(2020, 2020, "year"))
    assert filtered.size().getInfo() == 15
