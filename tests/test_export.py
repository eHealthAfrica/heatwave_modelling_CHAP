"""Live, skip-gated tests verifying the Earth Engine batch-export
harness, weekly covariate aggregation, and the batch export script
(EXPORT-01 through EXPORT-04)."""
from __future__ import annotations

import importlib.util
import os
import re
import time
from datetime import date
from pathlib import Path

import ee
import pytest

_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"
_HAS_CREDENTIALS = _KEY_FILE.exists() or bool(os.getenv("EE_SA_JSON"))

# NOTE: This gate is intentionally applied per-test (via `_REQUIRES_CREDENTIALS`) rather
# than as a module-level `pytestmark`. A module-level `pytestmark` would also skip
# `test_export_batch_module_exports`, which 04-VALIDATION.md requires to be runnable
# without live GCP credentials (`pytest tests/test_export.py -k module_exports`). Do
# not "restore" the module-level form.
_REQUIRES_CREDENTIALS = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Live GCP credentials not available (keys/service_account.json or EE_SA_JSON)",
)

# Second, independent gate for the live round-trip test only: this test submits
# a real Earth Engine batch task whose queue+run time is minutes, which blows
# 04-VALIDATION.md's 30-second max-feedback-latency budget, so it is opt-in
# rather than part of the default per-task fast loop -- while still being a
# real (not mocked) verification that Task 3 runs deliberately once.
_RUNS_LIVE_ROUNDTRIP = pytest.mark.skipif(
    not os.getenv("RUN_EE_BATCH_ROUNDTRIP"),
    reason="Set RUN_EE_BATCH_ROUNDTRIP=1 to run the real Earth Engine batch task round-trip (minutes, not seconds)",
)


def _props(fc: ee.FeatureCollection, keys):
    """Materialise a FeatureCollection's properties via a single `.getInfo()` call.

    Returns a plain Python list of dicts, one per feature, containing only the
    requested property keys. An absent property surfaces as `None` rather than
    raising, via `.get(key)`.
    """
    info = fc.getInfo()
    return [
        {key: feature["properties"].get(key) for key in keys}
        for feature in info["features"]
    ]


def test_export_batch_module_exports():
    """EXPORT-04: heatwave.batch exports the full async export harness, no
    credentials required."""
    from heatwave.batch import (
        chunk_asset_id,
        load_task_state,
        poll_until_complete,
        read_asset_rows,
        save_task_state,
        submit_or_resume,
        submit_table_export,
        task_state,
        write_rows_csv,
    )

    assert callable(chunk_asset_id)
    assert callable(load_task_state)
    assert callable(save_task_state)
    assert callable(submit_table_export)
    assert callable(submit_or_resume)
    assert callable(task_state)
    assert callable(poll_until_complete)
    assert callable(read_asset_rows)
    assert callable(write_rows_csv)


def test_batch_task_state_file_save_then_load_returns_same_state(tmp_path):
    """D-04: the task-state file round-trips through save/load, and a missing
    file loads as an empty dict rather than raising.

    Named without the "round_trip" substring so `-k round_trip` selects only
    the live asset round-trip test (04-VALIDATION.md's published selector),
    even though this test's own behavior is also a save/load round trip."""
    from heatwave.batch import load_task_state, save_task_state

    state_file = tmp_path / "tasks.json"
    state = {
        "c001": {
            "task_id": "T1",
            "asset_id": "projects/p/assets/covariate_chunk_c001",
            "state": "SUBMITTED",
        }
    }

    save_task_state(state, state_file)
    loaded = load_task_state(state_file)

    assert loaded == state
    assert load_task_state(tmp_path / "does_not_exist.json") == {}


def test_batch_submit_or_resume_skips_already_submitted_chunk(tmp_path):
    """D-05: a chunk recorded as SUBMITTED/RUNNING/COMPLETED is never
    resubmitted, and the (expensive) collection builder is never invoked."""
    from heatwave.batch import save_task_state, submit_or_resume

    def _raising_builder():
        raise AssertionError("build_collection_fn must not be invoked for a resumable chunk")

    for resumable_state in ("COMPLETED", "RUNNING"):
        state_file = tmp_path / f"tasks_{resumable_state}.json"
        save_task_state(
            {
                "c001": {
                    "task_id": "T-EXISTING",
                    "asset_id": "projects/p/assets/covariate_chunk_c001",
                    "state": resumable_state,
                }
            },
            state_file,
        )

        task_id = submit_or_resume(
            "c001", build_collection_fn=_raising_builder, state_file=state_file
        )

        assert task_id == "T-EXISTING"


def test_batch_submit_or_resume_resubmits_failed_chunk(tmp_path, monkeypatch):
    """D-05: a chunk recorded as FAILED is resubmitted -- the builder runs
    again and the persisted state file records the new task id."""
    import heatwave.batch as batch
    from heatwave.batch import save_task_state, submit_or_resume

    state_file = tmp_path / "tasks.json"
    save_task_state({"c001": {"task_id": "T-OLD", "state": "FAILED"}}, state_file)

    class _StubTask:
        id = "T-NEW"

    build_calls = []

    def _builder():
        build_calls.append(1)
        return "fake-collection"

    def _stub_submit_table_export(collection, asset_id, description):
        return _StubTask()

    monkeypatch.setattr(batch, "submit_table_export", _stub_submit_table_export)

    task_id = submit_or_resume("c001", build_collection_fn=_builder, state_file=state_file)

    assert task_id == "T-NEW"
    assert len(build_calls) == 1
    persisted = batch.load_task_state(state_file)
    assert persisted["c001"]["task_id"] == "T-NEW"


