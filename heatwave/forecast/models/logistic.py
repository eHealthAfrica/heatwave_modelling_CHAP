"""Regularised logistic regression per lead (MODEL-01), plus the Phase 11 negative controls.

The model follows the baselines' ``Predictor`` protocol: ``fit(ctx)`` uses only
``ctx.train_index(lead)`` rows (embargo and warm-up excluded), ``predict(lead, ward_pos,
origin_pos)`` returns float32 probabilities. Features come from the leakage-tested feature
store. The standardisation is fitted on the training sample only.

Negative controls (EVAL-06):
- ``year_shuffle_map``: each origin's panel features are replaced by those of the same ISO
  week slot in another year of the same split. Season and location stay true. If skill
  survives the shuffle, the model is living on season, place and trend rather than on the
  current state of the weather.
- skill-vs-lead decay is checked by the script with ``harness.persistence_decay_check``.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from heatwave.forecast import dataset, targets
from heatwave.forecast.climatology import iso_week_slots
from heatwave.forecast.features import REGISTRY

# 5.2M training rows x 57 features is about 2.4 GB in float64; neighbouring wards are near
# duplicates, so a seeded subsample loses little and keeps the fit inside laptop memory.
MAX_TRAIN_ROWS = 1_500_000

# One model per lead, so the constant lead feature carries no information.
EXCLUDED_FEATURES = ("lead_weeks",)

PERSISTENCE_FEATURES = ("hw_lag0", "hw_lag1", "hw_lag2", "hw_lag3", "hw_roll2", "hw_roll4", "hw_roll8")


def _family(names_or_family, registry=REGISTRY):
    return tuple(registry.names(family=names_or_family))


def ablation_ladder(registry=REGISTRY) -> tuple:
    """Cumulative feature steps: season, +location, +trend, +persistence, +heat, +land.

    The last step is the full feature set used by the main model.
    """
    season = tuple(n for n in _family("season", registry) if n not in EXCLUDED_FEATURES)
    location = _family("static", registry)
    trend = _family("trend", registry)
    persistence = tuple(n for n in PERSISTENCE_FEATURES if n in registry)
    heat = tuple(n for n in _family("recent_heat", registry) if n not in persistence) + _family("spatial", registry)
    land = _family("land_humidity", registry)
    steps, acc = [], ()
    for label, group in (
        ("season", season), ("+location", location), ("+trend", trend),
        ("+persistence", persistence), ("+heat", heat), ("+land", land),
    ):
        acc = acc + group
        steps.append((label, acc))
    return tuple(steps)


def full_feature_set(registry=REGISTRY) -> tuple:
    return ablation_ladder(registry)[-1][1]


def _lr_kwargs(cfg) -> dict:
    """Configured logistic-regression settings. Class weighting is refused: it distorts probabilities."""
    params = dict(cfg.models.params("logistic_regression"))
    if params.get("class_weight") not in (None, "none", "None"):
        raise ValueError("models.logistic_regression.class_weight must not be set: it distorts probabilities")
    params.pop("class_weight", None)
    penalty = params.pop("penalty", "l2")
    if penalty != "l2":
        raise ValueError(f"only an l2 penalty is supported in Phase 11, got {penalty!r}")
    params.setdefault("max_iter", 2000)
    params.setdefault("solver", "lbfgs")
    return params


def year_shuffle_map(panel, origins, seed: int):
    """Map each origin position to one with the same ISO week slot in a different year.

    Returns ``(lookup, self_mapped)``: ``lookup`` is an int64 array over all panel positions
    (-1 outside ``origins``). Only positions from ``origins`` (one split's origins) are used as
    map targets, so a shuffled feature never comes from another split. Origins whose slot occurs
    in one year only map to themselves and are counted in ``self_mapped``.
    """
    origins = np.unique(np.asarray(origins, dtype=np.int64))
    slots = iso_week_slots(panel.week_start).astype(np.int64)
    years = np.asarray(panel.week_start).astype("datetime64[D]").astype("datetime64[Y]").astype(np.int64) + 1970
    rng = np.random.default_rng(seed)
    lookup = np.full(len(slots), -1, dtype=np.int64)
    self_mapped = 0
    for s in np.unique(slots[origins]):
        pos = origins[slots[origins] == s]
        for t in pos:
            cand = pos[years[pos] != years[t]]
            if cand.size == 0:
                lookup[t] = t
                self_mapped += 1
            else:
                lookup[t] = rng.choice(cand)
    return lookup, self_mapped


def design_matrix(store, panel, static, cfg, feature_names, lead, ward_pos, origin_pos, feature_origin=None,
                  registry=REGISTRY, dtype=np.float64):
    """(rows, features) design for one lead. Season always follows the true target week; panel
    features are read at ``feature_origin`` (default: the row's own origin)."""
    ward_pos = np.asarray(ward_pos, dtype=np.int64)
    origin_pos = np.asarray(origin_pos, dtype=np.int64)
    fo = origin_pos if feature_origin is None else np.asarray(feature_origin, dtype=np.int64)
    tf = targets.timing_fields(panel, lead, cfg.latency_days)
    target_start = np.asarray(tf.target_week_start)[origin_pos]
    cols = dataset._gather_features(store, static, panel, feature_names, ward_pos, fo, target_start, lead, registry)
    X = np.column_stack([np.asarray(cols[nm], dtype=dtype) for nm in feature_names])
    if not np.isfinite(X).all():
        raise ValueError(f"non-finite feature values for lead {lead} (warm-up rows must be excluded)")
    return X


class LogisticForecaster:
    """Per-lead regularised logistic regression on the leakage-tested feature store."""

    def __init__(self, store, *, feature_names=None, name="logistic", max_train_rows=MAX_TRAIN_ROWS,
                 shuffle_seed=None, registry=REGISTRY):
        self.store = store
        self.registry = registry
        self.feature_names = tuple(full_feature_set(registry) if feature_names is None else feature_names)
        for nm in self.feature_names:
            if nm in EXCLUDED_FEATURES:
                raise ValueError(f"{nm} is constant within a single-lead model")
            registry.get(nm)  # KeyError for an unknown feature
        self.name = name
        self.max_train_rows = int(max_train_rows)
        self.shuffle_seed = shuffle_seed  # None = real features; int = year-shuffle negative control
        self.models, self.mean_, self.scale_, self.n_train_ = {}, {}, {}, {}

    # ------------------------------------------------------------------ design
    def _design(self, ctx_or_parts, lead, ward_pos, origin_pos, feature_origin=None):
        panel, static, cfg = ctx_or_parts
        return design_matrix(self.store, panel, static, cfg, self.feature_names, lead, ward_pos, origin_pos,
                             feature_origin, self.registry)

    def _feature_origins(self, panel, lead, split_origins, origin_pos):
        if self.shuffle_seed is None:
            return None
        lookup, _ = year_shuffle_map(panel, split_origins, self.shuffle_seed + 1000 * int(lead))
        fo = lookup[np.asarray(origin_pos, dtype=np.int64)]
        if (fo < 0).any():
            raise ValueError("origins outside split_origins cannot be year-shuffled")
        return fo

    # ------------------------------------------------------------------ fit / predict
    def fit(self, ctx, leads=None):
        """Fit one model per lead (default: every configured lead) on training rows only."""
        self._parts = (ctx.panel, ctx.static, ctx.cfg)
        kwargs = _lr_kwargs(ctx.cfg)
        leads = tuple(ctx.cfg.leads if leads is None else leads)
        for k in leads:
            if k not in ctx.cfg.leads:
                raise ValueError(f"lead {k} is not a configured lead {list(ctx.cfg.leads)}")
        for lead in leads:
            w, o = ctx.train_index(lead)
            w, o = np.asarray(w), np.asarray(o)
            if w.size > self.max_train_rows:
                rng = np.random.default_rng([int(ctx.cfg.seed), int(lead), 11])
                keep = np.sort(rng.choice(w.size, self.max_train_rows, replace=False))
                w, o = w[keep], o[keep]
            fo = self._feature_origins(ctx.panel, lead, np.asarray(ctx.train_index(lead)[1]), o)
            X = self._design(self._parts, lead, w, o, fo)
            y = targets.lead_label(ctx.panel, lead)[w, o].astype(np.int64)
            mean = X.mean(axis=0)
            scale = X.std(axis=0)
            scale[scale == 0] = 1.0
            mdl = LogisticRegression(**kwargs).fit((X - mean) / scale, y)
            self.models[lead], self.mean_[lead], self.scale_[lead] = mdl, mean, scale
            self.n_train_[lead] = int(w.size)
        return self

    def predict(self, lead, ward_pos, origin_pos, *, split_origins=None):
        """Probabilities for the given rows. For the year-shuffle control pass the split's origins."""
        if lead not in self.models:
            raise KeyError(f"lead {lead} not fitted")
        fo = None
        if self.shuffle_seed is not None:
            if split_origins is None:
                raise ValueError("the year-shuffle control needs split_origins to shuffle within one split")
            fo = self._feature_origins(self._parts[0], lead, split_origins, origin_pos)
        X = self._design(self._parts, lead, ward_pos, origin_pos, fo)
        X = (X - self.mean_[lead]) / self.scale_[lead]
        return self.models[lead].predict_proba(X)[:, 1].astype(np.float32)

    def coefficients(self, lead) -> list:
        """Standardised coefficients, largest magnitude first: [(feature, coef), ...]."""
        coef = self.models[lead].coef_.ravel()
        order = np.argsort(-np.abs(coef))
        return [(self.feature_names[i], float(coef[i])) for i in order]
