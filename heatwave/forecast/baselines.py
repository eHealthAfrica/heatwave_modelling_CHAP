"""The five baselines every model must beat (EVAL-01).

Dense-array predictors: ``predict(lead, ward_pos, origin_pos)`` returns float32
probabilities for the requested (ward, origin) rows of one lead. Fits use only the
training pairs of ``FitContext.train_index`` (``dataset.lead_row_index(..., "train")``:
embargo and warm-up excluded), except ``recent_climatology`` which reads an as-of
10-year base rate (anchors at least about 50 weeks before the target column).

Hyper-parameters here are module constants on purpose: the models config block (tuned in
Phase 12) never changes a baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from sklearn.linear_model import LogisticRegression

from heatwave.forecast import dataset, features, targets
from heatwave.forecast.climatology import Climatology, iso_week_slots, pooling_matrix
from heatwave.forecast.evaluation.slices import SEASONS, season_of
from heatwave.forecast.static import GEOZONES

PERSISTENCE_PSEUDO = 0.5  # cell estimate (pos + 0.5) / (n + 1)
DAMPED_C = 1.0
TREND_C = 1e6
N_SLOTS = 53


def _target_cols(origin_pos, lead) -> np.ndarray:
    return np.asarray(origin_pos, dtype=np.int64) + int(lead)


@dataclass(frozen=True, eq=False)
class FitContext:
    """Everything a baseline may fit on. ``clim`` must be fitted at ``cfg.splits.train_end``."""

    panel: object
    static: object
    clim: Climatology
    cfg: object
    train_index: Callable[[int], tuple] = None

    def __post_init__(self):
        if self.clim.fit_end != self.cfg.splits.train_end:
            raise ValueError(
                f"climatology fit_end {self.clim.fit_end} must equal splits.train_end {self.cfg.splits.train_end}"
            )
        object.__setattr__(self, "static", self.static.align(self.panel.wards))
        if self.train_index is None:
            panel, cfg = self.panel, self.cfg
            object.__setattr__(self, "train_index", lambda lead: dataset.lead_row_index(panel, cfg, lead, "train"))


class Predictor(Protocol):
    name: str

    def fit(self, ctx: FitContext) -> "Predictor": ...

    def predict(self, lead: int, ward_pos, origin_pos) -> np.ndarray: ...


def _f32(p) -> np.ndarray:
    return np.asarray(p, dtype=np.float32)


def _geozone_codes(static) -> np.ndarray:
    return np.array([GEOZONES.index(g) for g in static.geozone], dtype=np.int64)


def _season_codes(week_start) -> np.ndarray:
    return np.array([SEASONS.index(s) for s in season_of(week_start)], dtype=np.int64)


# --------------------------------------------------------------------------- climatology
class ClimatologyBaseline:
    """Pooled ISO-slot heatwave rate per ward over the training target weeks of each lead."""

    name = "climatology"

    def fit(self, ctx: FitContext):
        panel = ctx.panel
        hw = targets.heatwave_week_matrix(panel).astype(np.float64)
        slots = iso_week_slots(panel.week_start).astype(np.int64) - 1
        M = pooling_matrix().astype(np.float64)
        self.slots = slots
        self.rate = {}
        for lead in ctx.cfg.leads:
            _, o = ctx.train_index(lead)
            S = np.unique(_target_cols(o, lead))
            oh = np.zeros((S.size, N_SLOTS))
            oh[np.arange(S.size), slots[S]] = 1.0
            counts = oh.sum(axis=0) @ M.T
            pos = (hw[:, S] @ oh) @ M.T
            with np.errstate(invalid="ignore", divide="ignore"):
                self.rate[lead] = np.where(counts > 0, pos / counts, np.nan)
        return self

    def predict(self, lead, ward_pos, origin_pos):
        cols = _target_cols(origin_pos, lead)
        return _f32(self.rate[lead][np.asarray(ward_pos), self.slots[cols]])


# --------------------------------------------------------------------------- recent climatology
class RecentClimatologyBaseline:
    """10-year as-of base rate at the TARGET column, shrunk to the state rate with m pseudo-counts."""

    name = "recent_climatology"

    def fit(self, ctx: FitContext):
        cfg = ctx.cfg
        hw = targets.heatwave_week_matrix(ctx.panel)
        br, cnt = features.base_rate(hw, ctx.panel.week_start, years=cfg.baselines.recent_climatology_years)
        pos = br.astype(np.float64) * cnt[None, :]
        p_state = features.group_mean(br, ctx.static.state_id).astype(np.float64)
        m = float(cfg.baselines.shrinkage_pseudo_count)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.P = _f32((pos + m * p_state) / (cnt[None, :] + m))
        return self

    def predict(self, lead, ward_pos, origin_pos):
        return self.P[np.asarray(ward_pos), _target_cols(origin_pos, lead)]


# --------------------------------------------------------------------------- persistence
class PersistenceBaseline:
    """P(heatwave at target | y0, target season, geozone), smoothed cell frequency."""

    name = "persistence"

    def fit(self, ctx: FitContext):
        panel = ctx.panel
        self.hw = targets.heatwave_week_matrix(panel)
        self.season = _season_codes(panel.week_start)
        self.gz = _geozone_codes(ctx.static)
        self.table = {}
        for lead in ctx.cfg.leads:
            w, o = ctx.train_index(lead)
            cell = self._cell(lead, w, o)
            y = self.hw[w, _target_cols(o, lead)]
            pos = np.bincount(cell, weights=y, minlength=24)
            n = np.bincount(cell, minlength=24).astype(np.float64)
            self.table[lead] = ((pos + PERSISTENCE_PSEUDO) / (n + 2 * PERSISTENCE_PSEUDO)).reshape(2, 4, 3)
        return self

    def _cell(self, lead, w, o):
        w, o = np.asarray(w), np.asarray(o)
        y0 = self.hw[w, o].astype(np.int64)
        return (y0 * 4 + self.season[_target_cols(o, lead)]) * 3 + self.gz[w]

    def predict(self, lead, ward_pos, origin_pos):
        return _f32(self.table[lead].ravel()[self._cell(lead, ward_pos, origin_pos)])


# --------------------------------------------------------------------------- damped persistence
class DampedPersistenceBaseline:
    """Logistic on (xhi anomaly now, y0, sin, cos of the target week); damps toward climatology."""

    name = "damped_persistence"
    INPUTS = ("xhi_anom_lag0", "y0", "season_sin", "season_cos")

    def fit(self, ctx: FitContext):
        panel = ctx.panel
        self.hw = targets.heatwave_week_matrix(panel)
        self.anom = ctx.clim.anomaly(panel, "max_heat_index")
        self.week_start = panel.week_start
        self.models, self.coef_, self.intercept_ = {}, {}, {}
        for lead in ctx.cfg.leads:
            w, o = ctx.train_index(lead)
            X = self._design(lead, w, o)
            y = self.hw[w, _target_cols(o, lead)].astype(np.int64)
            mdl = LogisticRegression(C=DAMPED_C, solver="lbfgs", max_iter=2000).fit(X, y)  # default penalty: l2
            self.models[lead] = mdl
            self.coef_[lead], self.intercept_[lead] = mdl.coef_.copy(), mdl.intercept_.copy()
        return self

    def _design(self, lead, w, o):
        w, o = np.asarray(w), np.asarray(o)
        sin, cos = features.season_features(self.week_start[_target_cols(o, lead)])
        return np.column_stack([self.anom[w, o], self.hw[w, o], sin, cos]).astype(np.float64)

    def predict(self, lead, ward_pos, origin_pos):
        return _f32(self.models[lead].predict_proba(self._design(lead, ward_pos, origin_pos))[:, 1])


# --------------------------------------------------------------------------- trend + season
def _year_frac(week_start) -> np.ndarray:
    d = np.asarray(week_start).astype("datetime64[D]")
    y0 = d.astype("datetime64[Y]")
    doy = (d - y0.astype("datetime64[D]")).astype(np.int64)
    return y0.astype(np.int64) + 1970 + doy / 365.25


class TrendSeasonBaseline:
    """Logistic on a linear year trend, season harmonics and geozone dummies.

    A year term is allowed here (and only here): the baseline represents the warming
    trend and extrapolates it linearly into 2015-2020. The year term stays local to
    this module and is never a registered feature.
    """

    name = "trend_season"

    def fit(self, ctx: FitContext):
        panel = ctx.panel
        lo, hi = ctx.cfg.splits.train_years
        self.center = (lo + hi) / 2 + 0.5
        self.week_start = panel.week_start
        self.gz = _geozone_codes(ctx.static)
        hw = targets.heatwave_week_matrix(panel)
        T = panel.values.shape[1]
        self.models, self.coef_, self.intercept_ = {}, {}, {}
        for lead in ctx.cfg.leads:
            w, o = ctx.train_index(lead)
            cols = _target_cols(o, lead)
            key = cols * 3 + self.gz[np.asarray(w)]
            y = hw[np.asarray(w), cols]
            pos = np.bincount(key, weights=y, minlength=T * 3)
            tot = np.bincount(key, minlength=T * 3).astype(np.float64)
            cell = np.nonzero(tot > 0)[0]
            X = self._design(cell // 3, cell % 3)
            Xa = np.vstack([X, X])
            ya = np.r_[np.ones(cell.size), np.zeros(cell.size)].astype(np.int64)
            sw = np.r_[pos[cell], tot[cell] - pos[cell]]
            keep = sw > 0
            mdl = LogisticRegression(C=TREND_C, solver="lbfgs", max_iter=1000)
            mdl.fit(Xa[keep], ya[keep], sample_weight=sw[keep])
            self.models[lead] = mdl
            self.coef_[lead], self.intercept_[lead] = mdl.coef_.copy(), mdl.intercept_.copy()
        return self

    def _design(self, cols, gz) -> np.ndarray:
        ws = self.week_start[np.asarray(cols)]
        sin, cos = features.season_features(ws)
        gz = np.asarray(gz)
        return np.column_stack(
            [
                _year_frac(ws) - self.center,
                sin,
                cos,
                (gz == GEOZONES.index("NEZ")).astype(np.float64),
                (gz == GEOZONES.index("NCZ")).astype(np.float64),
            ]
        ).astype(np.float64)

    def predict(self, lead, ward_pos, origin_pos):
        X = self._design(_target_cols(origin_pos, lead), self.gz[np.asarray(ward_pos)])
        return _f32(self.models[lead].predict_proba(X)[:, 1])


# --------------------------------------------------------------------------- registry
BASELINE_REGISTRY = {
    "climatology": ClimatologyBaseline,
    "recent_climatology": RecentClimatologyBaseline,
    "persistence": PersistenceBaseline,
    "damped_persistence": DampedPersistenceBaseline,
    "trend_season": TrendSeasonBaseline,
}


def fit_baselines(ctx: FitContext, names=None) -> dict:
    """Fit the named baselines (default ``cfg.baselines.names``) for every configured lead."""
    names = tuple(ctx.cfg.baselines.names if names is None else names)
    out = {}
    for nm in names:
        if nm not in BASELINE_REGISTRY:
            raise KeyError(f"unknown baseline {nm!r}")
        out[nm] = BASELINE_REGISTRY[nm]().fit(ctx)
    return out


def train_base_rate(ctx: FitContext, lead: int) -> float:
    """Mean training label of the lead (default P/R/F1 threshold)."""
    w, o = ctx.train_index(lead)
    return float(targets.lead_label(ctx.panel, lead)[np.asarray(w), np.asarray(o)].mean())
