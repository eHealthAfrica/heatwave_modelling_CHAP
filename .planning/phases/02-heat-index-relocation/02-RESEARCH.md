# Phase 2: Heat Index Relocation - Research

**Researched:** 2026-09-13
**Domain:** Google Earth Engine server-side image math (RH/Heat Index), Python module relocation, pytest-based numeric verification of the NOAA/NWS Rothfusz Heat Index regression
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### RH formula fix (carried from Phase 1 code review WR-01)
- **D-01:** Add `.clamp(0, 100)` to the relative-humidity output (`100 - 5*(T-D)`) as part of the relocation into `heatwave/science/heat_index.py`. This is a deliberate, scoped exception to "relocated not rewritten" — the code is already being touched and tested here, so this is the natural point to fix a known correctness issue rather than deferring it further.
- **D-02:** No other behavioral changes beyond the clamp — the RH approximation formula itself (`100 - 5*(T-D)`), the Rothfusz Heat Index regression coefficients, and all other logic move verbatim.

### Test reference values (HIDX-02)
- **D-03:** Use NOAA/NWS's official published Heat Index reference table values as the ground truth for `tests/test_heat_index.py`'s known input/output assertions — not self-derived values. This avoids the test just re-deriving and checking against the same formula it's meant to validate.
- **D-04:** Test inputs should be expressed as ERA5-Land-realistic values (Kelvin temperature, matching the actual data pipeline) that convert to the Fahrenheit/RH pairs found in the NOAA table, so the test exercises the same unit-conversion path as production code, not an idealized shortcut.

### Claude's Discretion
- Whether `compute_relative_humidity` needs its own direct unit test or is sufficiently covered by the end-to-end Heat Index test (HIDX-02 only mandates testing "the Rothfusz Heat Index formula" — RH test coverage is additive, not required).
- Whether to also clean up the code-review Info-level nits already present in `nigeria_heat_index.py` (unused `Template`/`MacroElement` imports, the misleading `tempC`-holds-Kelvin variable name) while the file is being touched again for HIDX-03 — low-risk, high-value opportunistic cleanup, but not a hard requirement.
- Exact module-level structure of `heatwave/science/heat_index.py` (e.g., whether RH and Heat Index are separate functions or one combined pipeline function) — follow the existing `heatwave/data/` subpackage convention (plain functions, no classes, `from __future__ import annotations`, module docstring).
- Live-EE test pattern for `tests/test_heat_index.py` — since RH/Heat-Index math operates on `ee.Image`/`ee.Number` objects (server-side), tests inherently require an initialized EE session; follow Phase 1's established `pytest.mark.skipif` credential-gating pattern from `tests/test_integration.py` rather than inventing a new one.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

## Summary

This phase is a relocation, not a rewrite: `compute_relative_humidity()` and `compute_heat_index()` move verbatim from `nigeria_heat_index.py` (lines 32-66) into a new `heatwave/science/heat_index.py` module, following the exact plain-function, `from __future__ import annotations`, docstring-header style already established in `heatwave/data/boundary.py` and `heatwave/data/ingest.py`. The one sanctioned behavioral change (D-01) is adding `.clamp(0, 100)` to the RH output before it is renamed/added as a band — `ee.Image.clamp(low, high)` was confirmed directly from the installed `earthengine-api==1.6.8` source (`ee/image.py:1333`) to clamp **all bands of the calling image** to `[low, high]`, so it must be called on the single-band RH image *before* `image.addBands(rh)`, never on the full multi-band image afterward (that would incorrectly clamp `tmax`/`tmean`/`dewpoint` too).

The Rothfusz coefficients already in `nigeria_heat_index.py` (`c1..c9`) match the official NOAA/NWS regression exactly, cross-checked against two independently-sourced NOAA table entries by hand-computing the polynomial. However, the regression is a curve-fit approximation to Steadman's original table (NOAA's own equation page explicitly notes it is "not valid... beyond the range of data considered by Steadman" and applies separate low/high-humidity correction terms outside certain RH bands) — hand-computed values differ from published table entries by roughly 0.3-1°F even for in-range inputs. `tests/test_heat_index.py` must therefore assert closeness (`pytest.approx(expected, abs=1.5)` or similar), not exact equality, against NOAA table values.

