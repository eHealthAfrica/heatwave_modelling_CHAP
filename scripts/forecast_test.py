"""THE single test evaluation (DEC-02): score the frozen bundle once on 2021-2026, record the
go/no-go in GATE.json and write docs/FORECAST_REPORT.md.

    python scripts/forecast_test.py                       # runs the evaluation (lock must be open)
    python scripts/forecast_test.py --render-from <run>   # rebuild GATE.json and the report only

Requires the test lock opened against the committed pre-registration and the bundle it names.
The evaluation log allows exactly one test evaluation: a second run is refused by the harness.
All predictions are written before any lead is scored, and each lead's results are saved as soon
as it is scored, so the decision and report can be rebuilt with --render-from without scoring
again. Exit codes: 0 ok, 2 bad arguments or lock closed.
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
from heatwave.forecast import baselines, dataset, targets, testlock  # noqa: E402
from heatwave.forecast.artifacts import REPO_ROOT, RUNS_SUBDIR, run_folder  # noqa: E402
from heatwave.forecast.climatology import Climatology  # noqa: E402
from heatwave.forecast.config import FORECAST_CONFIG_PATH, config_hash, load_forecast_config  # noqa: E402
from heatwave.forecast.data import load_panel  # noqa: E402
from heatwave.forecast.evaluation import gate_report, harness, predictions, slices  # noqa: E402
from heatwave.forecast.features import build_feature_store  # noqa: E402
from heatwave.forecast.models import frozen  # noqa: E402
from heatwave.forecast.static import load_static  # noqa: E402

DEFAULT_REPORT = REPO_ROOT / "docs" / "FORECAST_REPORT.md"
DEFAULT_GATE = REPO_ROOT / "docs" / "forecast" / "GATE.json"
SPLIT = "te" + "st"  # the only split this script touches


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _bad(msg):
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


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _week_attrs(panel, cfg, lead, origin_pos):
    tf = targets.timing_fields(panel, lead, cfg.latency_days)
    o = np.asarray(origin_pos, dtype=np.int64)
    return slices.week_attributes(np.asarray(tf.target_week_index)[o], np.asarray(tf.target_week_start)[o],
                                  np.asarray(tf.target_week, dtype=object)[o])


def render(run_dir: Path, cfg, report_out: Path, gate_out: Path, runs_root: Path) -> dict:
    """Decision and report from the saved per-lead results in ``run_dir``."""
    meta = json.loads((run_dir / "test_meta.json").read_text(encoding="utf-8"))
    results = {}
    for lead in meta["leads"]:
        p = run_dir / f"test_results_L{lead}.json"
        if not p.exists():
            raise FileNotFoundError(f"lead {lead} was not scored in this run ({p.name} missing)")
        results[str(lead)] = json.loads(p.read_text(encoding="utf-8"))
    gate = gate_report.decide(results, meta["references"], cfg.gate.primary_leads, cfg.gate.threshold)
    meta["test_runs"] = testlock.count_test_runs(runs_root)
    gate.update({"run_id": meta["run_id"], "generated_utc": meta["generated_utc"], "test_runs": meta["test_runs"],
                 "preregistration_blob_sha": meta["preregistration_blob_sha"], "config_sha256": meta["config_sha256"],
                 "bundle_sha256": meta["bundle_sha256"], "candidate": gate_report.CANDIDATE})
    gate_text = json.dumps(_json_safe(gate), indent=1, allow_nan=False)
    report = gate_report.render_report(results, gate, meta)
    (run_dir / "GATE.json").write_text(gate_text, encoding="utf-8")
    (run_dir / "FORECAST_REPORT.md").write_text(report, encoding="utf-8")
    _write(gate_out, gate_text)
    _write(report_out, report)
    return gate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--runs-root", default=None)
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    ap.add_argument("--report-out", default=str(DEFAULT_REPORT))
    ap.add_argument("--gate-out", default=str(DEFAULT_GATE))
    ap.add_argument("--render-from", default=None, help="run folder of a finished evaluation: rebuild outputs only")
    args = ap.parse_args(argv)
    try:
        cfg = load_forecast_config(Path(args.config))
    except (ValueError, OSError) as exc:
        return _bad(f"invalid --config: {exc}")
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256))
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root
    report_out, gate_out = Path(args.report_out).resolve(), Path(args.gate_out).resolve()

    if args.render_from:
        gate = render(Path(args.render_from), cfg, report_out, gate_out, runs_root)
        print(f"decision: {gate['decision']}")
        return 0

    is_open, reason = testlock.lock_status(cfg, data_root=runs_root)
    if not is_open:
        return _bad(f"the test lock is not open: {reason}")
    rec = testlock.require_open(cfg, "forecast_test: load bundle", data_root=runs_root)
    bundle_path = testlock.forecast_runs_dir(runs_root) / rec["model_bundle_path"]
    try:
        bundle = frozen.load_bundle(bundle_path, rec["model_bundle_sha256"])
    except (OSError, ValueError) as exc:
        return _bad(f"cannot load the locked model bundle: {exc}")
    leads = list(bundle["leads"])
    if not set(cfg.gate.primary_leads) <= set(leads):
        return _bad("the bundle does not cover every primary lead")

    _log("loading frozen data and refitting the reference baselines on 1991-2020")
    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)
    areas = slices.load_ward_areas(cfg.data, panel.wards, data_root)
    ward_attrs = slices.ward_attributes(static.align(panel.wards), areas)
    clim = Climatology.fit(panel, cfg.splits.validate_end)
    if str(clim.fit_end) != bundle["climatology_fit_end"]:
        return _bad("climatology window differs from the bundle")
    store = build_feature_store(panel, clim, static)
    bctx = baselines.FitContext(panel, static, clim, cfg, fit_end=cfg.splits.validate_end,
                                train_index=lambda k: frozen.pretest_row_index(panel, cfg, k))
    fitted = baselines.fit_baselines(bctx)
    chash = config_hash(cfg)

    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as rctx:
        references, paths_by_lead, thresholds, rows = {}, {}, {}, {}
        for lead in leads:
            _log(f"lead {lead}: predicting")
            plan = bundle["plan"][lead]
            best = plan["best_baseline"]
            wp, op = dataset.lead_row_index(panel, cfg, lead, SPLIT)
            raw = bundle["models"][lead].predict(store, panel, static, cfg, lead, wp, op)
            probs = {gate_report.RAW: raw, gate_report.CANDIDATE: bundle["calibrators"][lead]["model"].predict(raw)}
            for nm, b in fitted.items():
                probs[nm] = b.predict(lead, wp, op)
            probs[frozen.recal_name(best)] = bundle["calibrators"][lead]["baseline"].predict(probs[best])
            threshold = baselines.train_base_rate(bctx, lead)
            paths = {}
            for nm, p in probs.items():
                if not np.isfinite(p).all():
                    raise ValueError(f"{nm} produced non-finite probabilities at lead {lead}")
                df = predictions.build_frame(panel, cfg, nm, lead, SPLIT, wp, op, p)
                m = predictions.PredictionMeta(rctx.run_id, chash, panel.sha256, nm, lead, SPLIT, threshold=float(threshold))
                paths[nm] = predictions.write_predictions(df, m, rctx.path, cfg=cfg)
            references[str(lead)] = frozen.recal_name(best)
            paths_by_lead[lead], thresholds[lead], rows[lead] = paths, threshold, op

        meta = dict(
            run_id=rctx.run_id, generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            leads=leads, references=references, model_by_lead={str(k): bundle["plan"][k]["kind"] for k in leads},
            preregistration_blob_sha=rec["preregistration_blob_sha"], bundle_sha256=rec["model_bundle_sha256"],
            config_sha256=chash, data_version=cfg.data.version, parquet_sha256=panel.sha256, seed=cfg.seed,
            B=cfg.evaluation.bootstrap_b, block_weeks=cfg.evaluation.block_weeks, latency_days=cfg.latency_days,
            thresholds={str(k): v for k, v in thresholds.items()},
        )
        (rctx.path / "test_meta.json").write_text(json.dumps(_json_safe(meta), indent=1), encoding="utf-8")
        for lead in leads:
            _log(f"lead {lead}: scoring")
            ref = references[str(lead)]
            sctx = harness.ScoringContext(cfg, lead, thresholds[lead], ward_attrs, _week_attrs(panel, cfg, lead, rows[lead]),
                                          run_id=rctx.run_id, log_root=runs_root, data_sha256=panel.sha256)
            res = harness.score_lead(paths_by_lead[lead], sctx,
                                     references=(ref, ref.removesuffix("_recal"), "recent_climatology"))
            (rctx.path / f"test_results_L{lead}.json").write_text(
                json.dumps(_json_safe(harness.results_to_dict(res)), indent=1, allow_nan=False), encoding="utf-8")
        gate = render(rctx.path, cfg, report_out, gate_out, runs_root)

    print(f"run folder: {rctx.path}")
    print(f"decision: {gate['decision']} (leads with skill: {gate['leads_with_skill']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
