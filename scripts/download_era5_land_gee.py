"""Download ERA5-Land daily data for northern Nigeria from Google Earth Engine.

Feeds the local pipeline (scripts/run_local_pipeline.py). Copernicus CDS's
derived-era5-land-daily-statistics is computed on demand and queues for hours per request;
Earth Engine's ECMWF/ERA5_LAND/DAILY_AGGR is precomputed (daily values from hourly
ERA5-Land, UTC days), so one variable-year arrives in ~20 s via ee.data.computePixels.

One NetCDF file per band per year, under <local_data_dir>/era5_land_daily_gee/<band>/<year>.nc,
on the native 0.1 degree ERA5-Land grid (pixel centres 2.5..15.0 E, 4.0..14.0 N).
Sea pixels (no ERA5-Land data) are NaN. Units are as in ERA5-Land (K, m3/m3, m/s, Pa, m, J/m2).

Safe to re-run: finished files are skipped, and a file only appears under its final name
once it has been written. The current year is always re-fetched so it picks up new days.
Uses the repo's Earth Engine credentials (heatwave/auth.py).

    python scripts/download_era5_land_gee.py
"""
from __future__ import annotations

import datetime as dt
import io
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ee
import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.auth import init_ee  # noqa: E402
from heatwave.config import settings  # noqa: E402

COLLECTION = settings.era5_land_collection
FIRST_YEAR = settings.climatology.baseline_start_year
ROOT = settings.local_data_dir / "era5_land_daily_gee"
MAX_PARALLEL = 12  # Earth Engine allows ~40 concurrent requests per project
RETRIES = 5
NODATA = -9999.0

# Native ERA5-Land grid: transform [0.1, 0, -180.05, 0, -0.1, 90.05]. Edges are offset by
# half a pixel, so these 126 x 101 pixels are centred on 2.5..15.0 E and 14.0..4.0 N.
WEST_EDGE, NORTH_EDGE, WIDTH, HEIGHT, RES = 2.45, 14.05, 126, 101, 0.1
GRID = {
    "dimensions": {"width": WIDTH, "height": HEIGHT},
    "affineTransform": {"scaleX": RES, "shearX": 0, "translateX": WEST_EDGE,
                        "shearY": 0, "scaleY": -RES, "translateY": NORTH_EDGE},
    "crsCode": "EPSG:4326",
}
LONS = np.round(WEST_EDGE + RES / 2 + RES * np.arange(WIDTH), 2)
LATS = np.round(NORTH_EDGE - RES / 2 - RES * np.arange(HEIGHT), 2)

BANDS = {  # band -> units
    "temperature_2m": "K",
    "temperature_2m_max": "K",
    "temperature_2m_min": "K",
    "dewpoint_temperature_2m": "K",
    "volumetric_soil_water_layer_1": "m3 m-3",
    "u_component_of_wind_10m": "m s-1",
    "v_component_of_wind_10m": "m s-1",
    "surface_pressure": "Pa",
    "total_precipitation_sum": "m",
    "surface_solar_radiation_downwards_sum": "J m-2",
}

log = logging.getLogger("era5land_gee")


def download(band: str, year: int, end: dt.date) -> str:
    """Fetch one band for one year (up to `end`, exclusive) to <band>/<year>.nc."""
    target = ROOT / band / f"{year}.nc"
    name = f"{band}/{year}"
    if target.exists() and target.stat().st_size > 0 and year < end.year:
        return f"skip {name} (already downloaded)"
    target.parent.mkdir(parents=True, exist_ok=True)
    stop = min(dt.date(year + 1, 1, 1), end)
    image = (ee.ImageCollection(COLLECTION)
             .filterDate(f"{year}-01-01", stop.isoformat())
             .select(band).toBands().toFloat().unmask(NODATA))
    request = {"expression": image, "fileFormat": "NPY", "grid": GRID}
    for attempt in range(1, RETRIES + 1):
        try:
            raw = ee.data.computePixels(request)
            # NUMPY_NDARRAY trips numpy's header-size guard (one field per day), so load raw NPY.
            arr = np.load(io.BytesIO(raw), max_header_size=10**7)
            dates = [dt.datetime.strptime(f[:8], "%Y%m%d") for f in arr.dtype.names]
            data = np.stack([arr[f] for f in arr.dtype.names]).astype("float32")
            data[data == NODATA] = np.nan
            ds = xr.Dataset(
                {band: (("time", "latitude", "longitude"), data, {"units": BANDS[band]})},
                coords={"time": np.array(dates, dtype="datetime64[ns]"),
                        "latitude": LATS, "longitude": LONS},
                attrs={"source": f"Google Earth Engine {COLLECTION}",
                       "note": "daily values from hourly ERA5-Land, UTC days; NaN = sea"},
            )
            part = target.with_suffix(".nc.part")
            ds.to_netcdf(part, encoding={band: {"zlib": True, "complevel": 4}})
            part.replace(target)
            return f"done {name} ({len(dates)} days, {target.stat().st_size / 1e6:.1f} MB)"
        except Exception as exc:  # quota / transient errors are retried with backoff
            msg = str(exc).splitlines()[-1] if str(exc) else repr(exc)
            log.warning("failed %s attempt %d: %s", name, attempt, msg)
            target.with_suffix(".nc.part").unlink(missing_ok=True)
            time.sleep(min(60, 5 * 2 ** (attempt - 1)))
    return f"FAILED {name}"


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[logging.FileHandler(ROOT / "download.log"), logging.StreamHandler(sys.stdout)],
    )
    init_ee()
    latest = ee.Date(ee.ImageCollection(COLLECTION).aggregate_max("system:time_start"))
    end = dt.date.fromisoformat(latest.format("YYYY-MM-dd").getInfo()) + dt.timedelta(days=1)
    jobs = [(band, year) for year in range(FIRST_YEAR, end.year + 1) for band in BANDS]
    log.info("starting: %d requests (%s to %s), up to %d in parallel",
             len(jobs), FIRST_YEAR, end - dt.timedelta(days=1), MAX_PARALLEL)
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        futures = [pool.submit(download, band, year, end) for band, year in jobs]
        for fut in as_completed(futures):
            result = fut.result()
            failed += result.startswith("FAILED")
            log.info(result)
    log.info("finished in %.1f min: %d of %d requests failed", (time.time() - t0) / 60, failed, len(jobs))


if __name__ == "__main__":
    main()
