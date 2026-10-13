"""How many evaluation rows fall outside each feature's training range (MODEL-04).

Tree models cannot extrapolate: beyond the training range they predict as at the edge. Under a
warming trend, the share of rows beyond the training maximum is an early sign of that risk.
Panel features depend only on (ward, origin), so the check works on whole origin columns.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from heatwave.forecast.features import REGISTRY, static_feature_matrix


def out_of_range_table(store, static, panel, feature_names, train_origins, eval_origins, registry=REGISTRY):
    """One row per panel or static feature: training min/max and the share of evaluation values outside it.

    ``train_origins`` / ``eval_origins`` are origin positions (every ward is used at each origin).
    Calendar (season) features are bounded by construction and are skipped.
    """
    tr = np.unique(np.asarray(train_origins, dtype=np.int64))
    ev = np.unique(np.asarray(eval_origins, dtype=np.int64))
    if tr.size == 0 or ev.size == 0:
        raise ValueError("train and eval origins must be non-empty")
    rows = []
    static_names = [nm for nm in feature_names if registry.get(nm).kind == "static"]
    smat = static_feature_matrix(static.align(panel.wards), static_names) if static_names else None
    for nm in feature_names:
        spec = registry.get(nm)
        if spec.kind == "panel":
            a_tr = np.asarray(store[nm][:, tr], dtype=np.float64)
            a_ev = np.asarray(store[nm][:, ev], dtype=np.float64)
        elif spec.kind == "static":
            col = smat[:, static_names.index(nm)].astype(np.float64)
            a_tr, a_ev = col, col
        else:
            continue
        a_tr, a_ev = a_tr[np.isfinite(a_tr)], a_ev[np.isfinite(a_ev)]
        lo, hi = float(a_tr.min()), float(a_tr.max())
        n = int(a_ev.size)
        below, above = int((a_ev < lo).sum()), int((a_ev > hi).sum())
        rows.append({
            "feature": nm, "family": spec.family, "train_min": lo, "train_max": hi,
            "eval_min": float(a_ev.min()), "eval_max": float(a_ev.max()), "n_eval": n,
            "n_below": below, "n_above": above, "frac_out": (below + above) / n if n else float("nan"),
        })
    df = pd.DataFrame(rows)
    return df.sort_values(["frac_out", "feature"], ascending=[False, True], ignore_index=True)
