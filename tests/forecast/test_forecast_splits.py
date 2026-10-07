from datetime import date

import numpy as np
import pytest

from heatwave.forecast import weeks
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.splits import (
    FEATURE_SHORT_WINDOW_WEEKS,
    assign_split,
    cutoff_indices,
    cv_folds,
    embargo_keep,
    fold_masks,
    refit_train_mask,
    split_masks,
)

cfg = load_forecast_config()
S = cfg.splits
LO = weeks.label_to_index("1991-W01")
HI = weeks.label_to_index("2027-W01")
ALL = np.arange(LO, HI)


def test_cutoffs():
    a, b = cutoff_indices(S)
    assert a == weeks.week_start_to_index(date(2014, 12, 29))
    assert b == weeks.week_start_to_index(date(2021, 1, 4))
    assert S.train_end.weekday() == 0 and S.validate_end.weekday() == 0


def test_assign_split_cases():
    def f(lab):
        return str(assign_split(np.array([weeks.label_to_index(lab)]), S)[0])

    assert f("2014-W52") == "train"
    assert f("2015-W01") == "validate"
    assert f("2020-W53") == "validate"
    assert f("2021-W01") == "test"
    assert f("2026-W38") == "test"


def test_assign_split_matches_config():
    got = assign_split(ALL, S)
    for i, g in zip(ALL, got):
        assert g == S.split_for_week_start(weeks.index_to_week_start(int(i)))


def test_assign_split_out_of_range():
    with pytest.raises(ValueError):
        assign_split(np.array([LO - 1]), S)
    with pytest.raises(ValueError):
        assign_split(np.array([HI]), S)


def test_masks_and_embargo():
    m = split_masks(ALL, S)
    tot = sum(m[k].astype(int) for k in ("train", "embargoed", "validate", "test"))
    assert (tot == 1).all()
    i_train, _ = cutoff_indices(S)
    assert ALL[m["train"]].max() == i_train - 15
    assert weeks.index_to_label(int(i_train - 15)) == "2014-W38"
    assert [weeks.index_to_label(int(i)) for i in ALL[m["embargoed"]]] == [
        f"2014-W{w}" for w in range(39, 53)
    ]


def test_embargo_value():
    assert S.embargo_weeks == max(cfg.leads) + FEATURE_SHORT_WINDOW_WEEKS == 14
    assert embargo_keep(np.array([5, 6]), 20, 14).tolist() == [True, False]


def test_refit_mask():
    _, i_val = cutoff_indices(S)
    m = refit_train_mask(ALL, S)
    assert ALL[m].max() == i_val - 15


def test_cv_folds():
    folds = cv_folds(S)
    assert [f.year for f in folds] == list(range(2005, 2021))
    for f in folds:
        y = f.year
        assert f.validate_start_index == weeks.week_start_to_index(date.fromisocalendar(y, 1, 1))
        assert f.validate_end_index == weeks.week_start_to_index(date.fromisocalendar(y + 1, 1, 1))
        assert f.train_max_target_exclusive == f.validate_start_index - 14
        assert f.climatology_end == date.fromisocalendar(y, 1, 1)
        tr, va = fold_masks(f, ALL)
        assert not (tr & va).any()
        assert ALL[tr].max() < ALL[va].min() - 14
    assert folds[0].validate_start == date(2005, 1, 3)
    _, va = fold_masks(folds[-1], ALL)
    assert weeks.label_to_index("2020-W53") in ALL[va]


def test_independent_of_values():
    a = split_masks(ALL, S)
    b = split_masks(ALL.copy(), S)
    assert all(np.array_equal(a[k], b[k]) for k in a)


def test_wr04_lenient_assign_and_issue_labels():
    from heatwave.forecast.splits import issue_split_labels

    got = assign_split(np.array([HI - 1, HI, HI + 5]), S, strict=False)
    assert list(got) == ["test", "beyond_test", "beyond_test"]
    with pytest.raises(ValueError):
        assign_split(np.array([LO - 1]), S, strict=False)
    m = split_masks(np.array([HI + 3]), S)
    assert not any(v.any() for v in m.values())
    lab = issue_split_labels(ALL, S)
    mk = split_masks(ALL, S)
    assert ((lab == "train") == mk["train"]).all() and ((lab == "embargoed") == mk["embargoed"]).all()
