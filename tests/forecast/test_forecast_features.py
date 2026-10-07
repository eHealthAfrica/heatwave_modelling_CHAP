"""As-of feature families: helpers, hand-checked values, warm-up, memory-safe real build."""
import re
from datetime import date

import numpy as np
import pytest

from heatwave.forecast import features as F
from heatwave.forecast import targets, weeks
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.features import (
    REGISTRY,
    base_rate,
    build_feature_store,
    group_mean,
    lag,
    season_features,
    static_feature_matrix,
    trail_mean,
    trail_sum,
)
from heatwave.forecast.fixtures import (
    SYNTHETIC_WARDS,
    subset_panel,
    synthetic_panel,
    synthetic_static_sources,
)
from heatwave.forecast.registry import FORBIDDEN_NAME_PATTERN, Registry
from heatwave.forecast.static import build_static_table


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel()


@pytest.fixture(scope="module")
def clim(panel):
    return Climatology.fit(panel, date(1999, 1, 4))


@pytest.fixture(scope="module")
def static(panel):
    geo, rows = synthetic_static_sources()
    return build_static_table(geo, rows, panel.wards)


@pytest.fixture(scope="module")
def store(panel, clim, static):
    return build_feature_store(panel, clim, static)


def first_valid(a):
    ok = ~np.isnan(a).any(axis=0)
    return int(np.argmax(ok)) if ok.any() else None


# ------------------------------------------------------------------ helpers
def test_lag_and_trailing_hand_checked():
    x = np.arange(24, dtype=np.float32).reshape(2, 12)
    assert np.array_equal(lag(x, 0), x)
    l2 = lag(x, 2)
    assert np.isnan(l2[:, :2]).all() and np.array_equal(l2[:, 2:], x[:, :-2])
    m4 = trail_mean(x, 4)
    assert np.isnan(m4[:, :3]).all()
    for t in range(3, 12):
        assert m4[0, t] == pytest.approx(x[0, t - 3 : t + 1].mean())
    s3 = trail_sum(x, 3)
    assert np.isnan(s3[:, :2]).all() and s3[1, 5] == x[1, 3:6].sum()
    assert m4.dtype == s3.dtype == l2.dtype == np.float32
    assert trail_mean(x, 20).shape == x.shape and np.isnan(trail_mean(x, 20)).all()


def test_trailing_does_not_use_future():
    x = np.random.default_rng(0).normal(size=(3, 40)).astype(np.float32)
    y = x.copy()
    y[:, 25:] = 1e9
    for fn, k in ((trail_mean, 8), (trail_sum, 8), (lag, 3)):
        assert np.array_equal(fn(x, k)[:, :25], fn(y, k)[:, :25], equal_nan=True)


# ------------------------------------------------------------------ threshold consistency
def test_threshold_matches_targets():
    assert F.HW_DAYS_THRESHOLD == targets.HEATWAVE_DAYS_THRESHOLD


# ------------------------------------------------------------------ recent heat / land
def test_recent_heat_values(panel, clim, store):
    hd = panel.values[:, :, list(panel.variables).index("heatwave_days")]
    mhi = clim.anomaly(panel, "mean_heat_index")
    pr = clim.anomaly(panel, "total_precipitation_mm")
    assert np.array_equal(store["hd_roll4"], trail_mean(hd, 4), equal_nan=True)
    assert np.array_equal(store["mhi_anom_lag1"], lag(mhi, 1), equal_nan=True)
    assert np.array_equal(store["hw_lag0"], (hd >= 3).astype(np.float32))
    assert np.array_equal(store["pr_anom_sum8"], trail_sum(pr, 8), equal_nan=True)
    assert np.array_equal(store["hd_lag3"][:, 3:], hd[:, :-3])


