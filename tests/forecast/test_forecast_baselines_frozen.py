"""Real-data magnitude checks for the five baselines and their CIs (frozen + slow).

Mirrors scripts/forecast_baselines.py (validate split only, B=200, tmp run folder and tmp log root).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast import baselines, dataset, testlock
from heatwave.forecast.artifacts import run_folder
from heatwave.forecast.evaluation import harness, slices

pytestmark = [pytest.mark.frozen, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
REF = {
    1: {"climatology": 0.13756, "recent_climatology": 0.13652, "persistence": 0.13058,
        "damped_persistence": 0.12488, "trend_season": 0.13304},
    6: {"climatology": 0.13756, "recent_climatology": 0.13652, "persistence": 0.13704,
        "damped_persistence": 0.13558, "trend_season": 0.13316},
}
ORDER = list(REF[1])


def _load_script():
    spec = importlib.util.spec_from_file_location("forecast_baselines_script", REPO / "scripts" / "forecast_baselines.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scored(forecast_cfg, frozen_panel, frozen_static, frozen_clim, tmp_path_factory):
    from heatwave.config import settings

    script = _load_script()
    root = tmp_path_factory.mktemp("frozen_baselines")
    areas = slices.load_ward_areas(forecast_cfg.data, frozen_panel.wards, Path(settings.local_data_dir))
    ward_attrs = slices.ward_attributes(frozen_static.align(frozen_panel.wards), areas)
    fctx = baselines.FitContext(frozen_panel, frozen_static, frozen_clim, forecast_cfg)
    fitted = baselines.fit_baselines(fctx)
    out = {"n_small": int(ward_attrs["small"].sum()), "res": {}, "p": {}, "nrows": {}}
    with run_folder(forecast_cfg, data_sha256=frozen_panel.sha256, data_root=root) as rctx:
        for lead in (1, 6):
            wp, op = dataset.lead_row_index(frozen_panel, forecast_cfg, lead, "validate")
            thr = baselines.train_base_rate(fctx, lead)
            paths, kept = script._store(frozen_panel, forecast_cfg, fitted, lead, "validate", wp, op,
                                        rctx.path, rctx.run_id, frozen_panel.sha256, thr)
            out["nrows"][lead] = len(wp)
            out["p"][lead] = {nm: fitted[nm].predict(lead, wp, op) for nm in fitted}
            sctx = harness.ScoringContext(
                forecast_cfg, lead, thr, ward_attrs, script._week_attrs(frozen_panel, forecast_cfg, lead, kept),
                B=200, run_id=rctx.run_id, log_root=root,
            )
            out["res"][lead] = harness.score_lead(paths, sctx, references=("climatology", "recent_climatology"))
    return out


def _brier(res):
    return {r["predictor"]: float(r["brier"]) for r in res.summary.to_dict("records")}


def _bss(res, ref, cand):
    c = res.comparisons
    return c[(c["reference"] == ref) & (c["candidate"] == cand)].iloc[0]


@pytest.mark.parametrize("lead", [1, 6])
def test_rows_and_probabilities(scored, lead):
    assert scored["nrows"][lead] == 1_520_074
    assert scored["res"][lead].n_rows == 1_520_074
    assert scored["res"][lead].p_valid
    for p in scored["p"][lead].values():
        assert np.isfinite(p).all() and p.min() >= 0.0 and p.max() <= 1.0


@pytest.mark.parametrize("lead", [1, 6])
def test_brier_matches_research(scored, lead):
    b = _brier(scored["res"][lead])
    for nm, ref in REF[lead].items():
        assert abs(b[nm] - ref) <= 0.002, (lead, nm, b[nm], ref)
    if lead == 1:
        assert 0.123 <= b["damped_persistence"] <= 0.127


def test_best_baseline(scored):
    assert harness.best_baseline(_brier(scored["res"][1]), ORDER) == "damped_persistence"
    assert harness.best_baseline(_brier(scored["res"][6]), ORDER) == "trend_season"


def test_persistence_skill_decays(scored):
    assert _bss(scored["res"][1], "climatology", "persistence")["bss"] > _bss(
        scored["res"][6], "climatology", "persistence")["bss"]


def test_lead1_damped_vs_recent_ci(scored):
    c = _bss(scored["res"][1], "recent_climatology", "damped_persistence")
    assert 0.07 <= c["bss"] <= 0.10
    assert 0.02 <= c["bss_week_lo"] <= 0.06
    assert 0.11 <= c["bss_week_hi"] <= 0.15
    assert c["bss_week_lo"] > 0


def test_climatology_strawman(scored):
    s = scored["res"][1].summary.set_index("predictor").loc["climatology"]
    assert 0.085 <= s["mean_p"] <= 0.093
    assert 0.150 <= s["base_rate"] <= 0.158


def test_small_ward_count_and_log_untouched(scored):
    assert scored["n_small"] == 3086
    assert testlock.count_test_runs() == 0
