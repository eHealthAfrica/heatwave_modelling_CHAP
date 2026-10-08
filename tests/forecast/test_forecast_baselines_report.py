"""Baselines validation markdown renderer (synthetic LeadResults, tiny B)."""
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from heatwave.forecast import report, targets, weeks
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.evaluation import baselines_report as BR
from heatwave.forecast.evaluation import harness, predictions as P, slices
from heatwave.forecast.fixtures import SYNTHETIC_WARDS, synthetic_panel, synthetic_static_sources
from heatwave.forecast.static import build_static_table

RUN_ID = "20270101T000000Z_abcdef12"
SHA = "a" * 64
LEADS = (1, 2, 3, 4, 5, 6)


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def results(cfg, tmp_path_factory):
    panel = synthetic_panel(last_week="2027-W10")
    geo, rows = synthetic_static_sources()
    st = build_static_table(geo, rows, SYNTHETIC_WARDS)
    attrs = slices.ward_attributes(st, slices.ward_areas_deg2(geo, st.wards))
    run_dir = tmp_path_factory.mktemp("runs") / "forecast_runs" / RUN_ID
    run_dir.mkdir(parents=True)
    w, o = lead_row_index(panel, cfg, 1, "validate")
    y = targets.lead_label(panel, 1)[w, o]
    rng = np.random.default_rng(5)
    paths = {}
    df = None
    for i, nm in enumerate(cfg.baselines.names):
        p = np.clip(0.12 + 0.02 * i + 0.1 * y * (i % 2) + rng.normal(0, 0.03, len(y)), 0.01, 0.99).astype(np.float32)
        df = P.build_frame(panel, cfg, nm, 1, "validate", w, o, p)
        paths[nm] = P.write_predictions(df, P.PredictionMeta(RUN_ID, SHA, SHA, nm, 1, "validate"), run_dir)
    idx = df["target_week_index"].to_numpy()
    start = {int(i): np.datetime64(weeks.index_to_week_start(int(i)).isoformat(), "D") for i in np.unique(idx)}
    wa = slices.week_attributes(idx, np.array([start[int(i)] for i in idx]), df["target_week"].astype(str).to_numpy())
    ctx = harness.ScoringContext(cfg, 1, 0.15, attrs, wa, B=20, h_bins=50, run_id=RUN_ID,
                                 log_root=tmp_path_factory.mktemp("log"))
    res = harness.score_lead(paths, ctx, references=["climatology", "recent_climatology"])
    return {k: dataclasses.replace(res, lead=k) for k in LEADS}


@pytest.fixture(scope="module")
def meta(cfg, results):
    s = results[1].summary
    best = {k: str(results[k].summary.sort_values("brier").iloc[0]["predictor"]) for k in LEADS}
    return dict(
        run_id=RUN_ID, generated_utc="2026-10-08T00:00:00Z", data_version="synthetic", parquet_sha256="0" * 64,
        config_sha256=SHA, seed=cfg.seed, B=20, block_weeks=4, ci_level=0.95, reliability_bins=10,
        shrinkage_pseudo_count=50, n_wards=6, n_small_wards=1, n_large_wards=5, test_runs=0,
        best_baseline_by_lead=best, baseline_order=list(cfg.baselines.names), primary_leads=[1, 2],
        decay_check={"lead_first": 1, "lead_last": 6, "bss_first": 0.2, "bss_last": 0.05, "ok": True,
                     "strictly_monotone": True},
        sanity={k: harness.sanity_flags(results[k]) for k in LEADS},
        mean_p_vs_obs={"climatology": (float(s.set_index("predictor").loc["climatology", "mean_p"]), 0.154)},
    )


@pytest.fixture(scope="module")
def md(results, meta):
    return BR.render_markdown(results, meta)


def test_caption_and_note(md):
    assert BR.CAPTION_VALIDATION == report.CAPTION + "; validation 2015-2020"
    assert md.splitlines()[2] == BR.CAPTION_VALIDATION
    assert md.splitlines()[0] == "# Baseline validation scores (2015-2020)"
    assert "Test years 2021-2026 are locked and unscored" in md
    assert "evaluation log test runs: 0" in md


def test_marker_last_and_no_accuracy(md):
    assert md.rstrip("\n").splitlines()[-1] == BR.GENERATED_MARKER
    assert "accuracy" not in md.lower()


def test_sections_in_order(md):
    heads = [
        "## Best baseline per lead", "## Brier by lead", "## Skill against climatology",
        "## Skill against recent climatology", "## Brier decomposition", "## Season (MAM highlighted)",
        "## Region", "## Calibration-in-the-large by year", "## Stratified ROC AUC", "## Reliability",
        "## Precision / recall / F1 at a stated threshold", "## Sanity checks", "## Notes",
    ]
    pos = [md.index(h) for h in heads]
    assert pos == sorted(pos)


def _section(md, head):
    a = md.index(head)
    b = md.find("\n## ", a + 1)
    return md[a: b if b > 0 else len(md)]


def _rows(sec, lead):
    return [l for l in sec.splitlines() if l.startswith(f"| {lead} |")]


def test_brier_and_skill_tables(md, cfg):
    sec = _section(md, "## Brier by lead")
    for k in LEADS:
        assert any(l.startswith(f"| {k} |") for l in sec.splitlines())
    for nm in cfg.baselines.names:
        assert nm in sec
    for head, ref in (("## Skill against climatology", "climatology"),
                      ("## Skill against recent climatology", "recent_climatology")):
        s = _section(md, head)
        assert "BSS week-block CI" in s and "BSS year-block CI" in s and "dBS" in s
        for k in LEADS:
            assert len(_rows(s, k)) == len(cfg.baselines.names) - 1
    assert "## Best baseline per lead" in md and "Phase 14 gate" in md


def test_season_region_citl_cover_all_leads(md):
    season = _section(md, "## Season (MAM highlighted)")
    assert "**MAM** (highlighted)" in season
    region = _section(md, "## Region")
    assert "large wards only" in region and "LGA-average wards" in region
    citl = _section(md, "## Calibration-in-the-large by year")
    assert "no interval" in citl
    for sec, per_lead in ((season, 4), (region, 10), (citl, 6)):
        for k in LEADS:
            assert len(_rows(sec, k)) == per_lead, (k, per_lead)


def test_decomposition_and_prf(md):
    dec = _section(md, "## Brier decomposition")
    assert "REL week-block CI" in dec and "RES week-block CI" in dec
    assert "conditional on those bin edges" in dec
    prf = _section(md, "## Precision / recall / F1 at a stated threshold")
    for col in ("threshold", "predicted-positive rate", "prevalence"):
        assert col in prf
    assert "never used to rank predictors" in prf


def test_notes(md):
    notes = _section(md, "## Notes")
    for s in (
        "strawman", "extrapolates the linear logit trend fitted on 1991-2014 into 2015-2020",
        "6 clusters", "exploratory", "conditional on the full-sample quantile bin edges",
        "without intervals", "m = 50", "Small wards", "reanalysis",
    ):
        assert s in notes, s
    sanity = _section(md, "## Sanity checks")
    assert "Persistence decay check" in sanity and "BSS(reference, reference) = 0" in sanity


def test_no_nan_text(md):
    assert " nan " not in md and "[nan" not in md


def test_empty_results_rejected(meta):
    with pytest.raises(ValueError):
        BR.render_markdown({}, meta)