def test_shapes_dtypes_and_counts(store, panel):
    assert store.names == REGISTRY.names(kind="panel") and len(store.names) == 49
    for nm in store.names:
        a = store[nm]
        assert a.dtype == np.float32 and a.shape == panel.values.shape[:2]
        assert not a.flags.writeable
    fams = {f: len(REGISTRY.names(family=f)) for f in ("recent_heat", "land_humidity", "trend", "spatial")}
    assert fams == {"recent_heat": 35, "land_humidity": 6, "trend": 4, "spatial": 4}


# ------------------------------------------------------------------ base rate
def _ref_base_rate(hw, week_start, t, years=10, pool=2):
    """Independent per-t loop using ISO tuples to positions through a dict."""
    pos_of = {}
    for i, w in enumerate(week_start):
        iso = w.astype(object).isocalendar()
        pos_of[(iso.year, iso.week)] = i
    iso = week_start[t].astype(object).isocalendar()
    vals = []
    for j in range(1, years + 1):
        y = iso.year - j
        wk = min(iso.week, date(y, 12, 28).isocalendar().week)
        anchor = date.fromisocalendar(y, wk, 1)
        for d in range(-pool, pool + 1):
            a = anchor + __import__("datetime").timedelta(weeks=d)
            ai = a.isocalendar()
            p = pos_of.get((ai.year, ai.week))
            if p is not None and p <= t:
                vals.append(hw[:, p])
    return (np.mean(vals, axis=0) if len(vals) >= 15 else None), len(vals)


def test_base_rate_matches_reference(panel):
    hw = (panel.values[:, :, 0] >= 3).astype(np.float32)
    vals, counts = base_rate(hw, panel.week_start)
    T = hw.shape[1]
    for t in list(range(0, T, 17)) + [158, 159, 160]:
        ref, c = _ref_base_rate(hw, panel.week_start, t)
        assert counts[t] == c
        if ref is None:
            assert np.isnan(vals[:, t]).all()
        else:
            assert np.allclose(vals[:, t], ref, atol=1e-6)


def test_base_rate_ignores_current_year(panel):
    T = panel.values.shape[1]
    zeros = np.zeros((3, T), dtype=np.float32)
    t = 400
    base, _ = base_rate(zeros, panel.week_start)
    pois = zeros.copy()
    pois[:, t - 10 : t] = 1.0
    pois[:, t + 1 : t + 3] = 1.0
    v, _ = base_rate(pois, panel.week_start)
    assert np.array_equal(v[:, t], base[:, t])


def test_base_rate_week53_origin(panel):
    labels = list(panel.week_labels)
    t = labels.index("1998-W53")
    hw = (panel.values[:, :, 0] >= 3).astype(np.float32)
    v, counts = base_rate(hw, panel.week_start)
    ref, c = _ref_base_rate(hw, panel.week_start, t)
    assert counts[t] == c and np.allclose(v[:, t], ref, atol=1e-6)


def test_warmup_positions(store, panel):
    assert panel.week_labels[0] == "1991-W02"
    assert first_valid(store["hw_base_rate_10y"]) == 159
    assert panel.week_labels[159] == "1994-W04"
    assert first_valid(store["hw_frac52"]) == 51
    assert first_valid(store["mhi_anom_mean156"]) == 155
    assert first_valid(store["hw_frac26"]) == 25
    assert first_valid(store["hd_lag3"]) == 3
    assert first_valid(store["hd_roll8"]) == 7


def test_base_rate_complexity_sanity():
    """Complexity guard, not a benchmark (WR-08): a generous bound that only a per-ward / per-week
    Python-loop regression (orders of magnitude slower) could break, even on a loaded runner."""
    import time

    p = synthetic_panel(last_week="2003-W20", wards=SYNTHETIC_WARDS)
    hw = (p.values[:, :, 0] >= 3).astype(np.float32)
    t0 = time.perf_counter()
    v, counts = base_rate(hw, p.week_start)
    assert time.perf_counter() - t0 < 30.0
    assert v.shape == hw.shape and counts.shape == (hw.shape[1],)


