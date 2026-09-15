"""Per-ward, per-calendar-day percentile climatology baseline (CLIM-01) with a
±N-day pooling window (CLIM-02) over the per-ward-daily FeatureCollection
produced by `heatwave/zonal.py`.

Day-of-year follows the 1-366 WMO/ETCCDI convention (D-05): Feb 29 gets its
own real doy=60 slot, never merged into or fallback-shared with Feb 28's
doy=59. Pooling windows wrap across the year boundary in both directions
(D-06) via explicit floor-mod arithmetic feeding ee.Filter.calendarRange's
native start>end wrap.
"""
from __future__ import annotations

import ee

from heatwave.config import settings

# Feb 29 gets its own day-of-year slot (D-05), so the modulus for wraparound
# arithmetic is 366, not 365, everywhere in this module.
DAYS_IN_LEAP_YEAR = 366


def floor_mod(n, m) -> ee.Number:
    """Python-style floored modulo: the result is always in [0, m), never negative.

    `ee.Number.mod()` uses a truncated, sign-follows-dividend convention (like
    JS/C), so `ee.Number(-3).mod(366)` returns -3, not 363 (verified live,
    03-RESEARCH.md Pitfall 2). Feeding a negative value to
    `ee.Filter.calendarRange` raises
    `Filter.calendarRange: Start and end date values must be >= 0`.
    Never "fix" that error by clamping to 0 -- the mod arithmetic above is
    the actual fix.
    """
    n = ee.Number(n)
    r = n.mod(m)
    return ee.Number(ee.Algorithms.If(r.lt(0), r.add(m), r))


def wrapped_day(n) -> ee.Number:
    """Map any integer day offset onto the 1..366 range, wrapping in both directions.

    Live-verified mappings (03-RESEARCH.md Pattern 3): -3 -> 363, 0 -> 366,
    1 -> 1, 366 -> 366, 367 -> 1, 730 -> 364.
    """
    return floor_mod(ee.Number(n).subtract(1), DAYS_IN_LEAP_YEAR).add(1)


def pooling_window_filter(doy, window_days) -> ee.Filter:
    """Return a calendarRange day_of_year filter for the ±window_days pool around doy.

    `ee.Filter.calendarRange` wraps natively when start > end (verified live:
    `calendarRange(363, 5, 'day_of_year')` matched both Dec 30-31 and Jan 1-5),
    so a manual union of two separate calendarRange filters is unnecessary and
    must not be added -- the only explicit wraparound handling needed is the
    floor-mod arithmetic in `wrapped_day` above (D-06).
    """
    doy = ee.Number(doy)
    start = wrapped_day(doy.subtract(window_days))
    end = wrapped_day(doy.add(window_days))
    return ee.Filter.calendarRange(start, end, "day_of_year")


def compute_climatology_thresholds(
    ward_daily_fc: ee.FeatureCollection,
    percentile: int | None = None,
    window_days: int | None = None,
    baseline_start_year: int | None = None,
    baseline_end_year: int | None = None,
    value_property: str = "value",
    ward_id_property: str = "ward_id",
) -> ee.FeatureCollection:
    """Compute the per-ward, per-calendar-day percentile climatology baseline (CLIM-01/CLIM-02).

    Resolves the four tuning parameters (percentile, pooling window, and both
    baseline years) from `heatwave.config.settings.climatology` when omitted
    (security V5) -- none of the configured default values appear as bare
    literals in this module; they are typed, validated config
    (`ClimatologyConfig`, REWORK-07), and hardcoding them is the config-drift
    tampering threat documented in 03-RESEARCH.md's Security Domain.

    Returns one feature per (ward_id, doy) that has pooled baseline data, each
    carrying `ward_id_property` (keyed by the actual `ward_id_property`
    argument, not a hardcoded `"ward_id"` literal -- WR-02), `doy`, and
    `threshold`. These output rows deliberately carry no `system:time_start`
    -- they are joined on (`ward_id_property`, `doy`) by
    `heatwave/science/heatwave.py` and are never calendarRange-filtered, so a
    future reader should not "restore" a timestamp they think is missing.
    """
    percentile = percentile or settings.climatology.percentile
    # `is not None` (not `or`) so an explicit 0 (the Feb-29 test's no-pooling
    # case) is not swallowed by falsiness.
    window_days = window_days if window_days is not None else settings.climatology.pooling_window_days
    baseline_start_year = baseline_start_year or settings.climatology.baseline_start_year
    baseline_end_year = baseline_end_year or settings.climatology.baseline_end_year

    # Reads the year from system:time_start (Pitfall 1) -- this is why
    # heatwave/zonal.py sets it on every row.
    baseline = ward_daily_fc.filter(
        ee.Filter.calendarRange(baseline_start_year, baseline_end_year, "year")
    )

    percentile_key = "p" + str(percentile)

    def threshold_for_day(doy):
        doy = ee.Number(doy)
        pooled = baseline.filter(pooling_window_filter(doy, window_days))
        # One reducer call per calendar day, grouped by ward -- NOT a Python
        # loop over wards (D-04's ward-count-agnostic requirement rules out
        # a nested wards.map(ward -> days.map(...)) O(wards x days) loop).
        # The group field below is an INDEX into `selectors` (index 1 =
        # ward_id_property), not a property name -- verified live.
        grouped = pooled.reduceColumns(
            reducer=ee.Reducer.percentile([percentile]).group(
                groupField=1, groupName=ward_id_property
            ),
            selectors=[value_property, ward_id_property],
        )
        groups = ee.List(grouped.get("groups"))
        return groups.map(
            lambda g: ee.Feature(
                None,
                {
                    # Output key matches the `ward_id_property` argument
                    # (WR-02) -- hardcoding this to the literal "ward_id"
                    # would silently break `flag_heatwave_days`'s join when
                    # a non-default `ward_id_property` is passed to both
                    # functions consistently, since the join filter there
                    # matches on `ward_id_property` against both sides.
                    ward_id_property: ee.Dictionary(g).get(ward_id_property),
                    "doy": doy,
                    "threshold": ee.Dictionary(g).get(percentile_key),
                },
            )
        )

    # Per D-02 and 03-RESEARCH.md Pitfall 3: ee.Reducer.percentile() does not
    # match numpy's default interpolation (EE returns 9.5 for the sample
    # 1..10 at p90; numpy's default 'linear' method returns 9.1). No
    # numpy/pandas/scipy/statistics reference implementation of this math may
    # be introduced here or in tests.
    return ee.FeatureCollection(
        ee.List(ee.List.sequence(1, DAYS_IN_LEAP_YEAR).map(threshold_for_day)).flatten()
    )
