---
phase: 02-heat-index-relocation
reviewed: 2026-09-13T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - heatwave/science/__init__.py
  - heatwave/science/heat_index.py
  - tests/test_heat_index.py
  - nigeria_heat_index.py
findings:
  critical: 0
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-09-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the relocation of the RH/Heat-Index math into `heatwave/science/heat_index.py`, the new
`heatwave/science/__init__.py` package marker, the new NOAA-table/clamp test suite in
`tests/test_heat_index.py`, and the call-site update in `nigeria_heat_index.py`.

The core relocation is sound: the D-01 clamp is correctly scoped to the single-band `rh` result
before `addBands` (never the multi-band composite), the Rothfusz coefficients and expression string
are byte-identical to the original, the Kelvin→Fahrenheit conversion arithmetic is untouched, and
`nigeria_heat_index.py` contains zero surviving formula logic — it is a pure consumer of the science
module now. I cross-checked the NOAA fixture math by hand (e.g. 310.928 K → 100.0°F, T−D=12 →
RH=40%) and the fixtures are internally consistent with the asserted expected values. No hardcoded
secrets, injection vectors, or dangerous function usage were found in any of the four files.

I did not find any Critical/security issues. I did find one genuine functional-robustness gap in the
Streamlit date-selection UI (pre-existing, but present in the file as currently reviewed) and three
lower-severity quality items, detailed below.

## Warnings

### WR-01: Date sliders can construct calendar-invalid dates that reach the Earth Engine filter unvalidated

**File:** `nigeria_heat_index.py:43-48`
**Issue:** `year`, `month`, and `day` are independent `st.slider` widgets with `day` ranging 1-31
regardless of the selected month/year. Combinations such as `month=2, day=30` or `month=4, day=31`
produce a syntactically well-formed but calendar-invalid date string (e.g. `"2020-02-30"`), which is
passed straight into `ee.Filter.date(selected_date)` at line 57 with no validation. `ee.Filter.date`
does not validate the string client-side (it is lazily evaluated server-side), so the failure surfaces
only when the map tile layer is rendered — as a broken/error tile rather than a clear application
error, making the root cause hard for a user or on-call developer to diagnose. This is reachable by
any user moving the sliders away from the default `(2012, 7, 15)`, not just an adversarial input.
**Fix:** Either use a single `st.date_input` widget (which only offers calendar-valid dates), or
validate/clamp `day` against `calendar.monthrange(year, month)[1]` before formatting
`selected_date`:
```python
import calendar

max_day = calendar.monthrange(year, month)[1]
day = min(day, max_day)
selected_date = f"{year:04d}-{month:02d}-{day:02d}"
```

## Info

### IN-01: `.set('system:time_start', ...)` on the Heat Index band is dead code

**File:** `heatwave/science/heat_index.py:40`
**Issue:** `HI.set('system:time_start', image.get('system:time_start'))` sets the property on `HI`
(the single-band image being appended), but `ee.Image.addBands` propagates the destination
(`image`) image's metadata/properties to the output, not the source (`HI`) image's — so this `.set()`
call has no observable effect on the image returned by `compute_heat_index`. Since the receiving
`image` already carries `system:time_start` from its originating `ImageCollection`, that property is
preserved regardless of this call. This was already flagged as "likely dead" in the phase's own
research notes (IN-03) and intentionally kept for byte-for-byte parity with the pre-relocation code
(D-02); I am re-flagging it here per the adversarial-review brief so it doesn't get silently
"restored" as load-bearing in a future refactor.
**Fix:** No action required for this phase (deliberately preserved per plan). If revisited later,
either remove the `.set()` call or replace it with a comment clarifying it's a no-op kept for
historical parity, to avoid a future maintainer assuming it does something.

### IN-02: `compute_heat_index`'s hard dependency on a pre-existing `relative_humidity` band is undocumented and untested

**File:** `heatwave/science/heat_index.py:22-26`
**Issue:** `compute_heat_index` unconditionally does `image.select('relative_humidity')`, which will
raise an Earth Engine "band not found" error if called on an image that hasn't first passed through
`compute_relative_humidity`. This precondition is called out explicitly in the plan's interface
contract (`# adds 'heat_index' band (deg F); requires 'relative_humidity' band present`), but the
function's own docstring omits it, and there is no test in `tests/test_heat_index.py` covering the
misuse case. Since Phase 3 is expected to treat these two functions as a stable public contract, an
undocumented implicit ordering dependency is an easy way to introduce a confusing runtime failure for
a future caller who doesn't chain the two functions in the required order.
**Fix:** Add the precondition to the docstring, e.g.:
```python
def compute_heat_index(image: ee.Image) -> ee.Image:
    """Return image with an added 'heat_index' band (Rothfusz regression, deg F).

    Requires `image` to already contain a 'relative_humidity' band (see
    `compute_relative_humidity`); raises an Earth Engine error otherwise.
    """
```

### IN-03: Inconsistent naming convention (camelCase vs. snake_case) in `nigeria_heat_index.py`

**File:** `nigeria_heat_index.py:24-34`
**Issue:** Module-level variables `startDate`, `endDate`, `relativeHumidity`, and `heatIndex` use
camelCase, while the rest of the codebase (`heatwave/config.py`, `heatwave/science/heat_index.py`,
`heatwave/data/*`) consistently uses snake_case per PEP 8. This is pre-existing and out of this
phase's stated scope (the plan explicitly restricts this file's edit to the import line and the
branca-import deletion), so I'm not asking for a fix in this phase — flagging only so it isn't
mistaken for the project's intended style if touched again.
**Fix:** Not required this phase; rename to `start_date`, `end_date`, `relative_humidity`,
`heat_index` in a future presentation-layer cleanup pass (the plan already earmarks Phase 5 for a
presentation-layer rewrite).

---

_Reviewed: 2026-09-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
