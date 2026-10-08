"""Lead-aligned labels and timing fields (FEAT-01, FEAT-02).

The label is ``heatwave_week = heatwave_days >= 3``: three or more hot days in
the target week, not necessarily consecutive. It is NOT ``heatwave_event_count``
(PITFALLS M1). The label is built in exactly one place, by integer gather on
panel positions (target position = origin position + k); positions past the end
of the data are NaN and never filled.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from heatwave.forecast import weeks

HEATWAVE_DAYS_THRESHOLD = 3
TARGET_NAME = "heatwave_week"
LABEL_DEFINITION = "heatwave_week = heatwave_days >= 3"


def _check_lead(k) -> int:
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k < 1:
        raise ValueError(f"lead must be an int >= 1, got {k!r}")
    return int(k)


def _check_latency(latency_days) -> int:
    if (
        isinstance(latency_days, bool)
        or not isinstance(latency_days, (int, np.integer))
        or latency_days < 0
    ):
        raise ValueError(f"latency_days must be an int >= 0, got {latency_days!r}")
    return int(latency_days)


def heatwave_week_matrix(panel) -> np.ndarray:
    """(n, T) float32: 1.0 where heatwave_days >= 3 else 0.0, per week."""
    j = panel.variables.index("heatwave_days")
    days = panel.values[:, :, j]
    return (days >= HEATWAVE_DAYS_THRESHOLD).astype(np.float32)


def lead_label(panel, k) -> np.ndarray:
    """(n, T) float32 label of week t+k at origin t; NaN where t+k > T-1."""
    k = _check_lead(k)
    base = heatwave_week_matrix(panel)
    n, T = base.shape
    out = np.full((n, T), np.nan, dtype=np.float32)
    if T > k:
        out[:, : T - k] = base[:, k:]
    return out


def has_label(panel, k) -> np.ndarray:
    """(T,) bool: origin positions whose lead-k target exists in the data."""
    k = _check_lead(k)
    T = panel.values.shape[1]
    mask = np.zeros(T, dtype=bool)
    if T > k:
        mask[: T - k] = True
    return mask


def effective_days_ahead(k, latency_days=0) -> int:
    """Days from the issue date (Sunday + latency) to the target week's Monday."""
    return 7 * _check_lead(k) - 6 - _check_latency(latency_days)


@dataclass(frozen=True, eq=False)
class TimingFields:
    last_obs_week_index: np.ndarray
    last_obs_week: tuple
    issue_date: np.ndarray
    target_week_index: np.ndarray
    target_week: tuple
    target_week_start: np.ndarray
    lead_weeks: int
    effective_days_ahead: np.ndarray
    latency_days: int


def timing_fields(panel, k, latency_days) -> TimingFields:
    k = _check_lead(k)
    latency_days = _check_latency(latency_days)
    idx = np.asarray(panel.week_index, dtype=np.int64)
    ws = np.asarray(panel.week_start).astype("datetime64[D]")
    issue = ws + np.timedelta64(6 + latency_days, "D")
    target_start = ws + np.timedelta64(7 * k, "D")
    target_idx = idx + k
    target_labels = tuple(weeks.index_to_label(int(i)) for i in target_idx)
    eda = (target_start - issue).astype("timedelta64[D]").astype(np.int64)
    return TimingFields(
        last_obs_week_index=idx,
        last_obs_week=tuple(panel.week_labels),
        issue_date=issue,
        target_week_index=target_idx,
        target_week=target_labels,
        target_week_start=target_start,
        lead_weeks=k,
        effective_days_ahead=eda,
        latency_days=latency_days,
    )
