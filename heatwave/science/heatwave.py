"""Heatwave day flagging and consecutive-run event detection.

Joins per-ward-daily rows produced by `heatwave/zonal.py` to their own
ward's, own calendar day's climatological threshold from
`heatwave/science/climatology.py`, flags exceedance days (CLIM-03), then
groups consecutive exceedance days into heatwave events subject to the
configured minimum run length (CLIM-04). This is the only stateful
server-side stage in Phase 3: the run-detection state machine below carries
state across elements, so ordering and per-ward partitioning are
correctness-critical, not cosmetic.

Output feeds Phase 4's weekly covariate aggregation into the CHAP
covariate table's `heatwave_days` (from `is_hot`) and
`heatwave_event_count` (count of distinct `event_id` values != NO_RUN)
columns.
"""
from __future__ import annotations

import ee

from heatwave.config import settings

# Sentinel for "not part of a run/event" -- used for every run_id/event_id
# on a non-hot day, and for every run_id whose length never reaches
# min_consecutive_days. Never write a bare -1 in this module; use this name
# so the sentinel's meaning is explicit at every call site.
NO_RUN = -1


def flag_heatwave_days(
    ward_daily_fc: ee.FeatureCollection,
    climatology_fc: ee.FeatureCollection,
    value_property: str = "value",
    ward_id_property: str = "ward_id",
) -> ee.FeatureCollection:
    """Join each ward-day row to its own ward's, own calendar day's threshold
    and flag exceedance (CLIM-03).

    Follows 03-RESEARCH.md Pattern 5 (verified live): an attribute-only
    equi-join keyed on BOTH `ward_id_property` and `doy` -- a single-field
    join on ward alone would silently apply one arbitrary calendar day's
    threshold to a whole year, which is exactly the T-03-13 tampering threat
    this join guards against.

    Returns every input row enriched with:
        threshold   double  the matched climatology row's threshold
        is_hot      int     1 when value > threshold (strictly greater --
                             CLIM-03 says "exceeds", so an exact tie is not
                             a heatwave day, per T-03-14), else 0

    Precondition: `value_property` must be non-null on every input row.
    `heatwave/zonal.py` emits a null `value` for ward polygons below Earth
    Engine's pixel-weight inclusion threshold; deciding the policy for those
    ward-days (never silently counting them as zero heatwave days) is
    Phase 4's job per D-03 and 03-RESEARCH.md Open Question 2. This function
    deliberately does not null-coalesce a missing value to 0 or "not hot" --
    that silent substitution is the data-integrity threat this phase
    documents rather than adopts (T-03-17).

    Join contract: the `(ward_id_property, doy)` join against `climatology_fc`
    is an OUTER join (`ee.Join.saveFirst(..., outer=True)`), not an inner one.
    Any ward-day whose `(ward_id, doy)` has no matching climatology threshold
    (e.g. a baseline data gap, or a newly-added ward with incomplete baseline
    history) still produces exactly one output row, with `threshold` and
    `is_hot` both explicitly null -- it is never silently dropped. Dropping
    the row would corrupt `tag_consecutive_runs`/`detect_heatwave_events`,
    whose state machine assumes gapless, one-row-per-calendar-day input per
    ward (see `detect_heatwave_events`'s docstring for that caller contract).
    """
    join_filter = ee.Filter.And(
        ee.Filter.equals(leftField=ward_id_property, rightField=ward_id_property),
        ee.Filter.equals(leftField="doy", rightField="doy"),
    )
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

    return joined.map(flag_one_row)


def _run_group_step(curr, state):
    """One step of the consecutive-run state machine (03-RESEARCH.md Pattern 6).

    `state` is `ee.List([prev_flag, group_id, tags_so_far])`. The new group
    id is: unchanged while `curr` is 0; the same group id while `curr` is 1
    and `prev_flag` was also 1 (still inside the same run); `group_id + 1`
    while `curr` is 1 and `prev_flag` was 0 (a new 0->1 transition starts a
    new run). The tag appended for this element is the new group id when
    `curr` is 1, else NO_RUN.
    """
    state = ee.List(state)
    prev_flag = ee.Number(state.get(0))
    group_id = ee.Number(state.get(1))
    tags_so_far = ee.List(state.get(2))
    curr = ee.Number(curr)
    new_group_id = ee.Number(
        ee.Algorithms.If(
            curr.eq(1),
            ee.Algorithms.If(prev_flag.eq(1), group_id, group_id.add(1)),
            group_id,
        )
    )
    tagged = ee.Algorithms.If(curr.eq(1), new_group_id, NO_RUN)
    return ee.List([curr, new_group_id, tags_so_far.add(tagged)])


