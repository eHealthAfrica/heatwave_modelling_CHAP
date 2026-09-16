"""Live, skip-gated tests verifying the Earth Engine batch-export
harness, weekly covariate aggregation, and the batch export script
(EXPORT-01 through EXPORT-04)."""
from __future__ import annotations

import os
import time
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