def test_chunk_fingerprint_is_ward_id_and_fallback_order_independent():
    """CR-02: chunk_fingerprint hashes sorted(ward_ids)/sorted(fallback_ward_ids),
    so the same logical chunk fingerprints identically regardless of the
    order its ward-id list happens to be iterated in."""
    from heatwave.batch import chunk_fingerprint

    fp1 = chunk_fingerprint(["W-B", "W-A"], "2020-01-01", "2020-02-01", ["W-B"])
    fp2 = chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2020-02-01", ["W-B"])
    assert fp1 == fp2


def test_chunk_fingerprint_changes_with_date_range_or_ward_set():
    """CR-02: chunk_fingerprint must be sensitive to exactly the parameters
    that determine a chunk's actual contents -- a changed start date, end
    date, ward-id set, or fallback-ward set must each produce a different
    fingerprint."""
    from heatwave.batch import chunk_fingerprint

    base = chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2020-02-01", [])

    assert chunk_fingerprint(["W-A", "W-B"], "2021-01-01", "2020-02-01", []) != base
    assert chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2021-02-01", []) != base
    assert chunk_fingerprint(["W-A", "W-C"], "2020-01-01", "2020-02-01", []) != base
    assert chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2020-02-01", ["W-A"]) != base


def test_batch_submit_or_resume_reuses_when_fingerprint_matches(tmp_path):
    """CR-02: a recorded, resumable state entry IS reused when the caller's
    freshly-computed fingerprint matches the one recorded at submission --
    the fingerprint check must not break ordinary, unchanged-parameters
    resumability."""
    from heatwave.batch import chunk_fingerprint, save_task_state, submit_or_resume

    state_file = tmp_path / "tasks.json"
    fp = chunk_fingerprint(["W-A"], "2020-01-01", "2020-02-01", [])
    save_task_state(
        {"c001": {"task_id": "T-EXISTING", "state": "COMPLETED", "fingerprint": fp}},
        state_file,
    )

    def _raising_builder():
        raise AssertionError("build_collection_fn must not run when the fingerprint matches")

    task_id = submit_or_resume(
        "c001", build_collection_fn=_raising_builder, state_file=state_file, fingerprint=fp
    )

    assert task_id == "T-EXISTING"


def test_batch_submit_or_resume_resubmits_on_fingerprint_mismatch(tmp_path, monkeypatch):
    """CR-02: a chunk recorded as COMPLETED (a RESUMABLE_STATES member) is
    NOT silently reused when the caller supplies a fingerprint that does
    not match the one recorded at submission time -- e.g. because the date
    range or --ward-batch-size partition changed between runs sharing the
    same (often default) --state-file. The mismatch forces the builder to
    run again, a genuinely new task id is submitted, and the persisted
    state records both the new task id and the new fingerprint -- proving
    a config change can never silently serve/mix stale data."""
    import heatwave.batch as batch
    from heatwave.batch import chunk_fingerprint, save_task_state, submit_or_resume

    state_file = tmp_path / "tasks.json"
    old_fingerprint = chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2020-02-01", [])
    save_task_state(
        {
            "c001": {
                "task_id": "T-OLD",
                "asset_id": "projects/p/assets/covariate_chunk_c001",
                "state": "COMPLETED",
                "fingerprint": old_fingerprint,
            }
        },
        state_file,
    )

    class _StubTask:
        id = "T-NEW"

    build_calls = []

    def _builder():
        build_calls.append(1)
        return "fake-collection"

    def _stub_submit_table_export(collection, asset_id, description):
        return _StubTask()

    monkeypatch.setattr(batch, "submit_table_export", _stub_submit_table_export)

    # A different date range now maps to the same chunk_id "c001" -- the
    # exact silent-stale-data scenario CR-02 describes.
    new_fingerprint = chunk_fingerprint(["W-A", "W-B"], "2021-01-01", "2021-02-01", [])
    task_id = submit_or_resume(
        "c001",
        build_collection_fn=_builder,
        state_file=state_file,
        fingerprint=new_fingerprint,
    )

    assert task_id == "T-NEW"
    assert len(build_calls) == 1
    persisted = batch.load_task_state(state_file)
    assert persisted["c001"]["task_id"] == "T-NEW"
    assert persisted["c001"]["fingerprint"] == new_fingerprint


def test_batch_chunk_asset_id_is_namespaced_under_the_configured_project():
    """D-07: chunk_asset_id derives its parent namespace from config, not a
    hardcoded project id, and never collides with the configured ward asset."""
    from heatwave.config import settings
    from heatwave.batch import chunk_asset_id

    asset_id = chunk_asset_id("c001")
    expected_root = settings.ward_asset_id.rsplit("/", 1)[0]

    assert asset_id.startswith(expected_root)
    assert "covariate_chunk_c001" in asset_id
    assert asset_id != settings.ward_asset_id


def test_batch_submit_table_export_rejects_non_covariate_asset_id():
    """T-04-11: submit_table_export raises ValueError before touching Earth
    Engine when the asset id's final segment does not start with the
    covariate_ prefix -- so a chunk export can never overwrite the configured
    ward boundary asset."""
    from heatwave.config import settings
    from heatwave.batch import submit_table_export

    with pytest.raises(ValueError):
        submit_table_export(collection=None, asset_id=settings.ward_asset_id, description="x")

    with pytest.raises(ValueError):
        submit_table_export(
            collection=None,
            asset_id="projects/p/assets/not_prefixed_correctly",
            description="x",
        )


