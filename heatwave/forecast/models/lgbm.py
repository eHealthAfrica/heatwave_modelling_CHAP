"""Per-lead LightGBM with expanding-window CV tuning (MODEL-02) and the out-of-fold predictions
used for calibration and model selection (MODEL-03).

CV design
- Tuning folds are expanding-window folds from ``splits.cv_folds`` whose validation year lies
  in the training era (``TUNE_FOLD_YEARS``), so the 2015-2020 validation split stays held out
  for the final comparison. Each fold refits the climatology and feature store on its own past.
- Inside a fold, early stopping uses the last ``ES_WEEKS`` target weeks of the fold's training
  rows; the rows used for fitting end ``embargo_weeks`` earlier. The fold's validation year is
  never used for fitting or early stopping, so its predictions are genuinely out of fold.
- A configuration is chosen per lead by mean fold Brier; ``n_estimators`` for the final fit is
  the median early-stopping iteration of that configuration.

No class reweighting: ``class_weight``, ``is_unbalance`` and ``scale_pos_weight`` are refused.
"""
from __future__ import annotations

import gc
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np

from heatwave.forecast import dataset, splits, targets
from heatwave.forecast.features import REGISTRY
from heatwave.forecast.models.calibration import Calibrator
from heatwave.forecast.models.logistic import MAX_TRAIN_ROWS, LogisticForecaster, design_matrix, full_feature_set

# Fixed thread count: LightGBM's deterministic mode is reproducible only for a fixed thread count.
N_THREADS = 8
ES_WEEKS = 52
ES_MAX_ROWS = 300_000
ES_PATIENCE = 50
MAX_TREES = 2000
MIN_TREES = 10
TUNE_FOLD_YEARS = (2010, 2011, 2012, 2013, 2014)
FORBIDDEN_PARAMS = ("class_weight", "is_unbalance", "scale_pos_weight")

# Overrides on top of models.lightgbm in forecast.yaml; all strongly regularised (large leaves).
GRID = (
    {"id": "nl7_mcs200", "num_leaves": 7, "min_child_samples": 200},
    {"id": "nl15_mcs200", "num_leaves": 15, "min_child_samples": 200},
    {"id": "nl15_mcs2000_l10", "num_leaves": 15, "min_child_samples": 2000, "reg_lambda": 10.0},
    {"id": "nl15_mcs500_col05", "num_leaves": 15, "min_child_samples": 500, "colsample_bytree": 0.5},
    {"id": "nl31_mcs1000", "num_leaves": 31, "min_child_samples": 1000},
    {"id": "nl63_mcs5000_l10", "num_leaves": 63, "min_child_samples": 5000, "reg_lambda": 10.0},
)


def base_params(cfg) -> dict:
    params = dict(cfg.models.params("lightgbm"))
    neutral = {
        "class_weight": lambda v: v is None or v in ("none", "None"),
        "is_unbalance": lambda v: v is None or v is False,
        "scale_pos_weight": lambda v: v is None or (not isinstance(v, bool) and float(v) == 1.0),
    }
    for k in FORBIDDEN_PARAMS:
        if not neutral[k](params.get(k)):
            raise ValueError(f"models.lightgbm.{k} must not be set: class reweighting distorts probabilities")
        params.pop(k, None)
    if params.get("deterministic") is not True:
        raise ValueError("models.lightgbm.deterministic must be true")
    params.pop("n_estimators", None)
    return params


def grid_params(cfg, config_id: str) -> dict:
    over = next((g for g in GRID if g["id"] == config_id), None)
    if over is None:
        raise KeyError(f"unknown LightGBM grid config {config_id!r}")
    p = base_params(cfg)
    p.update({k: v for k, v in over.items() if k != "id"})
    return p


def _estimator(params: dict, n_estimators: int, seed: int):
    return lgb.LGBMClassifier(
        **params, n_estimators=int(n_estimators), random_state=int(seed), n_jobs=N_THREADS, verbosity=-1
    )


def _subsample(w, o, cap, seed_parts):
    if w.size <= cap:
        return w, o
    keep = np.sort(np.random.default_rng(list(seed_parts)).choice(w.size, cap, replace=False))
    return w[keep], o[keep]


@dataclass
class RowContext:
    """Duck-typed fit context for fold training: explicit rows per lead instead of the train split."""

    panel: object
    static: object
    cfg: object
    rows: dict

    def train_index(self, lead):
        return self.rows[lead]