Earth Engine's `ee.Image`/`ee.Number` methods (`.select()`, `.expression()`, `.clamp()`) are ApiFunction-bound and require `ee.Initialize()` (`heatwave.auth.init_ee()`) to have populated the algorithm registry before they can be called — confirmed directly from the installed `ee/__init__.py` source. `tests/test_heat_index.py` must call `init_ee()` explicitly (reusing Phase 1's `pytest.mark.skipif` credential-gating pattern from `tests/test_integration.py`) rather than relying on EE's implicit lazy-init fallback, which uses a different (non-service-account) credential path.

**Primary recommendation:** Create `heatwave/science/__init__.py` (empty, matching `heatwave/data/__init__.py`) and `heatwave/science/heat_index.py` containing `compute_relative_humidity()` and `compute_heat_index()` moved verbatim except for the `.clamp(0, 100)` insertion; update `nigeria_heat_index.py` to import both functions instead of defining them inline; write `tests/test_heat_index.py` using the `pytest.mark.skipif`-gated live-EE pattern with NOAA-table-derived Kelvin/dewpoint fixtures and tolerance-based assertions.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HIDX-01 | RH/Heat-Index computation logic is relocated (not rewritten) from `nigeria_heat_index.py` into `heatwave/science/heat_index.py` | Architecture Patterns section gives the exact module structure and verbatim-move content, including the one sanctioned clamp fix; Common Pitfalls flags the clamp-ordering trap that would violate "not rewritten" by corrupting other bands |
| HIDX-02 | `tests/test_heat_index.py` verifies the Rothfusz Heat Index formula against known input/output values | Code Examples + Common Pitfalls give verified NOAA table entries, the Kelvin-fixture conversion math, the required tolerance (not exact equality), and the live-EE `getInfo()`/init requirement |
| HIDX-03 | `nigeria_heat_index.py` imports and uses `heatwave.science.heat_index` instead of inline definitions, and still boots cleanly | Architecture Patterns gives the exact import/call-site diff; Validation Architecture reuses the existing `AppTest`-based boot test pattern from `tests/test_integration.py::test_streamlit_app_boots_cleanly` |

## Architectural Responsibility Map

This project is a data pipeline, not a multi-tier web app — the standard Browser/SSR/API/CDN/DB tiers don't map cleanly. Tiers below are this codebase's closest analogues, per `PROJECT.md`/`STATE.md`.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| RH approximation (`100 - 5*(T-D)`, clamped) | Science/Domain module (`heatwave/science/`) | Earth Engine server (executes the expression graph) | Pure domain math over `ee.Image` bands; belongs beside other `heatwave/` subpackages (`data/`), not inline in the presentation script |
| Rothfusz Heat Index regression | Science/Domain module (`heatwave/science/`) | Earth Engine server | Same as above — deterministic formula, no UI/IO concerns, must be independently testable per HIDX-02 |
| Band/config lookups (`settings.bands.tmean`/`dewpoint`) | Config module (`heatwave/config.py`) | — | Already correctly isolated; RH/HI functions consume it, don't own it |
| Map/legend rendering, date sliders | Presentation (`nigeria_heat_index.py`, Streamlit) | — | Must only *call* the relocated functions after HIDX-03, never contain formula logic |
| Correctness verification (known input/output) | Test tier (`tests/test_heat_index.py`) | — | New per HIDX-02; must exercise the science module directly, not through the Streamlit script |

**Why this matters for planning:** the plan must not let any RH/Heat-Index math linger in or return to `nigeria_heat_index.py` after HIDX-03 — the presentation script's only remaining responsibility for this logic is importing and calling it.

