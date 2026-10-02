"""Local pipeline: ERA5-Land NetCDF files -> ward daily series -> weekly covariate table.

Per day and ward:
  - Heat Index (deg F) from daily MAXIMUM 2m temperature and daily mean dewpoint, so it
    describes the hottest part of the day. Computed per grid cell, then area-averaged.
  - Daily minimum 2m temperature (K), area-averaged.
  - Precipitation (mm, negatives from ERA5 rounding set to 0), relative humidity (%, from
    daily mean temperature and dewpoint) and top-layer soil moisture (m3/m3), area-averaged.
    These are passed through to the weekly table as covariates for CHAP; they don't enter
    the heatwave definition.
A day is a heatwave day when its Heat Index strictly exceeds the ward's own pooled
day-of-year percentile threshold over the baseline; >= min_consecutive_days such days in a
row make an event, counted in the ISO week it starts. A night is a hot night when Tmin
strictly exceeds its own threshold, built the same way.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from heatwave.config import ClimatologyConfig
from heatwave.local import science
from heatwave.local.grid import WardWeights, build_weights

log = logging.getLogger(__name__)

TMAX, TMIN, DEWPOINT = "temperature_2m_max", "temperature_2m_min", "dewpoint_temperature_2m"
TMEAN, PRECIP, SOIL = "temperature_2m", "total_precipitation_sum", "volumetric_soil_water_layer_1"
BANDS = (TMAX, TMIN, DEWPOINT, TMEAN, PRECIP, SOIL)

COVARIATE_COLUMNS = [
    "time_period", "location", "heatwave_days", "mean_heat_index", "max_heat_index",
    "heatwave_event_count", "hot_nights", "total_precipitation_mm", "mean_relative_humidity",
    "mean_soil_moisture",
]


@dataclass
class WardDaily:
    dates: pd.DatetimeIndex
    ward_ids: list[str]
    heat_index: np.ndarray     # (days, wards) deg F
    tmin: np.ndarray           # (days, wards) K
    precip_mm: np.ndarray      # (days, wards) mm
    rel_humidity: np.ndarray   # (days, wards) %
    soil_moisture: np.ndarray  # (days, wards) m3/m3


def available_years(era5_dir: Path) -> list[int]:
    years = sorted(int(p.stem) for p in (era5_dir / TMAX).glob("*.nc"))
    for band in BANDS[1:]:
        missing = [y for y in years if not (era5_dir / band / f"{y}.nc").exists()]
        if missing:
            raise FileNotFoundError(f"{band} is missing years {missing}")
    return years


def _open_year(era5_dir: Path, band: str, year: int) -> xr.DataArray:
    with xr.open_dataset(era5_dir / band / f"{year}.nc") as ds:
        return ds[band].load()


def ward_daily(era5_dir: Path, ward_ids: list[str], geoms: list,
               start: dt.date | None = None, end: dt.date | None = None) -> tuple[WardDaily, WardWeights]:
    """Reduce every available day (optionally within [start, end]) to ward means."""
    years = [y for y in available_years(era5_dir)
             if (start is None or y >= start.year) and (end is None or y <= end.year)]
    first = {b: _open_year(era5_dir, b, years[0]) for b in BANDS}
    lats, lons = first[TMAX].latitude.values, first[TMAX].longitude.values
    valid = np.logical_and.reduce([a.notnull().all("time").values for a in first.values()])
    weights = build_weights(geoms, lats, lons, valid=valid)
    log.info("weights: %d ward-cell pairs; %d point wards; %d wards on nearest valid cell",
             len(weights.cells), weights.n_point_wards, weights.n_nearest_wards)

    dates, cols = [], {k: [] for k in ("hi", "tmin", "precip", "rh", "soil")}
    for year in years:
        arrays = first if year == years[0] else {b: _open_year(era5_dir, b, year) for b in BANDS}
        t = pd.DatetimeIndex(arrays[TMAX].time.values)
        if any(not arrays[b].time.equals(arrays[TMAX].time) for b in BANDS):
            raise ValueError(f"{year}: band dates differ")
        keep = np.ones(len(t), bool)
        if start is not None:
            keep &= t >= pd.Timestamp(start)
        if end is not None:
            keep &= t <= pd.Timestamp(end)
        v = {b: arrays[b].values[keep].reshape(int(keep.sum()), -1) for b in BANDS}
        hi = science.heat_index_f(v[TMAX], science.relative_humidity(v[TMAX], v[DEWPOINT]))
        for key, grid in (("hi", hi), ("tmin", v[TMIN]),
                          ("precip", np.clip(v[PRECIP], 0, None) * 1000),
                          ("rh", science.relative_humidity(v[TMEAN], v[DEWPOINT])),
                          ("soil", v[SOIL])):
            cols[key].append(weights.reduce(grid).astype("float32"))
        dates.append(t[keep])
        log.info("reduced %d (%d days)", year, keep.sum())
    out = WardDaily(dates[0].append(dates[1:]), ward_ids,
                    *(np.concatenate(cols[k]) for k in ("hi", "tmin", "precip", "rh", "soil")))
    if not out.dates.equals(pd.date_range(out.dates[0], out.dates[-1])):
        raise ValueError("daily series has gaps")
    if any(np.isnan(a).any() for a in (out.heat_index, out.tmin, out.precip_mm,
                                        out.rel_humidity, out.soil_moisture)):
        raise ValueError("ward daily series contain NaN")
    return out, weights


def weekly_table(daily: WardDaily, clim: ClimatologyConfig) -> pd.DataFrame:
    """Flag hot days/nights and events, then aggregate to one row per (ISO week, ward).

    Only complete ISO weeks (7 days) are kept, so partial weeks at either end of the
    record don't understate counts.
    """
    doy = daily.dates.dayofyear.values
    years = daily.dates.year.values
    in_base = (years >= clim.baseline_start_year) & (years <= clim.baseline_end_year)
    if not in_base.any():
        raise ValueError("no days in the baseline period")

    hi_thr = science.doy_thresholds(daily.heat_index, doy, in_base, clim.percentile, clim.pooling_window_days)
    hot = science.exceeds(daily.heat_index, hi_thr, doy)
    starts = science.event_starts(hot, clim.min_consecutive_days)
    tn_thr = science.doy_thresholds(daily.tmin, doy, in_base, clim.percentile, clim.pooling_window_days)
    hot_night = science.exceeds(daily.tmin, tn_thr, doy)

    iso = daily.dates.isocalendar()
    labels = (iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)).values
    week_start = np.flatnonzero(np.r_[True, labels[1:] != labels[:-1]])
    week_len = np.diff(np.r_[week_start, len(labels)])
    complete = week_len == 7

    def per_week(x: np.ndarray, ufunc=np.add) -> np.ndarray:
        return ufunc.reduceat(x, week_start, axis=0)[complete]

    n_weeks, n_wards = int(complete.sum()), len(daily.ward_ids)
    table = pd.DataFrame({
        "time_period": np.repeat(labels[week_start][complete], n_wards),
        "location": np.tile(np.asarray(daily.ward_ids), n_weeks),
        "heatwave_days": per_week(hot.astype("int16")).ravel(),
        "mean_heat_index": (per_week(daily.heat_index.astype("float64")) / 7).ravel(),
        "max_heat_index": per_week(daily.heat_index, np.maximum).ravel(),
        "heatwave_event_count": per_week(starts.astype("int16")).ravel(),
        "hot_nights": per_week(hot_night.astype("int16")).ravel(),
        "total_precipitation_mm": per_week(daily.precip_mm.astype("float64")).ravel(),
        "mean_relative_humidity": (per_week(daily.rel_humidity.astype("float64")) / 7).ravel(),
        "mean_soil_moisture": (per_week(daily.soil_moisture.astype("float64")) / 7).ravel(),
    })
    return table[COVARIATE_COLUMNS]
