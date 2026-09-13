"""Live, skip-gated tests verifying the Rothfusz Heat Index formula against NOAA table values (HIDX-02)."""
from __future__ import annotations

import os
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

# NOTE: This gate is intentionally applied per-test (via `_REQUIRES_CREDENTIALS`) rather
# than as a module-level `pytestmark`. A module-level `pytestmark` would also skip
# `test_science_module_exports`, which 02-VALIDATION.md requires to be runnable without
# live GCP credentials (`pytest tests/test_heat_index.py -k export`). Do not "restore" the
# module-level form.
_REQUIRES_CREDENTIALS = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)


def _make_test_image(tmean_k: float, dewpoint_k: float) -> ee.Image:
    from heatwave.config import settings

    return ee.Image.constant([0, tmean_k, dewpoint_k]).rename(
        [settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint]
    )


def _band_value(image: ee.Image, band_name: str):
    return (
        image.select(band_name)
        .reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=ee.Geometry.Point([0, 0]),
            scale=1000,
        )
        .get(band_name)
        .getInfo()
    )


def test_science_module_exports():
    """HIDX-01: heatwave.science.heat_index exports both functions, no credentials required."""
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    assert callable(compute_relative_humidity)
    assert callable(compute_heat_index)


@_REQUIRES_CREDENTIALS
def test_heat_index_matches_noaa_table_96_50():
    """T=96F, RH=50% -> NOAA table HI=108F [CITED: weather.gov/arx/heat_index]."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    init_ee()
    image = _make_test_image(tmean_k=308.706, dewpoint_k=298.706)
    result = compute_heat_index(compute_relative_humidity(image))

    hi_value = _band_value(result, "heat_index")

    assert hi_value == pytest.approx(108, abs=1.5)


@_REQUIRES_CREDENTIALS
def test_heat_index_matches_noaa_table_100_40():
    """T=100F, RH=40% -> NOAA table HI=109F [CITED: noaa.gov/jetstream/synoptic/heat-index]."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    init_ee()
    image = _make_test_image(tmean_k=310.928, dewpoint_k=298.928)
    result = compute_heat_index(compute_relative_humidity(image))

    hi_value = _band_value(result, "heat_index")

    assert hi_value == pytest.approx(109, abs=1.5)


@_REQUIRES_CREDENTIALS
def test_heat_index_matches_noaa_table_90_70():
    """T=90F, RH=70% -> NOAA table HI=105F [CITED: NWS table reproduction, en.wikipedia.org/wiki/Heat_index]."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    init_ee()
    image = _make_test_image(tmean_k=305.372, dewpoint_k=299.372)
    result = compute_heat_index(compute_relative_humidity(image))

    hi_value = _band_value(result, "heat_index")

    assert hi_value == pytest.approx(105, abs=1.5)


@_REQUIRES_CREDENTIALS
def test_relative_humidity_clamped_above_100():
    """D-01: dewpoint above tmean (T-D negative) must clamp RH to 100, not exceed it."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    # T - D = -10 => unclamped RH would be 100 - 5*(-10) = 150
    image = _make_test_image(tmean_k=290.0, dewpoint_k=300.0)
    rh_value = _band_value(compute_relative_humidity(image), "relative_humidity")

    assert rh_value == 100


@_REQUIRES_CREDENTIALS
def test_relative_humidity_clamped_below_0():
    """D-01: dewpoint far below tmean (T-D large positive) must clamp RH to 0, not go negative."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    # T - D = 30 => unclamped RH would be 100 - 5*30 = -50
    image = _make_test_image(tmean_k=310.0, dewpoint_k=280.0)
    rh_value = _band_value(compute_relative_humidity(image), "relative_humidity")

    assert rh_value == 0


@_REQUIRES_CREDENTIALS
def test_source_bands_not_clamped():
    """D-01 guard: the clamp must hit only the single-band RH result, never the source bands."""
    from heatwave.auth import init_ee
    from heatwave.config import settings
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    # Same fixture as test_relative_humidity_clamped_above_100: tmean=290.0 would be
    # truncated to 100 if the clamp were mistakenly applied to the multi-band composite.
    image = _make_test_image(tmean_k=290.0, dewpoint_k=300.0)
    result = compute_relative_humidity(image)

    tmean_value = _band_value(result, settings.bands.tmean)

    assert tmean_value == 290.0
