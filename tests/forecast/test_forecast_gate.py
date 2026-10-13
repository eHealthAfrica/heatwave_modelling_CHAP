"""Pre-test freeze, the single test evaluation, GATE.json and the report (synthetic only)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast import splits, testlock
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.evaluation import gate_report as G
from heatwave.forecast.fixtures import add_synthetic_static, build_synthetic_frozen, synthetic_panel
from heatwave.forecast.models import frozen

REPO = Path(__file__).resolve().parents[2]


def _cmp(ref, bss, lo, hi):
    return {"reference": ref, "candidate": G.CANDIDATE, "bss": bss, "bss_week_lo": lo, "bss_week_hi": hi,
            "bss_year_lo": lo, "bss_year_hi": hi}


def test_decision_rule():
    res = {"1": {"comparisons": [_cmp("r", 0.05, 0.01, 0.09)]}, "2": {"comparisons": [_cmp("r", 0.05, -0.01, 0.09)]}}
    refs = {"1": "r", "2": "r"}
    g = G.decide(res, refs, (1, 2))
    assert g["decision"] == "no-go" and g["leads_with_skill"] == [1] and g["leads_without_skill"] == [2]
    res["2"]["comparisons"] = [_cmp("r", 0.02, 0.001, 0.03)]
    assert G.decide(res, refs, (1, 2))["decision"] == "go"
    res["2"]["comparisons"] = [_cmp("r", -0.02, -0.03, -0.01)]
    assert G.decide(res, refs, (1, 2))["decision"] == "no-go"
    with pytest.raises(ValueError):
        G.decide({"1": res["1"]}, refs, (1, 2))


def test_pretest_rows_stop_before_the_test_window_with_embargo():
    cfg = load_forecast_config()
    panel = synthetic_panel(last_week="2027-W10")
    for lead in (1, 6):
        w, o = frozen.pretest_row_index(panel, cfg, lead)
        tgt = np.asarray(panel.week_index)[o] + lead
        assert tgt.max() < splits.test_start_index() - cfg.splits.embargo_weeks
        assert tgt.max() >= splits.test_start_index() - cfg.splits.embargo_weeks - 1  # uses 2020 targets


def test_bundle_hash_is_checked(tmp_path):
    p = tmp_path / "b.joblib"
    sha = frozen.save_bundle({"schema": frozen.BUNDLE_SCHEMA, "x": 1}, p)
    assert frozen.load_bundle(p, sha)["x"] == 1
    with pytest.raises(ValueError):
        frozen.load_bundle(p, "0" * 64)


def test_test_script_refuses_when_lock_closed(tmp_path):
    spec = importlib.util.spec_from_file_location("_t", REPO / "scripts" / "forecast_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--runs-root", str(tmp_path), "--report-out", str(tmp_path / "r.md"),
                     "--gate-out", str(tmp_path / "g.json")]) == 2
    assert not (tmp_path / "r.md").exists()


def _run(script, *args):
    r = subprocess.run([sys.executable, str(REPO / "scripts" / script), *map(str, args)], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.slow
def test_freeze_and_single_test_end_to_end(tmp_path, monkeypatch):
    synth = add_synthetic_static(build_synthetic_frozen(tmp_path / "data", last_week="2021-W30"))
    runs = tmp_path / "runs"
    base = ("--data-root", synth.data_root, "--runs-root", runs, "--expected-parquet-sha256", synth.sha256)
    out = tmp_path / "out"
    _run("forecast_lightgbm.py", *base, "--docs-out", out / "LIGHTGBM_VALIDATION.md", "--leads", "1,2",
         "--tune-years", "2013,2014", "--grid", "nl7_mcs200", "--bootstrap-b", "10", "--max-train-rows", "20000", "--force")
    _run("forecast_recalibrate.py", *base, "--selection", out / "MODEL_SELECTION.json",
         "--docs-out", out / "RECALIBRATION_VALIDATION.md", "--bootstrap-b", "10", "--force")
    _run("forecast_freeze.py", *base, "--selection", out / "MODEL_SELECTION.json",
         "--recalibration", out / "RECALIBRATION.json", "--out", out / "MODEL_BUNDLE.json",
         "--max-train-rows", "20000", "--force")
    mb = json.loads((out / "MODEL_BUNDLE.json").read_text(encoding="utf-8"))
    assert set(mb["by_lead"]) == {"1", "2"} and len(mb["bundle_sha256"]) == 64
    assert testlock.count_test_runs(runs) == 0

    # The real lock needs a committed pre-registration; here it is stubbed open on synthetic data only.
    record = {"model_bundle_path": mb["bundle_path"], "model_bundle_sha256": mb["bundle_sha256"],
              "preregistration_blob_sha": "f" * 40}
    monkeypatch.setattr(testlock, "lock_status", lambda *a, **k: (True, "open (test stub)"))
    monkeypatch.setattr(testlock, "_read_lock", lambda *a, **k: (record, "ok"))
    spec = importlib.util.spec_from_file_location("_t2", REPO / "scripts" / "forecast_test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    args = ["--data-root", str(synth.data_root), "--runs-root", str(runs), "--expected-parquet-sha256", synth.sha256,
            "--report-out", str(out / "FORECAST_REPORT.md"), "--gate-out", str(out / "GATE.json")]
    assert mod.main(args) == 0
    gate = json.loads((out / "GATE.json").read_text(encoding="utf-8"))
    assert gate["decision"] in ("go", "no-go") and set(gate["by_lead"]) == {"1", "2"}
    assert gate["test_runs"] == 1 and testlock.count_test_runs(runs) == 1
    report = (out / "FORECAST_REPORT.md").read_text(encoding="utf-8")
    assert report.splitlines()[2] == G.CAPTION_TEST
    for s in ("Decision:", "Skill by lead", "Effective lead and skill mask", "Skill by season", "Skill by region",
              "rule-based", "reanalysis"):
        assert s in report
    if gate["decision"] == "no-go":
        assert "ECMWF" in report
    run_dir = next(p for p in sorted((runs / "forecast_runs").glob("2*")) if (p / "test_meta.json").exists())
    # outputs can be rebuilt without scoring again
    assert mod.main(args + ["--render-from", str(run_dir)]) == 0
    assert testlock.count_test_runs(runs) == 1
    # one-shot rule: a second evaluation is refused by the harness
    with pytest.raises(testlock.TestLockError):
        mod.main(args)
    assert testlock.count_test_runs(runs) == 1
