import numpy as np
import pandas as pd
import pytest

from heatwave.forecast import weeks
from heatwave.forecast.data import Panel
from heatwave.forecast.fixtures import synthetic_panel
from heatwave.forecast.targets import (
    HEATWAVE_DAYS_THRESHOLD,
    LABEL_DEFINITION,
    effective_days_ahead,
    has_label,
    heatwave_week_matrix,
    lead_label,
    timing_fields,
)


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel()


def _tiny_panel():
    vals = np.zeros((2, 4, 2), dtype=np.float32)
    # variables: heatwave_days, heatwave_event_count
    vals[0, :, 0] = [3, 2, 7, 0]
    vals[0, :, 1] = [0, 1, 1, 0]
    vals[1, :, 0] = [0, 3, 2, 4]
    idx = np.arange(4, dtype=np.int64)
    lab = weeks.index_labels(4)
    ws = np.array([weeks.index_to_week_start(int(i)) for i in idx], dtype="datetime64[D]")
    return Panel(vals, ("A", "B"), idx, lab, ws, ("heatwave_days", "heatwave_event_count"), "t", "x")


def test_label_uses_days_not_event_count():
    m = heatwave_week_matrix(_tiny_panel())
    assert HEATWAVE_DAYS_THRESHOLD == 3
    assert "heatwave_days >= 3" in LABEL_DEFINITION
    assert m[0].tolist() == [1, 0, 1, 0]  # days 3/event 0 -> 1; days 2/event 1 -> 0
    assert m[1].tolist() == [0, 1, 0, 1]


def test_lead_label_alignment_and_tail(panel):
    m = heatwave_week_matrix(panel)
    T = m.shape[1]
    for k in range(1, 7):
        lab = lead_label(panel, k)
        assert np.array_equal(lab[:, : T - k], m[:, k:])
        assert np.isnan(lab[:, T - k :]).all()
        assert has_label(panel, k).sum() == T - k


def test_lead_label_matches_independent_pandas_join(panel):
    j = panel.variables.index("heatwave_days")
    rows = []
    for i, w in enumerate(panel.wards):
        for t in range(panel.values.shape[1]):
            rows.append((w, pd.Timestamp(panel.week_start[t]), float(panel.values[i, t, j] >= 3)))
    df = pd.DataFrame(rows, columns=["ward", "ws", "hw"])
    for k in range(1, 7):
        lab = lead_label(panel, k)
        tgt = df.rename(columns={"ws": "target_ws", "hw": "y"})
        origin = df[["ward", "ws"]].copy()
        origin["target_ws"] = origin["ws"] + pd.Timedelta(days=7 * k)
        ref = origin.merge(tgt, on=["ward", "target_ws"], how="left")
        pos = {w: i for i, w in enumerate(panel.wards)}
        wp = {pd.Timestamp(s): t for t, s in enumerate(panel.week_start)}
        out = np.full(lab.shape, np.nan, dtype=np.float32)
        for w, s, y in zip(ref.ward, ref.ws, ref.y):
            out[pos[w], wp[s]] = y
        assert np.array_equal(lab, out, equal_nan=True)


@pytest.mark.parametrize("k", [0, True, 1.5, -1])
def test_bad_lead(panel, k):
    with pytest.raises(ValueError):
        lead_label(panel, k)


def test_timing_fields(panel):
    for k in range(1, 7):
        tf = timing_fields(panel, k, 0)
        ws = panel.week_start
        assert ((tf.issue_date - ws).astype(int) == 6).all()
        assert all(pd.Timestamp(d).weekday() == 6 for d in tf.issue_date)
        assert ((tf.target_week_start - ws).astype(int) == 7 * k).all()
        assert all(pd.Timestamp(d).weekday() == 0 for d in tf.target_week_start)
        assert np.array_equal(tf.target_week_index, panel.week_index + k)
        assert (tf.effective_days_ahead == (tf.target_week_start - tf.issue_date).astype(int)).all()
        assert tf.lead_weeks == k and tf.latency_days == 0
        assert tf.last_obs_week == tuple(panel.week_labels)


def test_effective_days_ahead(panel):
    assert [effective_days_ahead(k, 0) for k in range(1, 7)] == [1, 8, 15, 22, 29, 36]
    assert [effective_days_ahead(k, 9) for k in range(1, 7)] == [-8, -1, 6, 13, 20, 27]
    with pytest.raises(ValueError):
        effective_days_ahead(1, -1)
    with pytest.raises(ValueError):
        timing_fields(panel, 1, True)


def test_latency_in_timing(panel):
    tf = timing_fields(panel, 1, 9)
    assert (tf.effective_days_ahead == -8).all()


def test_boundaries():
    p = synthetic_panel(first_week="1992-W50", last_week="1993-W05")
    pos = p.week_labels.index("1992-W52")
    assert timing_fields(p, 1, 0).target_week[pos] == "1992-W53"
    assert timing_fields(p, 2, 0).target_week[pos] == "1993-W01"
    p = synthetic_panel(first_week="2014-W50", last_week="2015-W05")
    pos = p.week_labels.index("2014-W52")
    tf = timing_fields(p, 1, 0)
    assert tf.target_week[pos] == "2015-W01"
    assert str(tf.target_week_start[pos]) == "2014-12-29"
    p = synthetic_panel(first_week="2020-W50", last_week="2021-W05")
    pos = p.week_labels.index("2020-W52")
    assert timing_fields(p, 1, 0).target_week[pos] == "2020-W53"
    assert timing_fields(p, 2, 0).target_week[pos] == "2021-W01"


def test_labels_beyond_end(panel):
    tf = timing_fields(panel, 6, 0)
    assert tf.target_week[-1] == weeks.index_to_label(int(panel.week_index[-1]) + 6)
    assert not has_label(panel, 6)[-1]


@pytest.mark.frozen
def test_frozen_last_origin(frozen_panel, forecast_cfg):
    tf = timing_fields(frozen_panel, 1, forecast_cfg.latency_days)
    assert tf.last_obs_week[-1] == "2026-W38"
    assert str(tf.issue_date[-1]) == "2026-09-20"
    assert tf.target_week[-1] == "2026-W39"
    assert str(tf.target_week_start[-1]) == "2026-09-21"
    assert not has_label(frozen_panel, 1)[-1]
