"""Zonal reduction: gridded ERA5-Land Heat Index pixels -> per-ward-daily rows.

Reduces a gridded ee.ImageCollection (one Heat Index band per image, one image
per day) against a ward ee.FeatureCollection via ee.Image.reduceRegions,
producing a long-format table with one row per (ward, day):
`ward_id`, `value`, `doy`, `system:time_start`.

Hands off to `heatwave/science/climatology.py` and `heatwave/science/heatwave.py`.
`system:time_start` is mandatory on every output row: those downstream stages
filter with `ee.Filter.calendarRange`, which derives day-of-year from the
feature's timestamp and raises
`Collection.filter: Can't apply calendarRange filter to objects without a
timestamp.` on any feature lacking one.

A row may also carry `used_fallback_reducer` (D-09): a boolean, set on every
row of BOTH reduction paths, that is True when a ward listed in the caller's
`fallback_ward_ids` was sampled at a representative in-polygon point with a
non-area-weighted reducer (D-08, WR-04) rather than area-weighted-averaged
over its full polygon. This exists because Earth Engine's `reduceRegions`
area-weights regardless of which reducer is passed, so a ward polygon below
the ~0.4% pixel-weight inclusion threshold yields nothing no matter what
reducer is requested over the polygon itself -- only re-keying the geometry
to a single point escapes that area-weighting; `_representative_point_in_geometry`
(not a raw `.centroid()`) is used so that point is guaranteed to actually lie
on the ward's own polygon even when it is concave, multi-part, or has a
hole. This resolves the caller obligation the null-value
paragraph below hands to Phase 4: a null is neither dropped nor coalesced to
zero -- it is replaced by a genuine, lower-fidelity sampled value with its
provenance flagged, so a downstream CSV consumer can always tell which rows
came from which path.
"""
from __future__ import annotations

from typing import Iterable

import ee

from heatwave.config import settings

# ERA5-Land's verified nominal pixel scale in meters
# (image.projection().nominalScale() -> 11131.949..., verified live against
# heatwave-508110, 03-RESEARCH.md Pattern 1).
ERA5_LAND_NOMINAL_SCALE_M = 11132


def find_small_wards(
    images: ee.Image | Iterable[ee.Image],
    wards: ee.FeatureCollection,
    band: str = "heat_index",
    scale: int = ERA5_LAND_NOMINAL_SCALE_M,
    ward_id_property: str = "wardcode",
) -> ee.List:
    """Identify ward ids whose primary area-weighted reduction yields no value (D-08).

    Runs the exact same primary area-weighted reduction pass the main path in
    `reduce_to_ward_daily` uses against EVERY image in `images` (a single
    `ee.Image` is also accepted, for backward compatibility -- it then
    behaves as a single-sample check), and returns only the
    `ward_id_property` values of wards missing the `mean` property that
    reduction produces on EVERY sample (WR-05). That primary reducer OMITS
    the `mean` property entirely (rather than setting it to null) for a
    ward polygon below Earth Engine's ~0.4% pixel-weight inclusion
    threshold, so absence -- not nullness -- is what is tested server-side
    via `ee.Filter.notNull(["mean"])` inverted with `ee.Filter.Not(...)`.

    A ward's small-geometry status is meant to be a static property of its
    polygon against the fixed ERA5-Land grid (04-RESEARCH.md Pitfall 5) --
    it does not vary by date -- but the actual test performed here is a
    live data condition (whether reduceRegions happened to yield a `mean`
    for one specific day), not a direct geometric computation. Requiring
    agreement across 2-3 well-separated sample images (WR-05) means an
    incidental data anomaly on any ONE sampled day (a rare EE nodata
    sliver, boundary rasterization jitter) can no longer, by itself,
    permanently and silently downgrade an otherwise normal-sized ward to
    the lower-fidelity centroid-fallback path for the entire run -- a ward
    is only trusted as genuinely small when every sample agrees. Call this
    function ONCE per production run and reuse its result as the
    `fallback_ward_ids` argument for every day of every chunk. Never
    re-derive it per day: a transient spurious null would otherwise switch
    one day's reducer mid-series and silently corrupt the time-series
    provenance that `detect_heatwave_events`'s run-length state machine
    assumes is homogeneous.
    """
    if isinstance(images, ee.Image):
        images = [images]
    else:
        images = list(images)
    if not images:
        raise ValueError("find_small_wards requires at least one image")

    missing_id_sets = []
    for image in images:
        reduced = image.select(band).reduceRegions(
            collection=wards, reducer=ee.Reducer.mean(), scale=scale
        )
        missing_mean = reduced.filter(ee.Filter.Not(ee.Filter.notNull(["mean"])))
        missing_id_sets.append(set(missing_mean.aggregate_array(ward_id_property).getInfo()))

    consensus_ids = set.intersection(*missing_id_sets)
    return ee.List(sorted(consensus_ids))


