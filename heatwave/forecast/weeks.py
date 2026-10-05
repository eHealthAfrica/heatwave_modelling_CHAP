"""ISO week index for the forecast pipeline (DATA-02).

Rule: all time arithmetic (lags, leads, splits, embargo) uses the integer week
index or ``week_start`` dates, never label strings. Labels such as ``2020-W53``
are only parsed at the boundary and formatted for display.

Index 0 is ``1991-W02`` (Monday 1991-01-07), the first week of the frozen
covariate table. Negative indices denote weeks before the epoch.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterable

import numpy as np

EPOCH_LABEL = "1991-W02"
EPOCH_WEEK_START = date.fromisocalendar(1991, 2, 1)

_LABEL_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def _check_index(i) -> int:
    if isinstance(i, bool) or not isinstance(i, (int, np.integer)):
        raise ValueError(f"week index must be an int, got {i!r}")
    return int(i)


def parse_label(label) -> tuple[int, int]:
    """Parse ``YYYY-Www`` into (iso_year, iso_week); ValueError if invalid."""
    if not isinstance(label, str):
        raise ValueError(f"week label must be a str, got {label!r}")
    m = _LABEL_RE.match(label)
    if m is None:
        raise ValueError(f"invalid week label {label!r}: expected YYYY-Www")
    year, week = int(m.group(1)), int(m.group(2))
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError(f"invalid week label {label!r}: {exc}") from exc
    return year, week


def label_to_week_start(label) -> date:
    year, week = parse_label(label)
    return date.fromisocalendar(year, week, 1)


def week_start_to_label(d) -> str:
    if isinstance(d, datetime) or not isinstance(d, date):
        raise ValueError(f"week_start must be a datetime.date, got {d!r}")
    if d.weekday() != 0:
        raise ValueError(f"week_start {d} is not a Monday")
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_start_to_index(d) -> int:
    week_start_to_label(d)  # validates type and Monday
    return (d - EPOCH_WEEK_START).days // 7


def label_to_index(label) -> int:
    return (label_to_week_start(label) - EPOCH_WEEK_START).days // 7


def index_to_week_start(i) -> date:
    return EPOCH_WEEK_START + timedelta(weeks=_check_index(i))


def index_to_label(i) -> str:
    return week_start_to_label(index_to_week_start(i))


def week_end(label_or_index) -> date:
    """Sunday closing the week."""
    if isinstance(label_or_index, str):
        start = label_to_week_start(label_or_index)
    else:
        start = index_to_week_start(label_or_index)
    return start + timedelta(days=6)


def labels_to_indices(labels: Iterable) -> np.ndarray:
    """Vectorised label -> index; each unique label is parsed once."""
    values = list(labels)
    mapping: dict = {}
    out = np.empty(len(values), dtype=np.int64)
    for k, lab in enumerate(values):
        idx = mapping.get(lab)
        if idx is None:
            idx = label_to_index(lab)
            mapping[lab] = idx
        out[k] = idx
    return out


def index_labels(n_weeks: int, start: int = 0) -> tuple[str, ...]:
    start = _check_index(start)
    return tuple(index_to_label(i) for i in range(start, start + _check_index(n_weeks)))


def is_53_week_year(year: int) -> bool:
    return date(year, 12, 28).isocalendar().week == 53