## Standard Stack

No new libraries are introduced by this phase — it is a pure relocation within the existing stack.

### Core (already installed, unchanged)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| earthengine-api | 1.6.8 [VERIFIED: local `.venv` install, `ee.__version__`] | `ee.Image`/`ee.Number` server-side math (`.select()`, `.expression()`, `.clamp()`) | Already the project's sole EE binding; confirmed via direct inspection of `.venv/Lib/site-packages/ee/image.py` |
| pytest | 8.4.1 [VERIFIED: local `.venv` install, `pytest --version`] | Test runner for `tests/test_heat_index.py` | Already used by `tests/test_integration.py`/`tests/test_requirements.py`; no reason to introduce a second framework |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| streamlit.testing.v1.AppTest | bundled with `streamlit==1.49.1` [VERIFIED: `requirements.txt`] | In-process Streamlit boot check | Reused for HIDX-03's "still boots cleanly" re-verification, exactly as Phase 1 did for REWORK-08 |

### Alternatives Considered
No alternatives were evaluated — CONTEXT.md D-01-D-04 and the phase boundary explicitly scope this as a relocation of existing, already-decided logic; there is no library choice to make.

**Installation:** None required — no new packages.

## Package Legitimacy Audit

**Not applicable.** This phase installs no external packages (relocation-only; `earthengine-api`, `pytest`, and `streamlit` are already present and unchanged in `requirements.txt`). The Package Legitimacy Gate is skipped per its own scope ("whenever this phase installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
ERA5-Land ImageCollection (heatwave.data.ingest.load_era5_land)
        |
        |  .map(compute_relative_humidity)   <-- heatwave/science/heat_index.py
        v
ImageCollection + 'relative_humidity' band (clamped [0,100])
        |
        |  .map(compute_heat_index)          <-- heatwave/science/heat_index.py
        v
ImageCollection + 'heat_index' band (deg F)
        |
        v
nigeria_heat_index.py (Streamlit): filters by selected_date, renders via geemap.Map
```

Data enters via `heatwave.data.ingest.load_era5_land()` (Phase 1, unchanged), flows through the two relocated science functions (new in this phase), and only then reaches the presentation layer. After HIDX-03, `nigeria_heat_index.py` must contain zero formula logic on this path — only `.map(compute_relative_humidity)` / `.map(compute_heat_index)` calls and UI code.

### Recommended Project Structure
```
heatwave/
├── science/
│   ├── __init__.py       # empty, matches heatwave/data/__init__.py
│   └── heat_index.py     # compute_relative_humidity(), compute_heat_index()
tests/
└── test_heat_index.py    # new, HIDX-02
```

### Pattern 1: Plain-function science module (match `heatwave/data/` style)
**What:** Module docstring + `from __future__ import annotations` + `import ee` + `from heatwave.config import settings` + top-level functions, no classes.
**When to use:** Always, for this codebase's `heatwave/` subpackages — `heatwave/data/boundary.py` and `heatwave/data/ingest.py` are the canonical examples this phase must match.
**Example:**
```python
# Source: heatwave/data/boundary.py (existing codebase convention)
"""Ward (admin-3) boundary asset access."""
from __future__ import annotations

import ee

from heatwave.config import settings


def load_ward_boundary() -> ee.FeatureCollection:
    """Return the nationwide ward boundary FeatureCollection configured in config.yaml."""
    return ee.FeatureCollection(settings.ward_asset_id)
```

### Pattern 2: RH clamp must be applied to the single-band expression result, before `addBands`
**What:** `ee.Image.clamp(low, high)` — confirmed via `help(ee.Image.clamp)` against the installed `earthengine-api==1.6.8` — "Clamps the values in **all bands** of an image to lie within the specified range." [VERIFIED: local package inspection, `.venv/Lib/site-packages/ee/image.py:1333`]
**When to use:** Call `.clamp(0, 100)` on the `rh` single-band expression image, before `.rename()`/`addBands()` — never on `image` (the multi-band `tmax`/`tmean`/`dewpoint`/... composite) or you will silently clamp unrelated bands to `[0, 100]`, corrupting Kelvin temperature data.
**Example:**
```python
# Source: relocation target for heatwave/science/heat_index.py, per D-01/WR-01
def compute_relative_humidity(image: ee.Image) -> ee.Image:
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)

    rh = (
        image.expression('100 - 5 * (T - D)', {'T': T, 'D': D})
        .clamp(0, 100)              # <-- D-01 fix: applied here, single-band, pre-addBands
        .rename('relative_humidity')
    )
    return image.addBands(rh)
