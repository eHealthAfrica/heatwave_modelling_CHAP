"""scripts/forecast_baselines.py: static checks (quick) and synthetic end-to-end runs (slow)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from heatwave.forecast import report, testlock
from heatwave.forecast.evaluation import baselines_report as BR
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forecast_baselines.py"
BASELINES = ("climatology", "recent_climatology", "persistence", "damped_persistence", "trend_season")


def _run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.fixture()
def synth(tmp_path):
    return add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))


def _base(synth, tmp_path):
    return ("--data-root", synth.data_root, "--runs-root", tmp_path / "runs",
            "--expected-parquet-sha256", synth.sha256)


# ------------------------------------------------------------------------- quick source checks
def test_script_has_no_ee_import_and_no_test_split():
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("import ee", "from ee", "import geemap", "heatwave.auth", "from heatwave import auth"):
        assert bad not in src
    assert not re.search(r'lead_row_index\(.*"test"', src)
    assert 'split="test"' not in src
    assert not re.search(r"""['"]test['"]""", src)
    for needed in ("score_lead", "write_predictions", "fit_baselines"):
        assert needed in src


# ------------------------------------------------------------------------------ slow end to end
@pytest.mark.slow
def test_script_end_to_end(synth, tmp_path):
    docs = tmp_path / "out" / "BASELINES_VALIDATION.md"
    code, out = _run(*_base(synth, tmp_path), "--docs-out", docs, "--leads", "1,2", "--bootstrap-b", "20",
                     "--train-leads", "1", "--force")
    assert code == 0, out
    text = docs.read_text(encoding="utf-8")
    assert text.splitlines()[2] == BR.CAPTION_VALIDATION == report.CAPTION + "; validation 2015-2020"
    assert "Test years 2021-2026 are locked and unscored" in text and "test runs: 0" in text
    assert text.rstrip().endswith(BR.GENERATED_MARKER)
    assert "accuracy" not in text.lower()

    runs = list((tmp_path / "runs" / "forecast_runs").glob("2*"))
    assert len(runs) == 1
    run = runs[0]
    pred = run / "predictions"
    for nm in BASELINES:
        assert (pred / f"{nm}_L1_validate.parquet").exists()
        assert (pred / f"{nm}_L2_validate.parquet").exists()
        assert (pred / f"{nm}_L1_train.parquet").exists()
        assert not (pred / f"{nm}_L2_train.parquet").exists()
    assert not list(pred.glob("*_test.parquet"))
    assert (run / "baselines_results.json").exists() and (run / "BASELINES_VALIDATION.md").exists()
    manifest = json.loads((run / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed" and "pin_override" in manifest
    res = json.loads((run / "baselines_results.json").read_text(encoding="utf-8"))
    assert set(res["validate"]) == {"1", "2"} and set(res["train_diagnostics"]) == {"1"}

    root = tmp_path / "runs"
    assert testlock.count_test_runs(root) == 0
    log = testlock.read_log(root)
    assert log and all(r.get("split") != "test" for r in log)
    assert not [r for r in log if r.get("outcome") == "refused"]
    scores = [r for r in log if r.get("event") == "score"]
    val = [r for r in scores if r.get("split") == "validate"]
    assert sorted((r["predictor"], r["lead"]) for r in val) == sorted((nm, k) for nm in BASELINES for k in (1, 2))
    assert {r["split"] for r in scores} <= {"train", "validate"}

    import pyarrow.parquet as pq

    for nm in BASELINES:
        t = pq.read_table(pred / f"{nm}_L1_train.parquet").to_pandas()
        assert len(t) and not pd.isna(t["p"]).any()


@pytest.mark.slow
@pytest.mark.parametrize("where", ["frozen", "outputs", "keys"])
def test_script_refuses_bad_docs_out(synth, tmp_path, where):
    target = {
        "frozen": synth.dataset_dir / "R.md",
        "outputs": REPO / "outputs" / "R_test_baselines.md",
        "keys": REPO / "keys" / "R_test_baselines.md",
    }[where]
    code, out = _run(*_base(synth, tmp_path), "--docs-out", target, "--force")
    assert code == 2, out
    assert not target.exists()


@pytest.mark.slow
def test_script_docs_out_rules(synth, tmp_path):
    base = _base(synth, tmp_path)
    code, out = _run(*base, "--docs-out", tmp_path / "R.md")
    assert code == 2 and "--force" in out, out
    d = REPO / "docs" / "_baselines_tmp"
    d.mkdir(exist_ok=True)
    try:
        victim = d / "precious.md"
        victim.write_text("keep me\n", encoding="utf-8")
        code, out = _run(*base, "--docs-out", victim)
        assert code == 2 and "not generated" in out, out
        assert victim.read_text(encoding="utf-8") == "keep me\n"
    finally:
        for f in d.glob("*"):
            f.unlink()
        d.rmdir()


@pytest.mark.slow
def test_script_refuses_in_repo_runs_root(synth, tmp_path):
    bad = REPO / "tmp_baseline_runs_should_not_exist"
    code, out = _run("--data-root", synth.data_root, "--runs-root", bad, "--docs-out", tmp_path / "R.md",
                     "--expected-parquet-sha256", synth.sha256, "--force")
    assert code == 2, out
    assert not bad.exists()


@pytest.mark.slow
@pytest.mark.parametrize("flags", [("--bootstrap-b", "0"), ("--leads", "7"), ("--train-leads", "9")])
def test_script_refuses_bad_arguments(synth, tmp_path, flags):
    code, out = _run(*_base(synth, tmp_path), "--docs-out", tmp_path / "R.md", "--force", *flags)
    assert code == 2, out
    assert not (tmp_path / "runs").exists()
