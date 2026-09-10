"""ERA5-Land ingestion: select configured bands, filter by date, clip to the ward boundary.

Replaces the ECMWF/ERA5/DAILY pull in the original prototype. Per
outputs/01_Heatwave_Methodology.docx, ERA5-Land gives ~11.1km resolution
daily data from 1950-01-02, versus the coarser ERA5/DAILY collection used
before. Only selection/filtering/clipping happens here — per-ward zonal
reduction is a later pipeline stage (heatwave/zonal.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import ee

from heatwave.config import settings


@dataclass(frozen=True)
class Era5LandBands:
    tmax: ee.ImageCollection
    tmean: ee.ImageCollection
    dewpoint: ee.ImageCollection


def _select_band(band_name: str, start_date: str, end_date: str, boundary: ee.FeatureCollection) -> ee.ImageCollection:
    return (
        ee.ImageCollection(settings.era5_land_collection)
        .select(band_name)
        .filter(ee.Filter.date(start_date, end_date))
        .map(lambda image: image.clip(boundary))
    )


def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Era5LandBands:
    """Return the tmax/tmean/dewpoint ImageCollections, date-filtered and clipped to boundary."""
    start_date = start_date or settings.start_date
    end_date = end_date or settings.end_date

    return Era5LandBands(
        tmax=_select_band(settings.bands.tmax, start_date, end_date, boundary),
        tmean=_select_band(settings.bands.tmean, start_date, end_date, boundary),
        dewpoint=_select_band(settings.bands.dewpoint, start_date, end_date, boundary),
    )
