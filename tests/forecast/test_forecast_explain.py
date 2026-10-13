"""Grouped explanations (DEC-01): groups, permutation importance, SHAP grouping (synthetic only)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast.evaluation import explain
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen
from heatwave.forecast.models.logistic import full_feature_set

REPO = Path(__file__).resolve().parents[2]


def test_groups_partition_the_full_feature_set():
    g = explain.feature_groups()
    assert list(g) == ["season", "location", "trend", "persistence", "lagged heat", "soil/humidity/rain"]
    flat = [n for names in g.values() for n in names]
    assert sorted(flat) == sorted(full_feature_set()) and len(flat) == len(set(flat))


def test_permutation_finds_the_informative_group():
    rng = np.random.default_rng(0)
    names = ("a", "b", "c")
    X = rng.normal(size=(20000, 3))
    y = (rng.uniform(size=20000) < 1 / (1 + np.exp(-2 * X[:, 0]))).astype(float)
    predict = lambda Z: 1 / (1 + np.exp(-2 * Z[:, 0]))  # noqa: E731
    rows = explain.grouped_permutation(predict, X, y, names, {"signal": ("a",), "noise": ("b", "c")})
    assert rows[0]["group"] == "signal" and rows[0]["delta_brier_mean"] > 0.01
    assert abs(rows[1]["delta_brier_mean"]) < 1e-12
    with pytest.raises(ValueError):
        explain.grouped_permutation(predict, X, y, names, {"signal": ("a",)})  # b, c ungrouped


def test_grouped_contributions_sum_within_group():
    contrib = np.array([[1.0, -1.0, 2.0, 0.5], [1.0, -1.0, -2.0, 0.5]])  # last column = expected value
    rows = explain.grouped_contributions(contrib, ("a", "b", "c"), {"ab": ("a", "b"), "c": ("c",)})
    d = {r["group"]: r for r in rows}
    assert d["ab"]["mean_abs_shap"] == 0.0 and d["c"]["mean_abs_shap"] == 2.0
    assert d["c"]["share"] == 1.0


@pytest.mark.slow
def test_explain_script_end_to_end(tmp_path):
    synth = add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W20"))
    base = ("--data-root", synth.data_root, "--runs-root", tmp_path / "runs", "--expected-parquet-sha256", synth.sha256)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "forecast_lightgbm.py"), *map(str, base),
                        "--docs-out", out / "LIGHTGBM_VALIDATION.md", "--leads", "1,2", "--tune-years", "2013,2014",
                        "--grid", "nl7_mcs200", "--bootstrap-b", "10", "--max-train-rows", "20000", "--force"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "forecast_explain.py"), *map(str, base),
                        "--selection", out / "MODEL_SELECTION.json", "--docs-out", out / "EXPLAINABILITY.md",
                        "--ladder-leads", "1", "--max-train-rows", "20000", "--shap-rows", "2000", "--force"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (out / "EXPLAINABILITY.md").read_text(encoding="utf-8")
    for s in ("Grouped permutation importance", "Grouped SHAP", "Ablation ladder", "soil/humidity/rain"):
        assert s in text
    run = sorted((tmp_path / "runs" / "forecast_runs").glob("2*"))[-1]
    res = json.loads((run / "explain_results.json").read_text(encoding="utf-8"))
    assert set(res["shap"]) == {"1", "2"} and set(res["ladder"]) == {"1"}
    assert abs(sum(r["share"] for r in res["shap"]["1"]) - 1) < 1e-9
