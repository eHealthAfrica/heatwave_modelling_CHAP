"""Target-week splits, embargo and expanding-window CV folds (FEAT-05).

Membership depends only on target-week indices and config, never on data values.

Embargo: embargo_weeks = max(leads) + longest short feature window (8) = 14.
Training rows whose target falls within the embargo before a held-out cutoff are
dropped; validation rows are not embargoed. Trailing trend windows (26/52/156
weeks, 10-year base rate) only read weeks <= origin, so they introduce no
cross-boundary label leak.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from heatwave.forecast import weeks

SPLIT_NAMES = ("train", "validate", "test")
FEATURE_SHORT_WINDOW_WEEKS = 8


def cutoff_indices(splits_cfg) -> tuple[int, int]:
    return (
        weeks.week_start_to_index(splits_cfg.train_end),
        weeks.week_start_to_index(splits_cfg.validate_end),
    )


def _bounds(splits_cfg) -> tuple[int, int]:
    lo = weeks.week_start_to_index(date.fromisocalendar(splits_cfg.train_years[0], 1, 1))
    hi = weeks.week_start_to_index(date.fromisocalendar(splits_cfg.test_years[1] + 1, 1, 1))
    return lo, hi


def assign_split(target_week_index, splits_cfg) -> np.ndarray:
    t = np.asarray(target_week_index, dtype=np.int64)
    lo, hi = _bounds(splits_cfg)
    if t.size and (t.min() < lo or t.max() >= hi):
        raise ValueError(f"target week index outside configured years [{lo}, {hi})")
    i_train, i_val = cutoff_indices(splits_cfg)
    out = np.full(t.shape, "test", dtype="<U8")
    out[t < i_val] = "validate"
    out[t < i_train] = "train"
    return out


def embargo_keep(target_week_index, cutoff_index, embargo_weeks) -> np.ndarray:
    return np.asarray(target_week_index, dtype=np.int64) < (int(cutoff_index) - int(embargo_weeks))


def split_masks(target_week_index, splits_cfg) -> dict:
    t = np.asarray(target_week_index, dtype=np.int64)
    names = assign_split(t, splits_cfg)
    i_train, _ = cutoff_indices(splits_cfg)
    is_train = names == "train"
    keep = embargo_keep(t, i_train, splits_cfg.embargo_weeks)
    return {
        "train": is_train & keep,
        "embargoed": is_train & ~keep,
        "validate": names == "validate",
        "test": names == "test",
    }


def refit_train_mask(target_week_index, splits_cfg) -> np.ndarray:
    """Pre-test refit on train+validate years, same embargo before the test cutoff."""
    _, i_val = cutoff_indices(splits_cfg)
    return embargo_keep(target_week_index, i_val, splits_cfg.embargo_weeks)


@dataclass(frozen=True)
class CVFold:
    year: int
    validate_start_index: int
    validate_end_index: int
    train_max_target_exclusive: int
    climatology_end: date
    validate_start: date
    validate_end: date


def cv_folds(splits_cfg) -> tuple[CVFold, ...]:
    folds = []
    for y in range(splits_cfg.cv_first_year, splits_cfg.validate_years[1] + 1):
        start = date.fromisocalendar(y, 1, 1)
        end = date.fromisocalendar(y + 1, 1, 1)
        s, e = weeks.week_start_to_index(start), weeks.week_start_to_index(end)
        folds.append(
            CVFold(
                year=y,
                validate_start_index=s,
                validate_end_index=e,
                train_max_target_exclusive=s - splits_cfg.embargo_weeks,
                climatology_end=start,
                validate_start=start,
                validate_end=end,
            )
        )
    return tuple(folds)


def fold_masks(fold: CVFold, target_week_index) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(target_week_index, dtype=np.int64)
    train = t < fold.train_max_target_exclusive
    val = (t >= fold.validate_start_index) & (t < fold.validate_end_index)
    return train, val
