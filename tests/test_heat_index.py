"""Live, skip-gated tests verifying RH (Magnus) and the NWS Heat Index algorithm (HIDX-02)."""
from __future__ import annotations

import math
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


def _f_to_k(t_f: float) -> float:
    return (t_f - 32) * 5 / 9 + 273.15


def _dewpoint_k(t_f: float, rh: float) -> float:
    """Dewpoint giving exactly `rh` percent at `t_f` under the Magnus formula (its inverse)."""
    from heatwave.science.heat_index import MAGNUS_B, MAGNUS_C

    t_c = (t_f - 32) * 5 / 9
    gamma = math.log(rh / 100) + MAGNUS_B * t_c / (MAGNUS_C + t_c)
    return MAGNUS_C * gamma / (MAGNUS_B - gamma) + 273.15


def _nws_heat_index(t_f: float, rh: float) -> float:
    """Plain-Python NWS algorithm (wpc.ncep.noaa.gov/html/heatindex_equation.shtml)."""
    simple = 0.5 * (t_f + 61.0 + (t_f - 68.0) * 1.2 + rh * 0.094)
    if (simple + t_f) / 2 < 80:
        return simple
    hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh - 0.22475541 * t_f * rh
          - 0.00683783 * t_f**2 - 0.05481717 * rh**2 + 0.00122874 * t_f**2 * rh
          + 0.00085282 * t_f * rh**2 - 0.00000199 * t_f**2 * rh**2)
    if rh < 13 and 80 <= t_f <= 112:
        hi -= (13 - rh) / 4 * math.sqrt((17 - abs(t_f - 95)) / 17)
    elif rh > 85 and 80 <= t_f <= 87:
        hi += (rh - 85) / 10 * (87 - t_f) / 5
    return hi


def _ee_heat_index(t_f: float, rh: float) -> float:
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    init_ee()
    image = _make_test_image(tmean_k=_f_to_k(t_f), dewpoint_k=_dewpoint_k(t_f, rh))
    return _band_value(compute_heat_index(compute_relative_humidity(image)), "heat_index")


@_REQUIRES_CREDENTIALS
@pytest.mark.parametrize(
    ("t_f", "rh", "noaa_hi"),
    [
        (96, 50, 108),   # [CITED: weather.gov/arx/heat_index]
        (100, 40, 109),  # [CITED: noaa.gov/jetstream/synoptic/heat-index]
        (90, 70, 105),   # [CITED: NWS table reproduction, en.wikipedia.org/wiki/Heat_index]
    ],
)
def test_heat_index_matches_noaa_table(t_f, rh, noaa_hi):
    """HIDX-02: the true RH (via the Magnus inverse) gives NOAA's published table value."""
    assert _ee_heat_index(t_f, rh) == pytest.approx(noaa_hi, abs=1.5)


@_REQUIRES_CREDENTIALS
@pytest.mark.parametrize(
    ("t_f", "rh"),
    [
        (60, 30),    # cool Harmattan morning: simple formula, Rothfusz not valid here
        (77, 15),    # warm dry-season day below the 80F switch
        (95, 8),     # hot and very dry: Rothfusz with the low-humidity adjustment
        (84, 92),    # warm and saturated: Rothfusz with the high-humidity adjustment
        (104, 25),   # plain Rothfusz
    ],
)
def test_heat_index_follows_nws_algorithm(t_f, rh):
    """Each branch of the NWS procedure matches a plain-Python reference."""
    assert _ee_heat_index(t_f, rh) == pytest.approx(_nws_heat_index(t_f, rh), abs=0.05)


@_REQUIRES_CREDENTIALS
def test_heat_index_not_below_air_temperature_in_mild_dry_air():
    """Regression: Rothfusz used below 80F gave HI ~20F under the air temperature."""
    assert _ee_heat_index(77, 15) > 74


@_REQUIRES_CREDENTIALS
def test_relative_humidity_matches_magnus():
    """RH from T and D follows the Magnus formula to within 0.1 percentage points."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    image = _make_test_image(tmean_k=_f_to_k(95), dewpoint_k=_dewpoint_k(95, 20))
    rh_value = _band_value(compute_relative_humidity(image), "relative_humidity")

    assert rh_value == pytest.approx(20, abs=0.1)


@_REQUIRES_CREDENTIALS
def test_relative_humidity_clamped_above_100():
    """D-01: dewpoint above tmean (T-D negative) must clamp RH to 100, not exceed it."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    # Dewpoint above air temperature (supersaturated) => unclamped RH would be ~184
    image = _make_test_image(tmean_k=290.0, dewpoint_k=300.0)
    rh_value = _band_value(compute_relative_humidity(image), "relative_humidity")

    assert rh_value == 100


@_REQUIRES_CREDENTIALS
def test_relative_humidity_positive_in_dry_air():
    """A 30 K dewpoint depression is dry-season air at ~16% RH, not 0% (the old linear rule's value)."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    image = _make_test_image(tmean_k=310.0, dewpoint_k=280.0)
    rh_value = _band_value(compute_relative_humidity(image), "relative_humidity")

    assert rh_value == pytest.approx(15.9, abs=0.2)


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
