"""Pre-test refit and the frozen model bundle (DEC-02).

Recipe, frozen before the test lock opens:
1. Model per lead and its settings come from Phase 12 (`MODEL_SELECTION.json`); the calibration
   method per lead comes from the 2015-2020 recalibration (`RECALIBRATION.json`).
2. Calibrators are fitted on expanding-window out-of-fold predictions for 2015-2020: for each year,
   the model is fitted on target weeks before that year (minus the embargo), with the climatology
   and features refitted on that past, and predicts the year. The best baseline of each lead is
   treated the same way, so the test compares like with like.
3. The final model is refitted on all target weeks up to the test start minus the embargo
   (1991-2020), with the climatology fitted up to `splits.validate_end`.

The bundle holds the fitted estimators, standardisation, feature names and calibrators only; it
never holds a feature store or any data. Baselines have no hyperparameters and are refitted
deterministically from the frozen data at test time; only their calibrators are frozen here.
"""
from __future__ import annotations

import gc
import hashlib
from pathlib import Path

import joblib
import numpy as np

from heatwave.forecast import baselines, dataset, splits, targets
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.features import build_feature_store
from heatwave.forecast.models import lgbm
from heatwave.forecast.models.calibration import Calibrator
from heatwave.forecast.models.logistic import MAX_TRAIN_ROWS, LogisticForecaster, design_matrix, full_feature_set

CAL_YEARS = (2015, 2016, 2017, 2018, 2019, 2020)
BUNDLE_NAME = "model_bundle.joblib"
BUNDLE_SCHEMA = 1
MODEL_NAME = "forecast"          # calibrated trained model, scored on test
RAW_NAME = "forecast_raw"        # same model before calibration


def recal_name(name: str) -> str:
    return name + "_recal"


def pretest_row_index(panel, cfg, lead):
    """(ward_pos, origin_pos) of labelled rows with target weeks before the test start minus the embargo."""
    lead = dataset._check_lead(cfg, lead)
    n = len(panel.wards)
    tgt = np.asarray(panel.week_index, dtype=np.int64) + lead
    keep = targets.has_label(panel, lead) & (tgt < splits.test_start_index() - cfg.splits.embargo_weeks)
    keep[: dataset.warmup_first_position(panel)] = False
    origins = np.nonzero(keep)[0]
    if origins.size and splits.protected_mask(tgt[origins]).any():
        raise RuntimeError("pre-test rows reach the protected test window")
    return np.tile(np.arange(n), origins.size), np.repeat(origins, n)


def calibration_folds(cfg, years=CAL_YEARS):
    folds = {f.year: f for f in splits.cv_folds(cfg.splits)}
    missing = [y for y in years if y not in folds]
    if missing:
        raise ValueError(f"calibration years {missing} are not configured CV folds")
    return tuple(folds[y] for y in years)


class FrozenLeadModel:
    """One lead's fitted estimator plus what is needed to predict from a feature store."""

    def __init__(self, kind, estimator, feature_names, mean=None, scale=None):
        if kind not in ("lightgbm", "logistic"):
            raise ValueError(f"unknown model kind {kind!r}")
        self.kind, self.estimator, self.feature_names = kind, estimator, tuple(feature_names)
        self.mean, self.scale = mean, scale

    def predict(self, store, panel, static, cfg, lead, ward_pos, origin_pos):
        X = design_matrix(store, panel, static, cfg, self.feature_names, lead, ward_pos, origin_pos,
                          dtype=np.float32 if self.kind == "lightgbm" else np.float64)
        if self.kind == "logistic":
            X = (X - self.mean) / self.scale
        return self.estimator.predict_proba(X)[:, 1].astype(np.float32)


def _fit_model(kind, s, store, ctx, lead, max_train_rows):
    if kind == "lightgbm":
        m = lgbm.LightGBMForecaster(store, {lead: s["lgb_params"]}, {lead: s["n_estimators"]},
                                    max_train_rows=max_train_rows).fit(ctx, (lead,))
        return FrozenLeadModel("lightgbm", m.models[lead], m.feature_names), m.n_train_[lead]
    m = LogisticForecaster(store, max_train_rows=max_train_rows).fit(ctx, (lead,))
    return FrozenLeadModel("logistic", m.models[lead], m.feature_names, m.mean_[lead], m.scale_[lead]), m.n_train_[lead]


