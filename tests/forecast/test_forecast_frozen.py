"""Real-data integration tests on the frozen covariates-v1.0 dataset (local only).

Never writes to the real frozen folder; all modified copies live under tmp_path.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from heatwave.forecast import weeks
from heatwave.forecast.artifacts import finish_run, start_run
from heatwave.forecast.config import load_forecast_config
from heatwave.forecast.data import (
    MANIFEST_NAME,
    PARQUET_NAME,
    VARIABLES,
    FrozenDataError,
    assert_frozen_source,
    frozen_dataset_dir,
    load_panel,
    verify_frozen_parquet,
)

pytestmark = pytest.mark.frozen

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_frozen.py"


@pytest.fixture(scope="module")
def cfg():
    return load_forecast_config()


@pytest.fixture(scope="module")
def real_dir(cfg):
    return frozen_dataset_dir(cfg.data)


@pytest.fixture(scope="module")
def real_panel(cfg):
    return load_panel(cfg.data)


def _copy_dataset(cfg, real_dir, dest_root: Path, *, manifest_parquet_only=False) -> Path:
    d = dest_root / cfg.data.frozen_subdir / cfg.data.version
    d.mkdir(parents=True)
    shutil.copyfile(real_dir / PARQUET_NAME, d / PARQUET_NAME)
    manifest = json.loads((real_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest_parquet_only:
        manifest["outputs_sha256"] = {PARQUET_NAME: manifest["outputs_sha256"][PARQUET_NAME]}
        manifest["inputs_sha256"] = {}
    (d / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    os.chmod(d / PARQUET_NAME, 0o600)
    return d


def _flip(path: Path):
    size = path.stat().st_size
    with open(path, "r+b") as fh:
        fh.seek(size // 2)
        b = fh.read(1)
        fh.seek(size // 2)
        fh.write(bytes([b[0] ^ 0xFF]))


def test_real_panel_shape_and_hash(real_panel, real_dir):
    manifest = json.loads((real_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert real_panel.values.shape == (4841, 1863, 8)
    assert real_panel.values.dtype == np.float32
    assert int(np.isnan(real_panel.values).sum()) == 0
    assert real_panel.sha256 == manifest["outputs_sha256"][PARQUET_NAME]
    assert real_panel.sha256.startswith("82583fbf")
    assert real_panel.version == "covariates-v1.0"


def test_real_week_axis_matches_index(real_panel):
    assert real_panel.week_labels == tuple(weeks.index_labels(1863))
    assert np.array_equal(real_panel.week_index, np.arange(1863))
    assert real_panel.week_labels[0] == "1991-W02"
    assert real_panel.week_labels[-1] == "2026-W38"
    w53 = {lab for lab in real_panel.week_labels if lab.endswith("-W53")}
    assert w53 == {"1992-W53", "1998-W53", "2004-W53", "2009-W53", "2015-W53", "2020-W53"}
    assert (np.diff(real_panel.week_start) == np.timedelta64(7, "D")).all()


def test_real_values_roundtrip_row_group0(real_panel, real_dir):
    df = pq.ParquetFile(real_dir / PARQUET_NAME).read_row_group(0).to_pandas()
    wp = np.array([real_panel.ward_pos(w) for w in df["location"]])
    tp = np.array([real_panel.week_pos(t) for t in df["time_period"]])
    expect = df[list(VARIABLES)].to_numpy(dtype=np.float32)
    np.testing.assert_array_equal(real_panel.values[wp, tp, :], expect)


def test_modified_real_copy_rejected(cfg, real_dir, tmp_path):
    bad = _copy_dataset(cfg, real_dir, tmp_path / "bad")
    _flip(bad / PARQUET_NAME)
    with pytest.raises(FrozenDataError, match="sha256"):
        load_panel(cfg.data, data_root=tmp_path / "bad")
    _copy_dataset(cfg, real_dir, tmp_path / "good")
    path, _, sha = verify_frozen_parquet(cfg.data, data_root=tmp_path / "good")
    assert sha == cfg.data.expected_parquet_sha256


def test_verify_script_outputs_only_real(cfg, real_dir, tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--outputs-only"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    bad = _copy_dataset(cfg, real_dir, tmp_path, manifest_parquet_only=True)
    _flip(bad / PARQUET_NAME)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--outputs-only", "--data-root", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "MISMATCH" in r.stdout


def test_live_csv_refused(cfg):
    with pytest.raises(FrozenDataError):
        assert_frozen_source(REPO_ROOT / "outputs" / "covariate_table.csv", cfg.data)


def test_run_folder_for_real_data(cfg, real_panel, tmp_path):
    ctx = start_run(cfg, data_sha256=real_panel.sha256, data_root=tmp_path)
    finish_run(ctx)
    manifest = json.loads((ctx.path / "RUN_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["data"]["parquet_sha256"] == real_panel.sha256
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["code"]["git_commit"])
