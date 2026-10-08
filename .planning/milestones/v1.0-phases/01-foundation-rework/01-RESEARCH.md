# Phase 1: Foundation Rework - Research

**Researched:** 2026-09-11
**Domain:** Google Earth Engine (Python API) + Streamlit caching + pytest live-credential integration testing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Dewpoint/tmean date-matching fix (REWORK-02)
- **D-01:** Restructure `heatwave/data/ingest.py` to select `tmax`, `tmean`, and `dewpoint` as bands of a **single** `ee.ImageCollection` (one `.select([...])` call on `settings.era5_land_collection`, not three separately-filtered collections). Rationale: all three bands already come from the same source collection with identical date filters, so they are inherently 1:1 by day — the per-image `filterDate().first()` "join" in `nigeria_heat_index.py` is solving a problem that doesn't need to exist.
- **D-02:** This changes the shape of `Era5LandBands` (or replaces it with a single multi-band `ee.ImageCollection` return value) — Phase 2's relocation of the Heat Index/RH math into `heatwave/science/heat_index.py` must account for the new single-collection shape, not the old three-collection shape. Flag this for the Phase 2 planner.
- **D-03:** No `ee.Join` needed as a result of D-01 — the join-based fix option was considered and explicitly rejected in favor of eliminating the need for a join entirely.

