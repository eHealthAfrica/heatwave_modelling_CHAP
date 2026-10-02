"""Local pipeline: ERA5-Land NetCDF files -> ward daily series -> weekly covariate table.

Per day and ward:
  - Heat Index (deg F) from daily MAXIMUM 2m temperature and daily mean dewpoint, so it
    describes the hottest part of the day. Computed per grid cell, then area-averaged.
  - Daily minimum 2m temperature (K), area-averaged.
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

COVARIATE_COLUMNS = [
    "time_period", "location", "heatwave_days", "mean_heat_index", "max_heat_index",
    "heatwave_event_count", "hot_nights",
]


@dataclass
class WardDaily:
    dates: pd.DatetimeIndex
    ward_ids: list[str]
    heat_index: np.ndarray  # (days, wards) deg F
    tmin: np.ndarray        # (days, wards) K


def available_years(era5_dir: Path) -> list[int]:
    years = sorted(int(p.stem) for p in (era5_dir / TMAX).glob("*.nc"))
    for band in (TMIN, DEWPOINT):
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
    first = _open_year(era5_dir, TMAX, years[0])
    lats, lons = first.latitude.values, first.longitude.values
    weights = build_weights(geoms, lats, lons, valid=first.notnull().all("time").values)
    log.info("weights: %d ward-cell pairs; %d point wards; %d wards on nearest valid cell",
             len(weights.cells), weights.n_point_wards, weights.n_nearest_wards)

    dates, his, tmins = [], [], []
    for year in years:
        tmax, tmin, dew = (_open_year(era5_dir, b, year) for b in (TMAX, TMIN, DEWPOINT))
        if not (tmax.time.equals(tmin.time) and tmax.time.equals(dew.time)):
            raise ValueError(f"{year}: band dates differ")
        t = pd.DatetimeIndex(tmax.time.values)
        keep = np.ones(len(t), bool)
        if start is not None:
            keep &= t >= pd.Timestamp(start)
        if end is not None:
            keep &= t <= pd.Timestamp(end)
        flat = lambda a: a.values[keep].reshape(int(keep.sum()), -1)  # noqa: E731
        tx, tn, td = flat(tmax), flat(tmin), flat(dew)
        hi = science.heat_index_f(tx, science.relative_humidity(tx, td))
        his.append(weights.reduce(hi).astype("float32"))
        tmins.append(weights.reduce(tn).astype("float32"))
        dates.append(t[keep])
        log.info("reduced %d (%d days)", year, keep.sum())
    out = WardDaily(dates[0].append(dates[1:]), ward_ids, np.concatenate(his), np.concatenate(tmins))
    if not out.dates.equals(pd.date_range(out.dates[0], out.dates[-1])):
        raise ValueError("daily series has gaps")
    if np.isnan(out.heat_index).any() or np.isnan(out.tmin).any():
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
    })
    return table[COVARIATE_COLUMNS]
