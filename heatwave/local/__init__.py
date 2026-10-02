"""Local (numpy) pipeline: ERA5-Land NetCDF files on disk -> weekly ward covariate table.

Runs the same climatology / detection / weekly-aggregation method as the Earth Engine
pipeline, but on locally downloaded data, so the full 1991-present history for every ward
runs on one machine instead of hitting Earth Engine's ~12-hour per-task timeout.
"""