class LightGBMForecaster:
    """Per-lead LightGBM with fixed (tuned) parameters and tree counts; fitted on training rows only."""

    def __init__(self, store, params_by_lead: dict, n_estimators_by_lead: dict, *, feature_names=None,
                 name="lightgbm", max_train_rows=MAX_TRAIN_ROWS, registry=REGISTRY):
        self.store = store
        self.registry = registry
        self.feature_names = tuple(full_feature_set(registry) if feature_names is None else feature_names)
        self.params_by_lead = dict(params_by_lead)
        self.n_estimators_by_lead = dict(n_estimators_by_lead)
        self.name = name
        self.max_train_rows = int(max_train_rows)
        self.models, self.n_train_ = {}, {}

    def fit(self, ctx, leads=None):
        self._parts = (ctx.panel, ctx.static, ctx.cfg)
        leads = tuple(ctx.cfg.leads if leads is None else leads)
        for lead in leads:
            if lead not in self.params_by_lead or lead not in self.n_estimators_by_lead:
                raise KeyError(f"no tuned parameters for lead {lead}")
            w, o = (np.asarray(a) for a in ctx.train_index(lead))
            w, o = _subsample(w, o, self.max_train_rows, (ctx.cfg.seed, lead, 12))
            X = design_matrix(self.store, ctx.panel, ctx.static, ctx.cfg, self.feature_names, lead, w, o,
                              registry=self.registry, dtype=np.float32)
            y = targets.lead_label(ctx.panel, lead)[w, o].astype(np.int64)
            est = _estimator(self.params_by_lead[lead], self.n_estimators_by_lead[lead], ctx.cfg.seed + lead)
            self.models[lead] = est.fit(X, y)
            self.n_train_[lead] = int(w.size)
        return self

    def predict(self, lead, ward_pos, origin_pos):
        if lead not in self.models:
            raise KeyError(f"lead {lead} not fitted")
        panel, static, cfg = self._parts
        X = design_matrix(self.store, panel, static, cfg, self.feature_names, lead, ward_pos, origin_pos,
                          registry=self.registry, dtype=np.float32)
        return self.models[lead].predict_proba(X)[:, 1].astype(np.float32)

    def gain_importance(self, lead) -> list:
        """Total split gain per feature, largest first (a fitted-model description, not causal)."""
        booster = self.models[lead].booster_
        gain = booster.feature_importance(importance_type="gain")
        order = np.argsort(-gain)
        return [(self.feature_names[i], float(gain[i])) for i in order]


class CalibratedPredictor:
    """Wraps a fitted predictor with one calibrator per lead."""

    def __init__(self, base, calibrators: dict, name: str):
        self.base, self.calibrators, self.name = base, dict(calibrators), name

    def predict(self, lead, ward_pos, origin_pos):
        return self.calibrators[lead].predict(self.base.predict(lead, ward_pos, origin_pos))


# --------------------------------------------------------------------------- cross-validation
def tune_folds(cfg, years=TUNE_FOLD_YEARS):
    folds = {f.year: f for f in splits.cv_folds(cfg.splits)}
    missing = [y for y in years if y not in folds]
    if missing:
        raise ValueError(f"tuning fold years {missing} are not configured CV folds")
    for y in years:
        if folds[y].validate_end > cfg.splits.train_end:
            raise ValueError(f"tuning fold {y} overlaps the validation split")
    return tuple(folds[y] for y in years)


def _fold_rows(panel, cfg, lead, fold):
    """(fit rows, early-stopping rows, out-of-fold rows) for one lead and fold."""
    wt, ot = dataset.lead_row_index(panel, cfg, lead, "train", fold=fold)
    wv, ov = dataset.lead_row_index(panel, cfg, lead, "validate", fold=fold)
    tgt = np.asarray(panel.week_index, dtype=np.int64)[ot] + lead
    tmax = fold.train_max_target_exclusive
    es = tgt >= tmax - ES_WEEKS
    fit = tgt < tmax - ES_WEEKS - cfg.splits.embargo_weeks
    return (wt[fit], ot[fit]), (wt[es], ot[es]), (wv, ov), (wt, ot)


