---
phase: 01-foundation-rework
reviewed: 2026-09-13T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - heatwave/auth.py
  - heatwave/__init__.py
  - requirements.txt
  - heatwave/data/ingest.py
  - nigeria_heat_index.py
  - tests/test_integration.py
  - tests/test_requirements.py
findings:
  critical: 0
  warning: 3
  info: 5
  total: 8
status: issues_found
---

# Phase 01-foundation-rework: Code Review Report

**Reviewed:** 2026-09-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the Phase 1 foundation-rework changes: the consolidated `heatwave/auth.py` credential loader, the unconditional `blessings` stub in `heatwave/__init__.py`, the single-collection `load_era5_land()` restructure in `heatwave/data/ingest.py`, the caching/import-order fix in `nigeria_heat_index.py`, the `ee==0.2` removal from `requirements.txt`, and the new live-integration/regression tests.

Cross-checked the diff against `e4939de9aebe563c6cc548318ab8262342ffc25d..HEAD` and against the REWORK-01 through REWORK-08 decisions recorded in `01-CONTEXT.md`: the path-anchoring fix (D-defined pattern reused from `config.py`), the single multi-band `ee.ImageCollection` restructure (D-01/D-03, join eliminated), the Streamlit-layer-only `@st.cache_resource` wrapper (D-04/D-05), and the `ee==0.2` removal (REWORK-03) are all implemented as specified. Ran the full test suite locally against live credentials (`keys/service_account.json` present) — all 8 tests pass, confirming the live Earth Engine calls actually work end-to-end, not just that the code parses.

