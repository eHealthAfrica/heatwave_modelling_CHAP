# Phase 1: Foundation Rework - Pattern Map

**Mapped:** 2026-09-11
**Files analyzed:** 6 (5 modified, 1 new)
**Analogs found:** 6 / 6 (all analogs are in-repo sibling files — this is a small, self-contained package; no cross-project pattern borrowing needed)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `heatwave/data/ingest.py` | service (data-access) | CRUD (read/transform, single external query) | `heatwave/data/boundary.py` (same dir, same role) + itself pre-refactor (`_select_band` in current `ingest.py`) | exact (self-refactor, sibling module for style) |
| `heatwave/auth.py` | service (credential/client init) | request-response (init-once, side-effecting) | `heatwave/config.py` (path-anchoring pattern) | role-match for path pattern; auth.py itself is the file being fixed in place |
| `heatwave/__init__.py` | config/bootstrap (package init) | event-driven (runs once at import time) | `heatwave/auth.py`'s current inline stub block (being relocated, not a different file's pattern) | exact (moving existing code, not inventing new style) |
| `nigeria_heat_index.py` | controller/script (Streamlit entrypoint) | request-response (script re-run per Streamlit interaction) | itself, pre-fix (existing structure retained; only join/caching/import-order change) | exact (in-place fix, not modeled on a different file) |
| `requirements.txt` | config | batch (static dependency list) | itself (single-line deletion) | exact |
| `tests/test_integration.py` | test | request-response / batch (live integration checks) | none exists yet in repo — no prior test file to copy from | no analog (new pattern introduced this phase; RESEARCH.md Code Examples are the reference) |

## Pattern Assignments

### `heatwave/data/ingest.py` (service, CRUD/transform)

**Analog:** `heatwave/data/boundary.py` (sibling module, same package, same import/docstring conventions) and the current `ingest.py` itself (structure to be collapsed, not replaced).

**Current file in full** (`heatwave/data/ingest.py`, lines 1-48) — this is what gets restructured:
```python
"""ERA5-Land ingestion: select configured bands, filter by date, clip to the ward boundary.
...
"""
from __future__ import annotations

from dataclasses import dataclass

import ee

from heatwave.config import settings


@dataclass(frozen=True)
class Era5LandBands:
    tmax: ee.ImageCollection
    tmean: ee.ImageCollection
    dewpoint: ee.ImageCollection


def _select_band(band_name: str, start_date: str, end_date: str, boundary: ee.FeatureCollection) -> ee.ImageCollection:
    return (
        ee.ImageCollection(settings.era5_land_collection)
        .select(band_name)
        .filter(ee.Filter.date(start_date, end_date))
        .map(lambda image: image.clip(boundary))
    )


def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Era5LandBands:
    """Return the tmax/tmean/dewpoint ImageCollections, date-filtered and clipped to boundary."""
    start_date = start_date or settings.start_date
    end_date = end_date or settings.end_date

    return Era5LandBands(
        tmax=_select_band(settings.bands.tmax, start_date, end_date, boundary),
        tmean=_select_band(settings.bands.tmean, start_date, end_date, boundary),
        dewpoint=_select_band(settings.bands.dewpoint, start_date, end_date, boundary),
    )
```

**Sibling-module conventions to preserve** (`heatwave/data/boundary.py`, lines 1-11 — full file):
```python
"""Ward (admin-3) boundary asset access."""
from __future__ import annotations

import ee

from heatwave.config import settings


def load_ward_boundary() -> ee.FeatureCollection:
    """Return the nationwide ward boundary FeatureCollection configured in config.yaml."""
    return ee.FeatureCollection(settings.ward_asset_id)
```
Note the conventions to keep: `from __future__ import annotations` first line, single-quoted module docstring, flat `import ee` + `from heatwave.config import settings`, a one-line function docstring describing the return shape.

**Target pattern to implement** (per RESEARCH.md Pattern 1, verified against installed `earthengine-api==1.6.8`):
```python
def load_era5_land(
    boundary: ee.FeatureCollection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> ee.ImageCollection:
    """Return one ImageCollection with tmax/tmean/dewpoint as bands of the same image."""
    start_date = start_date or settings.start_date
    end_date = end_date or settings.end_date

    return (
        ee.ImageCollection(settings.era5_land_collection)
        .select([settings.bands.tmax, settings.bands.tmean, settings.bands.dewpoint])
        .filter(ee.Filter.date(start_date, end_date))
        .map(lambda image: image.clip(boundary))
    )
```
- Drop the `Era5LandBands` dataclass and the `_select_band` helper entirely (RESEARCH.md Open Question 1 recommends a bare `ee.ImageCollection` return — simplest, matches what the value actually is).
- Keep reading `settings.bands.tmax/tmean/dewpoint` and `settings.era5_land_collection` unchanged (CONTEXT.md "Reusable Assets").
- Document the exact band names available on the returned collection directly in the docstring (per RESEARCH.md recommendation) since there's no longer a 3-field dataclass to self-document the shape — this docstring is also what the Phase 2 planner will read when relocating heat-index math.