### Earth Engine init caching (REWORK-01)
- **D-04:** Keep `heatwave/auth.py` framework-agnostic — do NOT import Streamlit or decorate `init_ee()` directly with `@st.cache_resource`. `init_ee()` stays callable from non-Streamlit contexts (Phase 4's `scripts/run_batch_export.py` calls it directly, uncached, once per script run).
- **D-05:** Add a thin `@st.cache_resource`-wrapped wrapper at the Streamlit app layer only — in `nigeria_heat_index.py` now, and carry the same pattern into `heatwave/app/streamlit_app.py` when Phase 5 rewrites the presentation layer.

### Re-verification format (REWORK-05, REWORK-06, REWORK-07, REWORK-08)
- **D-06:** Persist re-verification as automated tests in `tests/test_integration.py`, not a one-off script. Tests run against the live `heatwave-508110` GCP project (real Earth Engine calls, not mocked) per the user's established preference for real verification.
- **D-07:** Mark these tests so they can be skipped when live GCP credentials aren't available (e.g., a skip condition checking for `keys/service_account.json` / `EE_SA_JSON` presence) — they should not block a contributor's local test run who lacks credentials, but must actually execute (not be mocked) whenever credentials are present.

### Claude's Discretion
- Exact resolution mechanism for `heatwave/auth.py`'s relative-path fragility (REWORK-04, `_LOCAL_KEY_FILE = "keys/service_account.json"`) and the `blessings` stub-out's import-order dependency — an established pattern already exists in this codebase (`heatwave/config.py` uses `Path(__file__).resolve().parent.parent / "config.yaml"`); apply the equivalent anchor for the key file path, and move the `blessings` stub to run unconditionally at `heatwave/__init__.py` import time so it no longer depends on `auth.py` being imported before `geemap`.
- Removing the unused `ee==0.2` line from `requirements.txt` (REWORK-03) — no decision needed, just delete it.
- Exact test structure/fixtures for `tests/test_integration.py` — planner/executor discretion, as long as it hits the live project per D-06/D-07.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. The custom HTML/JS dashboard idea (DASH-01) was already captured as a v2 requirement during roadmap creation, not re-raised here.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| REWORK-01 | Earth Engine initialization is cached (`st.cache_resource` or equivalent) so Streamlit reruns/interactions do not trigger repeated re-authentication/re-initialization | Architecture Pattern 2 (`st.cache_resource` wrapper around a side-effecting initializer); confirmed `auth.py` has zero Streamlit dependency at module scope so D-04 is satisfiable |
| REWORK-02 | Relative-humidity computation matches each tmean image to its corresponding dewpoint image via a robust, verifiable date-matching method (not a fragile per-image `filterDate().first()` call) | Architecture Pattern 1 (multi-band `.select()` on one source collection, verified via `ee.ImageCollection.select`/`ee.Image.select`/`ee.Image.expression` signatures) — eliminates the join requirement entirely |
| REWORK-03 | `requirements.txt` has the unused `ee==0.2` PyPI package removed, keeping only `earthengine-api` | Package Legitimacy Audit — verified `ee==0.2` is a namespace-colliding decoy package, not just unused weight; removal steps and current-venv cleanup documented |
| REWORK-04 | `heatwave/auth.py` resolves the local service-account key path correctly regardless of CWD, and the `blessings` stub-out works regardless of import order | Architecture Pattern 3 (path anchoring, matches `config.py`'s existing pattern) and Pattern 4 + Pitfall 4 (blessings stub relocation AND the `nigeria_heat_index.py` import-order fix needed to make it fully effective) |
| REWORK-05 | `load_ward_boundary()` re-verified to return all 4,841 ward features with correct properties against the live project | Validation Architecture test map; Environment Availability confirms credentials present locally |
| REWORK-06 | `load_era5_land()` re-verified to return correctly date-filtered, boundary-clipped bands | Validation Architecture test map; ties directly to the D-01 restructure in Pattern 1 |
| REWORK-07 | `heatwave.config.settings` verified/tested to load `config.yaml` correctly | Validation Architecture test map — simple unit-style assertion against the existing, unchanged `config.py` |
| REWORK-08 | `streamlit run nigeria_heat_index.py` boots cleanly (HTTP 200, no stderr) using fixed auth/join logic | Code Examples section provides two verified test approaches (`AppTest` in-process vs. subprocess+HTTP) with tradeoffs |
</phase_requirements>

## Summary

This phase is a verify-and-fix pass on already-working code, not new capability. All four bugs
were reproduced or confirmed directly against the project's own installed `.venv` (Python 3.12,
`earthengine-api==1.6.8`, `streamlit==1.49.1`, `geemap==0.36.2`) rather than assumed from training
data, so confidence is HIGH across the board.

The most important discovery is that **`ee==0.2` is not merely "unused dead weight" — it is a
namespace-colliding decoy package** unrelated to Google Earth Engine (its own PyPI metadata
describes it as "A wrapper for dd" by an author whose homepage literally asks you to "buy him a
beer"). It installs its own `ee/__init__.py` and `ee/main.py` into the **same top-level `ee`
import namespace** that `earthengine-api` uses. In the current `.venv` the real `earthengine-api`
`ee/__init__.py` happens to still be in place (confirmed byte-for-byte via hash), but an orphaned
`ee/main.py` from the decoy package survives in the same package directory and is what actually
imports `blessings` — not geemap, and not `earthengine-api`. Reinstalling `requirements.txt` in a
different order (or via a resolver that doesn't preserve line order) risks the decoy overwriting
the real Earth Engine client silently. REWORK-03's fix (delete the line) is correct and should be
treated as a real supply-chain risk fix, not cosmetic cleanup.

The dewpoint join fix (REWORK-02 / D-01) has a clean, verified solution: `ee.ImageCollection`'s
`.select()` accepts a list of band names and returns a collection where **every image already
carries all three bands**, because they come from one source collection with identical date
filters. This eliminates the fragile per-image `filterDate().first()` "join" entirely — there is
no join to write, correct, or test; the two images being joined were always the same image.

The Streamlit caching fix (REWORK-01 / D-04/D-05) is a standard, well-documented idiom:
`@st.cache_resource` on a thin wrapper works correctly even when the wrapped function returns
`None`, because `st.cache_resource` caches "this call happened," not just a return value — exactly
what's needed for a side-effecting initializer like `init_ee()`.

**Primary recommendation:** Fix all four issues as targeted, minimal-diff changes to the existing
files (no rewrites); write `tests/test_integration.py` using `pytest.mark.skipif` gated on
`keys/service_account.json`/`EE_SA_JSON` presence, calling the real `heatwave-508110` project.

## Architectural Responsibility Map

This project is a data pipeline, not a multi-tier web app — tiers are reframed accordingly.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Credential resolution & EE client init | Backend package (`heatwave/auth.py`) | — | Must stay framework-agnostic; called by both Streamlit app and future batch scripts (D-04) |
| EE init caching (avoid re-auth per rerun) | Presentation script (`nigeria_heat_index.py`) | — | `st.cache_resource` is a Streamlit-runtime concept; `auth.py` must not know about it (D-05) |
| Boundary/ERA5-Land data access | Backend package (`heatwave/data/`) | External service (Earth Engine) | Pure data-access layer; no business logic |
| RH / Heat Index math | Presentation script (`nigeria_heat_index.py`) — *unchanged this phase* | Backend package (Phase 2 target) | Explicitly deferred to Phase 2 (HIDX-01) per CONTEXT.md; only the join bug gets fixed in place |
| Config loading | Backend package (`heatwave/config.py`) | — | Already correct; reference pattern for the auth.py path fix |
| Live re-verification | Test suite (`tests/test_integration.py`) | External service (Earth Engine, real project) | Must not mock per D-06; must skip gracefully without credentials per D-07 |

## Standard Stack

### Core (already pinned — verified against installed `.venv`, no version changes needed)

| Library | Version (installed & pinned) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `earthengine-api` | 1.6.8 [VERIFIED: local .venv inspection] | Earth Engine Python client (`import ee`) | Official Google client; already the correct package for this project |
| `streamlit` | 1.49.1 [VERIFIED: local .venv inspection] | Presentation layer / caching primitives | Already in use; `st.cache_resource` ships with this version |
| `geemap` | 0.36.2 [VERIFIED: local .venv inspection] | Folium-backed EE map widget for Streamlit | Already in use |
| `google-auth` / `google.oauth2.service_account` | 2.40.3 [VERIFIED: local .venv inspection] | Service-account credential construction | Already correct; do not change per CONTEXT.md |
| `pytest` | 8.4.1 [VERIFIED: local .venv inspection] | Test runner for `tests/test_integration.py` | Already in requirements.txt |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `requests` | 2.32.5 [VERIFIED: local .venv inspection] | HTTP GET for the "boots cleanly / HTTP 200" check in REWORK-08's test, if the subprocess+HTTP approach is chosen over `AppTest` | Only needed if `streamlit.testing.v1.AppTest` (see Code Examples) is not used |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single-collection `.select([...])` (chosen, D-03) | `ee.Join` on `system:time_start` between separate tmean/dewpoint collections | Explicitly rejected by the user — adds complexity to solve a join problem that doesn't exist when both bands come from the same source collection with identical filters |
| subprocess + HTTP GET for REWORK-08 test | `streamlit.testing.v1.AppTest.from_file(...).run()` | `AppTest` runs in-process (faster, no port/process management on Windows), but only asserts "no exception raised during script execution" — it does not literally produce an "HTTP 200" the way the requirement text states. See Code Examples for both, with a recommendation. |

**Installation:**
No new packages need to be installed this phase. `requirements.txt` only loses one line
(`ee==0.2`). The currently-running `.venv` should also have the shadow package removed to make the
dev environment match the fixed `requirements.txt`:
```bash
pip uninstall ee -y
pip install -r requirements.txt --force-reinstall --no-deps earthengine-api
```
(Re-run the second command only if `pip uninstall ee` also removed files that overlap with
`earthengine-api`'s `ee/` package — verify with `python -c "import ee; print(ee.__version__)"`
afterward; it must print `1.6.8`, not error, and not print anything resembling a "dd wrapper".)

**Version verification:** All versions above were read directly from `pip show` output in the
project's own `.venv` — not from training data or a registry query — so no separate registry
check was needed. No packages are being added.

## Package Legitimacy Audit

This phase does not install any new package — it **removes** one (`ee==0.2`). The audit below
documents why removal is justified beyond "unused."

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `ee` (0.2) | PyPI | Unknown (metadata undated) | Not queried (not relevant — targeted for removal, not install) | `github.com/snarez/ee` (per its own PyPI metadata; unrelated to Earth Engine) | Not run — package is being removed, not installed | **REMOVED** |

**Verified finding (not from slopcheck, from direct inspection of the installed `.venv`):**
`ee==0.2`'s own PyPI `METADATA` describes it as `Summary: A wrapper for dd`, `Home-page:
https://github.com/snarez/ee`, `License: Buy snare a beer` — a joke/utility package that happens
to claim the `ee` import name, colliding with `earthengine-api`'s `ee` namespace. Its `main.py`
(orphaned in `site-packages/ee/` alongside the real `earthengine-api` `__init__.py`) imports
`blessings`, `fcntl` (Unix-only), and Python-2-only `StringIO` — confirming it is unrelated,
unmaintained, and platform-incompatible code that has no business being importable under `import
ee` in this project. [VERIFIED: local .venv package inspection — `pip show ee`,
`ee-0.2.dist-info/METADATA`, hash comparison of `ee/__init__.py` against `earthengine_api-1.6.8
.dist-info/RECORD`]

**Packages removed due to verified collision risk:** `ee==0.2`
**Packages flagged as suspicious:** none (no new installs this phase)

## Architecture Patterns

### Data Flow (after this phase's fixes)

```
config.yaml ──▶ heatwave/config.py (settings, unchanged)
                        │
                        ▼
   heatwave/auth.py::init_ee()  ◀── credential source resolution (unchanged order:
        │                            Streamlit secrets → EE_SA_JSON → local key file,
        │                            now path-anchored via Path(__file__).resolve())
        ▼
   ee.Initialize(credentials, project=settings.gcp_project_id)
        │
        ├──▶ heatwave/data/boundary.py::load_ward_boundary()
        │         └─▶ ee.FeatureCollection(settings.ward_asset_id)   [unchanged]
        │
        └──▶ heatwave/data/ingest.py::load_era5_land(boundary, start, end)
                  └─▶ ee.ImageCollection(settings.era5_land_collection)
                        .select([tmax, tmean, dewpoint])   ◀── NEW: one collection,
                        .filter(ee.Filter.date(start,end))     3 bands per image,
                        .map(clip to boundary)                  no join needed
                        │
                        ▼ (single multi-band ee.ImageCollection)
   nigeria_heat_index.py
        ├─▶ init_ee() now wrapped: @st.cache_resource def _cached_init_ee(): init_ee()
        ├─▶ compute_relative_humidity(image):     ◀── reads image.select(tmean_band) and
        │       T = image.select(tmean_band)           image.select(dewpoint_band) from the
        │       D = image.select(dewpoint_band)         SAME image — no filterDate/.first()
        │       rh = image.expression(...)
        └─▶ compute_heat_index(image)  [unchanged math, Rothfusz regression]
                        │
                        ▼
                 Streamlit UI (map, slider, legend) [unchanged]
```

### Recommended Project Structure (additions only)

```
heatwave/
├── __init__.py          # gains: unconditional blessings stub-out (moved from auth.py)
├── auth.py               # gains: Path(__file__)-anchored key file path; loses: blessings stub
├── config.py             # unchanged (reference pattern)
├── data/
│   ├── boundary.py        # unchanged
│   └── ingest.py          # restructured: single-collection multi-band select (D-01)
tests/
├── __init__.py            # new (if package-style test discovery is wanted; optional)
└── test_integration.py    # new: REWORK-05/06/07/08 as skippable live tests
```

### Pattern 1: Multi-band ImageCollection selection (replaces three-collection join)
**What:** Select all needed bands from one source collection in a single `.select()` call, so
every `ee.Image` yielded by the collection already carries every band, in lockstep by date.
**When to use:** Whenever multiple bands you need are already present on the same source images
(true here — ERA5-Land's `temperature_2m_max`/`temperature_2m`/`dewpoint_temperature_2m` are three
bands of the same daily image, not three separate products).
**Example:**
```python
# Source: ee.ImageCollection.select signature verified via
# `help(ee.ImageCollection.select)` against installed earthengine-api==1.6.8:
#   select(self, selectors, names=None, *args) -> ImageCollection
import ee
from heatwave.config import settings

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
Downstream (`nigeria_heat_index.py`), the old per-image join disappears entirely:
```python
# Source: ee.Image.select / ee.Image.expression signatures verified via
# `help(ee.Image.select)` / `help(ee.Image.expression)` against earthengine-api==1.6.8.
era5_land = load_era5_land(boundary, startDate, endDate)  # single multi-band collection

def compute_relative_humidity(image):
    T = image.select(settings.bands.tmean)
    D = image.select(settings.bands.dewpoint)
    rh = image.expression(
        '100 - 5 * (T - D)', {'T': T, 'D': D}
    ).rename('relative_humidity')
    return image.addBands(rh)

relativeHumidity = era5_land.map(compute_relative_humidity)
```
No `.filterDate(tempDate, tempDate.advance(1, 'day')).first()` call remains — there is nothing to
join because `T` and `D` are two bands of the one image already flowing through `.map()`.

### Pattern 2: `st.cache_resource` wrapper around a side-effecting, no-return initializer
**What:** Cache "this ran once" for a function with side effects and no meaningful return value.
**When to use:** Any expensive one-time setup call (auth, client init) invoked at Streamlit module
top-level, where the framework must not know about caching (D-04 keeps `auth.py` Streamlit-free).
**Example:**
```python
# Source: st.cache_resource docs (https://docs.streamlit.io/develop/api-reference/
# caching-and-state/st.cache_resource) — "cache_resource is for long-lived objects/
# side effects... acts like a singleton." Verified applicable to None-returning
# functions: the decorator caches the fact the call completed, keyed on function
# identity + args (none here), and skips re-execution on subsequent Streamlit reruns.
import streamlit as st
from heatwave.auth import init_ee

@st.cache_resource
def _cached_init_ee() -> None:
    init_ee()

_cached_init_ee()  # replaces the old unconditional `init_ee()` call at module top-level
```
This keeps `heatwave/auth.py` importable and callable with zero Streamlit dependency (verified:
`auth.py` only imports Streamlit defensively inside a `try/except` for the secrets check, never at
module top-level) — `scripts/run_batch_export.py` (Phase 4) can still call `init_ee()` directly,
uncached, exactly per D-04.

### Pattern 3: Path-anchored key file resolution (replicate `config.py`'s existing pattern)
**What:** Resolve the local service-account key file relative to the package location, not the
process's current working directory.
**Example:**
```python
# Source: heatwave/config.py, existing pattern already in this codebase (line 9):
#   _CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
from pathlib import Path

_LOCAL_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
...
return service_account.Credentials.from_service_account_file(
    str(_LOCAL_KEY_FILE), scopes=EE_SCOPES
)
```
Note: `str(_LOCAL_KEY_FILE)` — `from_service_account_file`'s signature is typed as `filename:
str` [VERIFIED: `help(service_account.Credentials.from_service_account_file)` against installed
`google-auth==2.40.3`]; passing a `Path` object directly is likely to work in CPython (most
stdlib/`open()`-based file APIs accept `os.PathLike`), but casting to `str` avoids relying on that
and matches the documented signature exactly.

### Pattern 4: `blessings` stub relocated to package `__init__.py`
**What:** Run the `sys.modules.setdefault("blessings", ...)` stub unconditionally when the
`heatwave` package itself is first imported, rather than only when `heatwave.auth` specifically is
imported.
**Example:**
```python
# heatwave/__init__.py
"""heatwave package. Stubs out `blessings` before any submodule (or geemap) can import it."""
import sys
import types

sys.modules.setdefault("blessings", types.ModuleType("blessings"))
```
**Important caveat found during research (see Common Pitfalls #4):** moving the stub into
`heatwave/__init__.py` only removes the import-order dependency if the *first* thing a caller does
is import something from the `heatwave` package — it does not help if a caller does `import
geemap.foliumap` before touching `heatwave` at all. `nigeria_heat_index.py` currently does exactly
that (see Pitfall 4) and must have its import order corrected as part of this same fix.

### Anti-Patterns to Avoid
- **Per-image client-orchestrated joins for same-source bands:** Don't call `.filterDate(...).
  first()` inside a `.map()` callback to line up bands that already live on the same image. This
  is what caused REWORK-02; the fix is Pattern 1, not a "more correct" join.
- **Decorating `auth.py` functions with `@st.cache_resource` directly:** Explicitly rejected by
  D-04 — keep `heatwave/auth.py` importable with zero Streamlit dependency at module scope.
- **Trusting `requirements.txt` line order to control install/overwrite order:** The `ee==0.2` /
  `earthengine-api` collision (see Package Legitimacy Audit) shows why relying on incidental
  install order for namespace-colliding packages is fragile — the correct fix is removing the
  colliding package outright, not reordering lines.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Caching an expensive one-time init across Streamlit reruns | A manual `if "ee_initialized" not in st.session_state:` guard | `@st.cache_resource` | Built-in, handles reruns/threads correctly, is the documented idiom for exactly this case |
| Matching two bands that are already on the same image | A manual per-image `filterDate().first()` "join" or `ee.Join` | `ImageCollection.select([...])` on one source collection | Zero code, zero failure modes — there's nothing to join |
| Skipping tests when credentials aren't available | Custom `try/except` wrapping every test body | `pytest.mark.skipif(not path.exists(...), reason=...)` at the test/module level | Standard, discoverable in test output as "skipped" not "passed trivially" or silently no-op |
| Verifying "streamlit boots cleanly, HTTP 200, no stderr" | Hand-rolled `socket`/manual port-availability polling | `streamlit.testing.v1.AppTest` (in-process) or `subprocess.Popen([..., "--server.headless=true"])` + `requests.get` with a retry loop | Both are documented, maintained approaches; hand-rolled port probing is a common source of flaky CI/test-harness bugs |

**Key insight:** every "bug" in this phase except the `ee==0.2` package was caused by hand-rolling
something the platform already provides for free (a join that isn't needed, a cache Streamlit
already ships, a path resolution pattern the codebase already has in `config.py`). The fix pattern
across all four issues is "use the existing primitive correctly," not "write new logic."

## Common Pitfalls

### Pitfall 1: Treating `ee==0.2` removal as purely cosmetic
**What goes wrong:** A future `pip install -r requirements.txt` (possibly with a resolver that
doesn't preserve line order, or on a fresh machine) could install `ee==0.2` after
`earthengine-api`, silently overwriting the real `ee/__init__.py` with the decoy package's, causing
`ee.Initialize`, `ee.ImageCollection`, etc. to not exist / behave unpredictably.
**Why it happens:** Both packages claim the top-level `ee` import name — pip has no mechanism to
detect or warn about this collision at install time.
**How to avoid:** Delete the `ee==0.2` line (REWORK-03) and also `pip uninstall ee` from the
current dev `.venv` to remove the orphaned `main.py`/`apitestcase`-adjacent files still lingering
in `site-packages/ee/` from the decoy package's earlier install.
**Warning signs:** `import ee; ee.main` succeeding when nothing in the real Earth Engine API
should expose a `main` submodule; `blessings` import errors that don't reference geemap or
earthengine-api anywhere in the traceback.

### Pitfall 2: Assuming `blessings` is required by the current geemap/earthengine-api versions
**What goes wrong:** Direct inspection of the installed `.venv` found **no import of `blessings`**
anywhere in `geemap==0.36.2`'s source, nor in `earthengine-api==1.6.8`'s `requires-dist`. The only
file in the entire dependency tree that imports `blessings` is the orphaned `ee/main.py` left
behind by the `ee==0.2` decoy package (see Pitfall 1) — which nothing in this codebase actually
calls.
**Why it happens:** The `blessings` stub-out was very likely written defensively based on a past
observation (possibly on Streamlit Community Cloud, with different transitively-resolved package
versions, or an older geemap release) — this could not be reproduced or confirmed in the current
environment. [ASSUMED: the original "geemap imports blessings" claim in the codebase's own
comments/PROJECT.md — could not verify against the currently pinned versions]
**How to avoid:** Keep the stub (per CONTEXT.md's locked discretion decision — it's cheap
insurance) but do not treat its necessity as proven fact for this exact dependency set. Do not use
this stub's presence as justification to skip testing `streamlit run nigeria_heat_index.py` for
real (REWORK-08) — the stub being vestigial in this environment doesn't mean it's vestigial on
Streamlit Community Cloud, where the whole justification originated.

### Pitfall 3: `ee.ImageCollection.select()` band-name collisions after restructuring
**What goes wrong:** After D-01's restructure, `image.select(settings.bands.tmean)` and
`image.select(settings.bands.dewpoint)` must be called with the exact configured band-name
strings (`temperature_2m`, `dewpoint_temperature_2m`) — since all three bands now live on one
image, a typo'd or swapped band name will silently select the wrong band rather than erroring
(Earth Engine band selection by exact string match either finds it or throws — it will not throw
for a valid-but-wrong band name).
**How to avoid:** Read band names from `settings.bands.*` everywhere (already the existing
convention — do not hardcode string literals as the current `nigeria_heat_index.py` does on line
44 with `settings.bands.tmean` — good — but line 33-38's old join code hardcodes nothing
band-related since it doesn't need to select by name at all; after the fix, add an explicit
band-name reference for dewpoint that currently doesn't exist inline).
**Warning signs:** RH values that are constant/nonsensical because `T` and `D` accidentally
selected the same band.

### Pitfall 4: Import order in `nigeria_heat_index.py` still defeats the `blessings` stub relocation
**What goes wrong:** `nigeria_heat_index.py`'s current import block is:
```python
import streamlit as st
import ee
import geemap.foliumap as geemap        # <-- imported BEFORE any heatwave.* import
from branca.element import Template, MacroElement

from heatwave.auth import init_ee        # <-- heatwave package first touched here
```
Moving the `blessings` stub to `heatwave/__init__.py` (Pattern 4) only executes it when something
from `heatwave` is first imported — which, in this file, happens **after** `geemap.foliumap` is
already imported on line 3. If some future geemap version (or a different environment's resolved
dependency set) does need `blessings` at import time, this ordering bug survives the "fix"
unless `nigeria_heat_index.py`'s import order is also corrected.
**How to avoid:** As part of this phase's fix to `nigeria_heat_index.py` (which is already being
touched for the join fix and caching wrapper), reorder imports so a `heatwave` import (e.g., `from
heatwave.auth import init_ee`, or even a bare `import heatwave`) happens before `import
geemap.foliumap`. This is a small addition to the scope CONTEXT.md describes for
`nigeria_heat_index.py` and should be called out explicitly in the plan rather than left implicit.
**Warning signs:** `streamlit run nigeria_heat_index.py` still fails with a `blessings`-related
`ModuleNotFoundError` on an environment lacking that package, even after the stub is "moved."

### Pitfall 5: `pytest.mark.skipif` evaluated at collection time, not test-run time
**What goes wrong:** `skipif` conditions are evaluated once, when pytest collects the test module
— if the credential check involves anything with side effects (e.g., actually calling
`init_ee()`), it will run at collection time for every test in the module, even ones that would
otherwise be skipped.
**How to avoid:** Keep the skip condition to a cheap, side-effect-free check:
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
Apply `pytestmark` at module level in `tests/test_integration.py` so all REWORK-05/06/07/08 tests
share one skip condition, evaluated cheaply.
**Warning signs:** Tests hang or fail with auth errors during collection rather than cleanly
skipping.

## Code Examples

### REWORK-08: verifying `streamlit run` boots cleanly — two verified approaches

**Approach A — `AppTest` (in-process, faster, recommended default):**
```python
# Source: streamlit.testing.v1.AppTest signature verified via
# `help(AppTest.from_file)` against installed streamlit==1.49.1.
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_streamlit_app_boots_cleanly():
    script = Path(__file__).resolve().parent.parent / "nigeria_heat_index.py"
    at = AppTest.from_file(str(script), default_timeout=60)
    at.run()
    assert not at.exception, f"App raised: {at.exception}"
```
Caveat: `AppTest` executes the script in-process and captures Python exceptions raised during the
run; it does not literally issue an HTTP GET or assert a status code, so it satisfies "no stderr /
boots cleanly" more directly than "HTTP 200" as literally written in REWORK-08's text. `geemap`'s
`Map.to_streamlit()` renders a custom HTML component — confirm during implementation that
`AppTest` handles this element type without raising (custom components are represented in the
`AppTest` tree; if it errors, fall back to Approach B).

**Approach B — subprocess + HTTP GET (matches REWORK-08's literal "HTTP 200" wording):**
```python
import subprocess
import time
import requests

def test_streamlit_app_http_200():
    proc = subprocess.Popen(
        ["streamlit", "run", "nigeria_heat_index.py",
         "--server.headless=true", "--server.port=8765"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        for _ in range(30):  # up to ~15s
            time.sleep(0.5)
            try:
                resp = requests.get("http://localhost:8765", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.ConnectionError:
                continue
        else:
            pytest.fail("Streamlit app did not respond with HTTP 200 in time")
    finally:
        proc.terminate()
        _, stderr = proc.communicate(timeout=10)
        assert "Traceback" not in stderr
```
Recommendation: use Approach A as the primary automated test (fast, no port/process management
flakiness — a known pain point on Windows per this project's own documented PowerShell/process
gotchas in `PROJECT_STATE.md` §8); Approach B may still be run once manually to literally confirm
"HTTP 200" if a stricter reading of REWORK-08 is wanted, but is more failure-prone as an automated
CI-style test.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Per-image `filterDate().first()` client-orchestrated join | Multi-band `.select()` on one source collection | N/A — this was always unnecessary given the data source, not a deprecated API | Eliminates the join, the silent-null risk, and the client-side loop entirely |
| No caching around `ee.Initialize()` in Streamlit | `st.cache_resource`-wrapped initializer | `st.cache_resource` has been the recommended caching primitive since Streamlit 1.18 (2023), replacing the older, now-deprecated `st.cache` | Streamlit reruns no longer re-authenticate |

**Deprecated/outdated:** `st.cache` (the pre-2023 single caching decorator) is deprecated in
favor of `st.cache_data`/`st.cache_resource` — not used anywhere in this codebase, no action
needed, noted only for completeness.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The original justification "geemap imports blessings, which fails to import on Streamlit Community Cloud" (from `heatwave/auth.py`'s own comment and `.planning/PROJECT.md`) reflects a real observation from a different environment/version set than the one currently installed, rather than a stale/incorrect assumption. | Common Pitfalls #2 | If wrong (i.e., the stub was never actually necessary anywhere), the stub is harmless dead code either way — low risk. If right, removing/weakening the stub could break Streamlit Community Cloud deploys specifically, which cannot be tested from this local environment. |
| A2 | `AppTest.from_file(...).run()` will not raise on `geemap.foliumap`'s `Map.to_streamlit()` custom HTML component embed. | Code Examples (REWORK-08 Approach A) | If wrong, Approach A test fails/errors even though the app is actually fine; planner should keep Approach B available as a fallback rather than committing solely to Approach A. |

## Open Questions (RESOLVED)

1. **Should `Era5LandBands` dataclass be removed entirely, or kept as a thin wrapper?** RESOLVED: Plan 01-02 Task 1 implements the bare `ee.ImageCollection` return recommendation below — `Era5LandBands` and `_select_band()` are removed entirely.
   - What we know: D-02 explicitly allows either "changes the shape of `Era5LandBands`... or
     replaces it with a single multi-band `ee.ImageCollection` return value."
   - What's unclear: whether Phase 2's planner would prefer a named type (even a trivial
     single-field dataclass) for self-documentation, versus a bare `ee.ImageCollection` return.
   - Recommendation: return a bare `ee.ImageCollection` from `load_era5_land()` (simplest, matches
     what the value actually is now) and document the exact band names available on it directly in
     the docstring, since `Era5LandBands` as a 3-field dataclass no longer reflects reality once
     there's only one collection. Flag this exact shape explicitly in this phase's plan output so
     the Phase 2 planner does not have to re-derive it from a diff.

2. **Exact reorder of `nigeria_heat_index.py` imports (Pitfall 4) — how much to touch in one phase.** RESOLVED: Plan 01-02 Task 2 treats the import reorder as in-scope, per the recommendation below.
   - What we know: CONTEXT.md scopes `nigeria_heat_index.py` changes to "the join/caching get
     fixed" for this phase, with relocation of the math itself deferred to Phase 2.
   - What's unclear: whether reordering the import block (to make the blessings-stub relocation
     actually effective) counts as within that stated scope or is scope creep.
   - Recommendation: treat it as in-scope — it's a one-line import reorder required to make the
     REWORK-04 fix actually work end-to-end in this exact file, not a new feature or rewrite.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `keys/service_account.json` | REWORK-05/06/07/08 live tests running (not skipping) | ✓ (confirmed present at `keys/service_account.json` in this working directory) | — | Tests fall back to `skip` per D-07 if absent on another machine/CI |
| Internet access to Earth Engine API endpoints | All live Earth Engine calls (auth, boundary, ingest, Streamlit boot) | Not independently verified in this research pass (no live `ee.Initialize()` call was made to avoid unnecessary auth during research) | — | None — blocks all REWORK-05/06/07/08 tests if unavailable; this is inherent to the phase's live-verification requirement (D-06), not a gap to fix |
| `earthengine-api`, `streamlit`, `geemap`, `pytest`, `google-auth` | Everything in this phase | ✓ all confirmed installed in `.venv` | 1.6.8 / 1.49.1 / 0.36.2 / 8.4.1 / 2.40.3 | — |

**Missing dependencies with no fallback:** none identified — all required tooling is already
installed in the project's `.venv`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.1 [VERIFIED: local .venv] |
| Config file | none — `pyproject.toml` has no `[tool.pytest.ini_options]` section (Wave 0 gap) |
| Quick run command | `pytest tests/test_integration.py -x -q` |
| Full suite command | `pytest -q` (only file will be `tests/test_integration.py` after this phase — `tests/` does not exist yet) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|--------------------|-------------|
| REWORK-01 | EE init is cached across reruns | integration (manual/inspection — caching behavior is hard to assert via pytest against a live Streamlit rerun cycle) | `pytest tests/test_integration.py::test_init_ee_idempotent -x` (asserts second call doesn't error / re-raises no new exception; true "no re-auth" verification is more reliably confirmed by manual `streamlit run` + repeated widget interaction, watching for auth latency) | ❌ Wave 0 |
| REWORK-02 | tmean/dewpoint are 1:1 by construction, no join needed | unit/integration | `pytest tests/test_integration.py::test_era5_land_bands_aligned -x` | ❌ Wave 0 |
| REWORK-03 | `ee==0.2` removed from requirements.txt | static check | `grep -q "^ee==" requirements.txt && exit 1 || exit 0` (or a trivial `test_requirements.py` assertion) | ❌ Wave 0 |
| REWORK-04 | key file path resolves regardless of CWD; blessings stub works regardless of import order | integration | `pytest tests/test_integration.py::test_auth_resolves_from_any_cwd -x` | ❌ Wave 0 |
| REWORK-05 | `load_ward_boundary()` returns 4,841 wards with correct properties | integration (live) | `pytest tests/test_integration.py::test_load_ward_boundary -x` | ❌ Wave 0 |
| REWORK-06 | `load_era5_land()` returns correct bands, date-filtered, clipped | integration (live) | `pytest tests/test_integration.py::test_load_era5_land -x` | ❌ Wave 0 |
| REWORK-07 | `settings` loads `config.yaml` correctly | unit | `pytest tests/test_integration.py::test_settings_loaded -x` | ❌ Wave 0 |
| REWORK-08 | `streamlit run nigeria_heat_index.py` boots cleanly | integration (live) | `pytest tests/test_integration.py::test_streamlit_app_boots_cleanly -x` (see Code Examples) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_integration.py -x -q` (skips gracefully without credentials, runs live with them)
- **Per wave merge:** same command — this phase has one test file
- **Phase gate:** full `pytest -q` green (or all-skipped, if run without credentials) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_integration.py` — does not exist yet; covers REWORK-01/02/04/05/06/07/08
- [ ] `tests/__init__.py` or equivalent — not strictly required by pytest's default rootdir-based
      discovery, but confirm `pyproject.toml`/`pytest.ini` doesn't need a `testpaths` entry added
      for `pytest` to find `tests/` automatically (default discovery from repo root should work
      without config, but verify once the directory exists)
- [ ] No shared `conftest.py` exists yet — the skip-condition constant (`_HAS_CREDENTIALS`) and key
      file path resolution are small enough to inline in `test_integration.py` directly per
      CONTEXT.md's "planner/executor discretion" on test structure; a `conftest.py` is optional,
      not required, for a single test file

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | yes | Service-account JSON credential flow via `google.oauth2.service_account` — already correct, unchanged this phase |
| V3 Session Management | no | No user sessions in this pipeline |
| V4 Access Control | no | Single-service-account, no multi-user access control surface in this phase |
| V5 Input Validation | no (narrow) | `config.yaml` is trusted, locally-authored input; no external/user-supplied input parsed in this phase's changed files |
| V6 Cryptography | no | No custom cryptography — credential handling delegates entirely to `google-auth`, never hand-rolled |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Service-account key committed to git | Information Disclosure | Already mitigated: `keys/`, `keys/*.json`, `.streamlit/secrets.toml` all in `.gitignore` [VERIFIED: `.gitignore` contents read directly] — no change needed, but the executor should re-confirm this stays true after editing `auth.py`'s path constant |
| Dependency namespace collision / supply-chain confusion (`ee==0.2` shadowing `earthengine-api`'s `ee`) | Tampering | Remove the colliding package (REWORK-03); more generally, verify any future dependency addition doesn't claim an import name already used by another intended dependency |
| Hardcoded/relative credential file paths breaking silently depending on CWD | Information Disclosure (indirect — can cause fallback to wrong/no credentials, or accidental use of a stale key elsewhere on the filesystem) | Path-anchor via `Path(__file__).resolve().parent.parent` (REWORK-04, Pattern 3) |

## Sources

### Primary (HIGH confidence)
- Local `.venv` package inspection via `pip show`, `help()`, and direct file/hash reads for
  `earthengine-api==1.6.8`, `streamlit==1.49.1`, `geemap==0.36.2`, `google-auth==2.40.3`,
  `pytest==8.4.1`, and the `ee==0.2` decoy package's own `METADATA`/`RECORD` — this is the
  project's actual installed environment, not a general registry lookup.
- `heatwave/config.py`, `heatwave/auth.py`, `heatwave/data/ingest.py`, `heatwave/data/boundary.py`,
  `nigeria_heat_index.py`, `requirements.txt`, `config.yaml`, `.gitignore` — read directly from the
  working tree.
- https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_resource — official
  docs, confirms `st.cache_resource` singleton/side-effect semantics.

### Secondary (MEDIUM confidence)
- WebSearch results on `st.cache_resource` + Earth Engine Streamlit integration patterns
  (Medium articles, geemap GitHub discussions) — corroborate that `st.cache_resource` wrapping
  `ee.Initialize()` is the community-standard pattern, cross-checked against official docs above.
- WebSearch results on `pytest.mark.skipif` credential-gating patterns — standard, well-established
  pytest idiom, not disputed by any source found.

### Tertiary (LOW confidence)
- The historical claim that geemap (some version) imports `blessings` and fails on Streamlit
  Community Cloud specifically — could not be corroborated by any external source found via
  WebSearch, and contradicted by direct inspection of the currently pinned versions (see Pitfall 2,
  Assumption A1). Flagged, not discarded — the stub is kept per locked discretion decision
  regardless.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions read directly from the installed `.venv`, no assumptions
- Architecture: HIGH — the `.select()` multi-band fix was verified against the actual installed
  `ee.ImageCollection.select`/`ee.Image.select`/`ee.Image.expression` signatures via `help()`
- Pitfalls: HIGH for the `ee==0.2` collision and blessings-necessity findings (both verified by
  direct file/hash/import-trace inspection); MEDIUM for the original blessings/Streamlit-Cloud
  claim's historical accuracy (could not verify, flagged as assumption)

**Research date:** 2026-09-11
**Valid until:** 2026-10-11 (30 days — dependency versions are pinned/stable; re-verify if
`requirements.txt` versions change before this phase is implemented)
