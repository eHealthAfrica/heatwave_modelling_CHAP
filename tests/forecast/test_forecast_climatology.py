"""Train-only climatology: pooling, naive reference, poison invariance (FEAT-03, FEAT-04c)."""
from datetime import date, datetime

import numpy as np
import pytest

from heatwave.forecast import weeks
from heatwave.forecast.climatology import (
    POOL_WEEKS,
    STD_FLOOR_FRAC,
    Climatology,
    iso_week_slots,
    pooling_matrix,
)
from heatwave.forecast.data import Panel
from heatwave.forecast.fixtures import (
    SYNTHETIC_WARDS,
    poison_future,
    subset_panel,
    synthetic_panel,
)


def test_pooling_matrix():
    M = pooling_matrix(2)
    assert M.shape == (53, 53) and M.dtype == bool

    def members(w):
        return set((np.nonzero(M[w - 1])[0] + 1).tolist())

    assert members(53) == {51, 52, 53, 1, 2}
    assert members(52) == {50, 51, 52, 53, 1, 2}
    assert members(1) == {51, 52, 53, 1, 2, 3}
    assert members(26) == {24, 25, 26, 27, 28}
    assert (M == M.T).all()


def test_iso_week_slots_matches_stdlib():
    start = weeks.index_to_week_start(0)
    ws = np.array([np.datetime64(weeks.index_to_week_start(i).isoformat(), "D") for i in range(0, 1900)])
    expect = [weeks.index_to_week_start(i).isocalendar().week for i in range(0, 1900)]
    assert iso_week_slots(ws).tolist() == expect
    assert start.isocalendar().week == 2


@pytest.fixture(scope="module")
def tiny():
    return synthetic_panel(first_week="1991-W02", last_week="1993-W10", wards=SYNTHETIC_WARDS[:2], seed=3)


def _naive(panel, end):
    ws = panel.week_start
    train = [i for i in range(len(ws)) if ws[i] < np.datetime64(end, "D")]
    wk = {i: weeks.index_to_week_start(int(panel.week_index[i])).isocalendar().week for i in train}

    def pos(w):
        return 52.5 if w == 53 else float(w)

    def pooled(slot):
        out = []
        for i in train:
            d = abs(pos(wk[i]) - pos(slot))
            d = min(d, 52 - d)
            if d <= 2:
                out.append(i)
        return out

    return pooled


def test_matches_naive_loop(tiny):
    end = date(1993, 1, 4)
    clim = Climatology.fit(tiny, end)
    pooled = _naive(tiny, end)
    for slot in range(1, 54):
        idx = pooled(slot)
        assert len(idx) == clim.pooled_counts[slot - 1]
        for v in range(len(tiny.variables)):
            x = tiny.values[:, idx, v].astype(np.float64)
            np.testing.assert_allclose(clim.mean[:, slot - 1, v], x.mean(axis=1), rtol=1e-5)
            np.testing.assert_allclose(clim.std[:, slot - 1, v], x.std(axis=1), rtol=1e-4, atol=1e-5)


def test_fit_provenance(tiny):
    end = date(1993, 1, 4)
    c = Climatology.fit(tiny, end)
    fr = c.fit_range()
    assert fr["first_week_label"] == "1991-W02" and fr["last_week_label"] == "1992-W53"
    assert c.first_week_index == tiny.week_index[0]
    assert c.n_fit_weeks == int((tiny.week_start < np.datetime64(end, "D")).sum())
    assert c.data_sha256 == tiny.sha256 == fr["data_sha256"]
    assert c.pool_weeks == POOL_WEEKS == 2
    assert c.last_week_start < end and c.fit_end == end
    med = np.median(c.std.astype(np.float64), axis=(0, 1))
    np.testing.assert_allclose(c.std_floor, np.maximum(STD_FLOOR_FRAC * med, 1e-6), rtol=1e-4)
    assert not c.mean.flags.writeable


@pytest.mark.parametrize("mode", ["garbage", "nan"])
def test_poison_invariance(tiny, mode):
    end = date(1993, 1, 4)
    last_pos = int((tiny.week_start < np.datetime64(end, "D")).sum()) - 1
    a = Climatology.fit(tiny, end)
    b = Climatology.fit(poison_future(tiny, last_pos, mode=mode), end)
    assert np.array_equal(a.mean, b.mean) and np.array_equal(a.std, b.std)
    assert np.array_equal(a.std_floor, b.std_floor)
    fa, fb = a.fit_range(), b.fit_range()
    fa.pop("data_sha256"), fb.pop("data_sha256")  # poisoned panel carries a derived sha by design
    assert fa == fb


@pytest.fixture(scope="module")
def full():
    return synthetic_panel()


def test_anomaly_train_standardised(full):
    end = date(2000, 1, 3)
    c = Climatology.fit(full, end)
    a = c.anomaly(full, "mean_heat_index")
    assert a.dtype == np.float32 and a.shape == full.values.shape[:2]
    train = a[:, full.week_start < np.datetime64(end, "D")]
    assert abs(float(train.mean())) < 0.1
    assert 0.8 <= float(train.std()) <= 1.2


def test_constant_variable_finite(full):
    vals = full.values.copy()
    vals[:, :, 1] = 5.0
    p = Panel(vals, full.wards, full.week_index, full.week_labels, full.week_start, full.variables, "s", "x" * 8)
    c = Climatology.fit(p, date(2000, 1, 3))
    a = c.anomaly(p, "mean_heat_index")
    assert np.isfinite(a).all() and (a == 0).all()


def test_anomaly_subset_and_unknown_ward(full):
    c = Climatology.fit(full, date(2000, 1, 3))
    a = c.anomaly(full, "mean_relative_humidity")
    sub = subset_panel(full, [1, 4])
    np.testing.assert_array_equal(c.anomaly(sub, "mean_relative_humidity"), a[[1, 4]])
    other = Panel(
        sub.values, ("ZZZ00001", sub.wards[1]), sub.week_index, sub.week_labels, sub.week_start, sub.variables, "s", "y"
    )
    with pytest.raises(ValueError):
        c.anomaly(other, "mean_relative_humidity")


def test_fit_validation(full):
    with pytest.raises(ValueError):
        Climatology.fit(full, date(2000, 1, 4))  # Tuesday
    with pytest.raises(ValueError):
        Climatology.fit(full, datetime(2000, 1, 3))
    with pytest.raises(ValueError):
        Climatology.fit(full, date(1991, 1, 7))  # no training weeks
    with pytest.raises(ValueError):
        Climatology.fit(full, date(1991, 3, 4))  # most slots empty


@pytest.mark.frozen
def test_real_fit(forecast_cfg, frozen_panel, frozen_clim):
    c = frozen_clim
    fr = c.fit_range()
    assert fr["first_week_label"] == "1991-W02" and fr["last_week_label"] == "2014-W52"
    assert c.n_fit_weeks == 1251
    assert c.data_sha256 == frozen_panel.sha256
    assert c.fit_end == forecast_cfg.splits.train_end
    assert int(c.pooled_counts.min()) >= 95
    assert np.isfinite(c.std_floor).all() and (c.std_floor > 0).all()
