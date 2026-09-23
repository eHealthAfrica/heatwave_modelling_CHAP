"""Earth Engine asynchronous batch-export harness for the covariate table.

The export destination is deliberately this project's own Earth Engine
asset namespace (see `submit_table_export` below) rather than a
Drive-based export -- service-account credentials have no Google Drive
storage quota, producing a `StorageQuotaExceeded` failure (04-RESEARCH.md
Pitfall 1) -- or a Cloud-Storage-bucket-based export (would require
provisioning new infrastructure, forbidden by CONTEXT.md D-07).
Submission and polling are deliberately separate calls so a caller does
not have to hold a process open between them (D-04). Results are read
back in pages because a single unbounded `getInfo()` would exceed Earth
Engine's documented 10MB-request / 100MiB-result limits.
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import ee

from heatwave.config import settings

# Guard prefix -- any asset this module writes must start with this, so a
# typo (or a caller passing the wrong asset id) can never target
# settings.ward_asset_id.
CHUNK_ASSET_PREFIX = "covariate_"
CHUNK_ASSET_BASENAME = "covariate_chunk_"
DEFAULT_STATE_FILE = Path("outputs/.batch_export_tasks.json")
DEFAULT_PAGE_SIZE = 5000
DEFAULT_POLL_INTERVAL_S = 30
TERMINAL_STATES = ("COMPLETED", "FAILED", "CANCELLED")
RESUMABLE_STATES = ("SUBMITTED", "READY", "RUNNING", "COMPLETED")


def chunk_asset_id(chunk_id: str, asset_root: str | None = None) -> str:
    """Build the covariate_-prefixed asset id for a given chunk.

    `asset_root` defaults to the configured ward asset's parent namespace --
    derived from config, never a hardcoded project id (D-07). Returns a
    flat sibling asset id, not a nested folder path: Earth Engine requires
    a parent asset folder to already exist, and D-07 forbids provisioning
    new infrastructure, so this module must not assume or create one.
    """
    if asset_root is None:
        asset_root = settings.ward_asset_id.rsplit("/", 1)[0]
    return f"{asset_root}/{CHUNK_ASSET_BASENAME}{chunk_id}"


def load_task_state(state_file: Path = DEFAULT_STATE_FILE) -> dict:
    """Load the resumable task-state file, or {} if it does not exist yet."""
    state_file = Path(state_file)
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text(encoding="utf-8"))


def save_task_state(state: dict, state_file: Path = DEFAULT_STATE_FILE) -> None:
    """Persist the resumable task-state file, creating its parent directory
    if absent."""
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def submit_table_export(collection: Any, asset_id: str, description: str) -> "ee.batch.Task":
    """Submit an asynchronous asset-export batch task (D-03).

    Validates `asset_id` before any Earth Engine call, per T-04-11: the
    final path segment must start with `CHUNK_ASSET_PREFIX`, so a chunk
    export can never overwrite the configured ward boundary asset.
    """
    final_segment = asset_id.rsplit("/", 1)[-1]
    if not final_segment.startswith(CHUNK_ASSET_PREFIX):
        raise ValueError(
            f"Refusing to export to asset id {asset_id!r}: its final path "
            f"segment {final_segment!r} does not start with the required "
            f"{CHUNK_ASSET_PREFIX!r} prefix."
        )

    task = ee.batch.Export.table.toAsset(
        collection=collection, description=description, assetId=asset_id
    )
    task.start()
    return task


def chunk_fingerprint(
    ward_ids: Iterable[str],
    start_date: str,
    end_date: str,
    fallback_ward_ids: Iterable[str] = (),
) -> str:
    """Fingerprint the parameters that determine a chunk's contents (CR-02).

    `submit_or_resume` keys resumability on `chunk_id` alone (e.g.
    `"c000"`), which carries no information about the ward-id list, date
    range, or fallback-ward set that a particular submission actually used
    to build that chunk's collection. Two runs that reuse the same (often
    default, fixed-path) state file but pass a different `--start-date`/
    `--end-date` or a different `--ward-batch-size` (which changes
    `plan_ward_chunks`'s partition, and therefore which ward ids `"c000"`
    maps to) would otherwise have their stale/mismatched state silently
    trusted. Hashing `sorted(ward_ids)` (order-independent: the same ward
    set must fingerprint identically regardless of iteration order) plus
    the date range plus `sorted(fallback_ward_ids)` lets a caller detect
    that mismatch before trusting a resumable state entry.
    """
    payload = json.dumps(
        {
            "ward_ids": sorted(ward_ids),
            "start": start_date,
            "end": end_date,
            "fallback": sorted(fallback_ward_ids),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def submit_or_resume(
    chunk_id: str,
    build_collection_fn: Callable[[], Any],
    asset_id: str | None = None,
    state_file: Path = DEFAULT_STATE_FILE,
    fingerprint: str | None = None,
) -> str:
    """Submit a chunk's export, or resume its already-recorded task id.

    D-05: a re-run must never resubmit completed or in-flight work, and
    must never rebuild the (expensive) computation graph just to discard
    it. `submit_table_export` is called through this module's own global
    name (not a local alias captured at import time) so a test can
    monkeypatch `heatwave.batch.submit_table_export`.

    `fingerprint` (CR-02, optional): the caller's freshly-computed
    `chunk_fingerprint(...)` for the parameters it is about to build this
    chunk from. When a recorded, otherwise-resumable state entry carries a
    *different* fingerprint than the one just supplied, that recorded state
    was produced by different parameters (a changed date range, a changed
    `--ward-batch-size` partition, or a changed fallback-ward set) and must
    never be silently reused -- this forces a resubmission instead, exactly
    as if no state had been recorded at all. When `fingerprint` is None
    (the default, preserving prior behaviour for callers that do not pass
    one), no fingerprint check is performed.
    """
    if asset_id is None:
        asset_id = chunk_asset_id(chunk_id)

    state = load_task_state(state_file)
    recorded = state.get(chunk_id)
    if recorded is not None and recorded.get("state") in RESUMABLE_STATES:
        if fingerprint is None or recorded.get("fingerprint") == fingerprint:
            return recorded["task_id"]
        # Fingerprint mismatch: fall through and force a resubmission rather
        # than trusting state built from different parameters (CR-02).

    collection = build_collection_fn()
    description = asset_id.rsplit("/", 1)[-1]
    task = submit_table_export(collection, asset_id, description)

    state[chunk_id] = {
        "task_id": task.id,
        "asset_id": asset_id,
        "state": "SUBMITTED",
        "fingerprint": fingerprint,
    }
    save_task_state(state, state_file)
    return task.id


def task_state(task_id: str) -> str:
    """Return the current lifecycle state string for a batch task id."""
    return ee.data.getTaskStatus(task_id)[0]["state"]


def poll_until_complete(
    task_ids: Iterable[str],
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S,
    timeout_s: int | None = None,
) -> dict[str, str]:
    """Poll a set of batch task ids until every one reaches a terminal state.

    Returns a `{task_id: final_state}` mapping. Does not raise on a
    FAILED/CANCELLED task -- reports it in the returned mapping and lets
    the caller decide, so one bad chunk does not abort polling of the rest.
    Raises `TimeoutError` naming the still-pending ids and their last known
    states if `timeout_s` elapses first.
    """
    pending = set(task_ids)
    results: dict[str, str] = {}
    last_known: dict[str, str] = {}
    start = time.time()

    while pending:
        for tid in list(pending):
            state = task_state(tid)
            last_known[tid] = state
            if state in TERMINAL_STATES:
                results[tid] = state
                pending.discard(tid)

        if not pending:
            break

        if timeout_s is not None and (time.time() - start) >= timeout_s:
            pending_states = {tid: last_known.get(tid, "UNKNOWN") for tid in pending}
            raise TimeoutError(
                f"poll_until_complete timed out after {timeout_s}s with tasks "
                f"still pending: {pending_states}"
            )

        time.sleep(poll_interval_s)

    return results


def read_asset_rows(
    asset_id: str, columns: Iterable[str], page_size: int = DEFAULT_PAGE_SIZE
) -> Iterator[dict]:
    """Stream a materialised asset's rows page-by-page as plain dicts.

    A single unbounded `fc.getInfo()` is forbidden here (04-RESEARCH.md
    Anti-Patterns: the 10MB-request / 100MiB-result quota); the caller
    streams this generator rather than materialising it. Breaks out of the
    loop if a page comes back empty, so a shrinking/racing collection
    cannot spin forever.
    """
    columns = list(columns)
    fc = ee.FeatureCollection(asset_id)
    total = fc.size().getInfo()

    offset = 0
    while offset < total:
        page = ee.List(fc.toList(page_size, offset)).getInfo()
        if not page:
            break
        for feature in page:
            properties = feature["properties"]
            yield {column: properties.get(column) for column in columns}
        offset += page_size


def write_rows_csv(rows: Iterable[dict], csv_path: Path, columns: Iterable[str]) -> int:
    """Write rows to a CSV with a header equal to `columns`, in order.

    `restval=""` is deliberate: an empty CSV field preserves "no value"
    rather than fabricating a 0, matching the phase-wide null-versus-zero
    rule. A row missing a key becomes an empty field instead of raising.
    """
    columns = list(columns)
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1

    return count
