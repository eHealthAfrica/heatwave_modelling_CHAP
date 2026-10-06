"""Pre-model data report: builders, markdown, and the report script."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast import dataset, report, splits, targets
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.fixtures import (
    add_synthetic_static,
    build_synthetic_frozen,
    synthetic_panel,
    synthetic_static_sources,
)
from heatwave.forecast.static import build_static_table

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forecast_data_report.py"
EXPECTED_CAPTION = (
    "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), "
    "4,841 wards in 19 northern states and the FCT"
)


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(last_week="2021-W20")


@pytest.fixture(scope="module")
def static(panel):
    geo, rows = synthetic_static_sources()
    return build_static_table(geo, rows, panel.wards)


@pytest.fixture(scope="module")
def tables(panel, static, cfg):
    t = report.prevalence_tables(panel, static, cfg)
    t["effective_days"] = report.effective_days_table(cfg)
    t["row_counts"] = report.row_count_table(panel, cfg)
    return t


def test_caption_exact():
    assert report.CAPTION == EXPECTED_CAPTION


def test_by_year_matches_independent_mean(panel, tables):
    j = panel.variables.index("heatwave_days")
    days = panel.values[:, :, j]
    by_year = tables["by_year"].set_index("iso_year")
    for y in by_year.index:
        cols = [i for i, lbl in enumerate(panel.week_labels) if int(lbl[:4]) == y]
        assert by_year.loc[y, "prevalence"] == pytest.approx(float((days[:, cols] >= 3).mean()))
    partial = set(by_year.index[by_year["partial"]])
    assert partial == {1991, 2021}


def test_by_region(tables):
    reg = tables["by_region"].set_index("group")
    for g in ("NWZ", "NEZ", "NCZ", "far_north", "central", "middle_belt"):
        assert reg.loc[g, "wards"] == 2


def test_by_era_and_split(panel, tables, cfg):
    era = tables["by_era"]
    assert list(era["era"]) == ["1991-2000", "2001-2010", "2011-2020", "2021-2026"]
    assert era.iloc[3]["weeks"] > 0
    sp = tables["by_split"].set_index("split")
    n, T = len(panel.wards), len(panel.week_index)
    assert sp.loc[list(splits.SPLIT_NAMES), "ward_weeks"].sum() == n * T
    assert sp.loc["overall", "ward_weeks"] == n * T
    assign = splits.assign_split(panel.week_index, cfg.splits)
    assert sp.loc["train", "weeks"] == int((assign == "train").sum())


def test_effective_days(tables):
    t = tables["effective_days"]
    assert list(t["lead_weeks"]) == [1, 2, 3, 4, 5, 6] or len(t) == 6
    assert list(t["effective_days_ahead"]) == [1, 8, 15, 22, 29, 36]
    assert list(t["operational_days_to_target_start"]) == [-8, -1, 6, 13, 20, 27]
    assert list(t["operational_days_to_target_end"]) == [-2, 5, 12, 19, 26, 33]


def test_row_counts_match_dataset(panel, cfg, tables):
    rc = tables["row_counts"]
    assert len(rc) == len(cfg.leads) * 3
    for _, r in rc.iterrows():
        wp, _ = dataset.lead_row_index(panel, cfg, int(r["lead_weeks"]), r["split"], drop_warmup=True)
        assert r["rows"] == len(wp)
    assert rc.attrs["warmup_first_position"] == dataset.warmup_first_position(panel)


def test_markdown(tables):
    meta = dict(
        data_version="synthetic", parquet_sha256="0" * 64, run_id="r1", generated_utc="2026-10-07T00:00:00Z",
        n_wards=6, first_week="1991-W02", last_week="2021-W20", latency_days=0,
    )
    md = report.render_markdown(tables, meta)
    assert md.count(EXPECTED_CAPTION) == 2
    assert md.splitlines()[2] == EXPECTED_CAPTION
    assert targets.LABEL_DEFINITION in md and "heatwave_event_count" in md
    for s in ("2026-10-06", "2026-09-27", "about 9 days", "latency_days = 0", "no live Earth Engine query"):
        assert s in md
    assert "regime" in md.lower() and "Validation is not representative of test" in md
    assert "accuracy" not in md.lower()
    rows = [l for l in md.splitlines() if l.startswith("|") and l.split("|")[1].strip() in "123456"]
    assert rows


# --------------------------------------------------------------------------- script
def _run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.fixture()
def synth(tmp_path):
    return add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))


def test_script_synthetic(synth, tmp_path):
    docs = tmp_path / "out" / "DATA_REPORT.md"
    code, out = _run(
        "--data-root", synth.data_root, "--runs-root", tmp_path / "runs", "--docs-out", docs,
        "--expected-parquet-sha256", synth.sha256,
    )
    assert code == 0, out
    assert docs.read_text(encoding="utf-8").count(EXPECTED_CAPTION) == 2
    runs = list((tmp_path / "runs" / "forecast_runs").iterdir())
    assert len(runs) == 1
    names = {p.name for p in runs[0].iterdir()}
    assert {
        "RUN_MANIFEST.json", "config.yaml", "DATA_REPORT.md", "prevalence_by_year.csv",
        "prevalence_by_region.csv", "prevalence_by_era.csv", "prevalence_by_split.csv",
        "effective_days.csv", "row_counts.csv",
    } <= names
    assert '"status": "completed"' in (runs[0] / "RUN_MANIFEST.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("where", ["frozen", "outputs", "keys", "notmd"])
def test_script_refuses_bad_docs_out(synth, tmp_path, where):
    target = {
        "frozen": synth.dataset_dir / "R.md",
        "outputs": REPO / "outputs" / "R_test_report.md",
        "keys": REPO / "keys" / "R_test_report.md",
        "notmd": tmp_path / "R.txt",
    }[where]
    code, out = _run(
        "--data-root", synth.data_root, "--runs-root", tmp_path / "runs", "--docs-out", target,
        "--expected-parquet-sha256", synth.sha256,
    )
    assert code == 2, out
    assert not target.exists()


def test_script_refuses_in_repo_runs_root(synth, tmp_path):
    code, out = _run(
        "--data-root", synth.data_root, "--runs-root", REPO / "tmp_runs_should_not_exist",
        "--docs-out", tmp_path / "R.md", "--expected-parquet-sha256", synth.sha256,
    )
    assert code != 0, out
    assert not (REPO / "tmp_runs_should_not_exist").exists()


def test_script_has_no_ee_import():
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("import ee", "from ee", "import geemap", "heatwave.auth", "from heatwave import auth"):
        assert bad not in src


@pytest.mark.frozen
def test_script_frozen(tmp_path):
    docs = tmp_path / "DATA_REPORT.md"
    code, out = _run("--runs-root", tmp_path, "--docs-out", docs)
    assert code == 0, out
    md = docs.read_text(encoding="utf-8")
    assert md.count(EXPECTED_CAPTION) == 2
    import re

    overall = re.search(r"\| overall \|[^\n]*\| ([\d.]+)% \|", md)
    assert overall and 10.0 <= float(overall.group(1)) <= 13.0
    for era, ref in (("1991-2000", 6.6), ("2001-2010", 11.2), ("2011-2020", 11.6), ("2021-2026", 21.5)):
        m = re.search(rf"\| {era} \|[^\n]*\| ([\d.]+)% \|", md)
        assert m and abs(float(m.group(1)) - ref) <= 1.0
