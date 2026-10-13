"""Per-lead probability calibration on out-of-fold predictions (MODEL-03).

Calibrators are fitted only on out-of-fold (OOF) CV predictions: each OOF probability comes
from a model that never saw that row, neither for fitting nor for early stopping. Platt and
isotonic are compared by leave-one-fold-out Brier on the OOF rows, and the winner is refitted
on all OOF rows. Outputs are clipped to [CLIP_LO, CLIP_HI].
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

CLIP_LO, CLIP_HI = 0.001, 0.999
METHODS = ("platt", "isotonic")
_EPS = 1e-6


def _logit(p):
    p = np.clip(np.asarray(p, dtype=np.float64), _EPS, 1 - _EPS)
    return np.log(p / (1 - p))


class Calibrator:
    """Platt (logistic on the logit) or isotonic map from raw to calibrated probability."""

    def __init__(self, method: str):
        if method not in METHODS:
            raise ValueError(f"unknown calibration method {method!r}; allowed: {METHODS}")
        self.method = method
        self._m = None

    def fit(self, p, y):
        p = np.asarray(p, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if p.shape != y.shape or p.size == 0:
            raise ValueError("calibration needs equal-length, non-empty p and y")
        if not (np.isfinite(p).all() and np.isfinite(y).all()):
            raise ValueError("calibration inputs must be finite")
        if self.method == "platt":
            # effectively unpenalised: two parameters on hundreds of thousands of rows
            self._m = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(_logit(p)[:, None], y.astype(int))
        else:
            self._m = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p, y)
        return self

    def predict(self, p) -> np.ndarray:
        if self._m is None:
            raise RuntimeError("calibrator not fitted")
        p = np.asarray(p, dtype=np.float64)
        if self.method == "platt":
            q = self._m.predict_proba(_logit(p)[:, None])[:, 1]
        else:
            q = self._m.predict(p)
        return np.clip(q, CLIP_LO, CLIP_HI).astype(np.float32)

    def describe(self) -> dict:
        if self.method == "platt" and self._m is not None:
            return {"method": "platt", "slope": float(self._m.coef_[0, 0]), "intercept": float(self._m.intercept_[0])}
        return {"method": self.method}


def lofo_predictions(p, y, fold_id, method: str) -> np.ndarray:
    """Leave-one-fold-out calibrated probabilities: each fold is mapped by a calibrator fitted on the others."""
    p, y, fold_id = np.asarray(p), np.asarray(y), np.asarray(fold_id)
    folds = np.unique(fold_id)
    if folds.size < 2:
        raise ValueError("leave-one-fold-out calibration needs at least two folds")
    out = np.empty(p.shape, dtype=np.float32)
    for f in folds:
        held = fold_id == f
        out[held] = Calibrator(method).fit(p[~held], y[~held]).predict(p[held])
    return out


def choose_calibrator(p, y, fold_id) -> tuple:
    """Pick Platt or isotonic by leave-one-fold-out Brier; refit the winner on all OOF rows.

    Returns ``(calibrator, cv_brier)`` where ``cv_brier`` maps each method, and ``raw``, to its
    leave-one-fold-out Brier score. Ties go to Platt (fewer parameters).
    """
    y64 = np.asarray(y, dtype=np.float64)
    cv = {"raw": float(np.mean((np.asarray(p, dtype=np.float64) - y64) ** 2))}
    for m in METHODS:
        q = lofo_predictions(p, y, fold_id, m).astype(np.float64)
        cv[m] = float(np.mean((q - y64) ** 2))
    best = min(METHODS, key=lambda m: (cv[m], METHODS.index(m)))
    return Calibrator(best).fit(p, y), cv
