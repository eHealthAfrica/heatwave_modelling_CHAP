"""Relative humidity and Heat Index computation over ERA5-Land ee.Image bands."""
from __future__ import annotations

import ee

from heatwave.config import settings


def compute_relative_humidity(image: ee.Image) -> ee.Image:
    """Return image with an added 'relative_humidity' band, clamped to [0, 100] (D-01/WR-01)."""
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)

    rh = (
        image.expression('100 - 5 * (T - D)', {'T': T, 'D': D})
        .clamp(0, 100)  # D-01 fix: single-band, pre-addBands -- never clamp the multi-band image
        .rename('relative_humidity')
    )
    return image.addBands(rh)


def compute_heat_index(image: ee.Image) -> ee.Image:
    """Return image with an added 'heat_index' band (Rothfusz regression, deg F)."""
    tempK = image.select(settings.bands.tmean)
    tempF = tempK.subtract(273.15).multiply(9 / 5).add(32)
    RH = image.select('relative_humidity')

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = [
        -42.379, 2.04901523, 10.14333127, -0.22475541,
        -0.00683783, -0.05481717, 0.00122874,
        0.00085282, -0.00000199
    ]

    HI = tempF.expression(
        'c1 + c2*T + c3*R + c4*T*R + c5*T**2 + c6*R**2 + c7*T**2*R + c8*T*R**2 + c9*T**2*R**2',
        {'T': tempF, 'R': RH, 'c1': c1, 'c2': c2, 'c3': c3,
         'c4': c4, 'c5': c5, 'c6': c6, 'c7': c7, 'c8': c8, 'c9': c9}
    ).rename('heat_index')

    return image.addBands(HI.set('system:time_start', image.get('system:time_start')))
