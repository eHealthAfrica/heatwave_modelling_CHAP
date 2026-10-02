"""Build the weekly ward covariate table locally from downloaded ERA5-Land files.

Prerequisite: `python scripts/download_era5_land_gee.py` (fills
<local_data_dir>/era5_land_daily_gee). Ward boundaries are fetched from Earth Engine once
and cached as <local_data_dir>/wards.geojson.

    python scripts/run_local_pipeline.py                       # full record, all wards
    python scripts/run_local_pipeline.py --max-wards 20 --output outputs/covariate_table_local_SAMPLE.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from heatwave.config import settings  # noqa: E402
from heatwave.local.grid import fetch_wards, fill_empty_from_lga, load_wards  # noqa: E402
from heatwave.local.pipeline import ward_daily, weekly_table  # noqa: E402

DEFAULT_OUTPUT_CSV = Path(__file__).resolve().parent.parent / "outputs" / "covariate_table.csv"

log = logging.getLogger("run_local_pipeline")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--max-wards", type=int, default=None, help="first N wards only (for quick checks)")
    parser.add_argument("--refresh-wards", action="store_true", help="re-fetch ward boundaries from Earth Engine")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t0 = time.time()

    wards_file = settings.local_data_dir / "wards.geojson"
    if args.refresh_wards or not wards_file.exists():
        log.info("fetching ward boundaries to %s", wards_file)
        fetch_wards(settings.ward_asset_id, wards_file)
    ward_ids, geoms, lgas = load_wards(wards_file)
    # A few wards in the asset have no geometry at all (area 0). They take the
    # area-weighted average of their LGA; the report lists which ones.
    geoms, filled = fill_empty_from_lga(geoms, lgas)
    if filled:
        report = args.output.parent / "wards_lga_average.csv"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("location,lgacode\n" + "".join(f"{ward_ids[i]},{lgas[i]}\n" for i in filled),
                          encoding="utf-8")
        log.warning("%d wards have no geometry and use their LGA average (listed in %s)", len(filled), report)
    if args.max_wards:
        ward_ids, geoms = ward_ids[: args.max_wards], geoms[: args.max_wards]
    log.info("%d wards", len(ward_ids))

    daily, _ = ward_daily(settings.local_data_dir / "era5_land_daily_gee", ward_ids, geoms)
    log.info("daily series %s to %s", daily.dates[0].date(), daily.dates[-1].date())
    table = weekly_table(daily, settings.climatology)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    part = args.output.with_suffix(".csv.part")
    table.to_csv(part, index=False, float_format="%.3f")
    part.replace(args.output)
    log.info("wrote %s: %d rows (%d wards x %d weeks, %s to %s) in %.1f min",
             args.output, len(table), len(ward_ids), len(table) // len(ward_ids),
             table.time_period.iloc[0], table.time_period.iloc[-1], (time.time() - t0) / 60)


if __name__ == "__main__":
    main()