```

### Pattern 3: Heat Index regression, verbatim
**What:** Move `compute_heat_index()` unchanged (D-02 — no formula changes). Only the module location, and optionally the `tempC` → `tempK` rename (IN-01) and dropping the dead `.set('system:time_start', ...)` call (IN-03), change.
**Example:**
```python
# Source: nigeria_heat_index.py lines 47-64, relocated verbatim (rename tempC->tempK optional per discretion)
def compute_heat_index(image: ee.Image) -> ee.Image:
    tempK = image.select(settings.bands.tmean)
    tempF = tempK.subtract(273.15).multiply(9 / 5).add(32)
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

    return image.addBands(HI)   # dropped dead .set('system:time_start', ...) call, see IN-03
```

### Pattern 4: `nigeria_heat_index.py` after HIDX-03
```python
# Source: relocation call-site update
from heatwave.science.heat_index import compute_relative_humidity, compute_heat_index
...
relativeHumidity = era5_land.map(compute_relative_humidity)
heatIndex = relativeHumidity.map(compute_heat_index)
```
The two `def compute_relative_humidity(...)` / `def compute_heat_index(...)` blocks (lines 32-66) are deleted from `nigeria_heat_index.py` entirely.

### Anti-Patterns to Avoid
- **Clamping the full multi-band image:** `image.clamp(0, 100)` after `addBands` would clamp `tmax`/`tmean`/`dewpoint` (Kelvin, ~250-320) down to 100, corrupting the data. Always clamp the isolated single-band `rh` expression result.
- **Changing the RH or Rothfusz formula "while you're in there":** D-02 explicitly forbids this — resist fixing the `T-D` linear-approximation's known accuracy limits or "improving" the regression; that's out of scope for this phase.
- **Relying on EE's implicit lazy `Initialize()`** in tests instead of calling `heatwave.auth.init_ee()` explicitly — see Common Pitfalls.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Clamping a raster/image band to a numeric range | A manual `min()`/`max()` expression or `.where()` conditional chain | `ee.Image.clamp(low, high)` | Single built-in call, confirmed to operate correctly across all bands of the image it's called on; avoids off-by-one/edge-case bugs in a hand-written min/max expression |
| Verifying a published numeric formula | Deriving your own "expected" values from the same formula under test | NOAA/NWS's independently published Heat Index table | A test that re-derives its own oracle from the formula it's validating cannot catch a coefficient transcription error; D-03 exists for exactly this reason |

**Key insight:** This phase's entire scope is about *not* hand-rolling anything new — even the one behavioral change (clamping) is satisfied by an existing one-line EE built-in, not custom logic.

## Common Pitfalls

### Pitfall 1: Clamping after `addBands` instead of before
**What goes wrong:** `.clamp(0, 100)` applied to the full multi-band image (post-`addBands`) silently truncates `tmax`/`tmean`/`dewpoint` (Kelvin values, ~250-320) down to 100, destroying the source temperature data used by `compute_heat_index()` downstream.
**Why it happens:** `ee.Image.clamp()` clamps *all* bands of its calling image — easy to call it in the wrong place when refactoring line-by-line.
**How to avoid:** Clamp only the standalone `rh` expression-result image, before it is renamed/added as a band (see Pattern 2).
**Warning signs:** Heat Index outputs of exactly 100 everywhere, or `tempF` computations that look wildly wrong for a subset of pixels.

### Pitfall 2: Asserting exact equality against NOAA table values
**What goes wrong:** A test asserting `heat_index.getInfo() == 108` (exact) will be flaky/wrong, because the Rothfusz regression is a curve-fit approximation to Steadman's original table, not an exact reproduction of it.
**Why it happens:** NOAA's own equation documentation states the regression is "not valid... beyond the range of data considered by Steadman" and applies separate correction terms for RH < 13% or RH > 85% — even within the "normal" range, hand-computing the polynomial against published table entries shows ~0.3-1°F differences (verified below).
**How to avoid:** Use `pytest.approx(expected, abs=1.5)` (or similar tolerance) when comparing computed Heat Index against NOAA table values, not `==`.
**Warning signs:** A "known good" fixture value fails by a fraction of a degree with no code changes — verify by hand-computing the polynomial before assuming the code is wrong.

### Pitfall 3: Relying on EE's implicit lazy-`Initialize()` instead of explicit `init_ee()`
**What goes wrong:** Per `ee/__init__.py`'s own docstring: *"If this hasn't been called by the time any object constructor is used, it will be called then"* — i.e., calling `ee.Image(...)`/`.expression()`/`.clamp()` without first calling `ee.Initialize()` triggers an **implicit default initialization** using persistent/default credentials, not the project's service-account credential chain (`heatwave.auth.init_ee()`).
**Why it happens:** EE is designed to "just work" for interactive/notebook use, which is convenient but means a test that forgets to call `init_ee()` may still "succeed" against the wrong GCP project/credentials, or fail with a confusing auth error instead of a clear one.
**How to avoid:** `tests/test_heat_index.py` must call `heatwave.auth.init_ee()` explicitly at the top of each test (or module-level, matching `tests/test_integration.py`'s pattern) before constructing any `ee.Image`.
**Warning signs:** Tests pass locally (persistent user credentials cached) but fail identically-configured in CI (no persistent credentials, only `EE_SA_JSON`).

### Pitfall 4: Comparing an `ee.Number`/`ee.Image` object directly instead of calling `.getInfo()`
**What goes wrong:** `assert heat_index_image.select('heat_index') == 108` always evaluates to a Python object-identity/graph comparison, never the numeric server-side result, and will not fail the way you expect.
**Why it happens:** EE's Python objects are lazy graph nodes; no computation happens until `.getInfo()` (or a reducer) is called.
**How to avoid:** Always call `.getInfo()` (or `.reduceRegion(...).getInfo()` for image-level results) to pull the concrete number before asserting.
**Warning signs:** A test "passes" trivially regardless of the formula's correctness, or raises a `TypeError`/comparison error instead of a numeric assertion failure.

### Pitfall 5: Renaming `tempC` to `tempK` (IN-01 cleanup) accidentally changing the math
**What goes wrong:** If cleaning up the misleading `tempC` variable name (Claude's discretion), a well-intentioned "fix" might also insert an *extra* Kelvin-to-Celsius conversion, double-converting and breaking the formula.
**Why it happens:** The reviewer's IN-01 finding is a naming-clarity issue only — `tempC.subtract(273.15).multiply(9/5).add(32)` is already numerically correct (K→C→F in one line); only the variable name is misleading.
**How to avoid:** If renaming, change only the identifier (`tempC` → `tempK`), touch zero arithmetic.
**Warning signs:** Heat Index values shift after a "no-op" cleanup commit — regression-test this rename with the same fixture values used for HIDX-02.

## Code Examples

### Verified Rothfusz coefficient cross-check (hand-computed against NOAA table)
Computed by hand using the exact coefficients present in `nigeria_heat_index.py` (matches [CITED: wpc.ncep.noaa.gov/html/heatindex_equation.shtml] exactly):

| T (°F) | RH (%) | NOAA table HI (°F) [CITED] | Hand-computed Rothfusz HI (°F) | Diff |
|--------|--------|------------------------------|----------------------------------|------|
| 96 | 50 | 108 [CITED: weather.gov/arx/heat_index] | 107.64 | 0.36 |
| 100 | 40 | 109 [CITED: noaa.gov/jetstream/synoptic/heat-index] | 109.26 | 0.26 |
| 90 | 70 | 105 [CITED: en.wikipedia.org/wiki/Heat_index, NWS table reproduction] | 105.92 | 0.92 |

All three confirm the code's coefficients are the correct, unmodified NOAA/NWS Rothfusz regression — no coefficient transcription errors — and demonstrate why `tests/test_heat_index.py` needs a tolerance (~1-1.5°F), not exact equality.

### Kelvin test-fixture derivation (D-04: ERA5-Land-realistic units)
Because `T - D` is unit-offset-invariant (the 273.15 K↔°C offset cancels in the subtraction — see IN-01), a target RH is reached by picking any Kelvin `tmean` and setting `dewpoint = tmean - (100 - target_RH) / 5`. Fahrenheit-to-Kelvin for `tmean`: `K = (F - 32) * 5/9 + 273.15`.

```python
# Source: derived for tests/test_heat_index.py fixtures, using NOAA table entries above
# T=96F, RH=50% -> HI=108F [CITED: weather.gov/arx/heat_index]
tmean_k = (96 - 32) * 5 / 9 + 273.15       # 308.706 K
dewpoint_k = tmean_k - (100 - 50) / 5       # 298.706 K  (T - D = 10 => RH = 100 - 5*10 = 50)