def test_write_rows_csv_writes_columns_in_declared_order(tmp_path):
    """write_rows_csv writes a header equal to the declared columns tuple in
    order, returns the row count, and tolerates a row missing a key."""
    from heatwave.batch import write_rows_csv

    csv_path = tmp_path / "out.csv"
    columns = ("location", "time_period", "heatwave_days")
    rows = [
        {"heatwave_days": 3, "location": "W-A", "time_period": "2020-W01"},
        {"location": "W-B", "time_period": "2020-W01"},  # missing heatwave_days
    ]

    count = write_rows_csv(rows, csv_path, columns)

    assert count == 2
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(columns)
    assert lines[2] == "W-B,2020-W01,"


@_REQUIRES_CREDENTIALS
@_RUNS_LIVE_ROUNDTRIP
def test_batch_export_asset_round_trip():
    """De-risk EXPORT-01: a real Export.table.toAsset submission, polled to
    COMPLETED, read back via pagination (page_size deliberately smaller than
    the row count so the pagination loop is genuinely exercised across more
    than one page), then deleted -- proving both 04-RESEARCH.md's [ASSUMED]
    asset-write-permission row and Open Question 3 (pagination robustness)
    live against heatwave-508110, not by assertion."""
    from heatwave.auth import init_ee
    from heatwave.batch import (
        chunk_asset_id,
        poll_until_complete,
        read_asset_rows,
        submit_table_export,
    )

    init_ee()

    asset_id = chunk_asset_id(f"roundtrip_smoke_{int(time.time())}")
    description = asset_id.rsplit("/", 1)[-1]

    # Rule 1 auto-fix (found live during Task 3): Export.table.toAsset rejects
    # null-geometry features with "Unable to export features with null
    # geometry." -- verified live against heatwave-508110 this session. Each
    # feature is given an arbitrary point geometry (distinct Nigeria-region
    # coordinates, unused by the property-round-trip assertions below) so the
    # export succeeds; this does not change what the test verifies.
    features = [
        ee.Feature(
            ee.Geometry.Point([3.0, 7.0]),
            {"location": "W-RT-A", "time_period": "2020-W23", "heatwave_days": 1},
        ),
        ee.Feature(
            ee.Geometry.Point([5.0, 8.0]),
            {"location": "W-RT-B", "time_period": "2020-W23", "heatwave_days": 2},
        ),
        ee.Feature(
            ee.Geometry.Point([7.0, 9.0]),
            {"location": "W-RT-C", "time_period": "2020-W23", "heatwave_days": 3},
        ),
    ]
    collection = ee.FeatureCollection(features)

    task = submit_table_export(collection, asset_id, description)
    try:
        final_states = poll_until_complete([task.id], poll_interval_s=10, timeout_s=900)
        assert final_states[task.id] == "COMPLETED"

        columns = ("location", "time_period", "heatwave_days")
        rows = list(read_asset_rows(asset_id, columns, page_size=2))
        rows.sort(key=lambda row: row["location"])

        assert len(rows) == 3
        assert rows[0] == {"location": "W-RT-A", "time_period": "2020-W23", "heatwave_days": 1}
        assert rows[1] == {"location": "W-RT-B", "time_period": "2020-W23", "heatwave_days": 2}
        assert rows[2] == {"location": "W-RT-C", "time_period": "2020-W23", "heatwave_days": 3}
    finally:
        try:
            ee.data.deleteAsset(asset_id)
        except Exception:
            pass


# --- EXPORT-02/EXPORT-03 weekly aggregation tests (plan 04-03) ---------------
#
# Everything below reproduces detect_heatwave_events' exact output row schema
# directly via _make_events_fc rather than running the real zonal reduction
# or climatology pass -- per CONTEXT.md's Integration Points, EXPORT-04 tests
# schema and aggregation correctness on a small bounded sample and never runs
# the full historical export inline.


def _make_events_fc(rows):
    """Build an `ee.FeatureCollection` reproducing `detect_heatwave_events`'
    exact output row schema (`ward_id`, `value`, `is_hot`, `event_id`,
    `system:time_start`) directly from literal
    `(ward_id, date_string, value, is_hot, event_id)` tuples.

    This exists so these tests never pay for a real zonal reduction or
    climatology pass (CONTEXT.md Integration Points). `value` may be `None`
    -- `ee.Feature` accepts a Python `None` as an explicit null property,
    reproducing a ward-day whose zonal reduction yielded no value (D-08).
    """
    features = [
        ee.Feature(
            None,
            {
                "ward_id": ward_id,
                "value": value,
                "is_hot": is_hot,
                "event_id": event_id,
                "system:time_start": ee.Date(date_string).millis(),
            },
        )
        for ward_id, date_string, value, is_hot, event_id in rows
    ]
    return ee.FeatureCollection(features)


def test_export_module_exports_aggregation_functions():
    """EXPORT-02/EXPORT-04: heatwave.export exports its ISO-week keying and
    weekly-aggregation functions plus the EXPORT-02 schema constant, no
    credentials required."""
    from heatwave.export import (
        COVARIATE_COLUMNS,
        GROUP_KEY_SEPARATOR,
        add_group_key,
        add_time_period,
        aggregate_weekly_metrics,
        build_covariate_table,
        event_start_weeks,
        iso_time_period,
        iso_year_and_week,
    )

    assert callable(iso_year_and_week)
    assert callable(iso_time_period)
    assert callable(add_time_period)
    assert callable(add_group_key)
    assert callable(aggregate_weekly_metrics)
    assert callable(event_start_weeks)
    assert callable(build_covariate_table)
    assert COVARIATE_COLUMNS == (
        "time_period",
        "location",
        "heatwave_days",
        "mean_heat_index",
        "max_heat_index",
        "heatwave_event_count",
    )
    assert GROUP_KEY_SEPARATOR == "::"


