"""scripts/forecast_logistic.py: static checks (quick) and a synthetic end-to-end run (slow)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from heatwave.forecast import testlock
from heatwave.forecast.evaluation import logistic_report as LR
from heatwave.forecast.evaluation.baselines_report import CAPTION_VALIDATION
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forecast_logistic.py"
BASELINES = ("climatology", "recent_climatology", "persistence", "damped_persistence", "trend_season")


def _main(*args) -> int:
    """Run the script's main() in-process (argument checks return before any data is loaded)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_script_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main([str(a) for a in args])


def _run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_script_has_no_ee_import_and_no_test_split():
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("import ee", "from ee", "import geemap", "heatwave.auth", "from heatwave import auth"):
        assert bad not in src
    assert not re.search(r"""['"]test['"]""", src)
    for needed in ("score_lead", "write_predictions", "fit_baselines", "LogisticForecaster", "split_origins=op"):
        assert needed in src


def test_bad_arguments_exit_2(tmp_path):
    assert _main("--leads", "9") == 2
    assert _main("--leads", "1", "--ablation-leads", "2") == 2
    assert _main("--bootstrap-b", "0") == 2
    assert _main("--docs-out", tmp_path / "x.md") == 2  # outside docs/ without --force


@pytest.mark.slow
def test_script_end_to_end(tmp_path):
    synth = add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))
    docs = tmp_path / "out" / "LOGISTIC_VALIDATION.md"
    code, out = _run(
        "--data-root", synth.data_root, "--runs-root", tmp_path / "runs",
        "--expected-parquet-sha256", synth.sha256, "--docs-out", docs,
        "--leads", "1,2,3", "--ablation-leads", "1", "--bootstrap-b", "20", "--force",
    )
    assert code == 0, out
    text = docs.read_text(encoding="utf-8")
    assert text.splitlines()[2] == CAPTION_VALIDATION
    assert "Test years 2021-2026 are locked and unscored" in text and "test runs: 0" in text
    assert text.rstrip().endswith(LR.GENERATED_MARKER)
    assert "accuracy" not in text.lower()
    for section in ("Skill against the baselines", "Ablation ladder", "Negative control", "Skill decay"):
        assert section in text

    runs = list((tmp_path / "runs" / "forecast_runs").glob("2*"))
    assert len(runs) == 1
    pred = runs[0] / "predictions"
    for nm in BASELINES + ("logistic", "logistic_shuffled"):
        for k in (1, 2, 3):
            assert (pred / f"{nm}_L{k}_validate.parquet").exists(), nm
    assert (pred / "logistic_ablation_season_L1_validate.parquet").exists()
    assert not (pred / "logistic_ablation_season_L2_validate.parquet").exists()
    assert not list(pred.glob("*_test.parquet")) and not list(pred.glob("*_train.parquet"))
    res = json.loads((runs[0] / "logistic_results.json").read_text(encoding="utf-8"))
    assert set(res["validate"]) == {"1", "2", "3"}
    assert res["meta"]["n_features"] == 57
    assert set(res["meta"]["control"]) == {"1", "2", "3"}
    assert testlock.count_test_runs(tmp_path / "runs") == 0
    assert testlock.verify_log_chain(tmp_path / "runs")
