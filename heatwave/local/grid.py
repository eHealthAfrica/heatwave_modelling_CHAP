"""Ward boundaries on disk and area weights from ERA5-Land grid cells to wards."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.ops import unary_union

RES = 0.1  # ERA5-Land native grid spacing, degrees; cell centres sit on multiples of 0.1


def fetch_wards(asset_id: str, path: Path) -> None:
    """Download the ward FeatureCollection from Earth Engine to a GeoJSON file."""
    import ee

    from heatwave.auth import init_ee

    init_ee()
    features, token = [], None
    while True:
        params = {"assetId": asset_id, "pageSize": 1000}
        if token:
            params["pageToken"] = token
        page = ee.data.listFeatures(params)
        features += page["features"]
        token = page.get("nextPageToken")
        if not token:
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    part.replace(path)


def load_wards(path: Path, id_property: str = "wardcode",
               lga_property: str = "lgacode") -> tuple[list[str], list, list[str]]:
    """(ward ids, shapely geometries, LGA codes) from a GeoJSON file, in file order."""
    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    ids = [str(f["properties"][id_property]) for f in features]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{id_property} is not unique across wards")
    lgas = [str(f["properties"][lga_property]) for f in features]
    return ids, [shape(f["geometry"]) for f in features], lgas


def fill_empty_from_lga(geoms: list, lgas: list[str]) -> tuple[list, list[int]]:
    """Give each ward with an empty geometry the outline of its whole LGA.

    The LGA outline is the union of the LGA's other wards, so the ward's value becomes the
    area-weighted LGA average. Returns the new geometries and the indices that were filled.
    """
    out, filled = list(geoms), []
    for i, geom in enumerate(geoms):
        if not geom.is_empty:
            continue
        siblings = [g for g, lga in zip(geoms, lgas) if lga == lgas[i] and not g.is_empty]
        if not siblings:
            raise ValueError(f"ward {i} has no geometry and no other ward in LGA {lgas[i]}")
        out[i] = unary_union(siblings)
        filled.append(i)
    return out, filled


@dataclass(frozen=True)
class WardWeights:
    """Sparse (ward, cell) weights; each ward's weights sum to 1.

    `cells` index the flattened (latitude, longitude) grid. Entries are sorted by ward,
    and `starts[i]` is the first entry of ward i, ready for np.add.reduceat.
    """
    wards: np.ndarray
    cells: np.ndarray
    weights: np.ndarray
    starts: np.ndarray
    n_point_wards: int     # wards given as points, valued at the cell they fall in
    n_nearest_wards: int   # wards overlapping only no-data cells, valued at the nearest valid cell

    def reduce(self, grid: np.ndarray) -> np.ndarray:
        """(days, n_cells) gridded values -> (days, n_wards) weighted ward means."""
        return np.add.reduceat(grid[:, self.cells] * self.weights, self.starts, axis=1)


def build_weights(geoms: list, lats: np.ndarray, lons: np.ndarray, valid: np.ndarray) -> WardWeights:
    """Area-weight each ward over the grid cells it overlaps.

    lats/lons are the grid's cell centres; `valid` (lat, lon) marks cells with data (ERA5-Land
    has none over sea and large lakes). Overlap areas are in square degrees scaled by
    cos(latitude), so they're proportional to true area. Polygon wards use overlap area with
    valid cells; point wards use the cell(s) they fall in; a ward whose overlap is all
    no-data cells falls back to the valid cell nearest its centroid.
    """
    n_lon = len(lons)
    lat0, lon0 = lats[0], lons[0]
    lat_step = lats[1] - lats[0]  # negative: north-to-south
    valid_idx = np.flatnonzero(valid.ravel())
    valid_lat = lats[valid_idx // n_lon]
    valid_lon = lons[valid_idx % n_lon]

    def cell_of(lon: float, lat: float) -> int:
        i = int(round((lat - lat0) / lat_step))
        j = int(round((lon - lon0) / RES))
        if not (0 <= i < len(lats) and 0 <= j < n_lon):
            raise ValueError(f"point ({lon}, {lat}) is outside the grid")
        return i * n_lon + j

    def nearest_valid(lon: float, lat: float) -> int:
        d2 = (valid_lat - lat) ** 2 + ((valid_lon - lon) * np.cos(np.radians(lat))) ** 2
        return int(valid_idx[np.argmin(d2)])

    wards, cells, weights = [], [], []
    n_point = n_nearest = 0
    for w, geom in enumerate(geoms):
        if geom.is_empty:
            raise ValueError(f"ward {w} has an empty geometry; drop it before building weights")
        if geom.geom_type in ("Point", "MultiPoint"):
            n_point += 1
            pts = list(geom.geoms) if geom.geom_type == "MultiPoint" else [geom]
            ids = np.unique([cell_of(p.x, p.y) for p in pts])
            ids = ids[valid.ravel()[ids]]
            if ids.size == 0:
                ids = np.array([nearest_valid(geom.centroid.x, geom.centroid.y)])
            wts = np.ones(ids.size)
        else:
            minx, miny, maxx, maxy = geom.bounds
            i0 = max(0, int(np.floor((maxy - lat0) / lat_step - 0.5)))
            i1 = min(len(lats) - 1, int(np.ceil((miny - lat0) / lat_step + 0.5)))
            j0 = max(0, int(np.floor((minx - lon0) / RES - 0.5)))
            j1 = min(n_lon - 1, int(np.ceil((maxx - lon0) / RES + 0.5)))
            ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
            ii, jj = ii.ravel(), jj.ravel()
            boxes = shapely.box(lons[jj] - RES / 2, lats[ii] - RES / 2,
                                lons[jj] + RES / 2, lats[ii] + RES / 2)
            area = shapely.area(shapely.intersection(geom, boxes)) * np.cos(np.radians(lats[ii]))
            ids = ii * n_lon + jj
            # Drop float slivers where a ward edge lies on a cell edge (< 1e-6 of the ward).
            keep = (area > 1e-6 * area.sum()) & valid.ravel()[ids]
            ids, wts = ids[keep], area[keep]
            if ids.size == 0:
                n_nearest += 1
                ids, wts = np.array([nearest_valid(geom.centroid.x, geom.centroid.y)]), np.ones(1)
        wards.append(np.full(ids.size, w))
        cells.append(ids)
        weights.append(wts / wts.sum())

    wards_a = np.concatenate(wards)
    starts = np.flatnonzero(np.r_[True, wards_a[1:] != wards_a[:-1]])
    if len(starts) != len(geoms):
        raise AssertionError("every ward must have at least one weighted cell")
    return WardWeights(wards_a, np.concatenate(cells), np.concatenate(weights).astype("float32"),
                       starts, n_point, n_nearest)
