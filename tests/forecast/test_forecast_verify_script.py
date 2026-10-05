"""CI-safe subprocess tests of scripts/verify_frozen.py on synthetic frozen data."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from heatwave.forecast.fixtures import build_synthetic_frozen

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "verify_frozen.py"


def run(ds, *extra, expected=None, root=None):
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--data-root",
        str(root or ds.data_root),
        "--expected-parquet-sha256",
        expected or ds.sha256,
        *extra,
    ]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.fixture()
def ds(tmp_path):
    return build_synthetic_frozen(tmp_path)


def flip_byte(path: Path):
    os.chmod(path, 0o600)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def test_full_ok(ds):
    code, out = run(ds)
    assert code == 0, out
    assert "OK" in out
    last = out.strip().splitlines()[-1]
    assert last.startswith("verify_frozen:") and "0 mismatches" in last


def test_outputs_only_ok_without_inputs(ds):
    code, out = run(ds, "--outputs-only")
    assert code == 0, out
    assert "era5_land_daily_gee" not in out


def test_tampered_parquet(ds):
    flip_byte(ds.parquet_path)
    code, out = run(ds)
    assert code == 1
    assert "MISMATCH" in out and "covariate_table.parquet" in out


def test_wrong_anchor(ds):
    code, out = run(ds, expected="0" * 64)
    assert code == 1
    assert "forecast.yaml" in out


def test_modified_input_full_vs_outputs_only(ds):
    flip_byte(ds.data_root / "era5_land_daily_gee" / "temperature_2m_max" / "1992.nc")
    code, out = run(ds)
    assert code == 1 and "MISMATCH" in out
    code, out = run(ds, "--outputs-only")
    assert code == 0, out


def test_modified_copied_input(ds):
    flip_byte(ds.dataset_dir / "inputs" / "wards.geojson")
    code, out = run(ds)
    assert code == 1 and "MISMATCH" in out


def test_missing_input(ds):
    (ds.data_root / "wards.geojson").unlink()
    code, out = run(ds)
    assert code == 1 and "MISSING" in out


def test_missing_manifest(ds):
    ds.manifest_path.unlink()
    code, _ = run(ds)
    assert code == 2


def test_bad_version_rejected(ds):
    code, _ = run(ds, "--version", "../outputs")
    assert code == 2


def test_manifest_version_mismatch(ds):
    m = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    m["version"] = "covariates-v9.9"
    ds.manifest_path.write_text(json.dumps(m), encoding="utf-8")
    code, _ = run(ds)
    assert code == 2


def test_escaping_key_is_bad_key(ds, tmp_path):
    outside = tmp_path.parent / "escape.nc"
    outside.write_bytes(b"x")
    m = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    m["inputs_sha256"]["../escape.nc"] = hashlib.sha256(b"x").hexdigest()
    ds.manifest_path.write_text(json.dumps(m), encoding="utf-8")
    code, out = run(ds)
    assert code == 1
    assert "BAD-KEY" in out


def _digest_tree(root: Path):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_script_never_modifies_files(ds):
    before = _digest_tree(ds.data_root)
    code, out = run(ds)
    assert code == 0, out
    assert _digest_tree(ds.data_root) == before