# T=100F, RH=40% -> HI=109F [CITED: noaa.gov/jetstream/synoptic/heat-index]
tmean_k = (100 - 32) * 5 / 9 + 273.15      # 310.928 K
dewpoint_k = tmean_k - (100 - 40) / 5       # 298.928 K  (T - D = 12 => RH = 40)

# T=90F, RH=70% -> HI=105F [CITED: Wikipedia NWS table reproduction]
tmean_k = (90 - 32) * 5 / 9 + 273.15       # 305.372 K
dewpoint_k = tmean_k - (100 - 70) / 5       # 299.372 K  (T - D = 6 => RH = 70)
```

### Recommended test pattern (skip-gated, live EE, tolerance-based)
```python
# Source: pattern reused from tests/test_integration.py (Phase 1, D-06/D-07)
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
Note: `ee.Image.constant([...])` + `reduceRegion(..., ee.Geometry.Point(...))` is a standard EE pattern for extracting a scalar from a constant test image; adjust reducer/geometry/scale as needed but keep the `getInfo()` call (Pitfall 4).

## State of the Art

No state-of-the-art shift applies here — the Rothfusz regression (1990) and its coefficients are unchanged, stable, and not subject to "current vs. deprecated" API churn. The only "current approach" question is Earth Engine's own API surface, and `ee.Image.clamp()` is a long-stable core method, not a recent addition.

