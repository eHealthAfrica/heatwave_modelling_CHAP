"""Tune LightGBM per lead with expanding-window CV, calibrate LightGBM and logistic on out-of-fold
predictions, select a model per lead by CV Brier, score everything on validation against the
baselines and logistic, and write docs/forecast/LIGHTGBM_VALIDATION.md, the reliability figure
and docs/forecast/MODEL_SELECTION.json.

    python scripts/forecast_lightgbm.py

Read-only on the frozen data; no Earth Engine access. Only training-era CV folds and the
validation split are used: test rows are never built, loaded or scored.
Exit codes: 0 ok, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.config import settings  # noqa: E402
from heatwave.forecast import baselines, dataset, targets, testlock  # noqa: E402
from heatwave.forecast.artifacts import REPO_ROOT, RUNS_SUBDIR, run_folder  # noqa: E402
from heatwave.forecast.climatology import Climatology  # noqa: E402
from heatwave.forecast.config import FORECAST_CONFIG_PATH, config_hash, load_forecast_config  # noqa: E402
from heatwave.forecast.data import frozen_dataset_dir, load_panel  # noqa: E402
from heatwave.forecast.evaluation import harness, predictions, slices  # noqa: E402
from heatwave.forecast.evaluation.extrapolation import out_of_range_table  # noqa: E402
from heatwave.forecast.evaluation.lightgbm_report import (  # noqa: E402
    CANDIDATES,
    GENERATED_MARKER,
    plot_reliability,
    reliability_check,
    render_markdown,
)
from heatwave.forecast.features import build_feature_store  # noqa: E402
from heatwave.forecast.models import lgbm  # noqa: E402
from heatwave.forecast.models.calibration import CLIP_HI, CLIP_LO, choose_calibrator  # noqa: E402
from heatwave.forecast.models.logistic import MAX_TRAIN_ROWS, LogisticForecaster, full_feature_set  # noqa: E402
from heatwave.forecast.static import load_static  # noqa: E402

DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_DOCS_OUT = DOCS_ROOT / "forecast" / "LIGHTGBM_VALIDATION.md"
SELECTION_NAME = "MODEL_SELECTION.json"
FIGURE_REL = "figures/phase12_reliability.png"
REFERENCES = ("recent_climatology", "damped_persistence", "trend_season", "logistic")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _inside(path: Path, base: Path) -> bool:
    base = base.resolve()
    return path == base or base in path.parents


def _int_list(text: str, what: str):
    try:
        vals = [int(t) for t in text.split(",") if t.strip() != ""]
    except ValueError:
        raise ValueError(f"{what} must be a comma list of integers, got {text!r}") from None
    if not vals:
        raise ValueError(f"{what} must not be empty")
    return vals


def _bad(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _week_attrs(panel, cfg, lead, origin_pos):
    tf = targets.timing_fields(panel, lead, cfg.latency_days)
    o = np.asarray(origin_pos, dtype=np.int64)
    return slices.week_attributes(
        np.asarray(tf.target_week_index)[o],
        np.asarray(tf.target_week_start)[o],
        np.asarray(tf.target_week, dtype=object)[o],
    )


def _store(panel, cfg, probs, lead, split, wp, op, run_dir, run_id, data_sha, threshold):
    chash = config_hash(cfg)
    paths = {}
    for nm, p in probs.items():
        if not np.isfinite(p).all():
            raise ValueError(f"{nm} produced non-finite probabilities on {split} rows (lead {lead})")
        df = predictions.build_frame(panel, cfg, nm, lead, split, wp, op, p)
        meta = predictions.PredictionMeta(run_id, chash, data_sha, nm, lead, split, threshold=float(threshold))
        paths[nm] = predictions.write_predictions(df, meta, run_dir, cfg=cfg)
    return paths


def _brier(p, y) -> float:
    return float(np.mean((np.asarray(p, dtype=np.float64) - np.asarray(y, dtype=np.float64)) ** 2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None, help="folder holding frozen/ (default: local_data_dir)")
    ap.add_argument("--runs-root", default=None, help="base for forecast_runs/ (default: data root)")
    ap.add_argument("--docs-out", default=str(DEFAULT_DOCS_OUT))
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    ap.add_argument("--leads", default=None, help="comma list (default: all configured leads)")
    ap.add_argument("--tune-years", default=",".join(map(str, lgbm.TUNE_FOLD_YEARS)))
    ap.add_argument("--grid", default=None, help="comma list of grid config ids (default: all)")
    ap.add_argument("--bootstrap-b", type=int, default=None, help="bootstrap replicates (default: config)")
    ap.add_argument("--max-train-rows", type=int, default=MAX_TRAIN_ROWS)
    ap.add_argument("--force", action="store_true",
                    help="allow --docs-out outside docs/ or over a file this script did not generate")
    args = ap.parse_args(argv)

    try:
        cfg = load_forecast_config(Path(args.config))
    except (ValueError, OSError) as exc:
        return _bad(f"invalid --config: {exc}")
    try:
        leads = _int_list(args.leads, "--leads") if args.leads else list(cfg.leads)
        tune_years = _int_list(args.tune_years, "--tune-years")
    except ValueError as exc:
        return _bad(str(exc))
    for k in leads:
        if k not in cfg.leads:
            return _bad(f"lead {k} is not a configured lead {list(cfg.leads)}")
    if len(tune_years) < 2:
        return _bad("--tune-years needs at least two folds (leave-one-fold-out calibration)")
    try:
        folds = lgbm.tune_folds(cfg, years=tuple(tune_years))
    except ValueError as exc:
        return _bad(str(exc))
    ids = [g["id"] for g in lgbm.GRID]
    grid = lgbm.GRID
    if args.grid:
        want = [t.strip() for t in args.grid.split(",") if t.strip()]
        unknown = [w for w in want if w not in ids]
        if unknown or not want:
            return _bad(f"--grid ids must be from {ids}")
        grid = tuple(g for g in lgbm.GRID if g["id"] in want)
    B = cfg.evaluation.bootstrap_b if args.bootstrap_b is None else args.bootstrap_b
    if B < 1:
        return _bad("--bootstrap-b must be >= 1")
    if args.max_train_rows < 1000:
        return _bad("--max-train-rows must be >= 1000")
    if not set(REFERENCES[:3]) <= set(cfg.baselines.names):
        return _bad(f"baselines.names must include {REFERENCES[:3]}")
    try:
        lgbm.base_params(cfg)
    except ValueError as exc:
        return _bad(str(exc))

    pin_override = None
    if args.expected_parquet_sha256 and args.expected_parquet_sha256 != cfg.data.expected_parquet_sha256:
        pin_override = {"pinned_in_forecast_yaml": cfg.data.expected_parquet_sha256,
                        "override_used": args.expected_parquet_sha256}
        print("WARNING: --expected-parquet-sha256 overrides the pinned anchor in forecast.yaml; "
              "the report and run manifest will record this.", file=sys.stderr)
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(
            cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256))
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root
    if _inside((runs_root / RUNS_SUBDIR).resolve(), REPO_ROOT):
        return _bad(f"--runs-root must not be inside the repository ({REPO_ROOT})")

    docs_out = Path(args.docs_out).resolve()
    if docs_out.suffix != ".md":
        return _bad(f"--docs-out must end in .md: {docs_out}")
    for base in (frozen_dataset_dir(cfg.data, data_root), REPO_ROOT / "outputs", REPO_ROOT / "keys"):
        if _inside(docs_out, base):
            return _bad(f"--docs-out must not be inside {base}")
    if not args.force:
        if not _inside(docs_out, DOCS_ROOT):
            return _bad(f"--docs-out must be under {DOCS_ROOT} (or pass --force): {docs_out}")
        if docs_out.exists() and docs_out != DEFAULT_DOCS_OUT.resolve():
            try:
                head = docs_out.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                head = ""
            if GENERATED_MARKER not in head:
                return _bad(f"{docs_out} exists and was not generated by this script (pass --force to overwrite)")
    selection_out = docs_out.parent / SELECTION_NAME
    figure_out = docs_out.parent / FIGURE_REL

    _log("loading frozen data")
    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)
    clim = Climatology.fit(panel, cfg.splits.train_end)
    areas = slices.load_ward_areas(cfg.data, panel.wards, data_root)
    ward_attrs = slices.ward_attributes(static.align(panel.wards), areas)

    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as rctx:
        # ---------------------------------------------------------------- CV (fold stores, freed per fold)
        _log(f"CV tuning: {len(grid)} configs x {len(folds)} folds x {len(leads)} leads")
        cv = lgbm.run_cv(panel, static, cfg, leads, grid=grid, folds=folds, max_train_rows=args.max_train_rows, log=_log)
        selection, cals = {}, {}
        for lead in leads:
            d = cv[lead]
            cid, n_est, mean_bs = lgbm.select_config(d)
            lgb_oof = d["lgb"][cid]["oof"]
            cal_lgb, cv_lgb = choose_calibrator(lgb_oof, d["y"], d["fold"])
            cal_lr, cv_lr = choose_calibrator(d["logistic"], d["y"], d["fold"])
            cv_brier = {"logistic": cv_lr["raw"], "logistic_cal": cv_lr[cal_lr.method],
                        "lightgbm": cv_lgb["raw"], "lightgbm_cal": cv_lgb[cal_lgb.method]}
            selected = min(CANDIDATES, key=lambda c: (cv_brier[c], CANDIDATES.index(c)))
            cals[lead] = {"lightgbm": cal_lgb, "logistic": cal_lr}
            selection[str(lead)] = {
                "selected": selected, "lgb_config": cid, "lgb_params": lgbm.grid_params(cfg, cid),
                "n_estimators": n_est, "grid_mean_fold_brier": mean_bs,
                "best_iter_by_fold": d["lgb"][cid]["best_iter"],
                "cal_lightgbm": {**cal_lgb.describe(), "cv_brier": cv_lgb},
                "cal_logistic": {**cal_lr.describe(), "cv_brier": cv_lr},
                "cv_brier": cv_brier, "n_oof_rows": int(d["y"].size),
                "oof_base_rate": float(d["y"].mean()),
            }
            _log(f"lead {lead}: config {cid}, {n_est} trees, calibrators {cal_lgb.method}/{cal_lr.method}, "
                 f"selected {selected}")
        del cv
        gc.collect()

        # ---------------------------------------------------------------- final fits on the train split
        _log("building feature store (train-era climatology)")
        store = build_feature_store(panel, clim, static)
        fctx = baselines.FitContext(panel, static, clim, cfg)
        _log("fitting baselines")
        fitted = baselines.fit_baselines(fctx)
        order = list(cfg.baselines.names)
        _log("fitting logistic")
        lr_model = LogisticForecaster(store, max_train_rows=args.max_train_rows).fit(fctx, leads)
        _log("fitting LightGBM with tuned settings")
        lgb_model = lgbm.LightGBMForecaster(
            store, {k: selection[str(k)]["lgb_params"] for k in leads},
            {k: selection[str(k)]["n_estimators"] for k in leads}, max_train_rows=args.max_train_rows,
        ).fit(fctx, leads)
        models = {
            "logistic": lr_model,
            "logistic_cal": lgbm.CalibratedPredictor(lr_model, {k: cals[k]["logistic"] for k in leads}, "logistic_cal"),
            "lightgbm": lgb_model,
            "lightgbm_cal": lgbm.CalibratedPredictor(lgb_model, {k: cals[k]["lightgbm"] for k in leads}, "lightgbm_cal"),
        }

        # ---------------------------------------------------------------- validation scoring
        val_results, thresholds = {}, {}
        for lead in leads:
            _log(f"lead {lead}: predicting and scoring")
            wp, op = dataset.lead_row_index(panel, cfg, lead, "validate")
            threshold = baselines.train_base_rate(fctx, lead)
            thresholds[lead] = threshold
            probs = {nm: fitted[nm].predict(lead, wp, op) for nm in order}
            for nm, m in models.items():
                probs[nm] = m.predict(lead, wp, op)
            paths = _store(panel, cfg, probs, lead, "validate", wp, op, rctx.path, rctx.run_id, panel.sha256, threshold)
            sctx = harness.ScoringContext(
                cfg, lead, threshold, ward_attrs, _week_attrs(panel, cfg, lead, op),
                B=B, run_id=rctx.run_id, log_root=runs_root, data_sha256=panel.sha256,
            )
            val_results[lead] = harness.score_lead(paths, sctx, references=REFERENCES)

        best, reliability = {}, {}
        for lead, res in val_results.items():
            brier = {r["predictor"]: float(r["brier"]) for r in res.summary.to_dict("records") if r["predictor"] in order}
            best[lead] = harness.best_baseline(brier, order)
            if best[lead] not in REFERENCES:
                raise RuntimeError(f"best baseline {best[lead]} at lead {lead} is not a scored reference {REFERENCES}")
            reliability[str(lead)] = {nm: reliability_check(res, nm) for nm in CANDIDATES}
            vb = {c: float(res.summary.set_index("predictor").loc[c, "brier"]) for c in CANDIDATES}
            selection[str(lead)]["validation_brier"] = vb
            selection[str(lead)]["validation_best_candidate"] = min(CANDIDATES, key=lambda c: vb[c])
            selection[str(lead)]["best_baseline"] = best[lead]

        _log("extrapolation check")
        names = [n for n in full_feature_set() if n not in ("target_season_sin", "target_season_cos")]
        tr_orig = fctx.train_index(1)[1]
        va_orig = dataset.lead_row_index(panel, cfg, 1, "validate")[1]
        extrap = out_of_range_table(store, static, panel, names, tr_orig, va_orig).to_dict("records")

        importance = {}
        for lead in leads:
            imp = lgb_model.gain_importance(lead)
            total = sum(g for _, g in imp) or 1.0
            importance[str(lead)] = [(nm, g / total) for nm, g in imp[:15]]

        rel_names = [c for c in CANDIDATES]
        plot_reliability(val_results, rel_names, rctx.path / "phase12_reliability.png")

        meta = dict(
            run_id=rctx.run_id,
            generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            data_version=cfg.data.version, parquet_sha256=panel.sha256, config_sha256=config_hash(cfg),
            seed=cfg.seed, B=B, block_weeks=cfg.evaluation.block_weeks, ci_level=cfg.gate.ci_level,
            lightgbm_version=lightgbm.__version__, n_threads=lgbm.N_THREADS,
            tune_years=list(tune_years), es_weeks=lgbm.ES_WEEKS, embargo_weeks=cfg.splits.embargo_weeks,
            grid=[dict(g) for g in grid], clip=[CLIP_LO, CLIP_HI], max_train_rows=args.max_train_rows,
            n_wards=len(panel.wards), primary_leads=list(cfg.gate.primary_leads),
            test_runs=testlock.count_test_runs(runs_root),  # raises on a broken log chain
            test_scored_in_run=testlock.count_test_scores(run_id=rctx.run_id, data_root=runs_root),
            log_chain_ok=testlock.verify_log_chain(runs_root),
            best_baseline_by_lead=best, references=list(REFERENCES), selection=selection,
            reliability=reliability, extrapolation=extrap, importance=importance,
            figure_rel=FIGURE_REL, pin_override=pin_override,
        )
        if pin_override:
            rctx.manifest["pin_override"] = pin_override
        md = render_markdown(val_results, meta)
        sel_doc = {
            "generated_by": "scripts/forecast_lightgbm.py", "run_id": rctx.run_id,
            "config_sha256": config_hash(cfg), "parquet_sha256": panel.sha256, "seed": cfg.seed,
            "lightgbm_version": lightgbm.__version__, "n_threads": lgbm.N_THREADS,
            "max_train_rows": args.max_train_rows, "tune_years": list(tune_years), "by_lead": selection,
        }
        sel_text = json.dumps(_json_safe(sel_doc), indent=1, allow_nan=False)
        payload = {"meta": meta, "thresholds": thresholds,
                   "validate": {k: harness.results_to_dict(r) for k, r in val_results.items()}}
        (rctx.path / "lightgbm_results.json").write_text(
            json.dumps(_json_safe(payload), indent=1, allow_nan=False), encoding="utf-8")
        (rctx.path / SELECTION_NAME).write_text(sel_text, encoding="utf-8")
        (rctx.path / "LIGHTGBM_VALIDATION.md").write_text(md, encoding="utf-8")

        docs_out.parent.mkdir(parents=True, exist_ok=True)
        figure_out.parent.mkdir(parents=True, exist_ok=True)
        for target, write in ((figure_out, lambda t: t.write_bytes((rctx.path / "phase12_reliability.png").read_bytes())),
                              (selection_out, lambda t: t.write_text(sel_text, encoding="utf-8")),
                              (docs_out, lambda t: t.write_text(md, encoding="utf-8"))):
            tmp = target.with_name(target.name + ".tmp")
            write(tmp)
            os.replace(tmp, target)

    print(f"run folder: {rctx.path}")
    print(f"docs report: {docs_out}")
    for lead in leads:
        s = selection[str(lead)]
        res = val_results[lead]
        c = res.comparisons
        row = c[(c["reference"] == best[lead]) & (c["candidate"] == s["selected"])].iloc[0]
        print(f"lead {lead}: selected {s['selected']} ({s['lgb_config']}, {s['n_estimators']} trees); "
              f"BSS vs {best[lead]} {row['bss']:.3f} [{row['bss_week_lo']:.3f}, {row['bss_week_hi']:.3f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
