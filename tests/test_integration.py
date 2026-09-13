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


def test_load_ward_boundary():
    # REWORK-05: exactly 4,841 ward features with the expected properties.
    from heatwave.auth import init_ee
    from heatwave.data.boundary import load_ward_boundary
    init_ee()
    boundary = load_ward_boundary()
    assert boundary.size().getInfo() == 4841

    property_names = boundary.first().propertyNames().getInfo()
    for expected in ("wardname", "wardcode", "lganame", "statename", "geozone"):
        assert expected in property_names


def test_load_era5_land():
    """REWORK-06: load_era5_land() returns correctly date-filtered, multi-band images.

    ee.Filter.date() uses a half-open interval [start, end), verified live: a 2020-01-01
    to 2020-01-05 window yields 4 daily images (01-01 through 01-04), not 5.
    """
    from heatwave.auth import init_ee
    from heatwave.data.boundary import load_ward_boundary
    from heatwave.data.ingest import load_era5_land

    init_ee()
    boundary = load_ward_boundary()
    collection = load_era5_land(boundary, "2020-01-01", "2020-01-05")

    assert collection.size().getInfo() == 4

    band_names = collection.first().bandNames().getInfo()
    for expected in ("temperature_2m_max", "temperature_2m", "dewpoint_temperature_2m"):
        assert expected in band_names


def test_era5_land_bands_aligned():
    """REWORK-02: tmax/tmean/dewpoint bands exist together on every image, no join needed."""
    from heatwave.auth import init_ee
    from heatwave.data.boundary import load_ward_boundary
    from heatwave.data.ingest import load_era5_land

    init_ee()
    boundary = load_ward_boundary()
    collection = load_era5_land(boundary, "2020-01-01", "2020-01-05")

    assert len(collection.first().bandNames().getInfo()) == 3


def test_streamlit_app_boots_cleanly():
    """REWORK-08: streamlit run nigeria_heat_index.py boots without raising an exception."""
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parent.parent / "nigeria_heat_index.py"
    at = AppTest.from_file(str(script), default_timeout=30)
    at.run()

    assert not at.exception, f"App raised: {at.exception}"
