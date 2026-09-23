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


def aggregate_weekly_metrics(
    dated_fc: ee.FeatureCollection,
    ward_id_property: str = "ward_id",
    value_property: str = "value",
) -> ee.FeatureCollection:
    """Aggregate per-(ward, day) rows (already carrying `group_key`) into
    one row per (ward, ISO week): `mean_heat_index`, `max_heat_index` and
    `heatwave_days`.

    Every server-side grouping below uses a SINGLE `.group()` call on the
    composite `group_key`; never chain two `.group()` calls (Pitfall 4).

    Output rows are built from a CANONICAL ward-week key set --
    `dated_fc.aggregate_array("group_key").distinct()` -- rather than from
    the reducer output directly, so no ward-week can ever be silently lost
    (EXPORT-03's completeness guarantee: every distinct (ward, week) in the
    input gets exactly one output row, whatever the reducers do or do not
    return for it).

    Two DIFFERENT, deliberately opposite null-handling rules meet in the
    same output row -- do not "harmonise" them:
      - `mean_heat_index`/`max_heat_index`: an unmatched ward-week means
        there was no usable data at all, which is a null and must NEVER
        become a fabricated `0` (CONTEXT.md D-08).
      - `heatwave_days`: an unmatched ward-week means there were genuinely
        no hot days that week, which is a real `0`, not missing data.
    """
    keys_fc = ee.FeatureCollection(
        dated_fc.aggregate_array("group_key")
        .distinct()
        .map(lambda k: ee.Feature(None, {"group_key": k}))
    )

    # Value metrics: one grouped reduction over ALL rows. `groupField=1` is
    # the INDEX of "group_key" within `selectors`, matching the convention
    # already used in climatology.py.
    metrics_reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.max(), sharedInputs=True)
        .group(groupField=1, groupName="group_key")
    )
    metrics_grouped = dated_fc.reduceColumns(
        reducer=metrics_reducer, selectors=[value_property, "group_key"]
    )
    def _to_metrics_feature(g):
        # A group whose every input value was null omits "mean"/"max"
        # entirely from its dictionary (the same absence-not-nullness
        # convention `heatwave/zonal.py`'s `find_small_wards` documents for
        # reduceRegions) -- `.contains()` before `.get()` reads that
        # absence as an explicit null rather than raising.
        g = ee.Dictionary(g)
        mean = ee.Algorithms.If(g.contains("mean"), g.get("mean"), None)
        max_ = ee.Algorithms.If(g.contains("max"), g.get("max"), None)
        return ee.Feature(None, {"group_key": g.get("group_key"), "mean": mean, "max": max_})

    metrics_fc = ee.FeatureCollection(
        ee.List(metrics_grouped.get("groups")).map(_to_metrics_feature)
    )

    # Hot-day counts: a second grouped reduction over only the is_hot==1
    # rows. Counting a filtered subcollection (rather than summing is_hot
    # across all rows) keeps this the same verified shape as the metrics
    # reduction above and sidesteps how EE treats a null is_hot in a sum.
    hot_rows = dated_fc.filter(ee.Filter.eq("is_hot", 1))
    hot_days_reducer = ee.Reducer.count().group(groupField=1, groupName="group_key")
    hot_grouped = hot_rows.reduceColumns(
        reducer=hot_days_reducer, selectors=["is_hot", "group_key"]
    )
    hot_counts_fc = ee.FeatureCollection(
        ee.List(hot_grouped.get("groups")).map(
            lambda g: ee.Feature(
                None,
                {
                    "group_key": ee.Dictionary(g).get("group_key"),
                    "count": ee.Dictionary(g).get("count"),
                },
            )
        )
    )

    # Outer-join both reductions onto the canonical key set, reusing
    # flag_heatwave_days' null-preserving idiom (heatwave.py lines 74-89):
    # a null-safe outer join followed by an ee.Algorithms.If check on the
    # match.
    metrics_joined = ee.Join.saveFirst("metrics_match", outer=True).apply(
        keys_fc, metrics_fc, ee.Filter.equals(leftField="group_key", rightField="group_key")
    )
    both_joined = ee.Join.saveFirst("hot_days_match", outer=True).apply(
        metrics_joined,
        hot_counts_fc,
        ee.Filter.equals(leftField="group_key", rightField="group_key"),
    )

    def _finalize(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        metrics_match = feature.get("metrics_match")
        hot_days_match = feature.get("hot_days_match")

        # D-08 null rule: no usable data this week -> null, never 0.
        mean_heat_index = ee.Algorithms.If(
            metrics_match, ee.Feature(metrics_match).get("mean"), None
        )
        max_heat_index = ee.Algorithms.If(
            metrics_match, ee.Feature(metrics_match).get("max"), None
        )
        # D-08's opposite rule: genuinely no hot days this week -> real 0,
        # never a null. These two rules must stay different.
        heatwave_days = ee.Algorithms.If(
            hot_days_match, ee.Feature(hot_days_match).get("count"), 0
        )

        parts = ee.String(feature.get("group_key")).split(GROUP_KEY_SEPARATOR)
        return (
            feature.set(
                "location",
                parts.get(0),
                "time_period",
                parts.get(1),
                "mean_heat_index",
                mean_heat_index,
                "max_heat_index",
                max_heat_index,
                "heatwave_days",
                heatwave_days,
            )
            .set("metrics_match", None, "hot_days_match", None)
        )

    return both_joined.map(_finalize)


def event_start_weeks(
    dated_fc: ee.FeatureCollection,
    ward_id_property: str = "ward_id",
) -> ee.FeatureCollection:
    """Count qualifying events by their START week, one row per (ward, ISO
    week) with at least one event start, carrying `group_key` and
    `heatwave_event_count`.

    Reproduces 04-RESEARCH.md Pattern 4's two-stage composition: first
    collapse each event (a (ward_id, event_id) pair, excluding `NO_RUN`) to
    its single earliest `system:time_start` via one `Reducer.min()` group,
    THEN attribute that start date to an ISO week and count starts per
    (ward, week) via a second, independent single-`.group()` count. This
    two-stage structure is what makes an event count in its STARTING week
    only -- a 4-day event beginning on a week's last day and running into
    the next week counts once, in the starting week, and zero times in the
    continuation week.

    04-RESEARCH.md flagged this exact composition as Assumption A4
    (building blocks independently verified live, composition itself not
    yet executed end-to-end); this module's caller,
    `test_heatwave_event_count_counts_event_starts_not_touched_weeks`, is
    the test that closes it.
    """
    real_events = dated_fc.filter(ee.Filter.neq("event_id", NO_RUN))

    def _set_event_key(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        ward_id = ee.String(feature.get(ward_id_property))
        event_id = ee.Number(feature.get("event_id")).format("%d")
        return feature.set("event_key", ward_id.cat(GROUP_KEY_SEPARATOR).cat(event_id))

    real_events = real_events.map(_set_event_key)

    starts_reducer = ee.Reducer.min().group(groupField=1, groupName="event_key")
    starts_grouped = real_events.reduceColumns(
        reducer=starts_reducer, selectors=["system:time_start", "event_key"]
    )

    def _to_start_feature(g):
        g = ee.Dictionary(g)
        parts = ee.String(g.get("event_key")).split(GROUP_KEY_SEPARATOR)
        ward_id = parts.get(0)
        start_date = ee.Date(g.get("min"))
        # The step that makes an event count in its STARTING week only.
        time_period = iso_time_period(start_date)
        group_key = ee.String(ward_id).cat(GROUP_KEY_SEPARATOR).cat(time_period)
        return ee.Feature(None, {"group_key": group_key, "event_marker": 1})

    event_start_features = ee.FeatureCollection(
        ee.List(starts_grouped.get("groups")).map(_to_start_feature)
    )

    count_reducer = ee.Reducer.count().group(groupField=1, groupName="group_key")
    count_grouped = event_start_features.reduceColumns(
        reducer=count_reducer, selectors=["event_marker", "group_key"]
    )

    def _to_count_feature(g):
        g = ee.Dictionary(g)
        return ee.Feature(
            None,
            {"group_key": g.get("group_key"), "heatwave_event_count": g.get("count")},
        )

    return ee.FeatureCollection(ee.List(count_grouped.get("groups")).map(_to_count_feature))


def build_covariate_table(
    events_fc: ee.FeatureCollection,
    ward_id_property: str = "ward_id",
    value_property: str = "value",
) -> ee.FeatureCollection:
    """Build the EXPORT-02 covariate table from `detect_heatwave_events`'
    output: one row per (ward, ISO week), properties EXACTLY
    `COVARIATE_COLUMNS`.

    This is the single entry point plan 04-04's `scripts/run_batch_export.py`
    calls per ward-batch chunk, immediately before handing the result to
    `heatwave.batch.submit_table_export`. Everything it does is
    server-side, so nothing is materialised client-side at full scale.
    """
    dated = add_group_key(add_time_period(events_fc), ward_id_property=ward_id_property)
    weekly = aggregate_weekly_metrics(
        dated, ward_id_property=ward_id_property, value_property=value_property
    )
    starts = event_start_weeks(dated, ward_id_property=ward_id_property)

    joined = ee.Join.saveFirst("event_count_match", outer=True).apply(
        weekly, starts, ee.Filter.equals(leftField="group_key", rightField="group_key")
    )

    def _finalize(feature: ee.Feature) -> ee.Feature:
        feature = ee.Feature(feature)
        match = feature.get("event_count_match")
        # A week with no event start is a genuine zero -- the opposite rule
        # from mean_heat_index's null, D-08.
        heatwave_event_count = ee.Algorithms.If(
            match, ee.Feature(match).get("heatwave_event_count"), 0
        )
        # Constructing a FRESH ee.Feature(None, {...}) rather than .set()-ing
        # onto the joined feature is what guarantees EXPORT-02 schema
        # exactness -- group_key, is_hot, event_id, run_id, doy, ward_id,
        # used_fallback_reducer and system:time_start must not leak into
        # the exported table.
        return ee.Feature(
            None,
            {
                "time_period": feature.get("time_period"),
                "location": feature.get("location"),
                "heatwave_days": feature.get("heatwave_days"),
                "mean_heat_index": feature.get("mean_heat_index"),
                "max_heat_index": feature.get("max_heat_index"),
                "heatwave_event_count": heatwave_event_count,
            },
        )

    return joined.map(_finalize)
