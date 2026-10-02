---
phase: 03-climatology-heatwave-detection
reviewed: 2026-09-13T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - heatwave/zonal.py
  - heatwave/science/climatology.py
  - heatwave/science/heatwave.py
  - tests/test_heatwave_detection.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-09-13
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the zonal-reduction, climatology-baseline, and heatwave-event-detection modules plus their test file. The day-of-year floor-mod/wraparound arithmetic in `climatology.py` (`floor_mod`, `wrapped_day`, `pooling_window_filter`) is correct and matches its own live-verified doc comments — I re-derived several of the claimed mappings (`-3 -> 363`, `0 -> 366`, `367 -> 1`, `730 -> 364`) by hand and they check out. The tiny-ward null-value handling in `zonal.py` that the task asked me to scrutinize (T-03-17) is also sound: I initially suspected `feature.get("mean")` might throw rather than resolve to `null` when Earth Engine's `reduceRegions` omits the `mean` property entirely for sub-pixel-weight wards (per 03-RESEARCH.md Pitfall 4), since `ee.Element.get()` (confirmed via the local `earthengine-api` source) takes no default-value argument the way `ee.Dictionary.get()` does. However, 03-01-SUMMARY.md confirms this exact behavior was live-tested against real Earth Engine and passed, so the current implementation is correct as shipped, not a bug.

The real defect this review found is in the run-detection stage (`heatwave/science/heatwave.py`): `flag_heatwave_days`'s threshold join defaults to an **inner** join (`ee.Join.saveFirst` with `outer` unset), which silently drops any ward-day lacking a matching `(ward_id, doy)` climatology threshold — this is undocumented and untested, unlike the accepted T-03-17 null-value threat. Because `tag_consecutive_runs`/`detect_heatwave_events` assume a gapless, one-row-per-calendar-day input (stated explicitly in their own docstring) and never verify that assumption, a silently dropped row corrupts consecutive-run/event boundaries for that ward without any error or log signal. This is a genuine, connected data-integrity bug, not merely the already-accepted small-ward-null edge case. Three further warnings and two info-level notes are also included below.

## Critical Issues

### CR-01: Inner join in `flag_heatwave_days` silently drops unmatched ward-days, corrupting consecutive-run detection

**File:** `heatwave/science/heatwave.py:64` (compounding into `heatwave/science/heatwave.py:101-183`)
**Issue:**
```python
joined = ee.Join.saveFirst("clim_match").apply(ward_daily_fc, climatology_fc, join_filter)
```
`ee.Join.saveFirst(matchKey, ordering=None, ascending=None, measureKey=None, outer=None)` defaults `outer` to falsy (confirmed in `.venv/Lib/site-packages/ee/join.py:190-217`, docstring: "If true, primary rows without matches will be included in the result."). With the default, this is an **inner** join: any `ward_daily_fc` row whose `(ward_id, doy)` has no matching row in `climatology_fc` is dropped from the output entirely — not flagged, not nulled, just silently absent. This is undocumented: the function's docstring only discusses the `value_property`-is-null precondition (the accepted T-03-17 threat) and says nothing about missing climatology coverage.

This is a realistic scenario, not a hypothetical: any ward/day combination for which the pooled ±window baseline has zero data points (a ward with a data gap during its baseline period, or a newly-added ward with incomplete baseline history) produces zero grouped rows for that `(ward_id, doy)` in `compute_climatology_thresholds`'s output, which means every detection-year day sharing that `doy` for that ward is silently dropped here.

The consequence is worse than a simple missing row: `tag_consecutive_runs`'s own docstring states its caller obligation plainly — "`flags_sorted_by_date` must already be for a single ward, in date order, **one element per day**" — and `detect_heatwave_events` never verifies this invariant before feeding `ward_fc.aggregate_array("is_hot")` into the state machine. If even one day is silently dropped by the inner join, the run-detection state machine treats the calendar day before and after the gap as adjacent list elements, silently merging or splitting runs incorrectly (e.g., a 2-day hot run followed by a dropped day followed by another 2-day hot run reads as one contiguous 4-day run and wrongly qualifies as an event under a `min_consecutive_days=3` threshold).

