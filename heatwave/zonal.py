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
"""
from __future__ import annotations

import ee

from heatwave.config import settings

# ERA5-Land's verified nominal pixel scale in meters
# (image.projection().nominalScale() -> 11131.949..., verified live against
# heatwave-508110, 03-RESEARCH.md Pattern 1).
ERA5_LAND_NOMINAL_SCALE_M = 11132


def reduce_to_ward_daily(
    image_collection: ee.ImageCollection,
    wards: ee.FeatureCollection,
    band: str = "heat_index",
    scale: int = ERA5_LAND_NOMINAL_SCALE_M,
    ward_id_property: str = "wardcode",
) -> ee.FeatureCollection:
    """Reduce a gridded Heat Index ImageCollection to per-ward-daily rows (CLIM-05).

    Returns a flat ee.FeatureCollection of N*M features (N wards, M images),
    each carrying:
        ward_id            string  copied from wards[ward_id_property]
        value              double  zonally-reduced band value for that ward on
                                    that day; null when the ward polygon falls
                                    below Earth Engine's ~0.4% pixel-weight
                                    inclusion threshold (see caller obligation
                                    below)
        doy                int     1-366, ee.Date.getRelative('day','year') + 1
        system:time_start  long    image date in millis

    Caller obligation (data-integrity, T-03-01): a null `value` means the ward
    polygon was too small relative to the ~11.1km pixel grid to receive a
    weighted `mean` from reduceRegions -- this row is present, not dropped.
    Callers (e.g. Phase 4's batch export) must treat a null value as missing
    data, never silently aggregate it as zero heatwave days.

    No ward count, ward id, date range, or collection id is hardcoded here
    (D-04): `wards`, `band`, `scale`, and `ward_id_property` are all caller
    parameters, so this function is reused unchanged at Phase 4's full
    nationwide ward scale.
    """

    def reduce_one_day(image: ee.Image) -> ee.FeatureCollection:
        date = image.date()
        doy = date.getRelative("day", "year").add(1)
        reduced = image.select(band).reduceRegions(
            collection=wards, reducer=ee.Reducer.mean(), scale=scale
        )

        def set_row_properties(feature: ee.Feature) -> ee.Feature:
            feature = ee.Feature(feature)
            return feature.set(
                "ward_id", feature.get(ward_id_property),
                "value", feature.get("mean"),
                "doy", doy,
                "system:time_start", date.millis(),
            )

        return reduced.map(set_row_properties)

    return ee.FeatureCollection(image_collection.map(reduce_one_day)).flatten()
