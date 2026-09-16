"""Weekly covariate aggregation: per-ward-daily heatwave rows -> the
CHAP-facing covariate table.

Upstream input contract (this module's `events_fc` argument, exactly
`heatwave/science/heatwave.py`'s `detect_heatwave_events` output): one row
per (ward, day), carrying `ward_id` (string), `value` (double, the day's
heat index -- may be null per `heatwave/zonal.py`'s D-08 caller
obligation), `is_hot` (int, 1/0), `event_id` (int, a qualifying event's run
id or `NO_RUN`), and `system:time_start` (long, day timestamp in millis).

Output contract: one row per (ward, ISO week) with properties EXACTLY
`time_period`, `location`, `heatwave_days`, `mean_heat_index`,
`max_heat_index`, `heatwave_event_count` (EXPORT-02's schema, per
CONTEXT.md D-06) -- no more, no fewer.

Caller obligation: this module's aggregation must run entirely server-side,
BEFORE the batch export, so what actually gets exported is the small
weekly grain (~8.8M rows for the full production run) rather than the
large daily grain (~62M rows). `build_covariate_table` is the single entry
point plan 04-04's `scripts/run_batch_export.py` calls per ward-batch
chunk, immediately before handing its result to
`heatwave.batch.submit_table_export`.
"""
from __future__ import annotations

import ee

from heatwave.science.heatwave import NO_RUN

# EXPORT-02's schema, in CSV column order. Plan 04-04's CSV writer consumes
# this tuple directly as its `csv.DictWriter` fieldnames, so the schema and
# the writer's column order can never drift apart.
COVARIATE_COLUMNS: tuple[str, ...] = (
    "time_period",
    "location",
    "heatwave_days",
    "mean_heat_index",
    "max_heat_index",
    "heatwave_event_count",
)

# `ee.String.split()` treats its argument as a regex, so a bare "|" would
# need escaping ("\\|") to avoid matching as regex alternation. "::" needs
# no escaping and is very unlikely to occur inside a ward code or an ISO
# week string.
GROUP_KEY_SEPARATOR: str = "::"


def iso_year_and_week(date: ee.Date) -> tuple[ee.Number, ee.Number]:
    """Return `(iso_week_year, iso_week)` for an `ee.Date`, matching
    Python's `date.isocalendar()` exactly.

    WARNING for future readers: `ee.Date.get('year')` is the plain
    CALENDAR year, not the ISO week-year. `2024-12-30` is a Monday
    belonging to ISO week `2025-W01`, but `get('year')` returns `2024` --
    so naively pairing `get('year')` with `get('week')` silently
    mis-buckets every year's Dec/Jan boundary days across all 35 years of
    the backfill (04-RESEARCH.md Pitfall 2). `date.get("week")` is NOT the
    part that needs fixing -- it is already correct ISO-8601 week
    numbering, verified live -- only the year component needs the
    Thursday-of-the-same-week trick below.

    Live-verified, this session and the prior research session, against
    Python's `date.isocalendar()` ground truth on eight edge-case dates:
    `2024-12-30`, `2024-12-31`, `2025-01-01`, `2025-01-05`, `2023-01-01`,
    `2023-01-02`, `2020-12-31`, `2021-01-01` -- covering both week-53 years
    and both Dec-to-Jan wraparound directions, 100% match. Do not
    "simplify" this back to `(date.get('year'), date.get('week'))`.
    """
    iso_weekday = date.getRelative("day", "week").add(1)  # Monday=1 .. Sunday=7
    thursday_of_this_week = date.advance(ee.Number(4).subtract(iso_weekday), "day")
    return thursday_of_this_week.get("year"), date.get("week")


def iso_time_period(date: ee.Date) -> ee.String:
    """Render `date`'s ISO week as `"YYYY-Www"` (e.g. `"2020-W23"`),
    EXPORT-02's `time_period` format (D-06).

    Uses explicit zero-padding format specifiers, not a bare `.format()`:
    week 1 must render as `W01` (EXPORT-02's example value is `2020-W23`),
    and an unpadded week number would also break lexical sorting of
    `time_period` in the exported CSV.
    """
    iso_year, iso_week = iso_year_and_week(date)
    return ee.String(iso_year.format("%d")).cat("-W").cat(iso_week.format("%02d"))


def add_time_period(
    fc: ee.FeatureCollection,
    time_period_property: str = "time_period",
) -> ee.FeatureCollection:
    """Set `time_period_property` on every feature to its ISO week string,
    derived from its own `system:time_start`.

    `system:time_start` is mandatory on every input row -- it is guaranteed
    by `heatwave/zonal.py`, which sets it precisely so this and every other
    date-derived downstream stage works.
    """

    def _set_time_period(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        date = ee.Date(feature.get("system:time_start"))
        return feature.set(time_period_property, iso_time_period(date))

    return fc.map(_set_time_period)


def add_group_key(
    fc: ee.FeatureCollection,
    ward_id_property: str = "ward_id",
    time_period_property: str = "time_period",
    group_key_property: str = "group_key",
) -> ee.FeatureCollection:
    """Set `group_key_property` on every feature to
    `<ward_id>::<time_period>` (`GROUP_KEY_SEPARATOR`-joined).

    A composite string key exists because `reduceColumns` supports grouping
    by only ONE field per `.group()` call. 04-RESEARCH.md verified live
    that chaining two `.group()` calls to group by (ward, week) returns
    silently swapped, wrong output -- values and week numbers cross-
    assigned between groups -- with no error raised (Pitfall 4). A single
    composite key with one `.group()` call is the verified-correct
    alternative; do not "optimise" this back into chained groups.
    """

    def _set_group_key(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        ward_id = ee.String(feature.get(ward_id_property))
        time_period = ee.String(feature.get(time_period_property))
        return feature.set(group_key_property, ward_id.cat(GROUP_KEY_SEPARATOR).cat(time_period))

    return fc.map(_set_group_key)
