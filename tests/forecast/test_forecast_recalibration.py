"""Leave-one-year-out recalibration and scripts/forecast_recalibrate.py (synthetic only)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast import testlock
from heatwave.forecast.evaluation import recalibration as RC
from heatwave.forecast.evaluation.baselines_report import CAPTION_VALIDATION
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "forecast_recalibrate.py"
LGB_SCRIPT = REPO / "scripts" / "forecast_lightgbm.py"


def test_loyo_fixes_a_regime_shift_without_seeing_the_held_out_year():
    rng = np.random.default_rng(0)
    years = np.repeat(np.arange(2015, 2021), 5000)
    true = rng.uniform(0.05, 0.4, years.size)
    y = (rng.uniform(size=years.size) < true).astype(float)
    raw = true * 0.6  # trained in rarer years: everything too low
    r = RC.loyo_recalibrate(raw, y, years)
    assert r["method"] in ("platt", "isotonic")
    assert abs(r["q"].mean() - y.mean()) < 0.01
    assert np.mean((r["q"] - y) ** 2) < np.mean((raw - y) ** 2)
    y2 = y.copy()
    y2[years == 2015] = 1 - y2[years == 2015]
    r2 = RC.loyo_recalibrate(raw, y2, years)
    if r2["method"] == r["method"]:
        np.testing.assert_array_equal(r["q"][years == 2015], r2["q"][years == 2015])


def test_loyo_needs_two_years():
    with pytest.raises(ValueError):
        RC.loyo_recalibrate([0.1, 0.2], [0, 1], [2015, 2015])


def test_script_source_checks():
    src = SCRIPT.read_text(encoding="utf-8")
    for bad in ("import ee", "from ee", "import geemap", "heatwave.auth"):
        assert bad not in src
    assert not re.search(r"""['"]test['"]""", src)
    for needed in ("load_predictions", "loyo_recalibrate", "score_lead", "reliability_check"):
        assert needed in src


def _main(*args) -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_recal_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main([str(a) for a in args])


def test_bad_arguments_exit_2(tmp_path):
    assert _main("--bootstrap-b", "0") == 2
    assert _main("--selection", tmp_path / "missing.json") == 2


@pytest.mark.slow
def test_script_end_to_end(tmp_path):
    synth = add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))
    base = ("--data-root", synth.data_root, "--runs-root", tmp_path / "runs",
            "--expected-parquet-sha256", synth.sha256)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(LGB_SCRIPT), *map(str, base), "--docs-out", out / "LIGHTGBM_VALIDATION.md",
                        "--leads", "1,2", "--tune-years", "2013,2014", "--grid", "nl7_mcs200",
                        "--bootstrap-b", "10", "--max-train-rows", "20000", "--force"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, base), "--selection", out / "MODEL_SELECTION.json",
                        "--docs-out", out / "RECALIBRATION_VALIDATION.md", "--bootstrap-b", "10", "--force"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (out / "RECALIBRATION_VALIDATION.md").read_text(encoding="utf-8")
    assert text.splitlines()[2] == CAPTION_VALIDATION
    assert "Test years 2021-2026 are locked and unscored" in text
    assert text.rstrip().endswith(RC.GENERATED_MARKER)
    rec = json.loads((out / "RECALIBRATION.json").read_text(encoding="utf-8"))
    assert set(rec["by_lead"]) == {"1", "2"}
    for v in rec["by_lead"].values():
        assert v["base_model"] in RC.MODELS
        for nm in RC.MODELS + RC.BASELINE_RECAL:
            assert v[nm]["method"] in ("platt", "isotonic")
    runs = sorted((tmp_path / "runs" / "forecast_runs").glob("2*"))
    assert len(runs) == 2
    pred = runs[-1] / "predictions"
    assert (pred / "lightgbm_recal_L1_validate.parquet").exists()
    assert (pred / "damped_persistence_recal_L2_validate.parquet").exists()
    assert not list(pred.glob("*_test.parquet"))
    assert testlock.count_test_runs(tmp_path / "runs") == 0