**Deprecated/outdated:** None identified for this phase's scope.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The three NOAA table entries (96°F/50%→108°F, 100°F/40%→109°F, 90°F/70%→105°F) are accurately extracted from their cited sources (WebSearch/WebFetch summaries of noaa.gov, weather.gov, and Wikipedia's NWS-table reproduction, not the primary table image itself, which is a PDF/PNG not machine-readable) | Code Examples, Common Pitfalls | If a cited value is slightly off, the test tolerance (±1.5°F) likely absorbs it, but the planner/test-author should re-confirm at least one value against the primary NOAA chart image before locking it into `tests/test_heat_index.py` as a hard fixture |
| A2 | No stated NOAA accuracy tolerance (e.g., "±1.3°F") could be found for the Rothfusz regression vs. Steadman's table in the specific NOAA/NWS pages checked; the ~0.3-1°F tolerance recommendation here is derived from this session's own hand-computation against 3 table entries, not from an official NOAA accuracy statement | Common Pitfalls (Pitfall 2), Code Examples | If the true worst-case error is larger than 1.5°F for some input combination, a chosen test fixture could still fail intermittently near threshold; recommend using the exact table values verified here (well within tolerance) rather than picking new untested ones |

## Open Questions (RESOLVED)

1. **Should `compute_relative_humidity` get its own direct unit test, or only be exercised indirectly through the Heat Index test?**
   - What we know: HIDX-02 only mandates testing "the Rothfusz Heat Index formula"; CONTEXT.md leaves RH test coverage to Claude's discretion.
   - What's unclear: Whether the planner wants a dedicated `test_relative_humidity_clamped_above_100`/`test_relative_humidity_clamped_below_0` pair (recommended above, since D-01's clamp fix is otherwise untested) or considers indirect coverage sufficient.
   - Recommendation: Include at least the two clamp-boundary tests directly (Code Examples above) — they test the *only* behavioral change this phase makes (D-01), so skipping direct coverage would leave the phase's one new bit of logic unverified.
   - RESOLVED: `02-01-PLAN.md` Task 1 implements this recommendation verbatim — `test_relative_humidity_clamped_above_100`, `test_relative_humidity_clamped_below_0`, and `test_source_bands_not_clamped` are all included as direct tests.