**Fix:** Use an outer join and handle the unmatched case explicitly and visibly, mirroring the explicit-null-handling pattern already used for `value_property`:
```python
joined = ee.Join.saveFirst("clim_match", outer=True).apply(
    ward_daily_fc, climatology_fc, join_filter
)

def flag_one_row(feature: ee.Feature) -> ee.Feature:
    feature = ee.Feature(feature)
    clim_match = feature.get("clim_match")
    threshold = ee.Algorithms.If(clim_match, ee.Feature(clim_match).get("threshold"), None)
    is_hot = ee.Algorithms.If(
        clim_match,
        ee.Number(feature.get(value_property)).gt(ee.Number(threshold)),
        None,
    )
    return feature.set("threshold", threshold, "is_hot", is_hot).set("clim_match", None)
```
And add an explicit precondition check (or documented caller contract) in `detect_heatwave_events` that rejects/flags gaps in a ward's date sequence before running `tag_consecutive_runs`, rather than silently trusting row-adjacency to mean calendar-adjacency.

## Warnings

### WR-01: `min_consecutive_days=0` is silently overridden by the config default

**File:** `heatwave/science/heatwave.py:158`
**Issue:**
```python
min_consecutive_days = min_consecutive_days or settings.climatology.min_consecutive_days
```
This uses Python truthiness (`or`), so an explicit caller-supplied `min_consecutive_days=0` is swallowed and silently replaced by the config default (3). This is the exact same class of bug that `climatology.py:89` already identifies and fixes for `window_days`, with a comment explaining why: *"`is not None` (not `or`) so an explicit 0 ... is not swallowed by falsiness."* The fix applied there was not carried over to the sibling `min_consecutive_days` parameter in this module, even though `0` is an equally legitimate (if unusual) explicit value here (meaning "every hot day is its own qualifying event").
**Fix:**
```python
min_consecutive_days = (
    min_consecutive_days if min_consecutive_days is not None else settings.climatology.min_consecutive_days
)
```

### WR-02: `ward_id_property` is not safely configurable across `climatology.py`/`heatwave.py`

**File:** `heatwave/science/climatology.py:117-125` (output dict), `heatwave/science/heatwave.py:60-63` (join filter)
**Issue:** `compute_climatology_thresholds(..., ward_id_property=...)` uses its `ward_id_property` argument only to read the ward id *value* out of the grouped dictionary; the *output* property key is hardcoded as the literal string `"ward_id"` regardless of what was passed in:
```python
"ward_id": ee.Dictionary(g).get(ward_id_property),   # climatology.py:120 — key is always "ward_id"
```
Meanwhile, `flag_heatwave_days(..., ward_id_property=...)` builds its join filter using the *same* `ward_id_property` value against both `ward_daily_fc` and `climatology_fc`:
```python
ee.Filter.equals(leftField=ward_id_property, rightField=ward_id_property)   # heatwave.py:61
```
If a caller passes a non-default `ward_id_property` (e.g. `"wardcode"`) consistently to both `compute_climatology_thresholds` and `flag_heatwave_days` — a reasonable thing to do given both functions expose the parameter — `climatology_fc` will only ever have a `"ward_id"` key, never `"wardcode"`, so the join filter's `rightField="wardcode"` will never match anything against `climatology_fc`. This fails silently (zero joined rows, not an exception), which is exactly the kind of quiet failure this phase's own docstrings elsewhere take pains to avoid.
**Fix:** Either make `compute_climatology_thresholds`'s output key match its `ward_id_property` argument (`ward_id_property: ee.Dictionary(g).get(ward_id_property)`), or remove the parameter's apparent configurability and document explicitly that the climatology/heatwave join contract requires the fixed name `"ward_id"` regardless of what `ward_id_property` is passed elsewhere.