@_REQUIRES_CREDENTIALS
def test_iso_time_period_matches_python_isocalendar_at_year_boundaries():
    """EXPORT-02/D-06: `iso_time_period` renders an ISO week string of the
    form `YYYY-Www`, zero-padded, matching Python's stdlib
    `date.isocalendar()` exactly -- including at the last Monday of
    December, which belongs to the FOLLOWING calendar year's ISO week 1,
    not the current year's week 1 (04-RESEARCH.md Pitfall 2). This test
    fails if anyone reverts `iso_year_and_week` to pairing
    `ee.Date.get('year')` with `ee.Date.get('week')`."""
    from heatwave.auth import init_ee
    from heatwave.export import iso_time_period

    init_ee()

    dates = [
        "2024-12-30",
        "2024-12-31",
        "2025-01-01",
        "2025-01-05",
        "2023-01-01",
        "2023-01-02",
        "2020-12-31",
        "2021-01-01",
    ]
    actual = ee.List([iso_time_period(ee.Date(d)) for d in dates]).getInfo()

    for d, got in zip(dates, actual):
        iso_year, iso_week, _ = date.fromisoformat(d).isocalendar()
        expected = f"{iso_year}-W{iso_week:02d}"
        assert got == expected, f"{d}: expected {expected}, got {got}"


@_REQUIRES_CREDENTIALS
def test_weekly_aggregation_matches_hand_computed_values():
    """EXPORT-02 regression guard for 04-RESEARCH.md Pitfall 4 (chained
    `.group()` calls silently swap values between groups): two wards over
    two ISO weeks, hand-computed per (ward, week) --
    `W-A`/`2020-W23` = mean 100.0 (= (100+110+90)/3), max 110.0,
    heatwave_days 2; `W-B`/`2020-W24` = mean 105.0 (= (80+130)/2), max
    130.0, heatwave_days 1. The two groups differ on EVERY aggregate field
    so a chained-`.group()` swap corrupting any single column -- including
    `mean_heat_index` alone -- is caught."""
    from heatwave.auth import init_ee
    from heatwave.export import add_group_key, add_time_period, aggregate_weekly_metrics

    init_ee()

    rows = [
        ("W-A", "2020-06-01", 100, 1, -1),
        ("W-A", "2020-06-02", 110, 1, -1),
        ("W-A", "2020-06-03", 90, 0, -1),
        ("W-B", "2020-06-08", 80, 0, -1),
        ("W-B", "2020-06-09", 130, 1, -1),
    ]
    events_fc = _make_events_fc(rows)
    dated = add_group_key(add_time_period(events_fc))
    weekly = aggregate_weekly_metrics(dated)

    by_key = {
        f"{r['location']}::{r['time_period']}": r
        for r in _props(
            weekly,
            ("location", "time_period", "mean_heat_index", "max_heat_index", "heatwave_days"),
        )
    }

    a = by_key["W-A::2020-W23"]
    assert a["mean_heat_index"] == pytest.approx(100.0, abs=1e-6)
    assert a["max_heat_index"] == pytest.approx(110.0, abs=1e-6)
    assert a["heatwave_days"] == 2

    b = by_key["W-B::2020-W24"]
    assert b["mean_heat_index"] == pytest.approx(105.0, abs=1e-6)
    assert b["max_heat_index"] == pytest.approx(130.0, abs=1e-6)
    assert b["heatwave_days"] == 1


@_REQUIRES_CREDENTIALS
def test_covariate_table_schema_is_exactly_the_export_02_columns():
    """EXPORT-02: `build_covariate_table`'s output property-key set is
    EXACTLY `{time_period, location, heatwave_days, mean_heat_index,
    max_heat_index, heatwave_event_count}` -- asserted via set equality so
    both a missing and an extra column fail. Internal properties
    (`group_key`, `is_hot`, `event_id`, `run_id`, `doy`, `ward_id`,
    `used_fallback_reducer`, `system:time_start`) must not leak into the
    exported table."""
    from heatwave.auth import init_ee
    from heatwave.export import COVARIATE_COLUMNS, build_covariate_table

    init_ee()

    rows = [
        ("W-A", "2020-06-01", 100, 1, -1),
        ("W-A", "2020-06-02", 110, 1, -1),
    ]
    events_fc = _make_events_fc(rows)
    table = build_covariate_table(events_fc)
    info = table.getInfo()

    assert len(info["features"]) >= 1
    for feature in info["features"]:
        assert set(feature["properties"].keys()) == set(COVARIATE_COLUMNS)