2. **Exact geometry/reducer boilerplate for extracting a scalar from a constant test image**
   - What we know: `ee.Image.constant([...]).rename([...])` + `.reduceRegion(ee.Reducer.first(), ee.Geometry.Point(...), scale=...)` is a standard, working EE pattern (used illustratively above) for pulling one number out of a synthetic image.
   - What's unclear: Whether the planner prefers this over `ee.Number` arithmetic directly (bypassing `ee.Image` entirely) for a simpler/faster test, since `compute_relative_humidity`/`compute_heat_index` are written against `ee.Image`, not `ee.Number`.
   - Recommendation: Keep tests against `ee.Image` (as shown) since that's the actual signature the production functions expect from `.map()`; do not rewrite the functions to accept `ee.Number` just to simplify testing.
   - RESOLVED: `02-01-PLAN.md` Task 1's `_make_test_image`/`_band_value` helpers keep tests against `ee.Image`, exactly as recommended.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All phase code | ✓ | 3.12.10 (`.venv`) | — |
| earthengine-api | `heatwave/science/heat_index.py` | ✓ | 1.6.8 | — |
| pytest | `tests/test_heat_index.py` | ✓ | 8.4.1 | — |
| Live GCP credentials (`keys/service_account.json`) | Live-EE tests in `tests/test_heat_index.py` | ✓ (present locally) | — | `pytest.mark.skipif` gate skips cleanly if absent (e.g., in CI without `EE_SA_JSON`) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None currently missing — credentials are present in this environment, and the skip-gate is the documented fallback for environments where they are not.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 [VERIFIED: local `.venv`] |
| Config file | none — no `pytest.ini`/`[tool.pytest.ini_options]` in `pyproject.toml`; discovery relies on default `test_*.py` naming |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_heat_index.py -v` |
| Full suite command | `.venv/Scripts/python -m pytest -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HIDX-01 | `heatwave/science/heat_index.py` exists and exports `compute_relative_humidity`/`compute_heat_index` with unchanged signatures | unit (import-level) | `pytest tests/test_heat_index.py -k import -x` | ❌ Wave 0 |
| HIDX-02 | Rothfusz formula matches NOAA table values within tolerance; RH clamps to [0,100] | live-EE, skip-gated | `pytest tests/test_heat_index.py -v` | ❌ Wave 0 |
| HIDX-03 | `nigeria_heat_index.py` imports from `heatwave.science.heat_index`, no inline defs remain, app still boots | smoke (AppTest, in-process) | `pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -v` | ✅ (existing, re-run as regression) |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python -m pytest tests/test_heat_index.py -v`
- **Per wave merge:** `.venv/Scripts/python -m pytest -v` (full suite, includes live-EE `test_integration.py` boot check)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_heat_index.py` — new file, covers HIDX-02 (and optionally direct RH-clamp coverage per Open Question 1)
- [ ] `heatwave/science/__init__.py` — new empty package file, required for `heatwave/science/heat_index.py` to be importable
- [ ] Framework install: none — pytest already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Unchanged — credential handling stays in `heatwave/auth.py`, not touched by this phase |
| V3 Session Management | No | No session concept in this pipeline |
| V4 Access Control | No | No new access boundaries introduced |
| V5 Input Validation | Yes (narrow) | The RH clamp (D-01) *is* an input-validation control on a numeric range — `ee.Image.clamp(0, 100)`, a built-in, not hand-rolled |
| V6 Cryptography | No | No cryptographic operations in this phase |