**Error handling:** none needed/added — matches `boundary.py`'s style of no try/except (EE errors propagate as-is; this is a data-access layer, not a user-facing boundary).

**Downstream call-site pattern to update** (`nigeria_heat_index.py`, lines 24-40 currently — see below).

---

### `heatwave/auth.py` (service, request-response/init-once)

**Analog for path-anchoring:** `heatwave/config.py`, line 9:
```python
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
```
This is the exact pattern to replicate for the key file constant. `config.py` anchors from `heatwave/config.py` → `.parent` (heatwave/) → `.parent` (repo root) → `/ "config.yaml"`. `auth.py` lives at the same depth (`heatwave/auth.py`), so the identical `.parent.parent` chain lands at repo root, then appends `keys/service_account.json`.

**Current `auth.py` blocks to change** (already read in full above, lines 1-67):
- Line 25: `_LOCAL_KEY_FILE = "keys/service_account.json"` → becomes path-anchored:
  ```python
  from pathlib import Path
  ...
  _LOCAL_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
  ```
- Line 53-55: `from_service_account_file(_LOCAL_KEY_FILE, ...)` → must cast to `str()` per RESEARCH.md Pattern 3 (verified against `google-auth==2.40.3`'s typed `filename: str` signature):
  ```python
  return service_account.Credentials.from_service_account_file(
      str(_LOCAL_KEY_FILE), scopes=EE_SCOPES
  )
  ```
- Lines 16-17 (`import sys`, `import types`) and line 27-29 (the `blessings` stub comment + `sys.modules.setdefault(...)` line) → **delete from `auth.py` entirely**; this logic moves to `heatwave/__init__.py` (see below). `auth.py` keeps its other imports (`json`, `os`, `ee`, `google.oauth2.service_account`, `heatwave.config.settings`) unchanged.
- **Do NOT change:** the credential resolution order (Streamlit secrets → `EE_SA_JSON` → local file, lines 32-55) — CONTEXT.md D-04 explicitly says this stays correct as-is. Do NOT add `@st.cache_resource` here — D-04 keeps this file Streamlit-free at module scope (it already only imports `streamlit` defensively inside a `try/except` inside `_load_credentials`, per lines 33-39 — preserve that defensive-import pattern exactly).

**Core init-once pattern (unchanged, keep as-is):**
```python
def init_ee() -> None:
    """Authenticate and initialize the Earth Engine client. Idempotent."""
    credentials = _load_credentials()
    ee.Initialize(credentials, project=settings.gcp_project_id)
```

---

### `heatwave/__init__.py` (bootstrap, event-driven at import time)

**Current state:** file exists but is completely empty (0 bytes).

**Analog:** the block being relocated *out of* `heatwave/auth.py` (lines 16-17, 27-29 currently) — this is a move, not a new pattern:
```python
"""heatwave package. Stubs out `blessings` before any submodule (or geemap) can import it."""
import sys
import types

sys.modules.setdefault("blessings", types.ModuleType("blessings"))
```
Per RESEARCH.md Pattern 4 / Pitfall 4: this only closes the import-order gap if callers import something from `heatwave` (or bare `import heatwave`) before `import geemap.foliumap`. This is why `nigeria_heat_index.py`'s import order must also change (below) — the two files' fixes are coupled.

---

### `nigeria_heat_index.py` (controller/script, request-response)

**Analog:** itself — in-place fix only, three coupled changes to the existing structure (no external file's pattern to copy).

**Current import block** (lines 1-9, full current state):
```python
import streamlit as st
import ee
import geemap.foliumap as geemap  # Folium backend for Streamlit
from branca.element import Template, MacroElement

from heatwave.auth import init_ee
from heatwave.config import settings
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
```
**Fix 1 (Pitfall 4 — import order):** move a `heatwave` import above `geemap.foliumap` so the relocated blessings stub (now in `heatwave/__init__.py`) actually executes first:
```python
import streamlit as st
import ee

from heatwave.auth import init_ee  # heatwave import first: triggers blessings stub
                                     # in heatwave/__init__.py before geemap loads

import geemap.foliumap as geemap  # Folium backend for Streamlit
from branca.element import Template, MacroElement

from heatwave.config import settings
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
```

**Fix 2 (D-04/D-05 — caching wrapper).** Current line 12: `init_ee()` called bare at module scope. Replace with the RESEARCH.md Pattern 2 wrapper (verified against `streamlit==1.49.1`):
```python
@st.cache_resource
def _cached_init_ee() -> None:
    init_ee()

_cached_init_ee()
```

**Fix 3 (D-01/D-02 — eliminate the join).** Current lines 24-40:
```python
era5_land = load_era5_land(boundary, startDate, endDate)
era5_2mt = era5_land.tmean
era5_2d = era5_land.dewpoint

# Compute Relative Humidity
def compute_relative_humidity(tempImage):
    tempDate = tempImage.date()
    dewpointImage = era5_2d.filterDate(tempDate, tempDate.advance(1, 'day')).first()

    rh = ee.Image(dewpointImage).expression(
        '100 - 5 * (T - D)',
        {'T': tempImage, 'D': ee.Image(dewpointImage)}
    ).rename('relative_humidity')

    return tempImage.addBands(rh.set('system:time_start', tempImage.get('system:time_start')))

relativeHumidity = era5_2mt.map(compute_relative_humidity)
```
Replace with (RESEARCH.md Pattern 1 downstream example — no filterDate/.first() join, both bands read from the same `image` argument):
```python
era5_land = load_era5_land(boundary, startDate, endDate)  # single multi-band collection

# Compute Relative Humidity
def compute_relative_humidity(image):
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)
    rh = image.expression(
        '100 - 5 * (T - D)', {'T': T, 'D': D}
    ).rename('relative_humidity')
    return image.addBands(rh)

relativeHumidity = era5_land.map(compute_relative_humidity)
```
Note per RESEARCH.md Pitfall 3: reference `settings.bands.dewpoint` explicitly (it doesn't appear as a literal anywhere in the current file — grep confirms `settings.bands.tmean` is the only `settings.bands.*` reference at line 44) — do not hardcode the raw ERA5-Land band-name string.

**Unchanged (do not touch):** `compute_heat_index()` (lines 43-60, Rothfusz regression math — Phase 2 relocates this, not Phase 1), the Streamlit UI/slider/map/legend block (lines 64-128).

---

### `requirements.txt` (config, batch)

**Change:** delete line 19 (`ee==0.2`) only. No analog needed — single-line removal, verified as a namespace-colliding decoy package unrelated to `earthengine-api` (RESEARCH.md Package Legitimacy Audit). All other lines unchanged, including `earthengine-api==1.6.8` (line 18) and `blessings==1.7` (line 5, kept — CONTEXT.md discretion says keep the stub as cheap insurance even though this environment's `blessings` import chain was traced to the decoy package's orphaned `main.py`, not to `geemap`/`earthengine-api` themselves).

---

### `tests/test_integration.py` (test, request-response/batch — NEW FILE)

**No existing analog** — `tests/` does not exist yet in this repo (confirmed: `find . -maxdepth 2 -iname "*test*"` returns nothing, no `tests/` directory, no other `test_*.py` file anywhere in the tree). This is the one file in this phase with zero in-repo precedent to copy structure from.

**Confirmed pytest config gap** (re-verified directly): `pyproject.toml` (4 lines of `[project]` + `[tool.setuptools.packages.find]` + `[build-system]`, full contents read) has **no `[tool.pytest.ini_options]` section** and there is no separate `pytest.ini`/`setup.cfg` in the repo root. Default rootdir-based test discovery will work once `tests/test_integration.py` exists (pytest discovers `test_*.py` from the invocation directory with no config needed), but there is nothing to inherit from — the executor should not assume any `testpaths`, markers registration, or fixture config already exists.

**Reference pattern (from RESEARCH.md, not from codebase — use directly, verified against installed versions):**

Skip-condition (module-level, cheap/side-effect-free per Pitfall 5):
```python
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
Confirmed locally present: `keys/service_account.json` exists in this working directory (verified via `ls keys`), so tests will execute live (not skip) in this environment, satisfying D-06/D-07's "must actually execute when credentials are present."

**Path-anchoring note:** this test's own `_KEY_FILE` constant reuses the same `Path(__file__).resolve().parent.parent / ...` idiom as `config.py`/`auth.py` — one more instance of the shared pattern (see Shared Patterns below), just anchored from `tests/` instead of `heatwave/`.

Boot-check pattern (REWORK-08, `AppTest` approach recommended as primary):
```python
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_streamlit_app_boots_cleanly():
    script = Path(__file__).resolve().parent.parent / "nigeria_heat_index.py"
    at = AppTest.from_file(str(script), default_timeout=60)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"
```
Caveat (RESEARCH.md Assumption A2): confirm during implementation that `AppTest` tolerates `geemap.foliumap`'s `Map.to_streamlit()` custom HTML component without raising; fall back to the subprocess+HTTP approach (RESEARCH.md Code Examples Approach B) if it errors.

**Test-to-requirement map to implement** (from RESEARCH.md Validation Architecture table — all live against `heatwave-508110`, none mocked, per D-06):
| Test name | Requirement |
|---|---|
| `test_init_ee_idempotent` | REWORK-01 |
| `test_era5_land_bands_aligned` | REWORK-02 |
| `test_auth_resolves_from_any_cwd` | REWORK-04 |
| `test_load_ward_boundary` | REWORK-05 (asserts 4,841 features + property shape) |
| `test_load_era5_land` | REWORK-06 (asserts bands present, date-filtered, clipped) |
| `test_settings_loaded` | REWORK-07 |
| `test_streamlit_app_boots_cleanly` | REWORK-08 |

REWORK-03 (`ee==0.2` removal) is a static check, not a live test — can live in the same file as a credential-independent assertion (e.g. reading `requirements.txt` and asserting no `^ee==` line), or the executor may choose to verify it manually; either is consistent with CONTEXT.md's "planner/executor discretion" on exact test structure.

## Shared Patterns

### Path-anchored resource resolution
**Source:** `heatwave/config.py` line 9 — `Path(__file__).resolve().parent.parent / "config.yaml"`
**Apply to:**
- `heatwave/auth.py` — `_LOCAL_KEY_FILE` constant (REWORK-04)
- `tests/test_integration.py` — `_KEY_FILE` constant for the skip condition, and the `nigeria_heat_index.py` script path in the boot-check test
```python
_ANCHOR = Path(__file__).resolve().parent.parent / "<relative-path-from-repo-root>"
```
This is the single most load-bearing shared pattern in this phase — three separate files independently need "resolve a repo-root-relative path regardless of process CWD," and the codebase already has one correct, established implementation to copy verbatim.

### Defensive/optional Streamlit import
**Source:** `heatwave/auth.py` lines 33-39 (`_load_credentials`):
```python
try:
    import streamlit as st
    has_earthengine_secret = "earthengine" in st.secrets
except Exception:
    has_earthengine_secret = False
```
**Apply to:** nothing new needs this exact pattern this phase, but it is the reason `auth.py` stays cache-decorator-free (D-04) — preserve it unchanged as evidence/enforcement of that boundary; the planner/executor should not "clean this up" into a top-level `import streamlit` during the auth.py edit.

### Single-source-collection band selection (replaces per-image join)
**Source:** RESEARCH.md Pattern 1 (no in-repo precedent — this is the new idiom this phase introduces)
**Apply to:** `heatwave/data/ingest.py` (the collection itself) and `nigeria_heat_index.py` (the downstream `.map()` callback that consumes it) — both files change together because the return shape change in `ingest.py` directly drives the callback rewrite in `nigeria_heat_index.py`. These two files must be edited as a single logical unit / cannot be split across plans without breaking the intermediate state.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/test_integration.py` | test | request-response/batch | No `tests/` directory or any test file exists anywhere in the repo yet (verified via filesystem search); planner must use RESEARCH.md's Code Examples section (skip-condition snippet + both `AppTest`/subprocess boot-check approaches) as the sole reference, not an in-repo analog. |

## Metadata

**Analog search scope:** `heatwave/` (all submodules), repo root (`nigeria_heat_index.py`, `requirements.txt`, `pyproject.toml`, `.gitignore`), `tests/` (confirmed absent), `keys/` (confirmed `service_account.json` present)
**Files scanned:** `heatwave/__init__.py`, `heatwave/auth.py`, `heatwave/config.py`, `heatwave/data/__init__.py`, `heatwave/data/boundary.py`, `heatwave/data/ingest.py`, `nigeria_heat_index.py`, `requirements.txt`, `pyproject.toml`, `.gitignore`
**Pattern extraction date:** 2026-09-11
