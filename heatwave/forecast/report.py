"""Pre-model data report builders (FEAT-06): label prevalence, timing, row counts, markdown.

Pure functions over Panel / StaticTable / ForecastConfig. No Earth Engine access: the
real-world ERA5-Land delay is a recorded constant, measured once outside this module.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from heatwave.forecast import dataset, splits, targets

CAPTION = "heatwave_week = heatwave_days >= 3; labels from ERA5-Land (reanalysis), 4,841 wards in 19 northern states and the FCT"

# (measured_on, latest_image_date, gap_days) from one-off live measurements (informational only).
MEASURED_DELAYS = (
    (date(2026, 10, 1), date(2026, 9, 23), 8),
    (date(2026, 10, 6), date(2026, 9, 27), 9),
)
OPERATIONAL_DELAY_DAYS = 9
LAT_FAR_NORTH = 11.5
LAT_MIDDLE_BELT = 9.5
ERAS = ((1991, 2000), (2001, 2010), (2011, 2020), (2021, 2026))
GEOZONES = ("NWZ", "NEZ", "NCZ")


def _iso_years(panel) -> np.ndarray:
    return np.array([int(lbl[:4]) for lbl in panel.week_labels], dtype=np.int64)


def _row(weeks_mask, label, n_wards):
    w = label[:, weeks_mask]
    return int(weeks_mask.sum()), int(w.size), (float(w.mean()) if w.size else float("nan"))


def prevalence_tables(panel, static, cfg) -> dict[str, pd.DataFrame]:
    label = targets.heatwave_week_matrix(panel)
    n, _T = label.shape
    years = _iso_years(panel)

    rows = []
    first_y, last_y = int(years.min()), int(years.max())
    for y in sorted(set(years.tolist())):
        wk, vw, prev = _row(years == y, label, n)
        rows.append(
            dict(iso_year=y, weeks=wk, ward_weeks=vw, prevalence=prev, partial=bool(y in (first_y, last_y)))
        )
    by_year = pd.DataFrame(rows)

    st = static.align(panel.wards) if tuple(static.wards) != tuple(panel.wards) else static
    lat = np.asarray(st.lat, dtype=np.float64)
    geo = np.asarray(st.geozone)
    groups = [("geozone", g, geo == g) for g in GEOZONES]
    groups += [
        ("latitude_band", "far_north", lat > LAT_FAR_NORTH),
        ("latitude_band", "central", (lat >= LAT_MIDDLE_BELT) & (lat <= LAT_FAR_NORTH)),
        ("latitude_band", "middle_belt", lat < LAT_MIDDLE_BELT),
    ]
    rows = []
    for grouping, name, m in groups:
        sub = label[m]
        rows.append(
            dict(
                grouping=grouping,
                group=name,
                wards=int(m.sum()),
                ward_weeks=int(sub.size),
                prevalence=float(sub.mean()) if sub.size else float("nan"),
            )
        )
    by_region = pd.DataFrame(rows)

    rows = []
    for lo, hi in ERAS:
        wk, vw, prev = _row((years >= lo) & (years <= hi), label, n)
        rows.append(dict(era=f"{lo}-{hi}", weeks=wk, ward_weeks=vw, prevalence=prev))
    by_era = pd.DataFrame(rows)

    sp = splits.assign_split(np.asarray(panel.week_index, dtype=np.int64), cfg.splits)
    rows = []
    for name in splits.SPLIT_NAMES:
        wk, vw, prev = _row(sp == name, label, n)
        rows.append(dict(split=name, weeks=wk, ward_weeks=vw, prevalence=prev))
    rows.append(dict(split="overall", weeks=int(label.shape[1]), ward_weeks=int(label.size), prevalence=float(label.mean())))
    by_split = pd.DataFrame(rows)
    return {"by_year": by_year, "by_region": by_region, "by_era": by_era, "by_split": by_split}


def effective_days_table(cfg) -> pd.DataFrame:
    rows = []
    for k in cfg.leads:
        rows.append(
            dict(
                lead_weeks=int(k),
                effective_days_ahead=targets.effective_days_ahead(k, cfg.latency_days),
                operational_days_to_target_start=7 * k - 6 - OPERATIONAL_DELAY_DAYS,
                operational_days_to_target_end=7 * k - OPERATIONAL_DELAY_DAYS,
            )
        )
    return pd.DataFrame(rows)


def row_count_table(panel, cfg) -> pd.DataFrame:
    rows = []
    for k in cfg.leads:
        for sp in splits.SPLIT_NAMES:
            ward_pos, origin_pos = dataset.lead_row_index(panel, cfg, k, sp, drop_warmup=True)
            rows.append(
                dict(lead_weeks=int(k), split=sp, rows=int(len(ward_pos)), origins=int(len(np.unique(origin_pos))))
            )
    df = pd.DataFrame(rows)
    p = dataset.warmup_first_position(panel)
    df.attrs["warmup_first_position"] = int(p)
    df.attrs["warmup_first_week"] = panel.week_labels[p]
    df.attrs["warmup_origins_dropped"] = int(p)
    return df


# --------------------------------------------------------------------------- markdown
def _pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100.0 * x:.1f}%"


def _table(df: pd.DataFrame, pct_cols=()) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in pct_cols:
                cells.append(_pct(float(v)))
            elif isinstance(v, (bool, np.bool_)):
                cells.append("yes" if v else "no")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(tables: dict[str, pd.DataFrame], meta: dict) -> str:
    sp = tables["by_split"].set_index("split")["prevalence"]
    yr = tables["by_year"].copy()
    rc = tables["row_counts"]
    first_year, last_year = int(yr["iso_year"].min()), int(yr["iso_year"].max())
    latest = max(MEASURED_DELAYS, key=lambda m: m[0])
    earlier = min(MEASURED_DELAYS, key=lambda m: m[0])
    L = []
    a = L.append
    a("# Pre-model data report: heatwave_week (Phase 9)")
    a("")
    a(CAPTION)
    a("")
    a("## Label definition")
    a("")
    a(
        f"`{targets.LABEL_DEFINITION}`: a ward-week is positive when at least 3 of its 7 days are "
        "heatwave days. This is the weekly `heatwave_days` count in the frozen covariate table, "
        "not `heatwave_event_count` (the number of distinct events starting in the week)."
    )
    a("")
    a("## Provenance")
    a("")
    a(f"- Data version: {meta.get('data_version')}")
    a(f"- Parquet sha256: {meta.get('parquet_sha256')}")
    a(f"- Run id: {meta.get('run_id')}")
    a(f"- Generated (UTC): {meta.get('generated_utc')}")
    a(f"- Wards: {meta.get('n_wards')}; weeks {meta.get('first_week')} to {meta.get('last_week')}")
    a(f"- latency_days (forecast.yaml): {meta.get('latency_days')}")
    a("")
    a("## Prevalence by split")
    a("")
    a(_table(tables["by_split"], ("prevalence",)))
    a("")
    a(
        f"Regime shift: prevalence is {_pct(sp['train'])} in train, {_pct(sp['validate'])} in validate and "
        f"{_pct(sp['test'])} in test. Validation is not representative of test, and neither matches training; "
        "later phases must respect this shift (calibration, thresholds and skill are not transferable "
        "between splits without checking). Splits here are by each week's own start date, before embargo."
    )
    a("")
    a("## Prevalence by era")
    a("")
    a(_table(tables["by_era"], ("prevalence",)))
    a("")
    a("## Prevalence by region")
    a("")
    a(
        f"Geozones NWZ / NEZ / NCZ, and latitude bands: far north (> {LAT_FAR_NORTH}N), "
        f"central ({LAT_MIDDLE_BELT}-{LAT_FAR_NORTH}N), middle belt (< {LAT_MIDDLE_BELT}N)."
    )
    a("")
    a(_table(tables["by_region"], ("prevalence",)))
    a("")
    a("## Prevalence by year")
    a("")
    a(_table(yr, ("prevalence",)))
    a("")
    a(f"Partial years: {first_year} and {last_year} are incomplete (marked partial = yes).")
    a("")
    a("## Timing: effective days ahead")
    a("")
    a(
        "Effective days ahead is the number of days from the issue date to the Monday of the target week "
        f"at latency_days = {meta.get('latency_days')}. The operational columns use the real delay of "
        f"about {OPERATIONAL_DELAY_DAYS} days."
    )
    a("")
    a(_table(tables["effective_days"]))
    a("")
    a("### Operational note: real ERA5-Land delay")
    a("")
    a(
        f"The real ERA5-Land delay was measured once by live Earth Engine query on {latest[0].isoformat()}: "
        f"the latest DAILY_AGGR image was {latest[1].isoformat()}, about {latest[2]} days behind "
        f"(about {earlier[2]} days on {earlier[0].isoformat()}, latest image {earlier[1].isoformat()}). "
        "This is informational only and was not re-measured for this report; no live Earth Engine query was made. "
        f"forecast.yaml sets latency_days = {meta.get('latency_days')}, so lead 1 is the next week after the "
        "last observed week. In real use lead 1's week is mostly past by the time the data arrive, and "
        "lead 2's week ends about 5 days after the issue date."
    )
    a("")
    a("## Row counts per lead and split")
    a("")
    a(
        "After the 14-week training embargo and the feature warm-up "
        f"(first usable origin position {rc.attrs.get('warmup_first_position', meta.get('warmup_first_position'))}, "
        f"{rc.attrs.get('warmup_first_week', meta.get('warmup_first_week'))}; "
        f"{rc.attrs.get('warmup_origins_dropped', meta.get('warmup_first_position'))} earlier origins dropped as warm-up)."
    )
    a("")
    a(_table(rc))
    a("")
    a("## Caveats")
    a("")
    a("- ISO week 53 occurs rarely and its prevalence is very noisy; do not read it on its own.")
    a(f"- The first panel week is {meta.get('first_week')} (1991 starts at W02) and the last is {meta.get('last_week')}, so the first and last years are partial.")
    a("- Labels come from ERA5-Land, a reanalysis, not station observations; they describe modelled heat, not measured heat.")
    a("")
    a(CAPTION)
    a("")
    return "\n".join(L)