def freeze(panel, static, cfg, selection, recalibration, *, leads=None, max_train_rows=MAX_TRAIN_ROWS,
           cal_years=CAL_YEARS, build_fold_store=None, log=print) -> dict:
    """Fit calibrators on 2015-2020 out-of-fold predictions and the final 1991-2020 models.

    ``selection`` / ``recalibration`` are the ``by_lead`` dicts of MODEL_SELECTION.json and
    RECALIBRATION.json. Returns the bundle dict (no data inside).
    """
    leads = sorted(int(k) for k in selection) if leads is None else list(leads)
    build_fold_store = build_fold_store or (lambda f: dataset.build_fold_store(panel, static, f))
    plan = {}
    for lead in leads:
        s = selection[str(lead)]
        kind = s["selected"].removesuffix("_cal")
        rc = recalibration[str(lead)]
        best = s["best_baseline"]
        plan[lead] = {"kind": kind, "settings": s, "model_method": rc[kind]["method"],
                      "best_baseline": best, "baseline_method": rc[best]["method"]}
    names = full_feature_set()
    oof = {lead: {"p": [], "pb": [], "y": [], "year": []} for lead in leads}
    for fold in calibration_folds(cfg, cal_years):
        log(f"calibration fold {fold.year}: building fold feature store")
        fclim, store = build_fold_store(fold)
        # per-lead fold rows: a baseline fitted for another lead must never see this fold's year
        bctx = baselines.FitContext(
            panel, static, fclim, cfg, fit_end=fold.climatology_end,
            train_index=lambda k, fold=fold: dataset.lead_row_index(panel, cfg, k, "train", fold=fold))
        bfit = baselines.fit_baselines(bctx, names=sorted({plan[k]["best_baseline"] for k in leads}))
        for lead in leads:
            pl = plan[lead]
            w, o = dataset.lead_row_index(panel, cfg, lead, "train", fold=fold)
            wv, ov = dataset.lead_row_index(panel, cfg, lead, "validate", fold=fold)
            rows = lgbm.RowContext(panel, static, cfg, {lead: (w, o)})
            model, _ = _fit_model(pl["kind"], pl["settings"], store, rows, lead, max_train_rows)
            p = model.predict(store, panel, static, cfg, lead, wv, ov)
            pb = bfit[pl["best_baseline"]].predict(lead, wv, ov)
            d = oof[lead]
            d["p"].append(p)
            d["pb"].append(pb)
            d["y"].append(targets.lead_label(panel, lead)[wv, ov])
            d["year"].append(np.full(wv.size, fold.year))
            log(f"calibration fold {fold.year} lead {lead}: done")
        del store
        gc.collect()

    calibrators, oof_summary = {}, {}
    for lead in leads:
        d = {k: np.concatenate(v) for k, v in oof[lead].items()}
        if not (np.isfinite(d["p"]).all() and np.isfinite(d["pb"]).all()):
            raise ValueError(f"non-finite out-of-fold predictions at lead {lead}")
        pl = plan[lead]
        cm = Calibrator(pl["model_method"]).fit(d["p"], d["y"])
        cb = Calibrator(pl["baseline_method"]).fit(d["pb"], d["y"])
        calibrators[lead] = {"model": cm, "baseline": cb}
        oof_summary[lead] = {"n_rows": int(d["y"].size), "base_rate": float(d["y"].mean()),
                             "mean_p_raw": float(d["p"].mean()), "mean_p_cal": float(cm.predict(d["p"]).mean()),
                             "mean_pb_raw": float(d["pb"].mean()), "mean_pb_cal": float(cb.predict(d["pb"]).mean())}

    log("final refit on 1991-2020")
    clim = Climatology.fit(panel, cfg.splits.validate_end)
    store = build_feature_store(panel, clim, static)
    models, n_train = {}, {}
    for lead in leads:
        rows = lgbm.RowContext(panel, static, cfg, {lead: pretest_row_index(panel, cfg, lead)})
        models[lead], n_train[lead] = _fit_model(plan[lead]["kind"], plan[lead]["settings"], store, rows, lead,
                                                 max_train_rows)
        log(f"final lead {lead}: {plan[lead]['kind']} fitted on {n_train[lead]:,} rows")
    del store
    gc.collect()
    return {
        "schema": BUNDLE_SCHEMA, "leads": leads, "feature_names": list(names),
        "climatology_fit_end": str(cfg.splits.validate_end), "calibration_years": list(cal_years),
        "plan": {lead: {k: v for k, v in pl.items() if k != "settings"} | {
            "lgb_config": pl["settings"].get("lgb_config"), "n_estimators": pl["settings"].get("n_estimators"),
            "lgb_params": pl["settings"].get("lgb_params")} for lead, pl in plan.items()},
        "models": models, "calibrators": calibrators, "n_train": n_train, "oof_summary": oof_summary,
        "max_train_rows": int(max_train_rows),
    }


def save_bundle(bundle: dict, path) -> str:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    joblib.dump(bundle, tmp, compress=3)
    tmp.replace(path)
    return sha256_file(path)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_bundle(path, expected_sha256: str) -> dict:
    """Load a bundle only when its bytes match the recorded hash."""
    got = sha256_file(path)
    if got != expected_sha256:
        raise ValueError(f"model bundle hash mismatch: {got} != {expected_sha256}")
    bundle = joblib.load(path)
    if bundle.get("schema") != BUNDLE_SCHEMA:
        raise ValueError("unsupported model bundle schema")
    return bundle


def describe(bundle: dict) -> dict:
    """JSON-safe summary of a bundle (for the manifest and the pre-registration)."""
    return {
        "schema": bundle["schema"], "leads": bundle["leads"], "n_features": len(bundle["feature_names"]),
        "climatology_fit_end": bundle["climatology_fit_end"], "calibration_years": bundle["calibration_years"],
        "max_train_rows": bundle["max_train_rows"],
        "by_lead": {str(k): {**bundle["plan"][k], "n_train": bundle["n_train"][k],
                             "calibrator_model": bundle["calibrators"][k]["model"].describe(),
                             "calibrator_baseline": bundle["calibrators"][k]["baseline"].describe(),
                             "oof": bundle["oof_summary"][k]} for k in bundle["leads"]},
    }