def _representative_point_in_geometry(geometry: ee.Geometry) -> ee.Geometry:
    """A point guaranteed to lie ON `geometry` (its interior or its
    boundary), even when `geometry` is concave, multi-part, or has a hole
    (WR-04).

    GEE's JavaScript API and documentation describe `ee.Geometry
    .pointOnSurface()` for exactly this guarantee, but this project's
    Python client exposes no such algorithm -- live-verified against
    heatwave-508110: `ee.ApiFunction.allSignatures()` lists no
    `Geometry.pointOnSurface` (nor does `dir(ee.Geometry)`, before or
    after `ee.Initialize()`). So this uses only APIs confirmed present in
    that signature list: prefer the geometric `centroid()` when it is
    actually `contains()`-ed by the geometry (the common convex/simple
    case, matching the pre-WR-04 behaviour); otherwise fall back to the
    geometry's own first vertex, which is always part of the geometry (a
    polygon's boundary counts as contained). `ee.List(geometry
    .coordinates()).flatten()` collapses Polygon-with-holes and
    MultiPolygon's differing coordinate-nesting depths into one flat
    `[lon, lat, lon, lat, ...]` list uniformly, so the first two elements
    are always a genuine vertex regardless of geometry shape -- verified
    live for both a hole-containing donut polygon and a two-part
    MultiPolygon.
    """
    centroid = geometry.centroid()
    flat_coords = ee.List(geometry.coordinates()).flatten()
    first_vertex = ee.Geometry.Point([flat_coords.get(0), flat_coords.get(1)])
    return ee.Geometry(
        ee.Algorithms.If(geometry.contains(centroid), centroid, first_vertex)
    )