@_REQUIRES_CREDENTIALS
def test_heatwave_event_count_counts_event_starts_not_touched_weeks():
    """EXPORT-02: closes 04-RESEARCH.md Assumption A4 end-to-end -- a
    single ward `W-E` with one 4-day event (`event_id=7`) starting on
    Sunday `2020-06-07` (the last day of ISO week `2020-W23`) and running
    through Wednesday `2020-06-10` (in `2020-W24`) yields
    `heatwave_event_count == 1` for `2020-W23` and `== 0` for `2020-W24` --
    the event is attributed to its STARTING week only, never the week it
    merely continues into. `heatwave_days` is 1 for `2020-W23` (only
    `06-07`) and 3 for `2020-W24` (`06-08`, `06-09`, `06-10`; the trailing
    `06-11`/`06-12` non-event days are not hot)."""
    from heatwave.auth import init_ee
    from heatwave.export import build_covariate_table

    init_ee()

    rows = [
        ("W-E", "2020-06-07", 100, 1, 7),
        ("W-E", "2020-06-08", 101, 1, 7),
        ("W-E", "2020-06-09", 102, 1, 7),
        ("W-E", "2020-06-10", 103, 1, 7),
        ("W-E", "2020-06-11", 50, 0, -1),
        ("W-E", "2020-06-12", 51, 0, -1),
    ]
    events_fc = _make_events_fc(rows)
    table = build_covariate_table(events_fc)

    by_week = {
        r["time_period"]: r
        for r in _props(table, ("time_period", "heatwave_event_count", "heatwave_days"))
    }

    week23 = by_week["2020-W23"]
    week24 = by_week["2020-W24"]
    assert week23["heatwave_event_count"] == 1
    assert week23["heatwave_days"] == 1
    assert week24["heatwave_event_count"] == 0
    assert week24["heatwave_days"] == 3


@_REQUIRES_CREDENTIALS
def test_covariate_table_uses_genuine_zero_for_weeks_without_events():
    """EXPORT-02/D-08 contrast case: a ward-week with real (non-null) data
    and no hot days gets a genuine integer `0` for `heatwave_days` and
    `heatwave_event_count` -- asserted with `== 0`, not `is None`."""
    from heatwave.auth import init_ee
    from heatwave.export import build_covariate_table

    init_ee()

    rows = [
        ("W-C", "2020-06-01", 70, 0, -1),
        ("W-C", "2020-06-02", 72, 0, -1),
    ]
    events_fc = _make_events_fc(rows)
    table = build_covariate_table(events_fc)
    props = _props(table, ("heatwave_days", "heatwave_event_count"))

    assert len(props) == 1
    assert props[0]["heatwave_days"] == 0
    assert props[0]["heatwave_event_count"] == 0


@_REQUIRES_CREDENTIALS
def test_covariate_table_preserves_null_heat_index_rather_than_zero():
    """EXPORT-02/D-08: a ward-week whose every daily `value` is null yields
    `mean_heat_index`/`max_heat_index` of `None` -- explicitly not `0` --
    and the row is still present (never dropped)."""
    from heatwave.auth import init_ee
    from heatwave.export import build_covariate_table

    init_ee()

    rows = [
        ("W-NULL", "2020-06-01", None, 0, -1),
        ("W-NULL", "2020-06-02", None, 0, -1),
    ]
    events_fc = _make_events_fc(rows)
    table = build_covariate_table(events_fc)
    props = _props(table, ("mean_heat_index", "max_heat_index"))

    assert len(props) == 1
    assert props[0]["mean_heat_index"] is None
    assert props[0]["max_heat_index"] is None


@_REQUIRES_CREDENTIALS
def test_covariate_table_completeness_every_ward_week_appears_exactly_once():
    """EXPORT-03: for 3 wards (`W-A`, `W-B`, `W-NULL`) across 2 ISO weeks
    (`2020-W23`, `2020-W24`) -- 3 x 2 = 6 distinct (ward, week) pairs,
    including the two all-null `W-NULL` ward-weeks -- the output has
    exactly 6 rows, and the set of `(location, time_period)` pairs equals
    the set present in the input, with no duplicates and no dropped
    ward-week."""
    from heatwave.auth import init_ee
    from heatwave.export import build_covariate_table

    init_ee()

    rows = [
        ("W-A", "2020-06-01", 100, 1, -1),
        ("W-A", "2020-06-08", 95, 0, -1),
        ("W-B", "2020-06-02", 85, 0, -1),
        ("W-B", "2020-06-09", 130, 1, -1),
        ("W-NULL", "2020-06-03", None, 0, -1),
        ("W-NULL", "2020-06-10", None, 0, -1),
    ]
    events_fc = _make_events_fc(rows)
    table = build_covariate_table(events_fc)
    props = _props(table, ("location", "time_period"))

    pairs = [(p["location"], p["time_period"]) for p in props]
    expected_pairs = {
        ("W-A", "2020-W23"),
        ("W-A", "2020-W24"),
        ("W-B", "2020-W23"),
        ("W-B", "2020-W24"),
        ("W-NULL", "2020-W23"),
        ("W-NULL", "2020-W24"),
    }

    assert len(pairs) == 6
    assert len(set(pairs)) == 6
    assert set(pairs) == expected_pairs


# --- EXPORT-01/EXPORT-03 batch export script tests (plan 04-04) -------------
#
# scripts/run_batch_export.py is deliberately NOT part of the `heatwave`
# package -- pyproject.toml's [tool.setuptools.packages.find] includes only
# `heatwave*` -- so it is loaded here via an explicit file-path import rather
# than a normal package import.

_RUN_BATCH_EXPORT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_batch_export.py"


