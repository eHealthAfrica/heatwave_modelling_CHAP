"""Static ward table: synthetic behaviour and real frozen metadata (FEAT-03)."""
import copy
import json

import numpy as np
import pytest
from shapely.geometry import shape

from heatwave.forecast.config import DataConfig
from heatwave.forecast.data import FrozenDataError
from heatwave.forecast.fixtures import (
    SYNTHETIC_WARDS,
    add_synthetic_static,
    build_synthetic_frozen,
    synthetic_static_sources,
)
from heatwave.forecast.static import GEOZONES, build_static_table, load_static

REAL_FLAGGED = {"NASAKW04", "PLSBSA20", "PLSBKK06", "PLSTNK08", "PLSQAP14", "BNSVDY02"}


def _src():
    geo, rows = synthetic_static_sources(SYNTHETIC_WARDS)
    return copy.deepcopy(geo), copy.deepcopy(rows)


def test_build_synthetic():
    geo, rows = _src()
    st = build_static_table(geo, rows, SYNTHETIC_WARDS)
    assert st.wards == SYNTHETIC_WARDS
    assert st.lat.dtype == np.float32 and st.lon.dtype == np.float32
    c = shape(geo["features"][4]["geometry"]).centroid
    assert st.lat[5] == np.float32(c.y) and st.lon[5] == np.float32(c.x)
    assert st.lat[4] == st.lat[5]
    assert st.lga_average_ward.tolist() == [False] * 5 + [True]
    assert st.empty_geometry.tolist() == [False] * 5 + [True]
    assert st.geozone == ("NWZ", "NWZ", "NEZ", "NEZ", "NCZ", "NCZ")
    assert len(set(st.lga_id.tolist())) == 3 and len(set(st.state_id.tolist())) == 3
    assert st.lga_id[0] == st.lga_id[1] != st.lga_id[2]
    assert not st.lat.flags.writeable


def test_align():
    geo, rows = _src()
    st = build_static_table(geo, rows, SYNTHETIC_WARDS)
    sub = st.align((SYNTHETIC_WARDS[3], SYNTHETIC_WARDS[0]))
    assert sub.wards == (SYNTHETIC_WARDS[3], SYNTHETIC_WARDS[0])
    assert sub.lga_id.tolist() == [st.lga_id[3], st.lga_id[0]]
    assert sub.lat[0] == st.lat[3]
    with pytest.raises(KeyError):
        st.align(("NOPE",))


def _bad_extra(geo, rows):
    geo["features"].append(copy.deepcopy(geo["features"][0]))
    geo["features"][-1]["properties"]["wardcode"] = "XXXXX001"


def _bad_dup(geo, rows):
    geo["features"].append(copy.deepcopy(geo["features"][0]))


def _bad_zone(geo, rows):
    geo["features"][0]["properties"]["geozone"] = "SSZ"


def _bad_flag_ward(geo, rows):
    rows[0]["location"] = "NOWARD01"


def _bad_flag_lga(geo, rows):
    rows[0]["lgacode"] = "99999"


def _bad_empty_lga(geo, rows):
    geo["features"][4]["geometry"] = {"type": "MultiPoint", "coordinates": []}


@pytest.mark.parametrize("mut", [_bad_extra, _bad_dup, _bad_zone, _bad_flag_ward, _bad_flag_lga, _bad_empty_lga])
def test_validation_failures(mut):
    geo, rows = _src()
    mut(geo, rows)
    with pytest.raises(FrozenDataError):
        build_static_table(geo, rows, SYNTHETIC_WARDS)


def test_missing_ward_fails():
    geo, rows = _src()
    del geo["features"][1]
    with pytest.raises(FrozenDataError):
        build_static_table(geo, rows, SYNTHETIC_WARDS)


def test_lgacode_padding_tolerated():
    geo, rows = _src()
    rows[0]["lgacode"] = "07023"
    assert build_static_table(geo, rows, SYNTHETIC_WARDS).lga_average_ward.sum() == 1


@pytest.fixture
def sf(tmp_path):
    return add_synthetic_static(build_synthetic_frozen(tmp_path))


def _dcfg(sf):
    return DataConfig("covariates-v1.0", "frozen", sf.sha256)


def test_load_static_synthetic(sf):
    st = load_static(_dcfg(sf), sf.wards, data_root=sf.data_root)
    assert st.wards == sf.wards and st.lga_average_ward.sum() == 1


@pytest.mark.parametrize("rel", ["inputs/wards.geojson", "wards_lga_average.csv"])
def test_load_static_tamper(sf, rel):
    p = sf.dataset_dir / rel
    b = bytearray(p.read_bytes())
    b[-2] ^= 0x01
    p.write_bytes(bytes(b))
    with pytest.raises(FrozenDataError):
        load_static(_dcfg(sf), sf.wards, data_root=sf.data_root)


@pytest.mark.parametrize("section,key", [("inputs_sha256", "wards.geojson"), ("outputs_sha256", "wards_lga_average.csv")])
def test_load_static_missing_key(sf, section, key):
    m = json.loads(sf.manifest_path.read_text())
    del m[section][key]
    sf.manifest_path.write_text(json.dumps(m))
    with pytest.raises(FrozenDataError):
        load_static(_dcfg(sf), sf.wards, data_root=sf.data_root)


@pytest.mark.frozen
def test_real_static(forecast_cfg, frozen_panel):
    st = load_static(forecast_cfg.data, frozen_panel.wards)
    assert len(st.wards) == 4841 and set(st.wards) == set(frozen_panel.wards)
    assert st.wards == frozen_panel.wards
    flagged = {w for w, f in zip(st.wards, st.lga_average_ward) if f}
    empty = {w for w, f in zip(st.wards, st.empty_geometry) if f}
    assert flagged == empty == REAL_FLAGGED
    counts = {z: st.geozone.count(z) for z in GEOZONES}
    assert counts == {"NWZ": 2004, "NCZ": 1518, "NEZ": 1319}
    assert not np.isnan(st.lat).any() and not np.isnan(st.lon).any()
    assert st.lat.min() >= 4.0 and st.lat.max() <= 14.5
    assert st.lon.min() >= 2.5 and st.lon.max() <= 15.0
