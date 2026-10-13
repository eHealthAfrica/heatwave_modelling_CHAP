"""Recalibrate the Phase 12 validation predictions leave-one-year-out on 2015-2020, score them
against the (also recalibrated) baselines, and write docs/forecast/RECALIBRATION_VALIDATION.md,
docs/forecast/RECALIBRATION.json and a reliability figure.

    python scripts/forecast_recalibrate.py

Reads the stored predictions of the Phase 12 run named in docs/forecast/MODEL_SELECTION.json; no
model is refitted and no Earth Engine access is made. Only validation predictions are read; test
rows are never built, loaded or scored. Exit codes: 0 ok, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.config import settings  # noqa: E402
from heatwave.forecast import testlock  # noqa: E402
from heatwave.forecast.artifacts import REPO_ROOT, RUNS_SUBDIR, run_folder  # noqa: E402
from heatwave.forecast.config import FORECAST_CONFIG_PATH, config_hash, load_forecast_config  # noqa: E402
from heatwave.forecast.data import frozen_dataset_dir, load_panel  # noqa: E402
from heatwave.forecast.evaluation import harness, predictions, slices  # noqa: E402
from heatwave.forecast.evaluation.lightgbm_report import plot_reliability, reliability_check  # noqa: E402
from heatwave.forecast.evaluation.recalibration import (  # noqa: E402
    BASELINE_RECAL,
    GENERATED_MARKER,
    MODELS,
    loyo_recalibrate,
    recal_name,
    render_markdown,
)
from heatwave.forecast.static import load_static  # noqa: E402

DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_DOCS_OUT = DOCS_ROOT / "forecast" / "RECALIBRATION_VALIDATION.md"
DEFAULT_SELECTION = DOCS_ROOT / "forecast" / "MODEL_SELECTION.json"
JSON_NAME = "RECALIBRATION.json"
FIGURE_REL = "figures/recalibration_reliability.png"
BASELINES_KEPT = ("climatology", "recent_climatology", "persistence", "damped_persistence", "trend_season")


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _inside(path: Path, base: Path) -> bool:
    base = base.resolve()
    return path == base or base in path.parents


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


def _week_attrs_from_frame(panel, df):
    tw = df["target_week_index"].to_numpy(dtype=np.int64)
    wi = np.asarray(panel.week_index, dtype=np.int64)
    pos = np.searchsorted(wi, tw)
    if (pos >= wi.size).any() or (wi[np.minimum(pos, wi.size - 1)] != tw).any():
        raise ValueError("target weeks outside the panel")
    start = np.asarray(panel.week_start).astype("datetime64[D]")[pos]
    return slices.week_attributes(tw, start, df["target_week"].astype(str).to_numpy())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None, help="folder holding frozen/ (default: local_data_dir)")
    ap.add_argument("--runs-root", default=None, help="base for forecast_runs/ (default: data root)")
    ap.add_argument("--selection", default=str(DEFAULT_SELECTION), help="MODEL_SELECTION.json from Phase 12")
    ap.add_argument("--source-run-dir", default=None, help="Phase 12 run folder (default: from --selection)")
    ap.add_argument("--docs-out", default=str(DEFAULT_DOCS_OUT))
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    ap.add_argument("--bootstrap-b", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="allow --docs-out outside docs/ or over a file this script did not generate")
    args = ap.parse_args(argv)

    try:
        cfg = load_forecast_config(Path(args.config))
    except (ValueError, OSError) as exc:
        return _bad(f"invalid --config: {exc}")
    B = cfg.evaluation.bootstrap_b if args.bootstrap_b is None else args.bootstrap_b
    if B < 1:
        return _bad("--bootstrap-b must be >= 1")
    try:
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        by_lead = sel["by_lead"]
    except (OSError, ValueError, KeyError) as exc:
        return _bad(f"cannot read --selection: {exc}")
    pin_override = None
    if args.expected_parquet_sha256 and args.expected_parquet_sha256 != cfg.data.expected_parquet_sha256:
        pin_override = {"pinned_in_forecast_yaml": cfg.data.expected_parquet_sha256,
                        "override_used": args.expected_parquet_sha256}
        print("WARNING: --expected-parquet-sha256 overrides the pinned anchor in forecast.yaml.", file=sys.stderr)
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(
            cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256))
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root
    if _inside((runs_root / RUNS_SUBDIR).resolve(), REPO_ROOT):
        return _bad(f"--runs-root must not be inside the repository ({REPO_ROOT})")
    src = Path(args.source_run_dir) if args.source_run_dir else runs_root / RUNS_SUBDIR / sel.get("run_id", "")
    if not (src / "predictions").is_dir():
        return _bad(f"source run has no predictions folder: {src}")
    leads = sorted(int(k) for k in by_lead)
    for k in leads:
        if k not in cfg.leads:
            return _bad(f"selection lead {k} is not a configured lead")

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
            head = docs_out.read_text(encoding="utf-8", errors="replace")
            if GENERATED_MARKER not in head:
                return _bad(f"{docs_out} exists and was not generated by this script (pass --force to overwrite)")

    _log("loading frozen data")
    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)
    areas = slices.load_ward_areas(cfg.data, panel.wards, data_root)
    ward_attrs = slices.ward_attributes(static.align(panel.wards), areas)
    chash = config_hash(cfg)

    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as rctx:
        results, calibrators, base_model, best_by_lead, reliability = {}, {}, {}, {}, {}
        for lead in leads:
            _log(f"lead {lead}: recalibrating and scoring")
            frames = {}
            for nm in BASELINES_KEPT + MODELS:
                path = predictions.prediction_path(src, nm, lead, "validate")
                df, meta = predictions.load_predictions(path, cfg, data_root=runs_root)
                if meta.split != "validate":
                    raise ValueError(f"{path} is not a validation prediction file")
                frames[nm] = (df, meta)
            ref_df = frames[MODELS[0]][0]
            years = np.array([int(s[:4]) for s in ref_df["target_week"].astype(str)], dtype=np.int64)
            calibrators[str(lead)] = {}
            out = {}
            for nm in MODELS + BASELINE_RECAL:
                df = frames[nm][0]
                if not (df["ward"].astype(str).to_numpy() == ref_df["ward"].astype(str).to_numpy()).all() or \
                        not (df["target_week_index"].to_numpy() == ref_df["target_week_index"].to_numpy()).all():
                    raise ValueError(f"{nm} rows are not aligned with {MODELS[0]} at lead {lead}")
                r = loyo_recalibrate(df["p"].to_numpy(), df["y"].to_numpy(), years)
                calibrators[str(lead)][nm] = {"method": r["method"], "cv_brier": r["cv_brier"],
                                              "final": r["final"].describe()}
                out[recal_name(nm)] = r["q"]
            paths = {}
            threshold = frames[MODELS[0]][1].threshold
            for nm, (df, meta) in frames.items():
                m = predictions.PredictionMeta(rctx.run_id, chash, panel.sha256, nm, lead, "validate", threshold=threshold)
                paths[nm] = predictions.write_predictions(df.copy(), m, rctx.path, cfg=cfg)
            for nm, q in out.items():
                df = ref_df.copy()
                df["predictor"] = df["predictor"].cat.rename_categories([nm])
                df["p"] = q.astype(np.float32)
                m = predictions.PredictionMeta(rctx.run_id, chash, panel.sha256, nm, lead, "validate", threshold=threshold)
                paths[nm] = predictions.write_predictions(df, m, rctx.path, cfg=cfg)
            best = by_lead[str(lead)]["best_baseline"]
            if best not in BASELINE_RECAL:
                raise RuntimeError(f"best baseline {best} at lead {lead} has no recalibrated counterpart")
            refs = ("recent_climatology", "damped_persistence", "trend_season",
                    recal_name("damped_persistence"), recal_name("trend_season"))
            sctx = harness.ScoringContext(
                cfg, lead, threshold, ward_attrs, _week_attrs_from_frame(panel, ref_df),
                B=B, run_id=rctx.run_id, log_root=runs_root, data_sha256=panel.sha256,
            )
            results[lead] = harness.score_lead(paths, sctx, references=refs)
            base_model[str(lead)] = by_lead[str(lead)]["selected"].removesuffix("_cal")
            best_by_lead[str(lead)] = best
            reliability[str(lead)] = {recal_name(n): reliability_check(results[lead], recal_name(n))
                                      for n in MODELS + BASELINE_RECAL}

        plot_reliability(results, [recal_name(n) for n in MODELS], rctx.path / "recalibration_reliability.png")
        meta = dict(
            run_id=rctx.run_id, source_run=src.name,
            generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            data_version=cfg.data.version, parquet_sha256=panel.sha256, config_sha256=chash, seed=cfg.seed, B=B,
            test_runs=testlock.count_test_runs(runs_root),
            test_scored_in_run=testlock.count_test_scores(run_id=rctx.run_id, data_root=runs_root),
            log_chain_ok=testlock.verify_log_chain(runs_root),
            calibrators=calibrators, base_model=base_model, best_baseline_by_lead=best_by_lead,
            reliability=reliability, figure_rel=FIGURE_REL, pin_override=pin_override,
        )
        md = render_markdown(results, meta)
        rec_doc = {
            "generated_by": "scripts/forecast_recalibrate.py", "run_id": rctx.run_id, "source_run": src.name,
            "config_sha256": chash, "parquet_sha256": panel.sha256, "calibration_years": [2015, 2020],
            "recipe": "leave-one-year-out choice of Platt vs isotonic on 2015-2020; final calibrator fitted on all "
                      "six years; outputs clipped",
            "by_lead": {str(k): {"base_model": base_model[str(k)], **calibrators[str(k)]} for k in leads},
        }
        rec_text = json.dumps(_json_safe(rec_doc), indent=1, allow_nan=False)
        (rctx.path / JSON_NAME).write_text(rec_text, encoding="utf-8")
        (rctx.path / "RECALIBRATION_VALIDATION.md").write_text(md, encoding="utf-8")
        (rctx.path / "recalibration_results.json").write_text(json.dumps(_json_safe(
            {"meta": meta, "validate": {k: harness.results_to_dict(r) for k, r in results.items()}}),
            indent=1, allow_nan=False), encoding="utf-8")

        figure_out = docs_out.parent / FIGURE_REL
        figure_out.parent.mkdir(parents=True, exist_ok=True)
        for target, write in ((figure_out, lambda t: t.write_bytes((rctx.path / "recalibration_reliability.png").read_bytes())),
                              (docs_out.parent / JSON_NAME, lambda t: t.write_text(rec_text, encoding="utf-8")),
                              (docs_out, lambda t: t.write_text(md, encoding="utf-8"))):
            tmp = target.with_name(target.name + ".tmp")
            write(tmp)
            os.replace(tmp, target)

    print(f"run folder: {rctx.path}")
    print(f"docs report: {docs_out}")
    for lead in leads:
        res = results[lead]
        model = recal_name(base_model[str(lead)])
        c = res.comparisons
        r = c[(c["reference"] == recal_name(best_by_lead[str(lead)])) & (c["candidate"] == model)].iloc[0]
        print(f"lead {lead}: {model} vs {recal_name(best_by_lead[str(lead)])} BSS {r['bss']:.3f} "
              f"[{r['bss_week_lo']:.3f}, {r['bss_week_hi']:.3f}]; reliability ok={reliability[str(lead)][model]['ok']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
