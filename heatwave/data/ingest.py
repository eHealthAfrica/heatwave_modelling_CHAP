"""ERA5-Land ingestion: select configured bands, filter by date, clip to the ward boundary.

Replaces the ECMWF/ERA5/DAILY pull in the original prototype. Per
outputs/01_Heatwave_Methodology.docx, ERA5-Land gives ~11.1km resolution
daily data from 1950-01-02, versus the coarser ERA5/DAILY collection used
before. Only selection/filtering/clipping happens here — per-ward zonal
reduction is a later pipeline stage (heatwave/zonal.py).
"""
from __future__ import annotations

import ee

from heatwave.config import settings


def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ee.ImageCollection:
    """Return the ERA5-Land collection, date-filtered and clipped to boundary.

    The returned collection carries `tmax` (band name `temperature_2m_max`),
    `tmean` (`temperature_2m`), and `dewpoint` (`dewpoint_temperature_2m`) as
    three bands of every image, date-filtered and clipped to `boundary`.
    """
    start_date = start_date or settings.start_date
    end_date = end_date or settings.end_date

    return (
        ee.ImageCollection(settings.era5_land_collection)
        .select([settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint])
        .filter(ee.Filter.date(start_date, end_date))
        .map(lambda image: image.clip(boundary))
    )
