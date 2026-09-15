# Phase 2: Heat Index Relocation - Pattern Map

**Mapped:** 2026-09-13
**Files analyzed:** 4 (2 new, 1 modified, 1 new test)
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `heatwave/science/__init__.py` | config (package marker) | — | `heatwave/data/__init__.py` | exact |
| `heatwave/science/heat_index.py` | service (domain/science module) | transform (server-side `ee.Image` pipeline) | `heatwave/data/boundary.py` + `heatwave/data/ingest.py` | exact (style), role-match (content is a relocation of `nigeria_heat_index.py` lines 32-66) |
| `nigeria_heat_index.py` (modified) | controller (Streamlit script, presentation) | request-response (UI render) | itself, pre-change (import call-site only) | exact |
| `tests/test_heat_index.py` | test | request-response (live-EE, skip-gated) | `tests/test_integration.py` | exact |

## Pattern Assignments

### `heatwave/science/__init__.py` (config, package marker)

**Analog:** `heatwave/data/__init__.py`

**Full content of analog** — confirmed empty (0 bytes; `Read` returned "the file exists but the contents are empty").

**Action:** Create `heatwave/science/__init__.py` as a zero-byte file, matching `heatwave/data/__init__.py` exactly. No docstring, no content.

---

### `heatwave/science/heat_index.py` (service, transform)

**Analogs:** `heatwave/data/boundary.py` (style/structure), `heatwave/data/ingest.py` (style/structure + config usage), `nigeria_heat_index.py` lines 32-66 (content source — this is what gets relocated)

**Module structure pattern** (from `heatwave/data/boundary.py`, full file, lines 1-11):
```python
"""Ward (admin-3) boundary asset access."""
from __future__ import annotations

import ee

from heatwave.config import settings


def load_ward_boundary() -> ee.FeatureCollection:
    """Return the nationwide ward boundary FeatureCollection configured in config.yaml."""
    return ee.FeatureCollection(settings.ward_asset_id)
```
Convention to replicate exactly: one-line module docstring, `from __future__ import annotations`, `import ee`, blank line, `from heatwave.config import settings`, two blank lines, then top-level functions with type-annotated signatures and a docstring. No classes.

**Config/band-access pattern** (from `heatwave/data/ingest.py`, lines 22-32):
```python
def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ee.ImageCollection:
    """Return the ERA5-Land collection, date-filtered and clipped to boundary."""
    start_date = start_date or settings.start_date
    end_date = end_date or settings.end_date

    return (
        ee.ImageCollection(settings.era5_land_collection)
        .select([settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint])
        .filter(ee.Filter.date(start_date, end_date))
        .map(lambda image: image.clip(boundary))
    )
```
Shows the `settings.bands.*` accessor pattern (`settings.bands.tmax`, `.tmean`, `.dewpoint`) already used correctly — `compute_relative_humidity`/`compute_heat_index` already reference `settings.bands.tmean`/`settings.bands.dewpoint` this same way; no change needed to these accessors.

**Content to relocate verbatim, with D-01 clamp fix** (source: `nigeria_heat_index.py` lines 32-64, current inline definitions):
```python
# Compute Relative Humidity
def compute_relative_humidity(image):
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)

    rh = image.expression(
        '100 - 5 * (T - D)',
        {'T': T, 'D': D}
    ).rename('relative_humidity')

    return image.addBands(rh)

# Compute Heat Index
def compute_heat_index(image):
    tempC = image.select(settings.bands.tmean)
    tempF = tempC.subtract(273.15).multiply(9/5).add(32)
    RH = image.select('relative_humidity')

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = [
        -42.379, 2.04901523, 10.14333127, -0.22475541,
        -0.00683783, -0.05481717, 0.00122874,
        0.00085282, -0.00000199
    ]

    HI = tempF.expression(
        'c1 + c2*T + c3*R + c4*T*R + c5*T**2 + c6*R**2 + c7*T**2*R + c8*T*R**2 + c9*T**2*R**2',
        {'T': tempF, 'R': RH, 'c1': c1, 'c2': c2, 'c3': c3,
         'c4': c4, 'c5': c5, 'c6': c6, 'c7': c7, 'c8': c8, 'c9': c9}
    ).rename('heat_index')

    return image.addBands(HI.set('system:time_start', image.get('system:time_start')))
```