def tag_consecutive_runs(flags_sorted_by_date: ee.List) -> ee.List:
    """Map a date-ordered 0/1 flag list for ONE ward to run ids (CLIM-04).

    Caller obligation: `flags_sorted_by_date` must already be for a single
    ward, in date order, one element per day -- this function does not
    partition by ward and does not sort. Partitioning and sorting are
    `detect_heatwave_events`'s job.

    Live-verified (03-RESEARCH.md Pattern 6): input
    [0,1,1,1,0,1,1,0,0,1,1,1,1,0] produces
    [-1,1,1,1,-1,2,2,-1,-1,3,3,3,3,-1] -- run ids increment on each 0->1
    transition, NO_RUN (-1) marks every non-hot position.

    Scale caveat (Pitfall 5, D-03): `ee.List`'s iterate-based state machine
    was verified correct and fast (well under ~2s) for lists up to 3,650
    elements (~10 years), but has NOT been verified at Phase 4's full
    ~10,950-element (30-year) scale. D-03 scopes this phase to small
    samples, so this state machine is correct to ship here -- Phase 4
    planning must benchmark at full scale before
    reusing this function unchanged; the documented fallback if it proves
    too slow is the array forward-difference run-length pattern (Open
    Question 1 / Alternatives Considered), not an ad hoc pandas
    reimplementation.
    """
    init_state = ee.List([0, 0, ee.List([])])
    final_state = ee.List(flags_sorted_by_date.iterate(_run_group_step, init_state))
    return ee.List(final_state.get(2))


def detect_heatwave_events(
    flagged_fc: ee.FeatureCollection,
    min_consecutive_days: int | None = None,
    ward_id_property: str = "ward_id",
) -> ee.FeatureCollection:
    """Group consecutive hot days into events, per ward (CLIM-04).

    Resolves `min_consecutive_days` from the climatology config section
    (security V5) when omitted -- the literal 3 never appears in this
    module; hardcoding it would be the config-drift tampering threat T-03-16
    documents.

    Partitions `flagged_fc` by `ward_id_property` via a server-side
    `aggregate_array(...).distinct()` and `.map()` -- no Python-level ward
    loop, so this function is ward-count-agnostic (D-04). Each ward's rows
    are sorted by `system:time_start` before the state machine runs;
    `tag_consecutive_runs`'s output is meaningless on unordered input.

    Adds two properties to every row:
        run_id      int  the run id from tag_consecutive_runs, NO_RUN when
                         the day is not hot
        event_id    int  run_id when that run's length reaches
                         min_consecutive_days, else NO_RUN

    T-03-15's per-ward isolation guard: partitioning by `ee.Filter.eq` plus
    the mandatory per-ward sort means one ward's short run can never merge
    with an adjacent ward's run into a false qualifying event.

    Caller contract (CR-01): this function does not verify that each ward's
    sorted rows are gapless, one row per calendar day -- `tag_consecutive_runs`
    treats row-adjacency in the sorted list as calendar-day adjacency, with no
    independent check against `system:time_start`. `flagged_fc` MUST come from
    `flag_heatwave_days` (whose outer join guarantees exactly one output row
    per input ward-day, with `is_hot` explicitly null rather than the row
    being dropped when no climatology threshold matches) or from an
    equivalent gapless source. Feeding this function a `flagged_fc` with
    missing ward-days (e.g. one reconstructed from a filtered or inner-joined
    collection) will silently merge or split runs across the gap.
    """
    # `is not None` (not `or`) so an explicit 0 (meaning "every hot day is
    # its own qualifying event") is not swallowed by falsiness -- mirrors
    # the fix already applied to `window_days` in climatology.py.
    min_consecutive_days = (
        min_consecutive_days
        if min_consecutive_days is not None
        else settings.climatology.min_consecutive_days
    )

    ward_ids = flagged_fc.aggregate_array(ward_id_property).distinct()

    def process_one_ward(ward_id):
        ward_fc = flagged_fc.filter(ee.Filter.eq(ward_id_property, ward_id)).sort("system:time_start")
        flags = ward_fc.aggregate_array("is_hot")
        tags = tag_consecutive_runs(flags)
        feats = ward_fc.toList(ward_fc.size())

        def tag_one_feature(i):
            i = ee.Number(i)
            feature = ee.Feature(feats.get(i))
            run_id = ee.Number(tags.get(i))
            # Run length: how many positions in this ward's tag list share
            # this run_id. ee.List.frequency() verified live on
            # earthengine-api 1.6.8 to return a plain occurrence count.
            run_length = tags.frequency(run_id)
            qualifies = run_id.neq(NO_RUN).And(run_length.gte(min_consecutive_days))
            event_id = ee.Number(ee.Algorithms.If(qualifies, run_id, NO_RUN))
            return feature.set("run_id", run_id, "event_id", event_id)

        return ee.List.sequence(0, ward_fc.size().subtract(1)).map(tag_one_feature)

    return ee.FeatureCollection(ee.List(ward_ids.map(process_one_ward)).flatten())
