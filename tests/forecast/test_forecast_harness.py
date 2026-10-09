"""Scoring harness over stored predictions (EVAL-01..04), synthetic 6-ward panel, small B."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heatwave.forecast import targets, testlock, weeks
from heatwave.forecast.config import config_hash, load_forecast_config
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.evaluation import harness, metrics, predictions as P, slices
from heatwave.forecast.fixtures import SYNTHETIC_WARDS, synthetic_panel, synthetic_static_sources
from heatwave.forecast.static import build_static_table

RUN_ID = "20270101T000000Z_abcdef12"
SHA = "a" * 64
B = 40
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def panel():
    return synthetic_panel(last_week="2027-W10")


@pytest.fixture(scope="module")
def attrs(panel):
    geo, rows = synthetic_static_sources()
    st = build_static_table(geo, rows, SYNTHETIC_WARDS)
    return slices.ward_attributes(st, slices.ward_areas_deg2(geo, st.wards))


def _week_attrs(df):
    idx = df["target_week_index"].to_numpy()
    uniq = np.unique(idx)
    start = {int(i): np.datetime64(weeks.index_to_week_start(int(i)).isoformat(), "D") for i in uniq}
    return slices.week_attributes(idx, np.array([start[int(i)] for i in idx]), df["target_week"].astype(str).to_numpy())


def _write(panel, cfg, run_dir, name, p_fn, lead=1, split="validate"):
    w, o = lead_row_index(panel, cfg, lead, split)
    y = targets.lead_label(panel, lead)[w, o]
    p = np.clip(p_fn(y, len(y)), 0, 1).astype(np.float32)
    df = P.build_frame(panel, cfg, name, lead, split, w, o, p)
    return P.write_predictions(df, P.PredictionMeta(RUN_ID, SHA, SHA, name, lead, split), run_dir), df


@pytest.fixture(scope="module")
def scored(panel, cfg, attrs, tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("runs") / "forecast_runs" / RUN_ID
    run_dir.mkdir(parents=True)
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 0.15, 100000)
    paths = {}
    paths["ref"], df = _write(panel, cfg, run_dir, "ref", lambda y, n: np.full(n, 0.15))
    paths["noisy"], _ = _write(panel, cfg, run_dir, "noisy", lambda y, n: 0.15 + 0.3 * y + noise[:n])
    paths["twin"], _ = _write(panel, cfg, run_dir, "twin", lambda y, n: np.full(n, 0.15))
    root = tmp_path_factory.mktemp("logroot")
    ctx = harness.ScoringContext(
        cfg, 1, 0.15, attrs, _week_attrs(df), B=B, h_bins=50, run_id=RUN_ID, log_root=root
    )
    res = harness.score_lead(paths, ctx, references=["ref"])
    return res, ctx, paths, root


def _arrays(paths, name, ref="ref"):
    d0, _ = P.load_predictions(paths[ref], load_forecast_config())
    d, _ = P.load_predictions(paths[name], load_forecast_config())
    r, c = P.align(d0, d)
    return d["p"].to_numpy(np.float64)[c], d["y"].to_numpy(np.float64)[c]


def test_summary_matches_metrics(scored):
    res, ctx, paths, _ = scored
    for name in ("ref", "noisy"):
        p, y = _arrays(paths, name)
        row = res.summary.set_index("predictor").loc[name]
        assert row["brier"] == pytest.approx(metrics.brier(p, y), rel=1e-12)
        assert row["n"] == len(p)
    s = res.summary.set_index("predictor").loc["noisy"]
    assert s["brier_week_lo"] <= s["brier"] <= s["brier_week_hi"]
    assert s["rel_week_lo"] <= s["rel_week_hi"] and s["res_week_lo"] <= s["res_week_hi"]
    assert np.isfinite(s["residual"])


def test_comparisons_self_zero(scored):
    res = scored[0]
    c = res.comparisons
    assert len(c) == 3 and set(c["reference"]) == {"ref"}
    own = c[c["candidate"] == "ref"].iloc[0]
    assert own["bss"] == 0.0
    for k in ("bss_week_lo", "bss_week_hi", "bss_year_lo", "bss_year_hi"):
        assert own[k] == 0.0
    noisy = c[c["candidate"] == "noisy"].iloc[0]
    assert noisy["bss"] > 0
    assert harness.sanity_flags(res) == {"probabilities_valid": True, "self_bss_zero": True}


def test_seed_reproducible(scored):
    res, ctx, paths, _ = scored
    again = harness.score_lead(paths, ctx, references=["ref"])
    pd.testing.assert_frame_equal(res.comparisons, again.comparisons)
    pd.testing.assert_frame_equal(res.summary, again.summary)


def test_auc_stratified_only(scored):
    a = scored[0].auc
    assert set(a["family"]) == {"season", "geozone", "lat_band"}
    assert not a["stratum"].astype(str).str.lower().isin(["all", "pooled"]).any()
    assert a["auc_week_lo"].notna().any()


def test_prf_and_citl(scored):
    res = scored[0]
    for c in ("threshold", "predicted_positive_rate", "prevalence", "f1_week_lo", "f1_week_hi"):
        assert c in res.prf.columns
    assert (res.prf["threshold"] == 0.15).all()
    n_years = res.citl[res.citl["predictor"] == "ref"]["year"].nunique()
    assert n_years == len(set(range(2015, 2021)))
    assert not any("accuracy" in c.lower() for t in (res.summary, res.prf, res.slices) for c in t.columns)


def test_reliability_present(scored):
    r = scored[0].reliability
    assert {"predictor", "bin", "n", "mean_p", "obs_freq"} <= set(r.columns)


def test_log_records(scored):
    res, ctx, paths, root = scored
    recs = [r for r in testlock.read_log(root) if r["event"] == "score"]
    assert recs and len(recs) % 3 == 0
    first = recs[:3]
    assert sorted(r["predictor"] for r in first) == ["noisy", "ref", "twin"]
    for r in first:
        assert r["outcome"] == "scored" and r["split"] == "validate"
        assert r["n_rows"] == res.n_rows and r["run_id"] == RUN_ID
        assert r["config_sha256"] == config_hash(ctx.cfg)


def test_mixed_lead_or_split_raises(panel, cfg, attrs, tmp_path):
    run_dir = tmp_path / "forecast_runs" / RUN_ID
    run_dir.mkdir(parents=True)
    a, df = _write(panel, cfg, run_dir, "a", lambda y, n: np.full(n, 0.2))
    b, _ = _write(panel, cfg, run_dir, "b", lambda y, n: np.full(n, 0.2), lead=2)
    ctx = harness.ScoringContext(cfg, 1, 0.2, attrs, _week_attrs(df), B=B, h_bins=50, log_root=tmp_path)
    with pytest.raises(ValueError):
        harness.score_lead({"a": a, "b": b}, ctx, references=["a"])
    with pytest.raises(ValueError):
        harness.score_lead({"a": a}, ctx, references=["missing"])


def test_slices_table(scored, attrs):
    res = scored[0]
    s = res.slices
    assert set(s["flag_filter"]) == set(slices.FLAG_FILTERS)
    assert set(s[s["family"] == "season"]["stratum"]) == set(slices.SEASONS)
    assert {"geozone", "lat_band", "year", "all"} <= set(s["family"])
    assert "bss_vs_ref" in s.columns and "bss_vs_ref_week_lo" in s.columns
    assert s[s["highlight"]]["stratum"].eq("MAM").all() and s["highlight"].any()
    one = s[s["predictor"] == "noisy"]
    for ff in slices.FLAG_FILTERS:
        tot = one[(one["family"] == "all") & (one["flag_filter"] == ff)]["n"].iloc[0]
        seas = one[(one["family"] == "season") & (one["flag_filter"] == ff)]["n"].sum()
        assert seas == tot
    # the synthetic empty-geometry ward counts as large, the other five are small
    lg = one[(one["family"] == "all") & (one["flag_filter"] == "large_wards_only")]["n"].iloc[0]
    assert 0 < lg < res.n_rows
    # self skill inside a slice is exactly zero
    r = s[(s["predictor"] == "ref") & (s["n"] > 0)]
    assert (r["bss_vs_ref"] == 0.0).all()


def test_empty_slice_is_nan(panel, cfg, attrs, tmp_path):
    run_dir = tmp_path / "forecast_runs" / RUN_ID
    run_dir.mkdir(parents=True)
    a, df = _write(panel, cfg, run_dir, "a", lambda y, n: np.full(n, 0.2))
    b, _ = _write(panel, cfg, run_dir, "b", lambda y, n: np.full(n, 0.3))
    small = attrs.copy()
    small["small"] = True
    ctx = harness.ScoringContext(cfg, 1, 0.2, small, _week_attrs(df), B=B, h_bins=50, log_root=tmp_path)
    res = harness.score_lead({"a": a, "b": b}, ctx, references=["a"])
    e = res.slices[res.slices["flag_filter"] == "large_wards_only"]
    assert (e["n"] == 0).all()
    assert e["brier"].isna().all() and e["bss_vs_a"].isna().all()


def test_helper_equals_week_stats():
    rng = np.random.default_rng(1)
    n, W = 500, 12
    p = rng.random(n).astype(np.float32).astype(np.float64)
    y = (rng.random(n) < p).astype(np.float64)
    w = rng.integers(0, W, n)
    e, ae = metrics.quantile_edges(p, 10), metrics.quantile_edges(p, 50)
    ref = metrics.week_stats(p, y, w, W, edges=e, auc_edges=ae, threshold=0.4)
    got = harness._week_stats_from_bins(p, y, w, W, metrics.assign_bins(p, e), metrics.assign_bins(p, ae), e, ae, 0.4)
    for f in ("n", "sum_y", "sum_p", "sse", "bin_n", "bin_sum_p", "bin_sum_y", "pos_hist", "neg_hist", "tp", "fp", "fn"):
        np.testing.assert_array_equal(getattr(ref, f), getattr(got, f))


def test_best_baseline():
    order = ("a", "b", "c")
    assert harness.best_baseline({"a": 0.2, "b": 0.1, "c": 0.1}, order) == "b"
    assert harness.best_baseline({"c": 0.1, "b": 0.1}, order) == "b"
    with pytest.raises(ValueError):
        harness.best_baseline({}, order)


def test_persistence_decay_check():
    r = harness.persistence_decay_check({1: 0.05, 4: -0.002, 5: 0.0, 6: 0.004})
    assert r["ok"] is True and r["strictly_monotone"] is False
    assert (r["lead_first"], r["lead_last"]) == (1, 6)
    assert harness.persistence_decay_check({1: 0.0, 6: 0.01})["ok"] is False


def test_results_to_dict_json(scored):
    d = harness.results_to_dict(scored[0])
    txt = json.dumps(d, allow_nan=False)
    assert "NaN" not in txt and "accuracy" not in txt.lower()
    assert d["lead"] == 1 and d["sanity"]["self_bss_zero"] is True


def test_isolation_static():
    pkg = REPO / "heatwave" / "forecast" / "evaluation"
    pat = re.compile(r"^\s*(from|import)\s+.*(forecast\.baselines|forecast import baselines|sklearn\.linear_model|lightgbm)", re.M)
    for f in ("harness.py", "metrics.py", "bootstrap.py", "slices.py", "predictions.py"):
        assert not pat.search((pkg / f).read_text(encoding="utf-8")), f
    src = (pkg / "harness.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(fit|predict)\(", src)
    assert "accuracy" not in src.lower()


def test_prf_surfaces_n_valid(scored):
    """Review WR-03: the number of defined bootstrap replicates is kept for P/R/F1."""
    res, ctx = scored[0], scored[1]
    for m in ("precision", "recall", "f1"):
        col = f"{m}_n_valid"
        assert col in res.prf.columns
        assert ((res.prf[col] > 0) & (res.prf[col] <= ctx.B)).all()
    # F1 has no undefined replicate once at least one true positive is possible in a block
    assert (res.prf["f1_n_valid"] == ctx.B).all()
