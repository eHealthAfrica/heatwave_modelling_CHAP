"""Slice and ward-flag definitions shared by the harness and the report (EVAL-04).

Single definitions of seasons (by the mid-week day), latitude bands (same
inequalities as ``report.prevalence_tables``), target years, and the ward flags
``small`` (geometry area < 0.01 deg^2, about one 0.1 x 0.1 degree ERA5-Land cell;
both areas scale with cos(lat) so the degree-squared comparison is exact) and
LGA-average. Slice confidence intervals are exploratory.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from shapely.geometry import shape

from heatwave.forecast import static as static_mod
from heatwave.forecast.data import frozen_dataset_dir, read_manifest
from heatwave.forecast.report import LAT_FAR_NORTH, LAT_MIDDLE_BELT

SEASONS = ("DJF", "MAM", "JJA", "SON")
HIGHLIGHT_SEASON = "MAM"
SMALL_WARD_AREA_DEG2 = 0.01
LAT_BANDS = ("far_north", "central", "middle_belt")
FLAG_FILTERS = ("all_wards", "large_wards_only", "exclude_lga_average", "lga_average_only")
FAMILIES = ("all", "season", "geozone", "lat_band", "year")

_SEASON_BY_MONTH = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
                    6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}


def season_of(week_start) -> np.ndarray:
    """Season of the mid-week day (week start + 3 days) as an array of strings."""
    d = np.asarray(week_start).astype("datetime64[D]") + np.timedelta64(3, "D")
    months = (d.astype("datetime64[M]").astype(np.int64) % 12) + 1
    return np.array([_SEASON_BY_MONTH[int(m)] for m in np.atleast_1d(months)], dtype=object).reshape(d.shape)


def lat_band(lat) -> np.ndarray:
    """far_north (> 11.5), middle_belt (< 9.5), else central; same as report.prevalence_tables."""
    lat = np.asarray(lat, dtype=np.float64)
    return np.where(lat > LAT_FAR_NORTH, "far_north", np.where(lat < LAT_MIDDLE_BELT, "middle_belt", "central")).astype(object)


def ward_areas_deg2(geojson: dict, wards) -> np.ndarray:
    """Polygon area in deg^2 per ward (nan for empty or missing geometry)."""
    area = {}
    for f in geojson.get("features", []):
        code = (f.get("properties") or {}).get("wardcode")
        geom = f.get("geometry")
        a = np.nan
        if geom:
            try:
                g = shape(geom)
                if not g.is_empty:
                    a = float(g.area)
            except (ValueError, TypeError, AttributeError):
                a = np.nan
        area[code] = a
    return np.array([area.get(w, np.nan) for w in wards], dtype=np.float64)


def load_ward_areas(data_cfg, wards, data_root=None) -> np.ndarray:
    """Areas from the hash-verified frozen wards.geojson (read only)."""
    d = frozen_dataset_dir(data_cfg, data_root)
    manifest = read_manifest(d)
    raw = static_mod._read_verified(
        d / "inputs" / "wards.geojson", manifest.get("inputs_sha256"), static_mod.WARDS_GEOJSON_KEY, "inputs_sha256"
    )
    return ward_areas_deg2(json.loads(raw.decode("utf-8")), wards)


def small_ward_flags(areas) -> np.ndarray:
    a = np.asarray(areas, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        return np.isfinite(a) & (a < SMALL_WARD_AREA_DEG2)


def ward_attributes(static, areas) -> pd.DataFrame:
    """Per-ward geozone, lat_band, lga_average, empty_geometry, small (indexed by ward code)."""
    return pd.DataFrame(
        {
            "geozone": np.asarray(static.geozone, dtype=object),
            "lat_band": lat_band(static.lat),
            "lga_average": np.asarray(static.lga_average_ward, dtype=bool),
            "empty_geometry": np.asarray(static.empty_geometry, dtype=bool),
            "small": small_ward_flags(areas),
        },
        index=pd.Index(list(static.wards), name="ward"),
    )


def week_attributes(target_week_index, target_week_start, target_week_label) -> pd.DataFrame:
    """Season and ISO year per distinct target week (indexed by target_week_index)."""
    idx = np.asarray(target_week_index)
    start = np.asarray(target_week_start).astype("datetime64[D]")
    label = np.asarray(target_week_label).astype(str)
    uniq, first = np.unique(idx, return_index=True)
    return pd.DataFrame(
        {
            "season": season_of(start[first]),
            "year": np.array([int(s[:4]) for s in label[first]], dtype=np.int64),
        },
        index=pd.Index(uniq, name="target_week_index"),
    )


def _flag_mask(name: str, small, lga_avg) -> np.ndarray:
    if name == "all_wards":
        return np.ones(len(small), dtype=bool)
    if name == "large_wards_only":
        return ~small
    if name == "exclude_lga_average":
        return ~lga_avg
    if name == "lga_average_only":
        return lga_avg
    raise ValueError(f"unknown flag filter {name!r}")


def row_slice_masks(ward_codes, target_week_index, ward_attrs, week_attrs, *,
                    families=FAMILIES, flag_filters=FLAG_FILTERS) -> dict:
    """{(family, stratum, flag_filter): bool mask over rows}."""
    wa = ward_attrs.loc[list(ward_codes)] if not isinstance(ward_codes, pd.Index) else ward_attrs.loc[ward_codes]
    ks = week_attrs.loc[np.asarray(target_week_index)]
    n = len(wa)
    small = wa["small"].to_numpy(dtype=bool)
    lga_avg = wa["lga_average"].to_numpy(dtype=bool)
    strata = {
        "all": [("all", np.ones(n, dtype=bool))],
        "season": [(s, ks["season"].to_numpy() == s) for s in SEASONS],
        "geozone": [(g, wa["geozone"].to_numpy() == g) for g in static_mod.GEOZONES],
        "lat_band": [(b, wa["lat_band"].to_numpy() == b) for b in LAT_BANDS],
        "year": [(int(y), ks["year"].to_numpy() == y) for y in sorted(ks["year"].unique())],
    }
    out = {}
    for fam in families:
        if fam not in strata:
            raise ValueError(f"unknown slice family {fam!r}")
        for stratum, m in strata[fam]:
            for ff in flag_filters:
                out[(fam, stratum, ff)] = m & _flag_mask(ff, small, lga_avg)
    return out