No Critical/security issues found — no hardcoded secrets, no injection vectors, `yaml.safe_load` used correctly, credential precedence order matches the documented contract. Findings below are Warnings (robustness/maintainability risks worth fixing) and Info (quality nits), several of which are pre-existing in code this phase touched but did not fully rewrite (the RH/Heat-Index math was explicitly deferred to Phase 2's HIDX-01 relocation per `01-CONTEXT.md` D-02, but is flagged here since it lives in a reviewed file today).

## Warnings

### WR-01: Unclamped relative-humidity approximation can feed invalid values into the Heat Index formula

**File:** `nigeria_heat_index.py:33-42` and `nigeria_heat_index.py:47-64`
**Issue:** `compute_relative_humidity()` computes `RH = 100 - 5*(T - D)` with no bound applied. This linear approximation is only valid over a narrow dewpoint-depression range; for larger `T - D` it produces negative RH, and for negative `T - D` (dewpoint above temperature, physically possible in some ERA5-Land grid cells/timesteps) it can exceed 100. That unbounded `RH` band is then fed straight into the Rothfusz regression in `compute_heat_index()` with no validity check, so out-of-range inputs silently produce physically meaningless `heat_index` values on the map instead of an error or a masked pixel — this could go unnoticed by a user (e.g. wrong-looking colors on the legend, not a crash).
**Fix:**
```python
rh = image.expression(
    '100 - 5 * (T - D)',
    {'T': T, 'D': D}
).clamp(0, 100).rename('relative_humidity')
```
Not introduced by this phase (the `100 - 5*(T-D)` formula itself is unchanged from the prior version — only the join was removed), but worth fixing now or explicitly flagging for Phase 2 (HIDX-01) before this logic is relocated to `heatwave/science/heat_index.py`.

### WR-02: `blessings` stub safety net depends on caller import order, with no test enforcing it

**File:** `heatwave/__init__.py:5`, `nigeria_heat_index.py:3-4`
**Issue:** `sys.modules.setdefault("blessings", types.ModuleType("blessings"))` only prevents a crash if some code imports the `heatwave` package (which runs this line) *before* anything does a real `import blessings` (directly, or transitively through `geocoder`/`geemap`). Today this is satisfied only because `nigeria_heat_index.py` manually places `from heatwave.auth import init_ee` before `import geemap.foliumap as geemap`, enforced purely by a code comment ("triggers heatwave package's blessings stub before geemap loads"), not by tooling.

Verified this is a real, live landmine, not a theoretical one: `blessings==1.7` is pinned in `requirements.txt` and pip reports it "successfully installed," but a bare `import blessings` on this Windows environment raises `ModuleNotFoundError: No module named '_curses'` (blessings hard-requires POSIX `curses`, which has no Windows build). Any future script or test that imports `geemap`, `geocoder`, or another transitive consumer of `blessings` *before* importing anything from `heatwave` will crash on Windows/Streamlit Cloud, and nothing in the current test suite would catch that regression.
**Fix:** Add a regression test asserting `sys.modules['blessings']` is the stub type immediately after `import heatwave` (guards the invariant this phase's REWORK-04 fix depends on), and/or move the guard somewhere it can't be bypassed by import order (e.g. a `conftest.py`/`sitecustomize.py`-level shim, or dropping the unusable `blessings==1.7` pin from `requirements.txt` entirely since it can never successfully import on this platform anyway).

### WR-03: Overly broad `except Exception` can mask real Streamlit secrets errors

**File:** `heatwave/auth.py:28-34`
**Issue:** `_load_credentials()` wraps `import streamlit as st` and `"earthengine" in st.secrets` in a bare `except Exception`, intended (per the inline comment) to cover exactly two cases: streamlit not installed, and no `secrets.toml` present. But it will also silently swallow any other exception from that block — e.g. a malformed `secrets.toml` (TOML parse error) or a permissions error reading the secrets file — and mis-report it as "no earthengine secret configured," silently falling through to the next credential source (`EE_SA_JSON` / local key file) instead of surfacing the real misconfiguration to the developer.
**Fix:** Narrow the catch or at least log/re-raise unexpected exception types, e.g.:
```python
except ModuleNotFoundError:
    has_earthengine_secret = False
except Exception as exc:
    if type(exc).__name__ != "StreamlitSecretNotFoundError":
        raise
    has_earthengine_secret = False
```

## Info

### IN-01: Misleading variable name `tempC` actually holds Kelvin

**File:** `nigeria_heat_index.py:48`
**Issue:** `tempC = image.select(settings.bands.tmean)` — `tmean` is ERA5-Land's `temperature_2m` band, which is in Kelvin, not Celsius. The following line, `tempF = tempC.subtract(273.15).multiply(9/5).add(32)`, is correct (it performs the Kelvin→Celsius step via `subtract(273.15)` before the Celsius→Fahrenheit conversion), but the name `tempC` will mislead the next reader — especially relevant since Phase 2 (HIDX-01) relocates this exact function.
**Fix:** Rename to `tempK` for clarity.

### IN-02: Unused imports `Template`, `MacroElement`

**File:** `nigeria_heat_index.py:5`
**Issue:** `from branca.element import Template, MacroElement` — neither name is referenced anywhere in the file. The legend (`display_heat_index_legend()`) is built from a plain HTML string passed to `st.markdown(..., unsafe_allow_html=True)`.
**Fix:** Remove the unused import.

### IN-03: Dead property-set on a value discarded by `addBands`

**File:** `nigeria_heat_index.py:64`
**Issue:** `HI.set('system:time_start', image.get('system:time_start'))` sets an image-level property on the `HI` band image passed into `image.addBands(...)`. `ee.Image.addBands()` returns a copy of the *calling* image (`image`, which already carries `system:time_start`) with the extra band(s) merged in — properties set on the argument image are not carried over. The `.set(...)` call has no observable effect.
**Fix:** Remove it, or replace with a comment noting `image` already carries the required time metadata.

### IN-04: `os.getenv("EE_SA_JSON")` read twice

**File:** `heatwave/auth.py:42-43`
**Issue:** `os.getenv("EE_SA_JSON")` is called once in the `if` condition and again to parse it — a minor duplication (not a correctness bug, since env vars can't change mid-call, but avoidable).
**Fix:**
```python
ee_sa_json = os.getenv("EE_SA_JSON")
if ee_sa_json:
    sa_info = json.loads(ee_sa_json)
    ...
```

### IN-05: No dedicated error when all three credential sources are absent

**File:** `heatwave/auth.py:48-50`
**Issue:** When none of the three documented credential sources (Streamlit secrets, `EE_SA_JSON`, local key file) are available, `_load_credentials()` falls through to `service_account.Credentials.from_service_account_file(str(_LOCAL_KEY_FILE), ...)`, which raises a raw `FileNotFoundError` pointing at `_LOCAL_KEY_FILE`. A contributor unfamiliar with the three-source contract will see a file-not-found error rather than a message naming all three attempted sources.
**Fix:** Raise a clearer error, e.g.:
```python
if not _LOCAL_KEY_FILE.exists():
    raise RuntimeError(
        "No Earth Engine credentials found. Tried: Streamlit secrets "
        "['earthengine'], EE_SA_JSON env var, and "
        f"{_LOCAL_KEY_FILE}."
    )
```

---

_Reviewed: 2026-09-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
