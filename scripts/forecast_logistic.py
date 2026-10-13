"""Fit the per-lead logistic regression on train, run the ablation ladder and the year-shuffle
negative control, score everything against the refitted baselines on validation, and write
docs/forecast/LOGISTIC_VALIDATION.md.

    python scripts/forecast_logistic.py

Read-only on the frozen data; no Earth Engine access. Only the train and validate splits are
ever requested: test rows are never built, loaded or scored. Exit codes: 0 ok, 2 bad arguments.
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
from heatwave.forecast.data import frozen_dataset_dir, load_panel  # noqa: E402
from heatwave.forecast.evaluation import harness, predictions, slices  # noqa: E402
from heatwave.forecast.evaluation.logistic_report import (  # noqa: E402
    GENERATED_MARKER,
    MODEL,
    SHUFFLED,
    ablation_name,
    render_markdown,
)
from heatwave.forecast.features import build_feature_store  # noqa: E402
from heatwave.forecast.models.logistic import MAX_TRAIN_ROWS, LogisticForecaster, ablation_ladder  # noqa: E402
from heatwave.forecast.static import load_static  # noqa: E402

DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_DOCS_OUT = DOCS_ROOT / "forecast" / "LOGISTIC_VALIDATION.md"
# Comparison references: recent climatology plus the two baselines that were ever best (Phase 10).
REFERENCES = ("recent_climatology", "damped_persistence", "trend_season")
SHUFFLE_SEED_OFFSET = 7919


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _inside(path: Path, base: Path) -> bool:
    base = base.resolve()
    return path == base or base in path.parents


def _int_list(text: str, what: str, allow_none: bool = False):
    if allow_none and text.strip().lower() == "none":
        return []
    try:
        vals = [int(t) for t in text.split(",") if t.strip() != ""]
    except ValueError:
        raise ValueError(f"{what} must be a comma list of integers, got {text!r}") from None
    if not vals and not allow_none:
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
    """Store one Parquet per predictor. Every probability must be finite."""
    chash = config_hash(cfg)
    paths = {}
    for nm, p in probs.items():
        if not np.isfinite(p).all():
            raise ValueError(f"{nm} produced non-finite probabilities on {split} rows (lead {lead})")
        df = predictions.build_frame(panel, cfg, nm, lead, split, wp, op, p)
        meta = predictions.PredictionMeta(run_id, chash, data_sha, nm, lead, split, threshold=float(threshold))
        paths[nm] = predictions.write_predictions(df, meta, run_dir, cfg=cfg)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None, help="folder holding frozen/ (default: local_data_dir)")
    ap.add_argument("--runs-root", default=None, help="base for forecast_runs/ (default: data root)")
    ap.add_argument("--docs-out", default=str(DEFAULT_DOCS_OUT))
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    ap.add_argument("--leads", default=None, help="comma list (default: all configured leads)")
    ap.add_argument("--ablation-leads", default="1,2", help="comma list or 'none'")
    ap.add_argument("--bootstrap-b", type=int, default=None, help="bootstrap replicates (default: config)")
    ap.add_argument("--max-train-rows", type=int, default=MAX_TRAIN_ROWS)
    ap.add_argument(
        "--force",
        action="store_true",
        help="allow --docs-out outside docs/ or over a file this script did not generate",
    )
    args = ap.parse_args(argv)

    try:
        cfg = load_forecast_config(Path(args.config))
    except (ValueError, OSError) as exc:
        return _bad(f"invalid --config: {exc}")
    try:
        leads = _int_list(args.leads, "--leads") if args.leads else list(cfg.leads)
        abl_leads = _int_list(args.ablation_leads, "--ablation-leads", allow_none=True)
    except ValueError as exc:
        return _bad(str(exc))
    for k in leads:
        if k not in cfg.leads:
            return _bad(f"lead {k} is not a configured lead {list(cfg.leads)}")
    if not set(abl_leads) <= set(leads):
        return _bad("--ablation-leads must be a subset of --leads")
    B = cfg.evaluation.bootstrap_b if args.bootstrap_b is None else args.bootstrap_b
    if B < 1:
        return _bad("--bootstrap-b must be >= 1")
    if args.max_train_rows < 1000:
        return _bad("--max-train-rows must be >= 1000")
    if not set(REFERENCES) <= set(cfg.baselines.names):
        return _bad(f"baselines.names must include {REFERENCES}")

    pin_override = None
    if args.expected_parquet_sha256 and args.expected_parquet_sha256 != cfg.data.expected_parquet_sha256:
        pin_override = {
            "pinned_in_forecast_yaml": cfg.data.expected_parquet_sha256,
            "override_used": args.expected_parquet_sha256,
        }
        print(
            "WARNING: --expected-parquet-sha256 overrides the pinned anchor in forecast.yaml; "
            "the report and run manifest will record this.",
            file=sys.stderr,
        )
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(
            cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256)
        )
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root
    if _inside((runs_root / RUNS_SUBDIR).resolve(), REPO_ROOT):
        return _bad(f"--runs-root must not be inside the repository ({REPO_ROOT})")

    docs_out = Path(args.docs_out).resolve()
    if docs_out.suffix != ".md":
        return _bad(f"--docs-out must end in .md: {docs_out}")
    forbidden = [frozen_dataset_dir(cfg.data, data_root), REPO_ROOT / "outputs", REPO_ROOT / "keys"]
    for base in forbidden:
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

    _log("loading frozen data")
    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)
    clim = Climatology.fit(panel, cfg.splits.train_end)
    areas = slices.load_ward_areas(cfg.data, panel.wards, data_root)
    ward_attrs = slices.ward_attributes(static.align(panel.wards), areas)
    _log("building feature store")
    store = build_feature_store(panel, clim, static)

    ladder = ablation_ladder()
    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as rctx:
        fctx = baselines.FitContext(panel, static, clim, cfg)
        _log("fitting baselines")
        fitted = baselines.fit_baselines(fctx)
        order = list(cfg.baselines.names)

        _log("fitting logistic (all leads)")
        main_model = LogisticForecaster(store, max_train_rows=args.max_train_rows).fit(fctx, leads)
        _log("fitting year-shuffled control (all leads)")
        shuffled = LogisticForecaster(
            store, name=SHUFFLED, max_train_rows=args.max_train_rows, shuffle_seed=cfg.seed + SHUFFLE_SEED_OFFSET
        ).fit(fctx, leads)
        ablations = {}
        if abl_leads:
            for label, names in ladder[:-1]:  # the last step is the main model
                _log(f"fitting ablation step {label} ({len(names)} features)")
                ablations[ablation_name(label)] = LogisticForecaster(
                    store, feature_names=names, name=ablation_name(label), max_train_rows=args.max_train_rows
                ).fit(fctx, abl_leads)

        val_results, thresholds = {}, {}
        for lead in leads:
            _log(f"lead {lead}: predicting and scoring")
            wp, op = dataset.lead_row_index(panel, cfg, lead, "validate")
            threshold = baselines.train_base_rate(fctx, lead)
            thresholds[lead] = threshold
            probs = {nm: fitted[nm].predict(lead, wp, op) for nm in order}
            probs[MODEL] = main_model.predict(lead, wp, op)
            probs[SHUFFLED] = shuffled.predict(lead, wp, op, split_origins=op)
            if lead in abl_leads:
                for nm, m in ablations.items():
                    probs[nm] = m.predict(lead, wp, op)
            paths = _store(panel, cfg, probs, lead, "validate", wp, op, rctx.path, rctx.run_id, panel.sha256, threshold)
            sctx = harness.ScoringContext(
                cfg, lead, threshold, ward_attrs, _week_attrs(panel, cfg, lead, op),
                B=B, run_id=rctx.run_id, log_root=runs_root, data_sha256=panel.sha256,
            )
            val_results[lead] = harness.score_lead(paths, sctx, references=REFERENCES)

        best, control, bss_recent = {}, {}, {}
        for lead, res in val_results.items():
            brier = {
                r["predictor"]: float(r["brier"]) for r in res.summary.to_dict("records") if r["predictor"] in order
            }
            best[lead] = harness.best_baseline(brier, order)
            if best[lead] not in REFERENCES:
                raise RuntimeError(f"best baseline {best[lead]} at lead {lead} is not a scored reference {REFERENCES}")
            c = res.comparisons
            row = c[(c["reference"] == best[lead]) & (c["candidate"] == SHUFFLED)].iloc[0]
            lo = float(row["bss_week_lo"])
            control[lead] = {"bss": float(row["bss"]), "bss_week_lo": lo, "ok": bool(not math.isfinite(lo) or lo <= 0)}
            r = c[(c["reference"] == "recent_climatology") & (c["candidate"] == MODEL)].iloc[0]
            bss_recent[lead] = float(r["bss"])
        decay = harness.persistence_decay_check(bss_recent) if len(leads) >= 2 else {}

        meta = dict(
            run_id=rctx.run_id,
            generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            data_version=cfg.data.version,
            parquet_sha256=panel.sha256,
            config_sha256=config_hash(cfg),
            seed=cfg.seed,
            B=B,
            block_weeks=cfg.evaluation.block_weeks,
            ci_level=cfg.gate.ci_level,
            train_end=str(cfg.splits.train_end),
            max_train_rows=args.max_train_rows,
            n_train_rows=main_model.n_train_,
            n_features=len(main_model.feature_names),
            feature_names=list(main_model.feature_names),
            lr_params=dict(cfg.models.params("logistic_regression")),
            n_wards=len(panel.wards),
            test_runs=testlock.count_test_runs(runs_root),  # raises on a broken log chain
            test_scored_in_run=testlock.count_test_scores(run_id=rctx.run_id, data_root=runs_root),
            log_chain_ok=testlock.verify_log_chain(runs_root),
            best_baseline_by_lead=best,
            references=list(REFERENCES),
            primary_leads=list(cfg.gate.primary_leads),
            ablation_leads=list(abl_leads),
            ablation_ladder=[(label, len(names)) for label, names in ladder],
            control=control,
            decay_check=decay,
            sanity={k: harness.sanity_flags(r) for k, r in val_results.items()},
            coefficients={k: main_model.coefficients(k) for k in leads},
            pin_override=pin_override,
        )
        if pin_override:
            rctx.manifest["pin_override"] = pin_override
        md = render_markdown(val_results, meta)
        payload = {
            "meta": meta,
            "thresholds": thresholds,
            "validate": {k: harness.results_to_dict(r) for k, r in val_results.items()},
        }
        (rctx.path / "logistic_results.json").write_text(
            json.dumps(_json_safe(payload), indent=1, allow_nan=False), encoding="utf-8"
        )
        (rctx.path / "LOGISTIC_VALIDATION.md").write_text(md, encoding="utf-8")

        docs_out.parent.mkdir(parents=True, exist_ok=True)
        tmp = docs_out.with_name(docs_out.name + ".tmp")
        tmp.write_text(md, encoding="utf-8")
        os.replace(tmp, docs_out)

    print(f"run folder: {rctx.path}")
    print(f"docs report: {docs_out}")
    for lead in sorted(best):
        print(
            f"lead {lead}: best baseline {best[lead]}, logistic BSS vs recent {bss_recent[lead]:.3f}, "
            f"control {'pass' if control[lead]['ok'] else 'FAIL'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
