"""Tests for the ISO week index (DATA-02)."""
from datetime import date, datetime

import numpy as np
import pytest

from heatwave.forecast.weeks import (
    EPOCH_LABEL,
    EPOCH_WEEK_START,
    index_labels,
    index_to_label,
    index_to_week_start,
    is_53_week_year,
    label_to_index,
    label_to_week_start,
    labels_to_indices,
    parse_label,
    week_end,
    week_start_to_index,
    week_start_to_label,
)

N_WEEKS = 1863
YEARS_53 = {1992, 1998, 2004, 2009, 2015, 2020, 2026}


def test_epoch_constants():
    assert EPOCH_LABEL == "1991-W02"
    assert EPOCH_WEEK_START == date(1991, 1, 7)


def test_endpoints():
    assert label_to_index("1991-W02") == 0
    assert index_to_week_start(0) == date(1991, 1, 7)
    assert index_to_label(1862) == "2026-W38"
    assert index_to_week_start(1862) == date(2026, 9, 14)


def test_round_trip_all_indices():
    prev = None
    for i in range(N_WEEKS):
        start = index_to_week_start(i)
        assert label_to_index(index_to_label(i)) == i
        assert week_start_to_index(start) == i
        assert start.weekday() == 0
        if prev is not None:
            assert (start - prev).days == 7
        prev = start


def test_week_53_2020():
    assert label_to_week_start("2020-W53") == date(2020, 12, 28)
    assert week_end("2020-W53") == date(2021, 1, 3)
    assert label_to_index("2021-W01") == label_to_index("2020-W53") + 1


def test_week_end_accepts_index():
    assert week_end(0) == date(1991, 1, 13)


def test_year_boundaries():
    assert week_start_to_label(date(2014, 12, 29)) == "2015-W01"
    assert week_start_to_label(date(2018, 12, 31)) == "2019-W01"
    assert label_to_week_start("2026-W53") == date(2026, 12, 28)


def test_is_53_week_year():
    got = {y for y in range(1991, 2027) if is_53_week_year(y)}
    assert got == YEARS_53
    for y in range(1991, 2027):
        assert is_53_week_year(y) == (date(y, 12, 28).isocalendar().week == 53)


@pytest.mark.parametrize("y", sorted(YEARS_53 - {2026}))
def test_w53_adjacent_to_next_w01(y):
    labels = index_labels(N_WEEKS)
    assert f"{y}-W53" in labels
    assert label_to_index(f"{y}-W53") == label_to_index(f"{y + 1}-W01") - 1


def test_negative_index_before_epoch():
    assert label_to_index("1991-W01") == -1


@pytest.mark.parametrize(
    "bad", ["2021-W53", "2014-W53", "2020-W5", "2020W05", "20-W05",
            "2020-W00", "2020-W54", None, 202005, b"2020-W05",
            "1991-W02" + chr(10), chr(10) + "1991-W02", "1991-W02 ", chr(0xFF11) * 4 + "-W02",
            "1991-W" + chr(0x0660) + chr(0x0662)],
)
def test_invalid_labels(bad):
    with pytest.raises(ValueError):
        label_to_index(bad)


def test_parse_label_ok():
    assert parse_label("2020-W53") == (2020, 53)


def test_invalid_week_start():
    with pytest.raises(ValueError):
        week_start_to_label(date(2021, 1, 3))  # Sunday
    with pytest.raises(ValueError):
        week_start_to_label(datetime(2021, 1, 4))  # datetime, not date
    with pytest.raises(ValueError):
        week_start_to_label("2021-01-04")


@pytest.mark.parametrize("bad", [True, 1.0, "3", None])
def test_invalid_index(bad):
    with pytest.raises(ValueError):
        index_to_label(bad)
    with pytest.raises(ValueError):
        index_to_week_start(bad)


def test_labels_to_indices():
    out = labels_to_indices(["1991-W03", "1991-W02", "1991-W03"])
    assert out.dtype == np.int64
    assert out.tolist() == [1, 0, 1]


def test_labels_to_indices_invalid():
    with pytest.raises(ValueError):
        labels_to_indices(["1991-W03", "2021-W53"])


def test_labels_to_indices_accepts_numpy_object_array():
    arr = np.array(["1991-W03", "1991-W02"], dtype=object)
    assert labels_to_indices(arr).tolist() == [1, 0]


def test_index_labels():
    assert index_labels(3) == ("1991-W02", "1991-W03", "1991-W04")
    assert index_labels(2, start=1) == ("1991-W03", "1991-W04")


@pytest.mark.frozen
def test_frozen_dir_fixture_points_at_manifest(frozen_dir):
    assert (frozen_dir / "MANIFEST.json").is_file()
