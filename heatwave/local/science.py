"""Numpy versions of the heat science: RH, Heat Index, day-of-year thresholds, events.

The RH and Heat Index formulas mirror heatwave/science/heat_index.py (Earth Engine) exactly.
Arrays are (days, locations) throughout; `doy` is the raw day of year (1-366, so in leap
years Feb 29 is 60 and Mar 1 is 61), matching the Earth Engine climatology's convention.
"""
from __future__ import annotations

import numpy as np

from heatwave.science.heat_index import MAGNUS_B, MAGNUS_C

_ROTHFUSZ = (-42.379, 2.04901523, 10.14333127, -0.22475541,
             -0.00683783, -0.05481717, 0.00122874, 0.00085282, -0.00000199)


def relative_humidity(t_k: np.ndarray, d_k: np.ndarray) -> np.ndarray:
    """RH (%) from air temperature and dewpoint in Kelvin (Magnus), clamped to [0, 100]."""
    t, d = t_k - 273.15, d_k - 273.15
    rh = 100 * np.exp(MAGNUS_B * d / (MAGNUS_C + d) - MAGNUS_B * t / (MAGNUS_C + t))
    return np.clip(rh, 0, 100)


def heat_index_f(t_k: np.ndarray, rh: np.ndarray) -> np.ndarray:
    """Heat Index (deg F) by the full NWS procedure; see heatwave/science/heat_index.py."""
    t = (t_k - 273.15) * 9 / 5 + 32
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    c1, c2, c3, c4, c5, c6, c7, c8, c9 = _ROTHFUSZ
    rothfusz = (c1 + c2 * t + c3 * rh + c4 * t * rh + c5 * t**2 + c6 * rh**2
                + c7 * t**2 * rh + c8 * t * rh**2 + c9 * t**2 * rh**2)
    with np.errstate(invalid="ignore"):
        dry = (13 - rh) / 4 * np.sqrt(np.clip((17 - np.abs(t - 95)) / 17, 0, None))
    rothfusz = rothfusz - np.where((rh < 13) & (t >= 80) & (t <= 112), dry, 0)
    rothfusz = rothfusz + np.where((rh > 85) & (t >= 80) & (t <= 87),
                                   (rh - 85) / 10 * (87 - t) / 5, 0)
    return np.where((simple + t) / 2 >= 80, rothfusz, simple)


def doy_thresholds(values: np.ndarray, doy: np.ndarray, in_baseline: np.ndarray,
                   percentile: float, window: int) -> np.ndarray:
    """(366, locations) percentile thresholds pooled over a +/-`window`-day wrapped window.

    Day d pools every baseline day whose doy lies within `window` days of d, wrapping
    across the year end (doy 366 pools with 1..window). Baseline values must not be NaN.
    numpy's default linear interpolation is used; Earth Engine's percentile reducer
    interpolates differently, which matters little with ~330 pooled values per day.
    """
    base_vals, base_doy = values[in_baseline], doy[in_baseline]
    if np.isnan(base_vals).any():
        raise ValueError("baseline values contain NaN")
    out = np.empty((366, values.shape[1]), dtype="float32")
    for d in range(1, 367):
        pooled = (base_doy - d + window) % 366 <= 2 * window
        out[d - 1] = np.percentile(base_vals[pooled], percentile, axis=0)
    return out


def exceeds(values: np.ndarray, thresholds: np.ndarray, doy: np.ndarray) -> np.ndarray:
    """True where a value strictly exceeds its own day-of-year threshold (NaN -> False)."""
    with np.errstate(invalid="ignore"):
        return values > thresholds[doy - 1]


def event_starts(hot: np.ndarray, min_len: int) -> np.ndarray:
    """True on the first day of every run of >= `min_len` consecutive hot days."""
    first = hot.copy()
    first[1:] &= ~hot[:-1]
    long_enough = np.ones_like(hot)
    for k in range(min_len):
        shifted = np.zeros_like(hot)
        shifted[: len(hot) - k] = hot[k:]
        long_enough &= shifted
    return first & long_enough
