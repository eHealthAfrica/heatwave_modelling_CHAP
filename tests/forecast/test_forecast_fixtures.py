"""Tests for the Phase 9 synthetic panel / manipulation / static fixtures."""
import hashlib
import json

import numpy as np
import pytest

from heatwave.forecast import weeks
from heatwave.forecast.data import VARIABLES, sha256_file
from heatwave.forecast.fixtures import (
    SYNTHETIC_WARDS,
    add_synthetic_static,
    build_synthetic_frozen,
    poison_future,
    subset_panel,
    synthetic_panel,
    synthetic_static_sources,
    truncate_panel,
)

V = {v: i for i, v in enumerate(VARIABLES)}


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel()


def test_shape_dtype_and_labels(panel):
    t = weeks.label_to_index("2003-W20") - weeks.label_to_index("1991-W02") + 1
    assert panel.shape == (6, t, 8)
    assert panel.values.dtype == np.float32
    assert not panel.values.flags.writeable
    assert "1992-W53" in panel.week_labels and "1998-W53" in panel.week_labels
    assert panel.wards == SYNTHETIC_WARDS


def test_seed_determinism(panel):
    assert np.array_equal(synthetic_panel(seed=0).values, panel.values)
    assert not np.array_equal(synthetic_panel(seed=1).values, panel.values)


def test_ranges_and_prevalence(panel):
    for name in ("heatwave_days", "hot_nights", "heatwave_event_count"):
        x = panel.values[:, :, V[name]]
        assert x.min() >= 0 and x.max() <= 7
        assert np.array_equal(x, np.round(x))
    hw = panel.values[:, :, V["heatwave_days"]] >= 3
    assert 0.05 < hw.mean() < 0.40
    assert (hw != (panel.values[:, :, V["heatwave_event_count"]] >= 1)).any()


def test_long_panel():
    p = synthetic_panel(last_week="2021-W20")
    assert p.week_labels[-1] == "2021-W20"


def test_truncate_poison_subset_do_not_mutate(panel):
    before = panel.values.copy()
    tr = truncate_panel(panel, 100)
    assert tr.shape == (6, 101, 8) and np.array_equal(tr.values, before[:, :101])
    for mode in ("garbage", "nan"):
        po = poison_future(panel, 100, mode=mode)
        assert np.array_equal(po.values[:, :101], before[:, :101])
        after = po.values[:, 101:]
        assert np.isnan(after).all() if mode == "nan" else (after > 1e5).all()
        assert po.sha256 != panel.sha256
    with pytest.raises(ValueError):
        poison_future(panel, 100, mode="bogus")
    sub = subset_panel(panel, [3, 1, 3])
    assert sub.wards == (SYNTHETIC_WARDS[1], SYNTHETIC_WARDS[3])
    assert np.array_equal(sub.values, before[[1, 3]])
    with pytest.raises(ValueError):
        subset_panel(panel, [])
    with pytest.raises(ValueError):
        subset_panel(panel, [6])
    assert np.array_equal(panel.values, before)


def test_static_sources():
    geo, rows = synthetic_static_sources()
    feats = {f["properties"]["wardcode"]: f for f in geo["features"]}
    assert set(feats) == set(SYNTHETIC_WARDS)
    assert feats["SOCCC002"]["geometry"]["coordinates"] == []
    assert feats["SOCCC001"]["properties"]["lgacode"] == "7023"
    assert rows == [{"location": "SOCCC002", "lgacode": "7023"}]


def test_add_synthetic_static(tmp_path):
    sf = add_synthetic_static(build_synthetic_frozen(tmp_path))
    m = json.loads(sf.manifest_path.read_text(encoding="utf-8"))
    geo = sf.dataset_dir / "inputs" / "wards.geojson"
    csv = sf.dataset_dir / "wards_lga_average.csv"
    assert m["inputs_sha256"]["wards.geojson"] == sha256_file(geo)
    assert m["outputs_sha256"]["wards_lga_average.csv"] == sha256_file(csv)
    assert len(json.loads(geo.read_text(encoding="utf-8"))["features"]) == 6
    assert csv.read_text(encoding="utf-8").splitlines()[0] == "location,lgacode"


def test_default_build_unchanged(tmp_path):
    sf = build_synthetic_frozen(tmp_path)
    m = json.loads(sf.manifest_path.read_text(encoding="utf-8"))
    assert "wards_lga_average.csv" not in m["outputs_sha256"]
    assert hashlib.sha256(sf.parquet_path.read_bytes()).hexdigest() == sf.sha256
