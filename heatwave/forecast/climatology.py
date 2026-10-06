"""Train-only per-ward, per-ISO-week climatology and anomalies (FEAT-03, FEAT-04c).

The climatology is fitted only on target weeks strictly before ``end`` (main split:
``splits.train_end`` = 2014-12-29, i.e. 1991-2014); each CV fold refits with its own
end (plan 09-05). Statistics are pooled over +-2 ISO weeks (circular, period 52); the
rare ISO week 53 is pooled with W52 and W01 (W53 sits at position 52.5). The fitted
object records its fit range and the data sha, and ``anomaly`` never refits, so the
same object is reused unchanged for validation, test and operational rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from heatwave.forecast import weeks
from heatwave.forecast.data import VARIABLES, Panel

N_SLOTS = 53
POOL_WEEKS = 2
STD_FLOOR_FRAC = 0.1
MIN_ABS_STD_FLOOR = 1e-6
CLIMATOLOGY_VARIABLES = VARIABLES


def iso_week_slots(week_start: np.ndarray) -> np.ndarray:
    """ISO week number 1..53 (int16) of Monday-start weeks given as datetime64[D]."""
    ws = np.asarray(week_start).astype("datetime64[D]")
    thu = ws + np.timedelta64(3, "D")
    jan1 = thu.astype("datetime64[Y]").astype("datetime64[D]")
    return ((thu - jan1).astype(np.int64) // 7 + 1).astype(np.int16)


def pooling_matrix(pool: int = POOL_WEEKS) -> np.ndarray:
    """(53,53) bool: M[i, j] True when slot j is pooled into slot i."""
    pos = np.arange(1, N_SLOTS + 1, dtype=np.float64)
    pos[52] = 52.5
    d = np.abs(pos[:, None] - pos[None, :])
    d = np.minimum(d, 52.0 - d)
    return d <= pool


def _ro(a: np.ndarray) -> np.ndarray:
    a.flags.writeable = False
    return a


@dataclass(frozen=True, eq=False)
class Climatology:
    variables: tuple
    wards: tuple
    mean: np.ndarray  # float32 (n, 53, V)
    std: np.ndarray  # float32 (n, 53, V), raw (before floor)
    pooled_counts: np.ndarray  # int (53,) weeks pooled per slot
    std_floor: np.ndarray  # float64 (V,)
    fit_end: date
    first_week_index: int
    last_week_index: int
    first_week_start: date
    last_week_start: date
    n_fit_weeks: int
    data_sha256: str
    pool_weeks: int

    def __post_init__(self):
        for a in (self.mean, self.std, self.pooled_counts, self.std_floor):
            a.flags.writeable = False
        object.__setattr__(self, "_ward_pos", {w: i for i, w in enumerate(self.wards)})

    @classmethod
    def fit(cls, panel: Panel, end: date) -> "Climatology":
        if isinstance(end, datetime) or not isinstance(end, date):
            raise ValueError(f"end must be a datetime.date, got {type(end).__name__}")
        if end.weekday() != 0:
            raise ValueError(f"end {end} is not a Monday")
        S = np.nonzero(panel.week_start < np.datetime64(end, "D"))[0]
        if S.size == 0:
            raise ValueError(f"no training weeks before {end}")
        slots = iso_week_slots(panel.week_start[S]).astype(np.int64) - 1
        oh = np.zeros((S.size, N_SLOTS), dtype=np.float64)
        oh[np.arange(S.size), slots] = 1.0
        M = pooling_matrix(POOL_WEEKS).astype(np.float64)
        counts = M @ oh.sum(axis=0)  # pooled weeks per slot
        if (counts == 0).any():
            raise ValueError(f"slots with no pooled training weeks: {np.nonzero(counts == 0)[0] + 1}")
        n = len(panel.wards)
        V = len(panel.variables)
        mean = np.empty((n, N_SLOTS, V), np.float32)
        std = np.empty((n, N_SLOTS, V), np.float32)
        floors = np.empty(V, np.float64)
        for v in range(V):
            x = panel.values[:, S, v].astype(np.float64)
            shift = x.mean(axis=1, keepdims=True)  # variance is shift-invariant; limits cancellation
            x -= shift
            s1 = (x @ oh) @ M.T  # (n, 53) pooled sums
            m = s1 / counts
            s2 = ((x * x) @ oh) @ M.T
            var = (s2 - 2.0 * m * s1 + counts * m * m) / counts
            sd = np.sqrt(np.maximum(var, 0.0))
            mean[:, :, v] = (m + shift).astype(np.float32)
            std[:, :, v] = sd.astype(np.float32)
            floors[v] = max(STD_FLOOR_FRAC * float(np.median(sd)), MIN_ABS_STD_FLOOR)
            del x, s1, m, s2, var, sd
        first, last = int(panel.week_index[S[0]]), int(panel.week_index[S[-1]])
        return cls(
            variables=tuple(panel.variables),
            wards=tuple(panel.wards),
            mean=mean,
            std=std,
            pooled_counts=counts.astype(np.int64),
            std_floor=floors,
            fit_end=end,
            first_week_index=first,
            last_week_index=last,
            first_week_start=weeks.index_to_week_start(first),
            last_week_start=weeks.index_to_week_start(last),
            n_fit_weeks=int(S.size),
            data_sha256=panel.sha256,
            pool_weeks=POOL_WEEKS,
        )

    def anomaly(self, panel: Panel, variable: str) -> np.ndarray:
        """(n, T) float32 anomalies of ``variable``; never refits."""
        try:
            rows = np.array([self._ward_pos[w] for w in panel.wards], dtype=np.int64)
        except KeyError as exc:
            raise ValueError(f"ward {exc.args[0]!r} not in climatology") from None
        v = self.variables.index(variable)
        pv = list(panel.variables).index(variable)
        slots = iso_week_slots(panel.week_start).astype(np.int64) - 1
        m = self.mean[rows][:, :, v][:, slots]
        s = self.std[rows][:, :, v][:, slots]
        x = panel.values[:, :, pv]
        floor = np.float32(self.std_floor[v])
        return ((x - m) / np.maximum(s, floor)).astype(np.float32)

    def fit_range(self) -> dict:
        return {
            "fit_end": self.fit_end.isoformat(),
            "first_week_index": self.first_week_index,
            "last_week_index": self.last_week_index,
            "first_week_label": weeks.index_to_label(self.first_week_index),
            "last_week_label": weeks.index_to_label(self.last_week_index),
            "first_week_start": self.first_week_start.isoformat(),
            "last_week_start": self.last_week_start.isoformat(),
            "n_fit_weeks": self.n_fit_weeks,
            "data_sha256": self.data_sha256,
            "pool_weeks": self.pool_weeks,
            "std_floor_frac": STD_FLOOR_FRAC,
            "std_floor": {k: float(f) for k, f in zip(self.variables, self.std_floor)},
        }
