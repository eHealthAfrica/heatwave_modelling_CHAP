"""Live, skip-gated integration tests re-verifying the Phase 1 foundation fixes (D-06/D-07).

These tests execute real Earth Engine calls against the live `heatwave-508110` GCP project
(never mocked) whenever service-account credentials are available locally
(`keys/service_account.json`) or via CI (`EE_SA_JSON` env var). When neither is present, the
whole module is skipped cleanly rather than failing/blocking a contributor without live
credentials.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

pytestmark = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)


def test_settings_loaded():
    """REWORK-07: heatwave.config.settings loads config.yaml into the typed Settings dataclass."""
    from heatwave.config import settings

    assert settings.gcp_project_id == "heatwave-508110"
    assert settings.ward_asset_id == "projects/heatwave-508110/assets/shp"
    assert settings.bands.tmax == "temperature_2m_max"
    assert settings.bands.tmean == "temperature_2m"
    assert settings.bands.dewpoint == "dewpoint_temperature_2m"
    assert settings.climatology.percentile == 90


def test_auth_resolves_from_any_cwd(tmp_path, monkeypatch):
    """REWORK-04: the local service-account key file resolves to a CWD-independent absolute path."""
    monkeypatch.chdir(tmp_path)

    import heatwave.auth

    assert heatwave.auth._LOCAL_KEY_FILE.is_absolute() is True
    assert heatwave.auth._LOCAL_KEY_FILE.exists() is True


def test_init_ee_idempotent():
    """REWORK-01 (idempotency proxy): calling init_ee() twice raises no exception.

    True "no re-auth on Streamlit rerun" is a manual check (see 01-VALIDATION.md's
    Manual-Only Verifications table); this test confirms init_ee() itself is safe to call
    repeatedly, which the @st.cache_resource wrapper in nigeria_heat_index.py relies on.
    """
    from heatwave.auth import init_ee

    init_ee()
    init_ee()