### Known Threat Patterns for this stack
No injection/auth/crypto threat surface applies — this phase only relocates deterministic numeric formulas operating on already-ingested raster data (no user-supplied input reaches this code path). The one relevant "threat" is a data-quality one (physically invalid RH values silently corrupting downstream Heat Index output), which D-01's clamp directly addresses.

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unbounded RH feeding invalid values into a downstream regression | Tampering (data integrity, not adversarial) | `ee.Image.clamp(0, 100)` on the RH band before use (D-01) |

## Sources

### Primary (HIGH confidence)
- Local `earthengine-api==1.6.8` package source, `.venv/Lib/site-packages/ee/image.py:1333` (`Image.clamp` signature/docstring) and `ee/__init__.py:164-215` (`Initialize()` docstring re: implicit lazy-init and `ApiFunction.initialize()`) — inspected directly via `help()` and source read, equivalent to official API reference for the exact installed version
- `nigeria_heat_index.py` (current repo state) — source of the exact formula/coefficients being relocated
- `heatwave/data/boundary.py`, `heatwave/data/ingest.py`, `heatwave/data/__init__.py`, `heatwave/config.py` — existing codebase conventions replicated
- `tests/test_integration.py` — existing `pytest.mark.skipif` credential-gating pattern reused
- `.planning/phases/01-foundation-rework/01-REVIEW.md` — WR-01 (RH clamp fix rationale), IN-01/IN-02/IN-03 (optional cleanup nits)

### Secondary (MEDIUM confidence)
- [The Heat Index Equation, NOAA/NCEP WPC](https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml) — Rothfusz coefficients and low/high-humidity adjustment formulas, cross-checked against the code's `c1..c9` (exact match)
- [Heat Index, NOAA Jetstream](https://www.noaa.gov/jetstream/synoptic/heat-index) — 100°F/40%RH → 109°F worked example
- [Heat Index, NWS Milwaukee/Sullivan (weather.gov/arx)](https://www.weather.gov/arx/heat_index) — 96°F/50%RH → 108°F worked example
- [Heat index, Wikipedia](https://en.wikipedia.org/wiki/Heat_index) — reproduces the NWS table in full; 90°F/70%RH → 105°F row used, article states the table is sourced from NOAA/NWS

### Tertiary (LOW confidence)
- None used as load-bearing claims; all WebSearch findings above were cross-verified either against the installed EE package source or by independent hand-computation of the Rothfusz polynomial.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies; existing versions confirmed via direct local inspection
- Architecture: HIGH - directly matches existing, reviewed codebase conventions (`heatwave/data/*`) and the locked D-01-D-04 decisions
- Pitfalls: HIGH - clamp behavior and EE lazy-init behavior confirmed from installed package source, not just training knowledge; NOAA table tolerance finding independently derived and cross-checked against 3 sources

**Research date:** 2026-09-13
**Valid until:** Formula/coefficients are stable indefinitely (1990 NWS standard, no version churn expected); re-verify only if `earthengine-api` is upgraded past 1.6.8 (30-90 day informal revalidation window for the EE API surface, no fixed deprecation schedule known).
