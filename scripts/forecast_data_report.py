"""Write the pre-model data report (FEAT-06) to a run folder and to docs/forecast/DATA_REPORT.md.

    python scripts/forecast_data_report.py

Read-only on the frozen data; no Earth Engine access. Exit codes: 0 ok, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.config import settings  # noqa: E402
from heatwave.forecast import report  # noqa: E402
from heatwave.forecast.artifacts import REPO_ROOT, run_folder  # noqa: E402
from heatwave.forecast.config import FORECAST_CONFIG_PATH, load_forecast_config  # noqa: E402
from heatwave.forecast.data import frozen_dataset_dir, load_panel  # noqa: E402
from heatwave.forecast.static import load_static  # noqa: E402

DEFAULT_DOCS_OUT = REPO_ROOT / "docs" / "forecast" / "DATA_REPORT.md"


def _inside(path: Path, base: Path) -> bool:
    base = base.resolve()
    return path == base or base in path.parents


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=None, help="folder holding frozen/ (default: local_data_dir)")
    ap.add_argument("--runs-root", default=None, help="base for forecast_runs/ (default: data root)")
    ap.add_argument("--docs-out", default=str(DEFAULT_DOCS_OUT))
    ap.add_argument("--config", default=str(FORECAST_CONFIG_PATH))
    ap.add_argument("--expected-parquet-sha256", default=None)
    args = ap.parse_args(argv)

    cfg = load_forecast_config(Path(args.config))
    if args.expected_parquet_sha256:
        cfg = dataclasses.replace(
            cfg, data=dataclasses.replace(cfg.data, expected_parquet_sha256=args.expected_parquet_sha256)
        )
    data_root = Path(args.data_root) if args.data_root else Path(settings.local_data_dir)
    runs_root = Path(args.runs_root) if args.runs_root else data_root

    docs_out = Path(args.docs_out).resolve()
    if docs_out.suffix != ".md":
        print(f"error: --docs-out must end in .md: {docs_out}", file=sys.stderr)
        return 2
    forbidden = [frozen_dataset_dir(cfg.data, data_root), REPO_ROOT / "outputs", REPO_ROOT / "keys"]
    for base in forbidden:
        if _inside(docs_out, base):
            print(f"error: --docs-out must not be inside {base}", file=sys.stderr)
            return 2

    panel = load_panel(cfg.data, data_root)
    static = load_static(cfg.data, panel.wards, data_root)

    with run_folder(cfg, data_sha256=panel.sha256, data_root=runs_root) as ctx:
        tables = report.prevalence_tables(panel, static, cfg)
        tables["effective_days"] = report.effective_days_table(cfg)
        tables["row_counts"] = report.row_count_table(panel, cfg)
        meta = dict(
            data_version=cfg.data.version,
            parquet_sha256=panel.sha256,
            run_id=ctx.run_id,
            generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            n_wards=len(panel.wards),
            first_week=panel.week_labels[0],
            last_week=panel.week_labels[-1],
            latency_days=cfg.latency_days,
        )
        md = report.render_markdown(tables, meta)
        csv_names = {
            "by_year": "prevalence_by_year.csv",
            "by_region": "prevalence_by_region.csv",
            "by_era": "prevalence_by_era.csv",
            "by_split": "prevalence_by_split.csv",
            "effective_days": "effective_days.csv",
            "row_counts": "row_counts.csv",
        }
        for key, name in csv_names.items():
            tables[key].to_csv(ctx.path / name, index=False)
        (ctx.path / "DATA_REPORT.md").write_text(md, encoding="utf-8")

        docs_out.parent.mkdir(parents=True, exist_ok=True)
        tmp = docs_out.with_name(docs_out.name + ".tmp")
        tmp.write_text(md, encoding="utf-8")
        os.replace(tmp, docs_out)

    print(f"run folder: {ctx.path}")
    print(f"docs report: {docs_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
