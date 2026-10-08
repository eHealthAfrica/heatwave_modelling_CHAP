"""Static ward table: location, geozone, LGA/state groups, LGA-average flag (FEAT-03).

Read only from the frozen, hash-verified ``inputs/wards.geojson`` and
``wards_lga_average.csv``: the raw bytes are hashed against the MANIFEST and the
same bytes are then parsed. Files are only ever opened "rb". No ward id is exposed
as a model feature; ``lga_id`` / ``state_id`` are grouping codes for spatial context.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union

from heatwave.forecast.config import DataConfig
from heatwave.forecast.data import FrozenDataError, frozen_dataset_dir, read_manifest

GEOZONES = ("NWZ", "NEZ", "NCZ")
WARDS_GEOJSON_KEY = "wards.geojson"  # MANIFEST inputs_sha256 key; file under inputs/
LGA_AVERAGE_KEY = "wards_lga_average.csv"  # MANIFEST outputs_sha256 key


def _norm_lga(x) -> str:
    return str(x).strip().lstrip("0")


@dataclass(frozen=True, eq=False)
class StaticTable:
    wards: tuple
    lat: np.ndarray  # float32 (n,)
    lon: np.ndarray  # float32 (n,)
    geozone: tuple
    statename: tuple
    lgacode: tuple  # strings exactly as in the geojson
    lga_id: np.ndarray  # int32 dense code of (statename, normalised lgacode)
    state_id: np.ndarray  # int32
    lga_average_ward: np.ndarray  # bool
    empty_geometry: np.ndarray  # bool

    def __post_init__(self):
        for arr in (self.lat, self.lon, self.lga_id, self.state_id, self.lga_average_ward, self.empty_geometry):
            arr.flags.writeable = False
        object.__setattr__(self, "_pos", {w: i for i, w in enumerate(self.wards)})

    def align(self, wards) -> "StaticTable":
        """Subset/reorder to exactly ``wards``; dense ids are kept (not renumbered)."""
        try:
            pos = np.array([self._pos[w] for w in wards], dtype=np.int64)
        except KeyError as exc:
            raise KeyError(f"ward {exc.args[0]!r} not in static table") from None
        return StaticTable(
            wards=tuple(wards),
            lat=self.lat[pos].copy(),
            lon=self.lon[pos].copy(),
            geozone=tuple(self.geozone[i] for i in pos),
            statename=tuple(self.statename[i] for i in pos),
            lgacode=tuple(self.lgacode[i] for i in pos),
            lga_id=self.lga_id[pos].copy(),
            state_id=self.state_id[pos].copy(),
            lga_average_ward=self.lga_average_ward[pos].copy(),
            empty_geometry=self.empty_geometry[pos].copy(),
        )


def build_static_table(geojson: dict, lga_rows: list, wards: tuple) -> StaticTable:
    """Pure builder; raises FrozenDataError on any metadata inconsistency."""
    feats = geojson.get("features") if isinstance(geojson, dict) else None
    if not isinstance(feats, list):
        raise FrozenDataError("wards geojson has no features list")
    recs = {}
    for f in feats:
        p = f.get("properties") or {}
        code = p.get("wardcode")
        if code is None:
            raise FrozenDataError("geojson feature without wardcode")
        if code in recs:
            raise FrozenDataError(f"duplicate wardcode in geojson: {code}")
        recs[code] = (p, f.get("geometry"))
    wards = tuple(wards)
    if len(set(wards)) != len(wards):
        raise FrozenDataError("duplicate wards in requested ward tuple")
    missing = sorted(set(wards) - set(recs))
    extra = sorted(set(recs) - set(wards))
    if missing or extra:
        raise FrozenDataError(
            f"ward set mismatch: {len(missing)} missing from geojson {missing[:5]}, "
            f"{len(extra)} extra in geojson {extra[:5]}"
        )
    for code, (p, _g) in recs.items():
        if p.get("geozone") not in GEOZONES:
            raise FrozenDataError(f"ward {code} geozone {p.get('geozone')!r} not in {GEOZONES}")

    flagged = {}
    for r in lga_rows:
        loc = str(r["location"]).strip()
        if loc not in recs:
            raise FrozenDataError(f"LGA-average ward {loc} not in ward set")
        if _norm_lga(r["lgacode"]) != _norm_lga(recs[loc][0].get("lgacode")):
            raise FrozenDataError(
                f"LGA-average ward {loc}: csv lgacode {r['lgacode']!r} != geojson {recs[loc][0].get('lgacode')!r}"
            )
        flagged[loc] = True

    def key(p):
        return (str(p.get("statename")), _norm_lga(p.get("lgacode")))

    geoms = {}
    empty = {}
    for code, (p, g) in recs.items():
        geom = shape(g) if g is not None else None
        empty[code] = geom is None or geom.is_empty
        geoms[code] = geom
    by_lga = {}
    for code, (p, _g) in recs.items():
        if not empty[code]:
            by_lga.setdefault(key(p), []).append(geoms[code])

    lat = np.empty(len(wards), np.float32)
    lon = np.empty(len(wards), np.float32)
    for i, code in enumerate(wards):
        p = recs[code][0]
        if empty[code]:
            members = by_lga.get(key(p))
            if not members:
                raise FrozenDataError(f"empty-geometry ward {code}: LGA {key(p)} has no non-empty ward")
            c = unary_union(members).centroid
        else:
            c = geoms[code].centroid
        lon[i], lat[i] = c.x, c.y

    lga_keys = sorted({key(recs[w][0]) for w in wards})
    lga_code = {k: j for j, k in enumerate(lga_keys)}
    states = sorted({str(recs[w][0].get("statename")) for w in wards})
    state_code = {s: j for j, s in enumerate(states)}
    return StaticTable(
        wards=wards,
        lat=lat,
        lon=lon,
        geozone=tuple(recs[w][0]["geozone"] for w in wards),
        statename=tuple(str(recs[w][0].get("statename")) for w in wards),
        lgacode=tuple(str(recs[w][0].get("lgacode")) for w in wards),
        lga_id=np.array([lga_code[key(recs[w][0])] for w in wards], dtype=np.int32),
        state_id=np.array([state_code[str(recs[w][0].get("statename"))] for w in wards], dtype=np.int32),
        lga_average_ward=np.array([w in flagged for w in wards], dtype=bool),
        empty_geometry=np.array([empty[w] for w in wards], dtype=bool),
    )


def _read_verified(path: Path, section: dict, key: str, section_name: str) -> bytes:
    expected = section.get(key) if isinstance(section, dict) else None
    if not expected:
        raise FrozenDataError(f"MANIFEST {section_name} has no sha256 for {key}")
    if not path.is_file():
        raise FrozenDataError(f"frozen file missing: {path}")
    with open(path, "rb") as fh:
        raw = fh.read()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise FrozenDataError(f"sha256 mismatch for {key} (frozen metadata altered)")
    return raw


def load_static(data_cfg: DataConfig, wards, data_root=None) -> StaticTable:
    """Hash-verified static table aligned to ``wards`` (Panel.wards order)."""
    d = frozen_dataset_dir(data_cfg, data_root)
    manifest = read_manifest(d)
    raw_geo = _read_verified(d / "inputs" / "wards.geojson", manifest.get("inputs_sha256"), WARDS_GEOJSON_KEY, "inputs_sha256")
    raw_csv = _read_verified(d / LGA_AVERAGE_KEY, manifest.get("outputs_sha256"), LGA_AVERAGE_KEY, "outputs_sha256")
    try:
        geojson = json.loads(raw_geo.decode("utf-8"))
        rows = list(csv.DictReader(io.StringIO(raw_csv.decode("utf-8"), newline="")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FrozenDataError(f"static metadata unparseable: {exc}") from exc
    return build_static_table(geojson, rows, tuple(wards))
