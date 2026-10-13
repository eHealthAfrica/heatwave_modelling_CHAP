"""Grouped explanations for the trained forecast models (DEC-01).

Groups follow the ablation ladder: season, location, trend, persistence, lagged heat (recent heat
and spatial means) and soil/humidity/rain. All explanations describe the fitted models on the
validation years; they are not causal statements.

- Grouped permutation importance: the columns of one group are shuffled together (the same row
  permutation for every column, so within-group correlation is kept) and the rise in Brier score
  is recorded, averaged over a few seeds.
- Grouped SHAP: per-row contributions summed within each group, then the mean absolute value.
  LightGBM uses its exact TreeSHAP (``pred_contrib``); logistic uses the exact linear SHAP on the
  standardised scale (coefficient times standardised value; the training mean is zero).
"""
from __future__ import annotations

import numpy as np

from heatwave.forecast.models.logistic import ablation_ladder

GROUP_LABELS = {
    "season": "season",
    "+location": "location",
    "+trend": "trend",
    "+persistence": "persistence",
    "+heat": "lagged heat",
    "+land": "soil/humidity/rain",
}


def feature_groups(registry=None) -> dict:
    """Ordered {group label: feature names}, derived from the cumulative ablation ladder."""
    ladder = ablation_ladder() if registry is None else ablation_ladder(registry)
    out, prev = {}, ()
    for label, names in ladder:
        out[GROUP_LABELS[label]] = tuple(n for n in names if n not in prev)
        prev = names
    return out


def _group_index(feature_names, groups) -> dict:
    pos = {n: i for i, n in enumerate(feature_names)}
    idx = {}
    for g, names in groups.items():
        cols = [pos[n] for n in names if n in pos]
        if cols:
            idx[g] = np.asarray(cols, dtype=np.int64)
    missing = set(feature_names) - {feature_names[i] for c in idx.values() for i in c}
    if missing:
        raise ValueError(f"features without a group: {sorted(missing)}")
    return idx


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, dtype=np.float64) - np.asarray(y, dtype=np.float64)) ** 2))


def grouped_permutation(predict, X, y, feature_names, groups, seeds=(0, 1, 2)) -> list:
    """[{group, n_features, base_brier, delta_brier_mean, delta_brier_sd}] sorted by mean rise."""
    idx = _group_index(tuple(feature_names), groups)
    base = brier(predict(X), y)
    rows = []
    for g, cols in idx.items():
        deltas = []
        for s in seeds:
            perm = np.random.default_rng([int(s), len(g)]).permutation(X.shape[0])
            Xp = X.copy()
            Xp[:, cols] = X[perm][:, cols]
            deltas.append(brier(predict(Xp), y) - base)
        rows.append({"group": g, "n_features": int(cols.size), "base_brier": base,
                     "delta_brier_mean": float(np.mean(deltas)), "delta_brier_sd": float(np.std(deltas))})
    return sorted(rows, key=lambda r: -r["delta_brier_mean"])


def grouped_contributions(contrib, feature_names, groups) -> list:
    """Mean |sum of contributions within the group| per row, and its share of the total."""
    contrib = np.asarray(contrib, dtype=np.float64)
    if contrib.shape[1] == len(feature_names) + 1:  # LightGBM appends the expected value
        contrib = contrib[:, :-1]
    idx = _group_index(tuple(feature_names), groups)
    vals = {g: float(np.mean(np.abs(contrib[:, cols].sum(axis=1)))) for g, cols in idx.items()}
    total = sum(vals.values()) or 1.0
    rows = [{"group": g, "mean_abs_shap": v, "share": v / total} for g, v in vals.items()]
    return sorted(rows, key=lambda r: -r["mean_abs_shap"])


def lightgbm_contributions(lgb_estimator, X) -> np.ndarray:
    """Exact TreeSHAP contributions (log-odds scale) from LightGBM itself."""
    return lgb_estimator.booster_.predict(X, pred_contrib=True)


def logistic_contributions(logistic_model, mean, scale, X) -> np.ndarray:
    """Exact linear SHAP on the standardised scale (log-odds)."""
    Z = (np.asarray(X, dtype=np.float64) - mean) / scale
    return Z * logistic_model.coef_.ravel()[None, :]
