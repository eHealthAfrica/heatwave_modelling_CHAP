"""Freeze the pre-test model bundle (DEC-02): calibrators from 2015-2020 out-of-fold predictions and
final models refitted on 1991-2020, with the Phase 12 settings and the recalibration methods.

    python scripts/forecast_freeze.py

Writes <runs>/forecast_runs/<run>/model_bundle.joblib and docs/forecast/MODEL_BUNDLE.json (bundle
path, sha256 and a summary). The bundle sha256 goes into the pre-registration. No test row is
built, loaded or scored. Exit codes: 0 ok, 2 bad arguments.
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
from heatwave.forecast.artifacts import REPO_ROOT, RUNS_SUBDIR, run_folder  # noqa: E402
from heatwave.forecast.config import FORECAST_CONFIG_PATH, config_hash, load_forecast_config  # noqa: E402
from heatwave.forecast.data import load_panel  # noqa: E402
from heatwave.forecast.models import frozen  # noqa: E402
from heatwave.forecast.models.logistic import MAX_TRAIN_ROWS  # noqa: E402
from heatwave.forecast.static import load_static  # noqa: E402

DOCS = REPO_ROOT / "docs" / "forecast"


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _bad(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _inside(path: Path, base: Path) -> bool:
    base = base.resolve()
    return path == base or base in path.parents


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--runs-root", default=None)
    ap.add_argument("--selection", default=str(DOCS / "MODEL_SELECTION.json"))
    ap.add_argument("--recalibration", default=str(DOCS / "RECALIBRATION.json"))
    ap.add_argument("--out", default=str(DOCS / "MODEL_BUNDLE.json"), help="bundle summary JSON")
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    ap.add_argument("--max-train-rows", type=int, default=MAX_TRAIN_ROWS)
    ap.add_argument("--cal-years", default=",".join(map(str, frozen.CAL_YEARS)))
    ap.add_argument("--force", action="store_true", help="allow --out outside docs/")
    args = ap.parse_args(argv)
    try:
        cfg = load_forecast_config(Path(args.config))
        sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
        rec = json.loads(Path(args.recalibration).read_text(encoding="utf-8"))
        cal_years = tuple(int(t) for t in args.cal_years.split(",") if t.strip())
    except (ValueError, OSError) as exc:
        return _bad(str(exc))
    if len(cal_years) < 2:
        return _bad("--cal-years needs at least two years")
    if sel.get("config_sha256") != config_hash(cfg) and not args.expected_parquet_sha256:
        return _bad("MODEL_SELECTION.json was produced under a different config")
    if sel.get("run_id") != rec.get("source_run"):
        return _bad("RECALIBRATION.json was not made from the run in MODEL_SELECTION.json")
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256))
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root
    if _inside((runs_root / RUNS_SUBDIR).resolve(), REPO_ROOT):
        return _bad("--runs-root must not be inside the repository")
    out = Path(args.out).resolve()
    if not args.force and not _inside(out, REPO_ROOT / "docs"):
        return _bad("--out must be under docs/ (or pass --force)")

    _log("loading frozen data")
    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)
    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as rctx:
        bundle = frozen.freeze(panel, static, cfg, sel["by_lead"], rec["by_lead"],
                               max_train_rows=args.max_train_rows, cal_years=cal_years, log=_log)
        bundle["provenance"] = {"run_id": rctx.run_id, "config_sha256": config_hash(cfg),
                                "parquet_sha256": panel.sha256, "selection_run": sel.get("run_id"),
                                "recalibration_run": rec.get("run_id"), "seed": cfg.seed}
        path = rctx.path / frozen.BUNDLE_NAME
        sha = frozen.save_bundle(bundle, path)
        summary = {
            "generated_by": "scripts/forecast_freeze.py",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bundle_path": f"{rctx.run_id}/{frozen.BUNDLE_NAME}", "bundle_sha256": sha,
            **bundle["provenance"], **frozen.describe(bundle),
        }
        text = json.dumps(_json_safe(summary), indent=1, allow_nan=False)
        (rctx.path / "BUNDLE_MANIFEST.json").write_text(text, encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, out)
    print(f"bundle: {path}")
    print(f"bundle sha256: {sha}")
    print(f"summary: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
