"""Relative humidity and Heat Index computation over ERA5-Land ee.Image bands."""
from __future__ import annotations

import ee

from heatwave.config import settings

# Magnus saturation vapour pressure coefficients over water (Alduchov & Eskridge 1996).
MAGNUS_B = 17.625
MAGNUS_C = 243.04  # deg C


def compute_relative_humidity(image: ee.Image) -> ee.Image:
    """Return image with an added 'relative_humidity' band, clamped to [0, 100] (D-01/WR-01).

    RH = 100 * e_s(D) / e_s(T) with the Magnus formula, T and D in deg C. This holds
    across the full humidity range, unlike the linear 100 - 5*(T - D) rule, which is
    only valid above ~50% RH and reads 0% for typical northern-Nigeria dry-season air.
    """
    T = image.select(settings.bands.tmean).subtract(273.15)
    D = image.select(settings.bands.dewpoint).subtract(273.15)

    rh = (
        image.expression(
            '100 * exp(b * D / (c + D) - b * T / (c + T))',
            {'T': T, 'D': D, 'b': MAGNUS_B, 'c': MAGNUS_C},
        )
        .clamp(0, 100)  # D-01 fix: single-band, pre-addBands -- never clamp the multi-band image
        .rename('relative_humidity')
    )
    return image.addBands(rh)


def compute_heat_index(image: ee.Image) -> ee.Image:
    """Return image with an added 'heat_index' band (NOAA/NWS algorithm, deg F).

    Follows the full NWS procedure (wpc.ncep.noaa.gov/html/heatindex_equation.shtml):
    Steadman's simple formula, replaced by the Rothfusz regression (plus its low- and
    high-humidity adjustments) where the simple result averaged with T is >= 80F.
    The Rothfusz regression alone is not valid below ~80F.
    """
    tempK = image.select(settings.bands.tmean)
    tempF = tempK.subtract(273.15).multiply(9 / 5).add(32)
    RH = image.select('relative_humidity')
    vars_ = {'T': tempF, 'R': RH}

    simple = tempF.expression('0.5 * (T + 61.0 + (T - 68.0) * 1.2 + R * 0.094)', vars_)

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = [
        -42.379, 2.04901523, 10.14333127, -0.22475541,
        -0.00683783, -0.05481717, 0.00122874,
        0.00085282, -0.00000199
    ]

    rothfusz = tempF.expression(
        'c1 + c2*T + c3*R + c4*T*R + c5*T**2 + c6*R**2 + c7*T**2*R + c8*T*R**2 + c9*T**2*R**2',
        {**vars_, 'c1': c1, 'c2': c2, 'c3': c3,
         'c4': c4, 'c5': c5, 'c6': c6, 'c7': c7, 'c8': c8, 'c9': c9}
    )
    # Dry-air adjustment: RH < 13% and 80F <= T <= 112F.
    dry = tempF.expression(
        '(13 - R) / 4 * sqrt((17 - abs(T - 95)) / 17)', vars_
    ).updateMask(RH.lt(13).And(tempF.gte(80)).And(tempF.lte(112))).unmask(0)
    # Humid adjustment: RH > 85% and 80F <= T <= 87F.
    humid = tempF.expression(
        '(R - 85) / 10 * (87 - T) / 5', vars_
    ).updateMask(RH.gt(85).And(tempF.gte(80)).And(tempF.lte(87))).unmask(0)
    rothfusz = rothfusz.subtract(dry).add(humid)

    use_rothfusz = simple.add(tempF).divide(2).gte(80)
    HI = simple.where(use_rothfusz, rothfusz).rename('heat_index')

    return image.addBands(HI.set('system:time_start', image.get('system:time_start')))
