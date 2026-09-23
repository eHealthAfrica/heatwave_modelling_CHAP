"""EXPORT-01's production entry point.

Runs the full ingest -> heat-index -> zonal -> climatology -> detection ->
weekly-aggregation pipeline across the ward boundary asset for a
configurable date range and writes the finished covariate table to
`outputs/covariate_table.csv` (D-06).

This module is deliberately NOT part of the pytest suite: the fast test
suite (`tests/test_export.py -k batch_export`) verifies this module's logic
-- date validation, chunk partitioning, the coverage gate, CSV
concatenation -- on small bounded inputs, credential-free and instant. The
real full-history run (D-01's full 1991-present backfill across every ward)
is a separate, deliberate, monitored, hours-long invocation that consumes
real Earth Engine compute quota (D-02). It is never triggered by this
module's import or by the test suite.

The run is split into ward-batch chunks (D-05): this script submits one
Earth Engine batch task per chunk, polls each to completion, and
re-concatenates every chunk's result into the one final table itself, so
the operator never stitches per-chunk outputs together by hand.

No Drive-based export, Cloud-Storage-bucket export, or any other new
remote destination is referenced anywhere in this module (D-07): the only
write target is the project's own Earth Engine asset namespace, via
`heatwave.batch`'s existing `covariate_`-prefixed asset guard.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

# `scripts/` is deliberately not an installed package (pyproject.toml's
# [tool.setuptools.packages.find] includes only `heatwave*`), and running
# this file directly (`python scripts/run_batch_export.py`) sets
# `sys.path[0]` to `scripts/` itself, not the repository root -- so the
# repository root must be added explicitly before the `heatwave.*` imports
# below can resolve when this script is invoked as a standalone entry
# point rather than collected by pytest (which inserts the root itself).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ee

from heatwave.auth import init_ee
from heatwave.batch import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_STATE_FILE,
    chunk_asset_id,
    chunk_fingerprint,
    load_task_state,
    save_task_state,
    submit_or_resume,
    poll_until_complete,
    read_asset_rows,
    write_rows_csv,
)
from heatwave.config import settings
from heatwave.data.boundary import load_ward_boundary
from heatwave.data.ingest import load_era5_land
from heatwave.export import COVARIATE_COLUMNS, build_covariate_table
from heatwave.science.climatology import compute_climatology_thresholds
from heatwave.science.heat_index import compute_heat_index, compute_relative_humidity
from heatwave.science.heatwave import detect_heatwave_events, flag_heatwave_days
from heatwave.zonal import find_small_wards, reduce_to_ward_daily

# 04-RESEARCH.md recommends 200-500 wards per chunk, giving roughly 10-25
# chunks for the full nationwide ward set -- well inside Earth Engine's
# task-queue limits while keeping each task independently retryable (D-05).
EXPORT_DEFAULT_WARD_BATCH_SIZE = 250

# D-06: the predictable path Phase 5's Streamlit rewrite reads.
DEFAULT_OUTPUT_CSV = Path("outputs/covariate_table.csv")

# D-09: a CSV so it is covered by the existing outputs/*.csv gitignore entry
# and is trivially readable by whoever consumes the covariate table.
DEFAULT_SMALL_WARD_REPORT = Path("outputs/small_wards_report.csv")

# The ERA5-Land collection's documented start (see heatwave/data/ingest.py);
# rejects any export range reaching further back than the source data does.
ERA5_LAND_EARLIEST_DATE = "1950-01-02"

# The boundary asset's verified id property (REWORK-05).
WARD_ID_PROPERTY = "wardcode"


def parse_iso_date(value: str) -> str:
    """V5 input validation: accept only a genuine `YYYY-MM-DD` string.

    A caller-supplied date string must never reach `ee.Filter.date()`
    unparsed -- this is the ASVS V5 control 04-RESEARCH.md's Security
    Domain requires for this phase's only externally-supplied value that
    reaches an Earth Engine query. Parsing and re-rendering (rather than
    returning the caller's original string) means only a canonical, already
    -validated value can ever propagate further.
    """
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            f"expected an ISO date YYYY-MM-DD, got {value!r}"
        )
    return parsed.isoformat()


def validate_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    """Validate a (start, end) export range (V5, D-01).

    Rejects an inverted or empty (start == end) range -- `load_era5_land`'s
    underlying date filter is half-open, so an empty range is an operator
    error, not a valid zero-length request -- and rejects a start earlier
    than `ERA5_LAND_EARLIEST_DATE`. Raises `ValueError` (not
    `argparse.ArgumentTypeError`) so this function is usable outside
    argparse, e.g. directly from tests or from `main`'s post-parse checks.
    """
    start_date = parse_iso_date(start_date)
    end_date = parse_iso_date(end_date)

    if start_date >= end_date:
        raise ValueError(
            f"start date {start_date!r} must be strictly before end date "
            f"{end_date!r} (the export range is half-open)"
        )
    if start_date < ERA5_LAND_EARLIEST_DATE:
        raise ValueError(
            f"start date {start_date!r} predates the ERA5-Land collection's "
            f"documented start ({ERA5_LAND_EARLIEST_DATE!r})"
        )

    return start_date, end_date


def plan_ward_chunks(ward_ids: list[str], batch_size: int) -> list[tuple[str, list[str]]]:
    """Partition `ward_ids` into consecutive ward-batch chunks (D-05).

    Returns `(chunk_id, ids)` tuples covering the input exactly once, in
    order, with no overlap and no trailing empty chunk. `chunk_id` is a
    zero-padded, deterministic batch index (e.g. `c000`, `c001`) --
    deterministic because the batch-harness's submit-or-resume helper keys
    its resume state on this id, so a non-deterministic id would silently
    resubmit already-completed work on a re-run.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    total = len(ward_ids)
    if total == 0:
        return []

    chunk_count = (total + batch_size - 1) // batch_size
    width = max(3, len(str(chunk_count - 1)))

    chunks: list[tuple[str, list[str]]] = []
    for index in range(chunk_count):
        start = index * batch_size
        end = min(start + batch_size, total)
        chunk_id = f"c{index:0{width}d}"
        chunks.append((chunk_id, ward_ids[start:end]))
    return chunks


def select_well_separated_sample_indices(total: int, sample_count: int = 3) -> list[int]:
    """Pick up to `sample_count` indices spread evenly across `[0, total)` (WR-05).

    Used to choose which images out of a run's full ERA5-Land image
    collection to sample for small-ward classification (`find_small_wards`)
    -- evenly spread (first, ~middle, last, for the default of 3) rather
    than always reusing a single arbitrary image, so a ward is only
    classified "small" if it agrees across genuinely well-separated sample
    dates. Returns fewer than `sample_count` (deduplicated, sorted)
    indices when `total` is smaller than that -- e.g. `total=1` always
    returns `[0]` -- and never returns an index outside `[0, total)`.
    """
    if total <= 0:
        return []
    if sample_count <= 1 or total == 1:
        return [0]
    positions = {
        round(i * (total - 1) / (sample_count - 1)) for i in range(sample_count)
    }
    return sorted(positions)


def fetch_small_ward_sample_images(
    sample_image_collection: ee.ImageCollection, sample_count: int = 3
) -> list[ee.Image]:
    """Fetch up to `sample_count` well-separated images from
    `sample_image_collection` for WR-05 small-ward classification, WITHOUT
    ever materialising the whole collection into one server-side List
    (04-VERIFICATION.md's gap: the previous
    `sample_image_collection.toList(sample_image_collection.size())`
    followed by `.size().getInfo()` eagerly listed every element of the
    full multi-decade default-range (~35-year) ERA5-Land collection just to
    count it, exceeding Earth Engine's per-request "User memory limit" --
    crashing every `--stage` unconditionally, before printing anything).

    `ee.ImageCollection.size()` returns the element count directly, with no
    listing required, and each sampled index is fetched independently via
    its own length-1 `.toList(1, index)` sublist. So this function's cost
    scales with `sample_count` (at most 3 images fetched), never with the
    size of `sample_image_collection` itself -- safe at the script's true
    default full 1991-present range. Returns `[]` when the collection is
    empty (caller is responsible for treating that as an error).
    """
    sample_image_count = sample_image_collection.size().getInfo()
    if sample_image_count == 0:
        return []
    sample_indices = select_well_separated_sample_indices(sample_image_count, sample_count)
    return [
        ee.Image(sample_image_collection.toList(1, index).get(0))
        for index in sample_indices
    ]


def build_chunk_collection(
    ward_ids,
    start_date: str,
    end_date: str,
    fallback_ward_ids=(),
    baseline_start_year: int | None = None,
    baseline_end_year: int | None = None,
) -> ee.FeatureCollection:
    """Build one ward-batch chunk's covariate rows (EXPORT-01).

    Reproduces the full Phase 1-3 pipeline call sequence, scoped to this
    chunk: ingest -> relative humidity -> heat index -> per-ward-daily
    reduction -> climatology thresholds -> day flagging -> event detection
    -> weekly aggregation. `fallback_ward_ids` must already be pre
    -intersected with this chunk's own ward ids by the caller -- this
    function never re-derives the small-ward set itself (04-RESEARCH.md
    Pitfall 5: a per-chunk re-derivation could switch a ward's reducer
    mid-series).
    """
    wards = load_ward_boundary().filter(
        ee.Filter.inList(WARD_ID_PROPERTY, ee.List(list(ward_ids)))
    )
    images = load_era5_land(boundary=wards, start_date=start_date, end_date=end_date)
    images = images.map(compute_relative_humidity).map(compute_heat_index)

    ward_daily = reduce_to_ward_daily(
        images, wards, ward_id_property=WARD_ID_PROPERTY, fallback_ward_ids=fallback_ward_ids
    )
    thresholds = compute_climatology_thresholds(
        ward_daily, baseline_start_year=baseline_start_year, baseline_end_year=baseline_end_year
    )
    flagged = flag_heatwave_days(ward_daily, thresholds)
    events = detect_heatwave_events(flagged)
    table = build_covariate_table(events)

    # Live-verified this session (and first found live in plan 04-01's own
    # round-trip test): Export.table.toAsset rejects every feature with a
    # null geometry ("Unable to export features with null geometry."). The
    # weekly covariate rows built above deliberately carry no geometry --
    # none of COVARIATE_COLUMNS is spatial -- so a placeholder point is
    # attached here, at the export boundary, rather than inside the
    # general-purpose aggregation module. The placeholder never reaches the
    # final CSV: read_asset_rows only ever reads the declared property
    # columns.
    return table.map(lambda feature: ee.Feature(feature).setGeometry(ee.Geometry.Point([0, 0])))


def assert_ward_coverage(collected_ward_ids: set, expected_ward_ids: set) -> None:
    """EXPORT-03's "no missing wards" guarantee.

    Raises when the collected and expected ward-id sets differ in EITHER
    direction, naming up to 20 differing ids on each side plus the total
    counts. This is 04-RESEARCH.md's Security Domain control: the final
    concatenation must verify the union of chunk ward ids equals the full
    expected set, never just concatenate whatever chunk CSVs happen to
    exist on disk.
    """
    collected_ward_ids = set(collected_ward_ids)
    expected_ward_ids = set(expected_ward_ids)

    missing = expected_ward_ids - collected_ward_ids
    unexpected = collected_ward_ids - expected_ward_ids

    if missing or unexpected:
        raise RuntimeError(
            "Ward coverage mismatch: "
            f"{len(missing)} missing (expected but not collected), "
            f"{len(unexpected)} unexpected (collected but not expected). "
            f"Missing sample: {sorted(missing)[:20]}. "
            f"Unexpected sample: {sorted(unexpected)[:20]}."
        )


def is_chunk_fingerprint_stale(entry: dict, expected_fingerprint: str) -> bool:
    """True when a chunk's recorded state entry was built from different
    parameters than the ones just computed for it (CR-02, collect-stage
    half).

    `--stage collect` recomputes `chunks` independently from
    `args.ward_batch_size` (and the current date range / small-ward set),
    just like `--stage submit` does -- if either changed between the two
    invocations while reusing the same state file, `chunk_id` could now
    map to a different ward subset than the one the recorded asset was
    actually built from. Returns False (not stale) when the recorded entry
    predates fingerprinting (`entry.get("fingerprint")` is None), so a
    legacy state file written before this fix does not spuriously lose all
    resumability.
    """
    recorded_fingerprint = entry.get("fingerprint")
    return recorded_fingerprint is not None and recorded_fingerprint != expected_fingerprint


def persist_polled_task_states(
    state: dict,
    chunks: list[tuple[str, list[str]]],
    final_states: dict[str, str],
    state_file: Path,
) -> dict:
    """Write each chunk's polled terminal outcome back into the task-state
    file (CR-01/IN-01).

    `submit_or_resume` writes `state[chunk_id]["state"] = "SUBMITTED"`
    exactly once, at submission time, and nothing else in this module ever
    updated it -- `save_task_state` was imported but never called. Without
    this, a chunk whose task actually transitioned to FAILED/CANCELLED
    stayed recorded as SUBMITTED (a `RESUMABLE_STATES` member) forever, so
    a later `--stage submit` retry would see the stale entry, treat it as
    still in-flight, and silently skip resubmission -- there was no way to
    recover short of hand-editing the state file. Mutates and returns
    `state` in place for convenience; always calls `save_task_state`, even
    if no entry actually changed, so callers never have to remember to
    call it separately.
    """
    for chunk_id, _ in chunks:
        entry = state.get(chunk_id)
        if entry is not None:
            entry["state"] = final_states.get(entry["task_id"], entry.get("state", "UNKNOWN"))
    save_task_state(state, state_file)
    return state


def concatenate_chunk_csvs(
    chunk_csvs, output_path: Path, expected_ward_ids: set
) -> int:
    """Merge every chunk CSV into one final table, coverage-gated (D-05/D-06, EXPORT-03).

    Reads every chunk CSV, verifies each file's header equals
    `list(COVARIATE_COLUMNS)` -- a mismatched header means a chunk was
    produced by a different schema version and must abort, not be silently
    coerced -- accumulates the collected `location` values, and streams
    rows into a temporary file in `output_path`'s own directory. The
    two-directional coverage gate runs BEFORE the temporary file is
    promoted; on any failure the temporary file is removed so no sibling
    artefact survives to be mistaken for the real table. Promotion is an
    atomic rename, so `output_path` either does not exist or is complete,
    never half-written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(COVARIATE_COLUMNS)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8", dir=output_path.parent, delete=False
    )
    tmp_path = Path(tmp.name)
    row_count = 0
    collected_ward_ids: set = set()

    try:
        writer = csv.DictWriter(tmp, fieldnames=columns)
        writer.writeheader()

        for chunk_csv in chunk_csvs:
            chunk_csv = Path(chunk_csv)
            with open(chunk_csv, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != columns:
                    raise ValueError(
                        f"Chunk CSV {chunk_csv} has header {reader.fieldnames!r}, "
                        f"expected {columns!r} -- refusing to merge a mismatched schema"
                    )
                for row in reader:
                    writer.writerow(row)
                    row_count += 1
                    collected_ward_ids.add(row["location"])

        tmp.close()
        assert_ward_coverage(collected_ward_ids, expected_ward_ids)
        os.replace(tmp_path, output_path)
    except Exception:
        tmp.close()
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return row_count


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (EXPORT-01).

    Default `--start-date`/`--end-date` derive the full historical backfill
    from config (D-01) rather than from a hardcoded literal, and
    deliberately not from the viewer's own ingestion window, which predates
    the climatology baseline. `--stage plan` prints the chunk plan, the
    D-09 small-ward report count, and the D-02 quota/runtime warning, then
    returns without submitting any Earth Engine task.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        type=parse_iso_date,
        default=f"{settings.climatology.baseline_start_year}-01-01",
    )
    parser.add_argument("--end-date", type=parse_iso_date, default=settings.end_date)
    parser.add_argument(
        "--ward-batch-size", type=int, default=EXPORT_DEFAULT_WARD_BATCH_SIZE
    )
    parser.add_argument("--max-wards", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument(
        "--stage", choices=("plan", "submit", "collect", "all"), default="all"
    )
    args = parser.parse_args(argv)

    try:
        start_date, end_date = validate_date_range(args.start_date, args.end_date)
    except ValueError as exc:
        print(f"Invalid export date range: {exc}", file=sys.stderr)
        return 2

    init_ee()

    ward_ids = sorted(load_ward_boundary().aggregate_array(WARD_ID_PROPERTY).getInfo())
    if args.max_wards is not None:
        ward_ids = ward_ids[: args.max_wards]

    chunks = plan_ward_chunks(ward_ids, args.ward_batch_size)

    # D-08/D-09: run the small-ward detection exactly once per run, before
    # chunking, and reuse its result for every chunk (04-RESEARCH.md
    # Pitfall 5 -- never re-derive this per chunk or per day).
    wards_fc = load_ward_boundary().filter(
        ee.Filter.inList(WARD_ID_PROPERTY, ee.List(ward_ids))
    )
    sample_image_collection = load_era5_land(
        boundary=wards_fc, start_date=start_date, end_date=end_date
    ).map(compute_relative_humidity).map(compute_heat_index)

    # WR-05: cross-validate small-ward classification against 2-3
    # well-separated sample dates rather than trusting a single arbitrary
    # image -- find_small_wards only classifies a ward as small when EVERY
    # sample agrees, so one incidental data anomaly on a single day (a rare
    # EE nodata sliver, boundary rasterization jitter) can no longer, by
    # itself, permanently and silently downgrade an otherwise normal-sized
    # ward to the lower-fidelity centroid-fallback path for the entire run.
    sample_images = fetch_small_ward_sample_images(sample_image_collection)
    if not sample_images:
        print(
            f"No ERA5-Land images available in {start_date}..{end_date} to "
            "determine small-ward classification from",
            file=sys.stderr,
        )
        return 2

    small_ward_ids = find_small_wards(
        sample_images, wards_fc, ward_id_property=WARD_ID_PROPERTY
    ).getInfo()

    DEFAULT_SMALL_WARD_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_SMALL_WARD_REPORT, "w", newline="", encoding="utf-8") as f:
        report_writer = csv.writer(f)
        report_writer.writerow(["ward_id"])
        for small_ward_id in small_ward_ids:
            report_writer.writerow([small_ward_id])

    print(f"D-09 small-ward (centroid-fallback) count: {len(small_ward_ids)}", file=sys.stderr)
    if small_ward_ids:
        print(f"D-09 small-ward sample: {small_ward_ids[:5]}", file=sys.stderr)

    print(f"Validated export range: {start_date} to {end_date}")
    print(f"Ward count: {len(ward_ids)}")
    print(f"Chunk count: {len(chunks)} (ward-batch size {args.ward_batch_size})")
    print(f"Small-ward count (D-08/D-09): {len(small_ward_ids)}")
    print(
        "WARNING (D-01/D-02): the full range consumes real Earth Engine compute "
        "quota and can take HOURS to complete. Review this plan before submitting."
    )

    if args.stage == "plan":
        return 0

    small_ward_set = set(small_ward_ids)

    if args.stage in ("submit", "all"):
        for chunk_id, chunk_ward_ids in chunks:
            chunk_fallback_ids = [w for w in chunk_ward_ids if w in small_ward_set]
            # CR-02: fingerprint the exact parameters this chunk is built
            # from (its ward-id list, the date range, its fallback-ward
            # subset) so submit_or_resume can detect a config change across
            # runs that share the same (often default, fixed-path) state
            # file -- e.g. a different --start-date/--end-date or a
            # different --ward-batch-size that reshuffles which ward ids
            # this chunk_id maps to -- and force a resubmission instead of
            # silently trusting stale/mismatched recorded state.
            fingerprint = chunk_fingerprint(
                chunk_ward_ids, start_date, end_date, chunk_fallback_ids
            )
            submit_or_resume(
                chunk_id,
                build_collection_fn=lambda wids=chunk_ward_ids, fbids=chunk_fallback_ids: build_chunk_collection(
                    wids, start_date, end_date, fallback_ward_ids=fbids
                ),
                asset_id=chunk_asset_id(chunk_id),
                state_file=args.state_file,
                fingerprint=fingerprint,
            )

    if args.stage == "submit":
        return 0

    if args.stage in ("collect", "all"):
        state = load_task_state(args.state_file)
        task_ids = [state[cid]["task_id"] for cid, _ in chunks if cid in state]
        final_states = poll_until_complete(task_ids, poll_interval_s=args.poll_interval)

        # CR-01/IN-01: persist the polled outcome immediately, before doing
        # anything else with it, so a later --stage submit can always tell a
        # genuinely FAILED/CANCELLED chunk apart from one still resumable --
        # even if this process is interrupted partway through the rest of
        # the collect loop below.
        state = persist_polled_task_states(state, chunks, final_states, args.state_file)

        chunk_csvs = []
        chunk_dir = args.output.parent
        chunk_dir.mkdir(parents=True, exist_ok=True)

        for chunk_id, chunk_ward_ids in chunks:
            entry = state.get(chunk_id)
            if entry is None:
                print(f"No recorded task for chunk {chunk_id}; skipping", file=sys.stderr)
                continue

            # CR-02: chunks are recomputed here from args.ward_batch_size,
            # independently of whatever partition was used at --stage
            # submit time. If --ward-batch-size (or the date range, or the
            # small-ward set) differs between the submit and collect
            # invocations, chunk_id could now map to a different ward
            # subset than the one the recorded asset was actually built
            # from -- refuse to pair mismatched expectations rather than
            # silently collecting them.
            chunk_fallback_ids = [w for w in chunk_ward_ids if w in small_ward_set]
            expected_fingerprint = chunk_fingerprint(
                chunk_ward_ids, start_date, end_date, chunk_fallback_ids
            )
            if is_chunk_fingerprint_stale(entry, expected_fingerprint):
                print(
                    f"Chunk {chunk_id}'s recorded fingerprint does not match this "
                    "run's current parameters (date range/--ward-batch-size/ward "
                    "set changed since --stage submit); refusing to collect "
                    "potentially mismatched state -- rerun --stage submit with a "
                    "fresh --state-file",
                    file=sys.stderr,
                )
                continue

            final_state = final_states.get(entry["task_id"], "UNKNOWN")
            if final_state != "COMPLETED":
                print(
                    f"Chunk {chunk_id} ended in state {final_state}; excluded from concatenation",
                    file=sys.stderr,
                )
                continue

            chunk_csv_path = chunk_dir / f"{chunk_id}.csv"
            rows = read_asset_rows(entry["asset_id"], COVARIATE_COLUMNS)
            write_rows_csv(rows, chunk_csv_path, COVARIATE_COLUMNS)
            chunk_csvs.append(chunk_csv_path)

        row_count = concatenate_chunk_csvs(
            chunk_csvs, args.output, expected_ward_ids=set(ward_ids)
        )
        print(f"Wrote {row_count} rows to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