def run_cv(panel, static, cfg, leads, *, grid=GRID, folds=None, max_train_rows=MAX_TRAIN_ROWS,
           with_logistic=True, build_store=None, log=print):
    """Expanding-window CV over the tuning folds.

    Returns a dict per lead with:
      ``y``, ``fold`` (OOF labels and fold year per OOF row),
      ``lgb``: {config_id: {"oof": p, "fold_brier": {year: bs}, "best_iter": {year: it}}},
      ``logistic``: OOF p of the logistic model (if ``with_logistic``).
    Fold feature stores are built one at a time (``build_store(fold) -> (clim, store)``) and freed.
    """
    folds = tune_folds(cfg) if folds is None else tuple(folds)
    build_store = build_store or (lambda f: dataset.build_fold_store(panel, static, f))
    names = full_feature_set()
    out = {k: {"y": [], "fold": [], "lgb": {g["id"]: {"oof": [], "fold_brier": {}, "best_iter": {}} for g in grid},
               "logistic": []} for k in leads}
    for fold in folds:
        log(f"CV fold {fold.year}: building fold feature store")
        _, store = build_store(fold)
        for lead in leads:
            (wf, of), (we, oe), (wv, ov), (wt, ot) = _fold_rows(panel, cfg, lead, fold)
            if wv.size == 0 or we.size == 0 or wf.size == 0:
                raise ValueError(f"fold {fold.year} lead {lead} has empty fit, early-stopping or OOF rows")
            lab = targets.lead_label(panel, lead)
            wf, of = _subsample(wf, of, max_train_rows, (cfg.seed, lead, fold.year, 1))
            we, oe = _subsample(we, oe, ES_MAX_ROWS, (cfg.seed, lead, fold.year, 2))
            dm = lambda w, o: design_matrix(store, panel, static, cfg, names, lead, w, o, dtype=np.float32)  # noqa: E731
            Xf, Xe, Xv = dm(wf, of), dm(we, oe), dm(wv, ov)
            yf, ye = lab[wf, of].astype(np.int64), lab[we, oe].astype(np.int64)
            yv = lab[wv, ov].astype(np.float64)
            out[lead]["y"].append(yv)
            out[lead]["fold"].append(np.full(yv.size, fold.year, dtype=np.int64))
            for g in grid:
                est = _estimator(grid_params(cfg, g["id"]), MAX_TREES, cfg.seed + lead)
                est.fit(Xf, yf, eval_X=(Xe,), eval_y=(ye,), eval_metric="binary_logloss",
                        callbacks=[lgb.early_stopping(ES_PATIENCE, verbose=False)])
                it = max(int(est.best_iteration_ or MAX_TREES), MIN_TREES)
                p = est.predict_proba(Xv, num_iteration=it)[:, 1]
                rec = out[lead]["lgb"][g["id"]]
                rec["oof"].append(p.astype(np.float32))
                rec["fold_brier"][fold.year] = float(np.mean((p - yv) ** 2))
                rec["best_iter"][fold.year] = it
            if with_logistic:
                lr = LogisticForecaster(store, max_train_rows=max_train_rows).fit(
                    RowContext(panel, static, cfg, {lead: (wt, ot)}), (lead,))
                out[lead]["logistic"].append(lr.predict(lead, wv, ov))
            log(f"CV fold {fold.year} lead {lead}: done")
            del Xf, Xe, Xv
        del store
        gc.collect()
    for lead in leads:
        d = out[lead]
        d["y"], d["fold"] = np.concatenate(d["y"]), np.concatenate(d["fold"])
        d["logistic"] = np.concatenate(d["logistic"]) if d["logistic"] else None
        for rec in d["lgb"].values():
            rec["oof"] = np.concatenate(rec["oof"])
    return out


def select_config(cv_lead: dict) -> tuple:
    """(config_id, n_estimators): lowest mean fold Brier (ties: grid order); trees = median best iteration."""
    order = [g["id"] for g in GRID if g["id"] in cv_lead["lgb"]]
    mean_bs = {c: float(np.mean(list(cv_lead["lgb"][c]["fold_brier"].values()))) for c in order}
    best = min(order, key=lambda c: (mean_bs[c], order.index(c)))
    n_est = max(int(np.median(list(cv_lead["lgb"][best]["best_iter"].values()))), MIN_TREES)
    return best, n_est, mean_bs


__all__ = [
    "GRID", "TUNE_FOLD_YEARS", "N_THREADS", "LightGBMForecaster", "CalibratedPredictor", "RowContext",
    "Calibrator", "base_params", "grid_params", "tune_folds", "run_cv", "select_config",
]
