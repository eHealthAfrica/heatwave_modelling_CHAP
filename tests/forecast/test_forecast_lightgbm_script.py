"""scripts/forecast_lightgbm.py: static checks (quick) and a synthetic end-to-end run (slow)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from heatwave.forecast import testlock
from heatwave.forecast.evaluation import lightgbm_report as LR
from heatwave.forecast.evaluation.baselines_report import CAPTION_VALIDATION
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forecast_lightgbm.py"


def _run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_script_has_no_ee_import_and_no_test_split():
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("import ee", "from ee", "import geemap", "heatwave.auth", "from heatwave import auth"):
        assert bad not in src
    assert not re.search(r"""['"]test['"]""", src)
    for needed in ("run_cv", "choose_calibrator", "score_lead", "write_predictions", "out_of_range_table"):
        assert needed in src


def test_bad_arguments_exit_2(tmp_path):
    assert _run("--leads", "9")[0] == 2
    assert _run("--tune-years", "2014")[0] == 2  # one fold cannot do leave-one-fold-out
    assert _run("--tune-years", "2015,2016")[0] == 2  # overlaps validation
    assert _run("--grid", "nope")[0] == 2
    assert _run("--bootstrap-b", "0")[0] == 2
    assert _run("--docs-out", tmp_path / "x.md")[0] == 2


@pytest.mark.slow
def test_script_end_to_end(tmp_path):
    synth = add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))
    docs = tmp_path / "out" / "LIGHTGBM_VALIDATION.md"
    code, out = _run(
        "--data-root", synth.data_root, "--runs-root", tmp_path / "runs",
        "--expected-parquet-sha256", synth.sha256, "--docs-out", docs, "--leads", "1,2",
        "--tune-years", "2013,2014", "--grid", "nl7_mcs200,nl15_mcs200", "--bootstrap-b", "20",
        "--max-train-rows", "20000", "--force",
    )
    assert code == 0, out
    text = docs.read_text(encoding="utf-8")
    assert text.splitlines()[2] == CAPTION_VALIDATION
    assert "Test years 2021-2026 are locked and unscored" in text and "test runs: 0" in text
    assert text.rstrip().endswith(LR.GENERATED_MARKER)
    assert "accuracy" not in text.lower()
    assert (docs.parent / "figures" / "phase12_reliability.png").stat().st_size > 1000
    sel = json.loads((docs.parent / "MODEL_SELECTION.json").read_text(encoding="utf-8"))
    assert set(sel["by_lead"]) == {"1", "2"}
    for s in sel["by_lead"].values():
        assert s["selected"] in LR.CANDIDATES
        assert s["selected"] == min(LR.CANDIDATES, key=lambda c: s["cv_brier"][c])
        assert s["cal_lightgbm"]["method"] in ("platt", "isotonic")
        assert s["lgb_params"]["deterministic"] is True

    runs = list((tmp_path / "runs" / "forecast_runs").glob("2*"))
    assert len(runs) == 1
    pred = runs[0] / "predictions"
    for nm in ("logistic", "logistic_cal", "lightgbm", "lightgbm_cal", "damped_persistence"):
        assert (pred / f"{nm}_L1_validate.parquet").exists(), nm
    assert not list(pred.glob("*_test.parquet")) and not list(pred.glob("*_train.parquet"))
    assert testlock.count_test_runs(tmp_path / "runs") == 0
    assert testlock.verify_log_chain(tmp_path / "runs")
