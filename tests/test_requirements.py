"""Credential-independent static regression check for REWORK-03.

Unlike tests/test_integration.py, this file is intentionally NOT skip-gated: it needs no
live GCP access, so it always runs regardless of credential availability.
"""
from __future__ import annotations

from pathlib import Path

_REQUIREMENTS_PATH = Path(__file__).resolve().parent.parent / "requirements.txt"


def test_requirements_no_ee_decoy_package():
    """requirements.txt must never reintroduce the namespace-colliding ee==0.2 decoy package."""
    lines = _REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

    assert all(line.strip() != "ee==0.2" for line in lines)