### WR-03: `ClimatologyConfig` performs no runtime validation despite being described as "validated config"

**File:** `heatwave/config.py:12-18, 39-51`
**Issue:** `climatology.py`'s module docstring states the four tuning parameters are "typed, validated config (`ClimatologyConfig`, REWORK-07)". In reality, `ClimatologyConfig` is a plain frozen dataclass with only type *annotations* (not runtime-enforced) and no `__post_init__`/validator logic at all. `load_settings()` passes `raw["climatology"]` straight through `ClimatologyConfig(**raw["climatology"])` with no range or consistency checks. A malformed `config.yaml` — e.g. `percentile: 150`, `baseline_start_year: 2020` with `baseline_end_year: 1991` (start after end), `pooling_window_days: -5`, or `min_consecutive_days: 0` — would load without error and silently propagate into nonsensical `ee.Filter.calendarRange`/percentile calls rather than failing fast at startup.
**Fix:** Add a `__post_init__` to `ClimatologyConfig` that validates each field, e.g.:
```python
def __post_init__(self):
    if not (0 < self.percentile < 100):
        raise ValueError(f"percentile must be in (0, 100), got {self.percentile}")
    if self.baseline_start_year > self.baseline_end_year:
        raise ValueError("baseline_start_year must be <= baseline_end_year")
    if self.pooling_window_days < 0:
        raise ValueError("pooling_window_days must be >= 0")
    if self.min_consecutive_days < 1:
        raise ValueError("min_consecutive_days must be >= 1")
```

## Info

### IN-01: `_props()` test helper cannot distinguish a null property from an absent one

**File:** `tests/test_heatwave_detection.py:58-69`, used by `test_zonal_reduction_tiny_ward_row_is_null_not_dropped` (line 155)
**Issue:** `_props()` reads properties via `feature["properties"].get(key)`, which returns `None` both when a property is present with an explicit JSON `null` value and when the key is absent from the properties dict entirely. `test_zonal_reduction_tiny_ward_row_is_null_not_dropped` asserts `tiny_rows[0]["value"] is None`, which is intended to confirm `zonal.py` sets `"value"` to an explicit null (per its documented contract), but the assertion would pass identically if a future regression stopped setting the `"value"` key at all. The test still correctly proves the *row* isn't dropped (via the `len(tiny_rows) == 1` and `doy` assertions), but it doesn't actually pin down the "null, not absent" nuance its own docstring emphasizes.
**Fix:** Make `_props()` (or a targeted assertion) distinguish the two cases, e.g.:
```python
assert "value" in info["features"][idx]["properties"]
assert info["features"][idx]["properties"]["value"] is None
```

### IN-02: `reduce_to_ward_daily`'s output rows carry more than the documented schema

**File:** `heatwave/zonal.py:66-75`
**Issue:** The docstring states the output "carr[ies]" exactly four properties (`ward_id`, `value`, `doy`, `system:time_start`). In practice, `set_row_properties` calls `feature.set(...)` on the `reduceRegions` output feature, which additively sets those four properties without removing the ward polygon's original properties or its geometry — every one of the ward `FeatureCollection`'s original properties (and its full polygon geometry) is still attached to every one of the N×M output rows. This doesn't break correctness, but it's a documentation/contract mismatch: a Phase 4 caller reading this docstring could reasonably assume the row schema is exactly those four fields and be surprised to find arbitrary ward metadata and geometry riding along on every row.
**Fix:** Either strip to the documented schema explicitly (e.g. `ee.Feature(feature.geometry(), {...four keys...})` or `.select([...], retainGeometry=False)`), or update the docstring to state that ward and image properties/geometry are also retained, not just the four listed fields.

---

_Reviewed: 2026-09-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