def build_fallback_ward_centroids(
    small_wards: ee.FeatureCollection,
    ward_id_property: str = "wardcode",
) -> ee.FeatureCollection:
    """Re-key each small ward's geometry to a representative POINT (D-08, WR-04).

    `reduceRegions` area-weights regardless of which reducer is passed, so a
    sub-pixel-weight polygon yields nothing from a non-area-weighted reducer
    either -- only a POINT geometry escapes that area-weighting
    (04-RESEARCH.md Pattern 2, live-verified). A pixel-center-containment
    sampling approach was also tried during research and does NOT work here:
    it still requires a pixel center to fall inside the region, which a
    small ward's original polygon can fail even when its centroid falls
    squarely inside a pixel. Do not "simplify" this into that approach.

    Uses `_representative_point_in_geometry`, not raw `.centroid()` (WR-04):
    a small ward selected by `find_small_wards` is exactly the kind of
    irregular, possibly concave or multi-part polygon whose raw geometric
    centroid can fall outside the polygon entirely (e.g. a crescent or
    donut shape) or inside a neighboring ward -- silently sampling a value
    that has no relationship to the ward it is nominally representing.

    Each output feature carries only `ward_id_property` as a property.
    """

    def to_representative_point(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        return ee.Feature(
            _representative_point_in_geometry(feature.geometry()),
            {ward_id_property: feature.get(ward_id_property)},
        )

    return small_wards.map(to_representative_point)


def reduce_to_ward_daily(
    image_collection: ee.ImageCollection,
    wards: ee.FeatureCollection,
    band: str = "heat_index",
    scale: int = ERA5_LAND_NOMINAL_SCALE_M,
    ward_id_property: str = "wardcode",
    fallback_ward_ids: ee.List | list[str] | None = None,
) -> ee.FeatureCollection:
    """Reduce a gridded Heat Index ImageCollection to per-ward-daily rows (CLIM-05).

    Returns a flat ee.FeatureCollection of N*M features (N wards, M images),
    each carrying:
        ward_id                string  copied from wards[ward_id_property]
        value                  double  reduced band value for that ward on
                                        that day; null when the ward polygon
                                        falls below Earth Engine's ~0.4%
                                        pixel-weight inclusion threshold AND
                                        it is not listed in
                                        `fallback_ward_ids` (see caller
                                        obligation below)
        doy                    int     1-366, ee.Date.getRelative('day','year') + 1
        system:time_start      long    image date in millis
        used_fallback_reducer  bool    True when this row came from the
                                        representative-in-polygon-point
                                        sample (D-08, WR-04), False when it
                                        came from the primary area-weighted
                                        mean (D-09)

    Caller obligation (data-integrity, T-03-01): a null `value` means the ward
    polygon was too small relative to the ~11.1km pixel grid to receive a
    weighted `mean` from reduceRegions, and it was not listed in
    `fallback_ward_ids` -- this row is present, not dropped. Callers (e.g.
    Phase 4's batch export) must treat a null value as missing data, never
    silently aggregate it as zero heatwave days.

    `fallback_ward_ids` (D-08, optional, default None): a static list of ward
    ids -- computed once via `find_small_wards`, never re-derived per day
    (04-RESEARCH.md Pitfall 5) -- to sample at a guaranteed-in-polygon
    representative point (WR-04, see `_representative_point_in_geometry`)
    with a non-area-weighted, first-value reducer instead of
    area-weight-averaging their polygon with the primary mean reducer.
    When None, behaviour is
    unchanged from Phase 3 except every row now also carries an explicit
    fallback-provenance flag set to False. When supplied, the ward
    collection is partitioned once (outside the per-day map) via an
    inclusion-list filter and its complement, so a ward in the fallback
    list is excluded from the primary reduction and can never be reduced
    twice in one day; total row count stays N*M. A null value is never
    coalesced to 0 anywhere -- the fallback produces a genuine, if
    lower-fidelity, sampled value instead.

    No ward count, ward id, date range, or collection id is hardcoded here
    (D-04): `wards`, `band`, `scale`, and `ward_id_property` are all caller
    parameters, so this function is reused unchanged at Phase 4's full
    nationwide ward scale.
    """
    if fallback_ward_ids is None:
        primary_wards = wards
        fallback_centroids = ee.FeatureCollection([])
    else:
        fallback_list = ee.List(fallback_ward_ids)
        in_fallback = ee.Filter.inList(ward_id_property, fallback_list)
        primary_wards = wards.filter(ee.Filter.Not(in_fallback))
        fallback_centroids = build_fallback_ward_centroids(
            wards.filter(in_fallback), ward_id_property
        )

    def reduce_one_day(image: ee.Image) -> ee.FeatureCollection:
        date = image.date()
        doy = date.getRelative("day", "year").add(1)
        reduced = image.select(band).reduceRegions(
            collection=primary_wards, reducer=ee.Reducer.mean(), scale=scale
        )

        def set_row_properties(feature: ee.Feature) -> ee.Feature:
            feature = ee.Feature(feature)
            return feature.set(
                "ward_id", feature.get(ward_id_property),
                "value", feature.get("mean"),
                "doy", doy,
                "system:time_start", date.millis(),
                "used_fallback_reducer", False,
            )

        primary_rows = reduced.map(set_row_properties)

        fallback_reduced = image.select(band).reduceRegions(
            collection=fallback_centroids, reducer=ee.Reducer.first(), scale=scale
        )

        def set_fallback_row_properties(feature: ee.Feature) -> ee.Feature:
            feature = ee.Feature(feature)
            return feature.set(
                "ward_id", feature.get(ward_id_property),
                "value", feature.get("first"),
                "doy", doy,
                "system:time_start", date.millis(),
                "used_fallback_reducer", True,
            )

        fallback_rows = fallback_reduced.map(set_fallback_row_properties)

        return primary_rows.merge(fallback_rows)

    return ee.FeatureCollection(image_collection.map(reduce_one_day)).flatten()