def _load_run_batch_export():
    """Load scripts/run_batch_export.py as a standalone module.

    An explicit file-path-based module spec load is the stable way to test a
    production entry-point script that is deliberately not an installed
    package, without adding packaging machinery or relying on implicit
    namespace-package resolution. Raises (via the loader) if the script has
    not been created yet -- this is the RED-phase failure mode every
    non-gated test below relies on.
    """
    spec = importlib.util.spec_from_file_location("run_batch_export", _RUN_BATCH_EXPORT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Second, independent opt-in gate, next to _RUNS_LIVE_ROUNDTRIP above: a
# full-pipeline graph (ingest -> heat index -> zonal -> climatology ->
# detection -> weekly aggregation) is expensive even on a tiny sample --
# Phase 3 measured a single lazily-evaluated graph spanning zonal reduction
# through event detection at 65.81s for a 60-row fixture (see
# test_end_to_end_climatology_and_event_pipeline in
# tests/test_heatwave_detection.py), so a full-pipeline graph cannot fit
# 04-VALIDATION.md's 30-second per-task budget. It is opt-in and run
# deliberately in Task 2 of this plan, rather than being dropped or faked.
_RUNS_PIPELINE_SMOKE = pytest.mark.skipif(
    not os.getenv("RUN_EE_PIPELINE_SMOKE"),
    reason="Set RUN_EE_PIPELINE_SMOKE=1 to run the live end-to-end pipeline smoke test (tens of seconds)",
)


def test_persist_polled_task_states_writes_failed_not_submitted(tmp_path):
    """CR-01/IN-01: after polling, persist_polled_task_states writes each
    chunk's polled terminal outcome back to the on-disk state file -- a
    FAILED task must be persisted as FAILED, not left at its original
    SUBMITTED forever. Proves save_task_state (long imported into
    run_batch_export.py, never called before this fix) is actually wired
    up to the collect stage's polled result."""
    from heatwave.batch import load_task_state, save_task_state

    module = _load_run_batch_export()

    state_file = tmp_path / "tasks.json"
    save_task_state(
        {
            "c000": {"task_id": "T-OK", "asset_id": "a0", "state": "SUBMITTED"},
            "c001": {"task_id": "T-BAD", "asset_id": "a1", "state": "SUBMITTED"},
        },
        state_file,
    )
    state = load_task_state(state_file)
    chunks = [("c000", ["W-A"]), ("c001", ["W-B"])]
    final_states = {"T-OK": "COMPLETED", "T-BAD": "FAILED"}

    returned = module.persist_polled_task_states(state, chunks, final_states, state_file)

    assert returned["c000"]["state"] == "COMPLETED"
    assert returned["c001"]["state"] == "FAILED"

    persisted = load_task_state(state_file)
    assert persisted["c000"]["state"] == "COMPLETED"
    assert persisted["c001"]["state"] == "FAILED"


def test_persist_polled_task_states_leaves_unknown_entries_untouched(tmp_path):
    """persist_polled_task_states must not raise or fabricate an entry for
    a chunk_id that was never recorded in state (e.g. it was never
    submitted); a task id absent from final_states keeps its prior
    recorded state rather than being clobbered (this only arises if a
    caller passes a final_states mapping that omits an id it actually
    polled -- poll_until_complete itself always reports every id it was
    given)."""
    from heatwave.batch import load_task_state, save_task_state

    module = _load_run_batch_export()

    state_file = tmp_path / "tasks.json"
    save_task_state({"c000": {"task_id": "T-OK", "state": "SUBMITTED"}}, state_file)
    state = load_task_state(state_file)
    chunks = [("c000", ["W-A"]), ("c999", ["W-Z"])]

    module.persist_polled_task_states(state, chunks, final_states={}, state_file=state_file)

    persisted = load_task_state(state_file)
    assert persisted["c000"]["state"] == "SUBMITTED"
    assert "c999" not in persisted


def test_is_chunk_fingerprint_stale_detects_mismatch_but_not_legacy_entries():
    """CR-02 (collect-stage half): a recorded state entry whose fingerprint
    does not match the freshly-computed one for the chunk's CURRENT
    parameters is stale (e.g. --ward-batch-size changed between --stage
    submit and --stage collect, reshuffling which ward ids this chunk_id
    now maps to) -- but a legacy entry with no recorded fingerprint at all
    is never considered stale, so a state file written before this fix
    does not spuriously lose all resumability."""
    from heatwave.batch import chunk_fingerprint

    module = _load_run_batch_export()

    fp_a = chunk_fingerprint(["W-A", "W-B"], "2020-01-01", "2020-02-01", [])
    fp_b = chunk_fingerprint(["W-A", "W-C"], "2020-01-01", "2020-02-01", [])
    assert fp_a != fp_b

    matching_entry = {"task_id": "T1", "fingerprint": fp_a}
    assert module.is_chunk_fingerprint_stale(matching_entry, fp_a) is False

    mismatched_entry = {"task_id": "T1", "fingerprint": fp_a}
    assert module.is_chunk_fingerprint_stale(mismatched_entry, fp_b) is True

    legacy_entry = {"task_id": "T1"}
    assert module.is_chunk_fingerprint_stale(legacy_entry, fp_b) is False


def test_select_well_separated_sample_indices_spans_the_full_range():
    """WR-05: select_well_separated_sample_indices picks indices spread
    across the full [0, total) range (first, ~middle, last for the
    default sample_count=3), rather than always the same single index --
    the specific bug this whole fix addresses is find_small_wards trusting
    only ever index 0."""
    module = _load_run_batch_export()

    indices = module.select_well_separated_sample_indices(100)
    assert indices[0] == 0
    assert indices[-1] == 99
    assert len(indices) == len(set(indices))
    assert all(0 <= i < 100 for i in indices)
    assert len(indices) <= 3


def test_select_well_separated_sample_indices_handles_small_totals():
    """WR-05: a total smaller than sample_count must not raise or return an
    out-of-range index -- it returns as many distinct, in-range indices as
    are actually available."""
    module = _load_run_batch_export()

    assert module.select_well_separated_sample_indices(0) == []
    assert module.select_well_separated_sample_indices(1) == [0]

    indices_2 = module.select_well_separated_sample_indices(2)
    assert indices_2 == sorted(set(indices_2))
    assert all(0 <= i < 2 for i in indices_2)


def test_fetch_small_ward_sample_images_never_materialises_full_collection(monkeypatch):
    """Regression test for 04-VERIFICATION.md's gap: the pre-fix
    `sample_image_collection.toList(sample_image_collection.size())`
    followed by `.size().getInfo()` eagerly materialised the ENTIRE
    ~35-year default-range ERA5-Land collection into one server-side List
    just to count it, exceeding Earth Engine's "User memory limit" at that
    scale (reproduced live, twice, at both 100 wards and the full 4,841
    -ward count -- see the gap entry). This proves the fix's contract
    without needing a real multi-decade live collection in the fast suite:
    a fake collection declares a size far larger than a single request
    could ever afford to list, and raises immediately if the code under
    test ever asks for anything other than a length-1 sublist -- so this
    test fails loudly if someone reintroduces `.toList(n)` with the full
    collection size."""
    module = _load_run_batch_export()

    class _FakeSublist:
        def __init__(self, offset):
            self._offset = offset

        def get(self, index):
            return self._offset

    class _RecordingImageCollection:
        """Stands in for a huge ee.ImageCollection; records every
        `.toList()` call so the test can assert none of them tried to
        list more than one element."""

        def __init__(self, total):
            self._total = total
            self.toList_calls: list[tuple[int, int]] = []

        def size(self):
            return self

        def getInfo(self):
            return self._total

        def toList(self, count, offset=0):
            self.toList_calls.append((count, offset))
            if count != 1:
                raise AssertionError(
                    f"fetch_small_ward_sample_images must only ever request "
                    f"a length-1 sublist, got toList({count!r}, {offset!r}) "
                    "-- this is exactly the WR-05 regression "
                    "(04-VERIFICATION.md gap) that eagerly materialised the "
                    "whole collection just to count it"
                )
            return _FakeSublist(offset)

    class _FakeEE:
        """Stands in for the `ee` module inside run_batch_export.py --
        `fetch_small_ward_sample_images` only ever touches `ee.Image`."""

        @staticmethod
        def Image(value):
            return value

    monkeypatch.setattr(module, "ee", _FakeEE)

    # A declared size far larger than any real single request could afford
    # to materialise as one List -- proves the fix's cost is independent of
    # collection size (~35 years of daily ERA5-Land images).
    total = 12_784
    fake_collection = _RecordingImageCollection(total=total)

    result = module.fetch_small_ward_sample_images(fake_collection, sample_count=3)

    expected_offsets = module.select_well_separated_sample_indices(total, 3)
    assert result == expected_offsets
    assert fake_collection.toList_calls == [(1, offset) for offset in expected_offsets]
    assert len(fake_collection.toList_calls) <= 3


def test_fetch_small_ward_sample_images_returns_empty_for_empty_collection():
    """An empty collection must short-circuit before any `.toList()` call
    -- `select_well_separated_sample_indices(0)` returns `[]`, so no sample
    should ever be fetched from an empty range."""
    module = _load_run_batch_export()

    class _EmptyImageCollection:
        def size(self):
            return self

        def getInfo(self):
            return 0

        def toList(self, count, offset=0):
            raise AssertionError("must not call toList() on an empty collection")

    result = module.fetch_small_ward_sample_images(_EmptyImageCollection())
    assert result == []


def test_batch_export_script_module_exports():
    """EXPORT-01/EXPORT-04: scripts/run_batch_export.py loads via an
    explicit file-path import and exposes its full documented interface, no
    credentials required. Fails with a loader error until Task 2 creates
    the script (RED)."""
    module = _load_run_batch_export()

    assert callable(module.parse_iso_date)
    assert callable(module.validate_date_range)
    assert callable(module.plan_ward_chunks)
    assert callable(module.build_chunk_collection)
    assert callable(module.assert_ward_coverage)
    assert callable(module.concatenate_chunk_csvs)
    assert callable(module.main)
    assert str(module.DEFAULT_OUTPUT_CSV).replace("\\", "/").endswith("outputs/covariate_table.csv")


def test_batch_export_parse_iso_date_rejects_malformed_input():
    """V5/EXPORT-01: parse_iso_date accepts only YYYY-MM-DD and raises on
    anything else, so a free-form string can never reach ee.Filter.date()
    unparsed."""
    module = _load_run_batch_export()

    assert module.parse_iso_date("2020-01-01") == "2020-01-01"

    for bad_value in ("2020/01/01", "2020-13-45", "last tuesday", "", "2020-01-01 OR 1=1"):
        with pytest.raises(Exception):
            module.parse_iso_date(bad_value)


def test_batch_export_validate_date_range_rejects_inverted_and_prehistoric_ranges():
    """V5/D-01: validate_date_range rejects an empty (start==end) range, an
    inverted range, and a pre-ERA5-Land-collection-start range; a genuinely
    valid range passes through unchanged."""
    module = _load_run_batch_export()

    with pytest.raises(Exception):
        module.validate_date_range("2020-01-01", "2020-01-01")

    with pytest.raises(Exception):
        module.validate_date_range("2021-01-01", "2020-01-01")

    with pytest.raises(Exception):
        module.validate_date_range("1900-01-01", "2020-01-01")

    assert module.validate_date_range("1991-01-01", "2025-09-15") == ("1991-01-01", "2025-09-15")


def test_batch_export_plan_ward_chunks_partitions_without_loss_or_overlap():
    """D-05: plan_ward_chunks partitions ward ids into consecutive,
    zero-padded, deterministic chunks with no loss, no overlap and no
    trailing empty chunk."""
    module = _load_run_batch_export()

    ward_ids_1000 = [f"W-{i:04d}" for i in range(1000)]
    chunks = module.plan_ward_chunks(ward_ids_1000, 250)

    assert len(chunks) == 4
    reconstructed = [ward_id for _, ids in chunks for ward_id in ids]
    assert reconstructed == ward_ids_1000

    chunk_ids = [chunk_id for chunk_id, _ in chunks]
    assert len(set(chunk_ids)) == len(chunk_ids)
    assert all(re.match(r"^c\d+$", chunk_id) for chunk_id in chunk_ids)

    chunks_again = module.plan_ward_chunks(ward_ids_1000, 250)
    assert [chunk_id for chunk_id, _ in chunks_again] == chunk_ids

    ward_ids_1001 = [f"W-{i:04d}" for i in range(1001)]
    chunks_1001 = module.plan_ward_chunks(ward_ids_1001, 250)
    assert len(chunks_1001) == 5
    assert len(chunks_1001[-1][1]) == 1

    assert module.plan_ward_chunks([], 250) == []


def test_batch_export_coverage_gate_rejects_missing_wards():
    """EXPORT-03: assert_ward_coverage raises when the collected and
    expected ward-id sets differ in EITHER direction -- a missing ward is a
    bug, and so is an unexpected extra one."""
    module = _load_run_batch_export()

    module.assert_ward_coverage({"W-1", "W-2"}, {"W-1", "W-2"})

    with pytest.raises(Exception) as excinfo_missing:
        module.assert_ward_coverage({"W-1"}, {"W-1", "W-2"})
    assert "W-2" in str(excinfo_missing.value)

    with pytest.raises(Exception):
        module.assert_ward_coverage({"W-1", "W-3"}, {"W-1"})


def test_batch_export_concatenate_writes_single_header_and_all_rows(tmp_path):
    """D-05/D-06: concatenate_chunk_csvs merges chunk CSVs into one file with
    exactly one COVARIATE_COLUMNS header and every input data row."""
    from heatwave.export import COVARIATE_COLUMNS

    module = _load_run_batch_export()

    header = ",".join(COVARIATE_COLUMNS)
    chunk_a = tmp_path / "chunk_a.csv"
    chunk_b = tmp_path / "chunk_b.csv"
    chunk_a.write_text(
        header + "\n"
        "2020-W23,W-A,1,100.0,110.0,0\n"
        "2020-W24,W-A,0,90.0,95.0,0\n",
        encoding="utf-8",
    )
    chunk_b.write_text(
        header + "\n"
        "2020-W23,W-B,2,80.0,130.0,1\n"
        "2020-W24,W-B,0,70.0,75.0,0\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "covariate_table.csv"
    row_count = module.concatenate_chunk_csvs(
        [chunk_a, chunk_b], output_path, expected_ward_ids={"W-A", "W-B"}
    )

    assert row_count == 4
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert lines[0] == header
    data_rows = set(lines[1:])
    assert data_rows == {
        "2020-W23,W-A,1,100.0,110.0,0",
        "2020-W24,W-A,0,90.0,95.0,0",
        "2020-W23,W-B,2,80.0,130.0,1",
        "2020-W24,W-B,0,70.0,75.0,0",
    }


def test_batch_export_concatenate_refuses_to_finalise_on_incomplete_coverage(tmp_path):
    """EXPORT-03: when the chunk CSVs collectively cover only a subset of
    expected_ward_ids, concatenate_chunk_csvs raises, the target output path
    does NOT exist afterwards, and no sibling temp/partial file survives --
    the guard against a half-failed run leaving a file that looks
    complete."""
    from heatwave.export import COVARIATE_COLUMNS

    module = _load_run_batch_export()

    header = ",".join(COVARIATE_COLUMNS)
    chunk_a = tmp_path / "chunk_a.csv"
    chunk_a.write_text(header + "\n" "2020-W23,W-A,1,100.0,110.0,0\n", encoding="utf-8")

    output_path = tmp_path / "covariate_table.csv"
    before_listing = set(tmp_path.iterdir())

    with pytest.raises(Exception):
        module.concatenate_chunk_csvs([chunk_a], output_path, expected_ward_ids={"W-A", "W-B"})

    assert not output_path.exists()
    after_listing = set(tmp_path.iterdir())
    assert after_listing == before_listing


@_REQUIRES_CREDENTIALS
@_RUNS_PIPELINE_SMOKE
def test_batch_export_small_sample_pipeline_produces_export_02_rows():
    """EXPORT-01: build_chunk_collection composes the full ingest -> heat
    index -> zonal -> climatology -> detection -> weekly-aggregation
    pipeline over 2 real ward ids from the live boundary asset, a ~3-week
    date range, and a 2-year climatology baseline -- proving the composed
    graph actually executes, not merely constructs."""
    from heatwave.data.boundary import load_ward_boundary
    from heatwave.auth import init_ee
    from heatwave.export import COVARIATE_COLUMNS

    init_ee()
    module = _load_run_batch_export()

    ward_ids = load_ward_boundary().limit(2).aggregate_array("wardcode").getInfo()

    table = module.build_chunk_collection(
        ward_ids,
        start_date="2020-06-01",
        end_date="2020-06-22",
        fallback_ward_ids=(),
        baseline_start_year=2019,
        baseline_end_year=2020,
    )

    info = table.limit(5).getInfo()
    assert len(info["features"]) >= 1
    for feature in info["features"]:
        assert set(feature["properties"].keys()) == set(COVARIATE_COLUMNS)
        assert re.match(r"^\d{4}-W\d{2}$", feature["properties"]["time_period"])
