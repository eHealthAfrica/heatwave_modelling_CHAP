"""Real-data leakage variant (local only; skipped when the frozen data is absent)."""
import gc

import numpy as np
import pytest

from heatwave.forecast import splits, targets, weeks
from heatwave.forecast.dataset import lead_row_index
from heatwave.forecast.climatology import Climatology
from heatwave.forecast.features import REGISTRY, build_feature_store
from heatwave.forecast.fixtures import subset_panel
from heatwave.forecast.leakage import (
    check_poison_invariance,
    check_registry,
    check_train_only_statistics,
    check_truncation_invariance,
)

pytestmark = pytest.mark.frozen

N_WARDS = 200
FORCED_LABELS = ("1994-W04", "2004-W53", "2014-W52", "2015-W01", "2020-W53", "2021-W01", "2026-W38")


@pytest.fixture(scope="module")
def subset(frozen_panel, forecast_cfg):
    rng = np.random.default_rng(forecast_cfg.seed)
    pos = rng.choice(len(frozen_panel.wards), size=N_WARDS, replace=False)
    return subset_panel(frozen_panel, pos)


@pytest.fixture(scope="module")
def origins(frozen_panel, forecast_cfg):
    rng = np.random.default_rng(forecast_cfg.seed + 1)
    T = frozen_panel.values.shape[1]
    forced = [frozen_panel.week_pos(lab) for lab in FORCED_LABELS]
    rand = [int(x) for x in rng.choice(np.arange(159, T), size=3, replace=False)]
    return sorted(set(forced + rand))


def _build(frozen_clim, frozen_static):
    return lambda p: build_feature_store(p, frozen_clim, frozen_static.align(p.wards)).arrays


def test_registry_real():
    check_registry(REGISTRY)


def test_truncation_invariance_real(subset, origins, frozen_clim, frozen_static):
    check_truncation_invariance(_build(frozen_clim, frozen_static), subset, origins)


def test_poison_invariance_real(subset, origins, frozen_clim, frozen_static):
    check_poison_invariance(_build(frozen_clim, frozen_static), subset, origins)


def test_train_only_statistics_real(frozen_panel, forecast_cfg):
    end = forecast_cfg.splits.train_end
    check_train_only_statistics(lambda p: Climatology.fit(p, end), frozen_panel, end, modes=("garbage",))
    gc.collect()


def test_real_split_integrity(frozen_panel, forecast_cfg):
    cfg = forecast_cfg
    p = frozen_panel
    T = p.values.shape[1]
    lab = targets.has_label(p, 6)
    tgt = p.week_index[lab] + 6
    m = splits.split_masks(tgt, cfg.splits)
    assert weeks.index_to_label(int(tgt[m["train"]].max())) == "2014-W38"
    assert "2020-W53" in {weeks.index_to_label(int(t)) for t in tgt[m["validate"]]}
    assert weeks.index_to_label(int(tgt[m["test"]].min())) == "2021-W01"
    # lead 1: the last origin has no label and is in no split
    assert not targets.has_label(p, 1)[T - 1]
    assert p.week_labels[T - 1] == "2026-W38"
    for s in splits.SPLIT_NAMES:
        _, o = lead_row_index(p, cfg, 1, s)
        assert (o != T - 1).all()


def test_real_target_alignment(frozen_panel, forecast_cfg):
    p = frozen_panel
    rng = np.random.default_rng(forecast_cfg.seed + 2)
    iv = list(p.variables).index("heatwave_days")
    T = p.values.shape[1]
    for _ in range(50):
        lead = int(rng.choice(forecast_cfg.leads))
        w = int(rng.integers(len(p.wards)))
        t = int(rng.integers(0, T - lead))
        label = targets.lead_label(p, lead)[w, t]
        target_pos = p.week_pos(weeks.index_to_label(int(p.week_index[t]) + lead))
        assert label == float(p.values[w, target_pos, iv] >= 3)