# ------------------------------------------------------------------ spatial
def test_group_means(panel, clim, static, store):
    hd = panel.values[:, :, 0]
    lga = np.asarray(static.lga_id)
    for i in range(len(panel.wards)):
        same = lga == lga[i]
        assert np.allclose(store["lga_mean_hd_lag0"][i], hd[same].mean(axis=0), atol=1e-5)
    st = np.asarray(static.state_id)
    assert np.allclose(group_mean(hd, st)[0], hd[st == st[0]].mean(axis=0), atol=1e-5)
    assert np.array_equal(store["state_mean_hd_lag0"], group_mean(hd, st))


def test_group_mean_on_subset(panel, clim, static):
    sub = subset_panel(panel, [0, 1, 2])
    s = build_feature_store(sub, clim, static, names=["lga_mean_hd_lag0"])
    hd = sub.values[:, :, 0]
    lga = np.asarray(static.align(sub.wards).lga_id)
    for i in range(3):
        assert np.allclose(s["lga_mean_hd_lag0"][i], hd[lga == lga[i]].mean(axis=0), atol=1e-5)


# ------------------------------------------------------------------ static / season
def test_static_matrix(static):
    names = ("lat", "lon", "geozone_NWZ", "geozone_NEZ", "geozone_NCZ", "lga_average_ward")
    m = static_feature_matrix(static)
    assert m.shape == (6, 6) and m.dtype == np.float32
    assert np.allclose(m[:, 2:5].sum(axis=1), 1)
    assert m[list(static.wards).index("SOCCC002"), names.index("lga_average_ward")] == 1


def test_season_features():
    ws = np.array(["2020-12-28", "2021-01-04", "2016-02-29"], dtype="datetime64[D]")
    s, c = season_features(ws)
    for i, d in enumerate(ws.astype(object)):
        from datetime import timedelta

        doy = (d + timedelta(days=3)).timetuple().tm_yday
        assert s[i] == pytest.approx(np.sin(2 * np.pi * doy / 365.25), abs=1e-6)
        assert c[i] == pytest.approx(np.cos(2 * np.pi * doy / 365.25), abs=1e-6)
    assert np.isfinite(s).all() and s.dtype == np.float32


# ------------------------------------------------------------------ registry / store
def test_registry_totals_and_names():
    assert (len(REGISTRY), len(REGISTRY.names(kind="panel")), len(REGISTRY.names(kind="static")),
            len(REGISTRY.names(kind="calendar"))) == (58, 49, 6, 3)
    assert all(s.max_lookahead == 0 for s in REGISTRY)
    assert not [n for n in REGISTRY.names() if FORBIDDEN_NAME_PATTERN.search(n)]
    assert "lga_average_ward" in REGISTRY
    Registry().register(REGISTRY.get("lga_average_ward"))


def test_build_never_fits(monkeypatch, panel, clim, static):
    def boom(*a, **k):
        raise AssertionError("fit called")

    monkeypatch.setattr(Climatology, "fit", boom)
    s = build_feature_store(panel, clim, static, names=["mhi_anom_lag0", "hd_lag1"])
    assert s.names == ("mhi_anom_lag0", "hd_lag1")
    with pytest.raises(KeyError):
        build_feature_store(panel, clim, static, names=["nope"])


# ------------------------------------------------------------------ real data
@pytest.mark.frozen
def test_full_real_build(frozen_panel, frozen_clim, frozen_static):
    s = build_feature_store(frozen_panel, frozen_clim, frozen_static)
    n, T = frozen_panel.values.shape[:2]
    assert (n, T) == (4841, 1863) and len(s.names) == 49
    for nm in s.names:
        a = s[nm]
        assert a.dtype == np.float32 and a.shape == (n, T)
        assert not np.isnan(a[:, 159:]).any(), nm
    assert first_valid(s["hw_base_rate_10y"]) == 159
    del s
