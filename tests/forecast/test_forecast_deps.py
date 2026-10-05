"""Smoke tests for the forecasting ML stack pins (DATA-05)."""
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pytest

REQ = Path(__file__).resolve().parents[2] / "requirements.txt"


def _pins():
    pins = {}
    for line in REQ.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, ver = line.partition("==")
        pins[name.lower().replace("_", "-")] = ver
    return pins


def test_core_pins_unchanged():
    pins = _pins()
    assert pins["numpy"] == "2.3.3"
    assert pins["pandas"] == "2.3.2"
    assert pins["pyarrow"] == "21.0.0"


def test_ml_pins_present():
    pins = _pins()
    assert pins["scikit-learn"] == "1.9.1"
    assert pins["lightgbm"] == "4.7.0"
    assert pins["shap"] == "0.52.0"


@pytest.mark.parametrize(
    "name",
    ["numpy", "pandas", "pyarrow", "scikit-learn", "lightgbm", "shap",
     "scipy", "joblib", "numba", "llvmlite"],
)
def test_installed_versions_match_requirements(name):
    assert version(name) == _pins()[name]


def test_ml_imports():
    import lightgbm
    import shap  # noqa: F401
    import sklearn

    assert sklearn.__version__ == "1.9.1"
    assert lightgbm.__version__ == "4.7.0"


def _model():
    from lightgbm import LGBMClassifier

    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 3))
    y = (X[:, 0] + 0.5 * X[:, 1] + rng.normal(scale=0.5, size=300) > 0).astype(int)
    m = LGBMClassifier(
        n_estimators=10, num_leaves=4, deterministic=True, force_row_wise=True,
        num_threads=1, verbose=-1, random_state=0,
    )
    m.fit(X, y)
    return m, X


def test_lightgbm_pred_contrib():
    m, X = _model()
    contrib = m.booster_.predict(X, pred_contrib=True)
    raw = m.booster_.predict(X, raw_score=True)
    assert contrib.shape == (300, 4)
    assert np.allclose(contrib.sum(axis=1), raw, atol=1e-6)


def test_shap_tree_explainer():
    import shap

    m, X = _model()
    sv = shap.TreeExplainer(m).shap_values(X[:10])
    sv = np.asarray(sv[1] if isinstance(sv, list) else sv)
    assert sv.shape[0] == 10
    assert sv.shape[1] == 3