**Target form after relocation + D-01 fix** (this is the file's expected final content — combines the boundary.py/ingest.py style header with the verbatim logic plus the single clamp insertion; RESEARCH.md Pattern 2/3 already verified this against the installed `earthengine-api` source):
```python
"""Relative humidity and Heat Index computation over ERA5-Land ee.Image bands."""
from __future__ import annotations

import ee

from heatwave.config import settings


def compute_relative_humidity(image: ee.Image) -> ee.Image:
    """Return image with an added 'relative_humidity' band, clamped to [0, 100] (D-01/WR-01)."""
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)

    rh = (
        image.expression('100 - 5 * (T - D)', {'T': T, 'D': D})
        .clamp(0, 100)  # D-01 fix: single-band, pre-addBands — never clamp the multi-band image
        .rename('relative_humidity')
    )
    return image.addBands(rh)


def compute_heat_index(image: ee.Image) -> ee.Image:
    """Return image with an added 'heat_index' band (Rothfusz regression, deg F)."""
    tempC = image.select(settings.bands.tmean)
    tempF = tempC.subtract(273.15).multiply(9 / 5).add(32)
    RH = image.select('relative_humidity')

    c1, c2, c3, c4, c5, c6, c7, c8, c9 = [
        -42.379, 2.04901523, 10.14333127, -0.22475541,
        -0.00683783, -0.05481717, 0.00122874,
        0.00085282, -0.00000199,
    ]

    HI = tempF.expression(
        'c1 + c2*T + c3*R + c4*T*R + c5*T**2 + c6*R**2 + c7*T**2*R + c8*T*R**2 + c9*T**2*R**2',
        {'T': tempF, 'R': RH, 'c1': c1, 'c2': c2, 'c3': c3,
         'c4': c4, 'c5': c5, 'c6': c6, 'c7': c7, 'c8': c8, 'c9': c9},
    ).rename('heat_index')

    return image.addBands(HI.set('system:time_start', image.get('system:time_start')))
```
Note: `tempC` variable name and the `.set('system:time_start', ...)` call are left as-is above (verbatim per D-02) — renaming to `tempK` / dropping the dead `.set()` call are explicitly Claude's Discretion (opportunistic cleanup), not required.

**Critical constraint (do not violate):** `.clamp(0, 100)` must be called on the single-band `rh` expression result, before `.rename()`/before it is added via `addBands()` — never on `image` (the multi-band composite) afterward, or `tmax`/`tmean`/`dewpoint` (Kelvin, ~250-320) get silently truncated to 100. See RESEARCH.md Pitfall 1.

---

### `nigeria_heat_index.py` (modified) — controller, request-response

**Analog:** itself (before/after diff) — this is a call-site update only, no new pattern needed beyond the import.

**Current inline definition + call sites to remove** (lines 32-66, shown in full above under "Content to relocate verbatim").

**Import pattern already established in this file** (lines 7-9, existing convention to extend):
```python
from heatwave.config import settings
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
```

**Required change:** add a third import line following the exact same style:
```python
from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index
```
Then delete the two `def compute_relative_humidity(...):` / `def compute_heat_index(...):` blocks (lines 32-64) entirely. The call sites immediately after each (`relativeHumidity = era5_land.map(compute_relative_humidity)` at line 44, `heatIndex = relativeHumidity.map(compute_heat_index)` at line 66) are unchanged — they already reference the functions by name, so once the import resolves the same names, no further edit is needed there.

**Boot-check regression test already exists and must still pass unmodified:** `tests/test_integration.py::test_streamlit_app_boots_cleanly` (lines 107-115) uses `streamlit.testing.v1.AppTest.from_file(...)` — HIDX-03 is verified by re-running this exact existing test, not by writing a new one.

---

### `tests/test_heat_index.py` (test, live-EE skip-gated)

**Analog:** `tests/test_integration.py` (full file, 116 lines)

**Skip-gate header pattern** (lines 1-22, copy verbatim structure, adjust only the module docstring):
```python
"""Live, skip-gated integration tests re-verifying the Phase 1 foundation fixes (D-06/D-07)."""
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
```

**Explicit `init_ee()` call pattern inside each test function** (lines 60-66, `test_load_ward_boundary`):
```python
def test_load_ward_boundary():
    # REWORK-05: exactly 4,841 ward features with the expected properties.
    from heatwave.auth import init_ee
    from heatwave.data.boundary import load_ward_boundary
    init_ee()
    boundary = load_ward_boundary()
    assert boundary.size().getInfo() == 4841
```
Note the in-function `import` style (imports deferred inside each `test_*` function, not at module top) — this is the established convention in `test_integration.py` (every test function does its own local imports of `heatwave.auth.init_ee` plus whatever module it's testing) and should be replicated in `test_heat_index.py`.

**`.getInfo()` extraction requirement** (Pitfall 4, RESEARCH.md): every assertion in the new test must pull a concrete value via `.getInfo()` (or `.reduceRegion(...).getInfo()`), never compare `ee.Image`/`ee.Number` objects directly. `test_load_era5_land` (lines 73-91) demonstrates this: `collection.size().getInfo()`, `collection.first().bandNames().getInfo()`.

**Full recommended test-file content** (source: RESEARCH.md's Code Examples section, already synthesized against this exact analog and the NOAA-table fixture math in D-03/D-04 — use as the concrete starting point for `tests/test_heat_index.py`):
```python
"""Live, skip-gated tests verifying the Rothfusz Heat Index formula against NOAA table values (HIDX-02)."""
from __future__ import annotations

import os
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

pytestmark = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)


def _make_test_image(tmean_k: float, dewpoint_k: float) -> ee.Image:
    from heatwave.config import settings
    return ee.Image.constant([tmean_k, 0, dewpoint_k]).rename(
        [settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint]
    )


def test_heat_index_matches_noaa_table_96_50():
    """T=96F, RH=50% -> NOAA table HI=108F [CITED], approx-matched within regression tolerance."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index

    init_ee()
    image = _make_test_image(tmean_k=308.706, dewpoint_k=298.706)
    result = compute_heat_index(compute_relative_humidity(image))

    hi_value = result.select("heat_index").reduceRegion(
        reducer=ee.Reducer.first(), geometry=ee.Geometry.Point([0, 0]), scale=1000
    ).get("heat_index").getInfo()

    assert hi_value == pytest.approx(108, abs=1.5)


def test_relative_humidity_clamped_above_100():
    """D-01: dewpoint above tmean (T-D negative) must clamp RH to 100, not exceed it."""
    from heatwave.auth import init_ee
    from heatwave.science.heat_index import compute_relative_humidity

    init_ee()
    # T - D = -10 => unclamped RH would be 100 - 5*(-10) = 150
    image = _make_test_image(tmean_k=290.0, dewpoint_k=300.0)
    rh_value = compute_relative_humidity(image).select("relative_humidity").reduceRegion(
        reducer=ee.Reducer.first(), geometry=ee.Geometry.Point([0, 0]), scale=1000
    ).get("relative_humidity").getInfo()

    assert rh_value == 100
```
Additional NOAA fixture pairs available for further `test_heat_index_matches_noaa_table_*` cases (D-03/D-04, cross-checked against 3 independent sources):
| T (°F) | RH (%) | NOAA HI (°F) | tmean_k | dewpoint_k |
|--------|--------|--------------|---------|------------|
| 96 | 50 | 108 | 308.706 | 298.706 |
| 100 | 40 | 109 | 310.928 | 298.928 |
| 90 | 70 | 105 | 305.372 | 299.372 |

Use `pytest.approx(expected, abs=1.5)`, never `==` exact equality (Pitfall 2 — Rothfusz is a curve-fit approximation, hand-verified to differ from table values by ~0.3-1°F).

A low-humidity clamp-boundary counterpart (`T - D` large positive => unclamped RH negative) should mirror `test_relative_humidity_clamped_above_100` with `dewpoint_k` set far below `tmean_k` to drive `100 - 5*(T-D)` below 0, asserting `rh_value == 0`.

---

## Shared Patterns

### Plain-function module style (no classes)
**Source:** `heatwave/data/boundary.py`, `heatwave/data/ingest.py`
**Apply to:** `heatwave/science/heat_index.py`
```python
"""<one-line module docstring>."""
from __future__ import annotations

import ee

from heatwave.config import settings


def <function_name>(...) -> ee.Image:
    """<docstring>."""
    ...
```

### Config/band access via `settings.bands.*`
**Source:** `heatwave/config.py` (lines 21-25, `Bands` dataclass), used in `heatwave/data/ingest.py` line 32 and already in `nigeria_heat_index.py` lines 34-35
**Apply to:** `heatwave/science/heat_index.py` — reference `settings.bands.tmean` / `settings.bands.dewpoint`, unchanged from current inline usage.

### Live-EE skip-gated test pattern
**Source:** `tests/test_integration.py` lines 1-22 (module header) and lines 60-66 (per-test `init_ee()` + local imports)
**Apply to:** `tests/test_heat_index.py` — identical `pytestmark = pytest.mark.skipif(...)` gate, identical `_KEY_FILE`/`_HAS_CREDENTIALS` computation, identical explicit `init_ee()` call inside each test before constructing any `ee.Image`.

### `.getInfo()` before asserting
**Source:** `tests/test_integration.py` lines 66, 87, 89-91, 104
**Apply to:** every assertion in `tests/test_heat_index.py` — never compare `ee.Image`/`ee.Number` graph objects directly (Pitfall 4).

## No Analog Found

None — all 4 files have a strong (exact or role-match) analog in the existing codebase.

## Metadata

**Analog search scope:** `heatwave/data/` (boundary.py, ingest.py, __init__.py), `heatwave/config.py`, `tests/test_integration.py`, `nigeria_heat_index.py` (root)
**Files scanned:** 6 (all read in full; largest was `tests/test_integration.py` at 116 lines — no file exceeded the 2,000-line large-file threshold, single-pass reads used throughout)
**Pattern extraction date:** 2026-09-13
