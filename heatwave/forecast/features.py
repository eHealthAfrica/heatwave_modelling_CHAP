"""As-of feature families on the dense (ward x week) panel (FEAT-03).

Every panel feature at origin position t is a pure float32 function of panel weeks <= t:
trailing windows are full-window-or-NaN (no forward fill, no centred windows, no negative
shifts), the 10-year base rate only reads anchors in prior ISO years, and spatial means
use the same week t only. Climatology anomalies come from the already fitted object that
is passed in; this module never refits it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from heatwave.forecast.registry import FAMILIES, FeatureSpec, Registry

HW_DAYS_THRESHOLD = 3  # kept independent of targets.py; a test asserts the two are equal
LONGEST_FIXED_WINDOW_WEEKS = 156
BASE_RATE_YEARS = 10
BASE_RATE_POOL_WEEKS = 2
BASE_RATE_MIN_OBS = 15


# --------------------------------------------------------------------------- helpers
def _check_k(k, name):
    if type(k) is not int or k < 0:
        raise ValueError(f"{name} must be a non-negative int, got {k!r}")
    return k


def lag(x: np.ndarray, k: int) -> np.ndarray:
    """out[:, t] = x[:, t-k]; NaN for t < k."""
    _check_k(k, "k")
    out = np.full(x.shape, np.nan, dtype=np.float32)
    if k == 0:
        out[:] = x
    elif k < x.shape[1]:
        out[:, k:] = x[:, :-k]
    return out


def _windows(x, w):
    if type(w) is not int or w < 1:
        raise ValueError(f"window must be an int >= 1, got {w!r}")
    return sliding_window_view(x, w, axis=1) if w <= x.shape[1] else None


def trail_mean(x: np.ndarray, w: int) -> np.ndarray:
    """Mean of x[:, t-w+1..t]; NaN until a full window exists. float64 accumulation."""
    out = np.full(x.shape, np.nan, dtype=np.float32)
    win = _windows(x, w)
    if win is not None:
        out[:, w - 1 :] = win.mean(axis=2, dtype=np.float64)
    return out


def trail_sum(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float32)
    win = _windows(x, w)
    if win is not None:
        out[:, w - 1 :] = win.sum(axis=2, dtype=np.float64)
    return out


def _weeks_in_year(year: int) -> int:
    return date(year, 12, 28).isocalendar().week


def base_rate(hw, week_start, *, years=BASE_RATE_YEARS, pool=BASE_RATE_POOL_WEEKS, min_obs=BASE_RATE_MIN_OBS):
    """Trailing same-season base rate from prior ISO years only.

    Anchors for origin t: ISO (year(t) - j, min(week(t), weeks_in_year(year(t) - j))), j = 1..years,
    each widened by offsets -pool..+pool. Returns (values float32 (n,T), counts int64 (T,)).
    """
    hw = np.asarray(hw)
    n, T = hw.shape
    ws = week_start.astype("datetime64[D]")
    origin = ws[0].astype(object)
    pos = np.empty((T, years), dtype=np.int64)
    for t in range(T):
        iso = ws[t].astype(object).isocalendar()
        for j in range(1, years + 1):
            y = iso.year - j
            anchor = date.fromisocalendar(y, min(iso.week, _weeks_in_year(y)), 1)
            pos[t, j - 1] = (anchor - origin).days // 7
    arange_t = np.arange(T)
    sums = np.zeros((n, T), dtype=np.float64)
    counts = np.zeros(T, dtype=np.int64)
    for d in range(-pool, pool + 1):
        idx = pos + d
        valid = (idx >= 0) & (idx <= arange_t[:, None])
        clipped = np.clip(idx, 0, T - 1)
        for j in range(years):
            m = valid[:, j]
            sums += hw[:, clipped[:, j]] * m[None, :]
        counts += valid.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        values = (sums / counts[None, :]).astype(np.float32)
    values[:, counts < min_obs] = np.nan
    return values, counts


def group_mean(x: np.ndarray, group_id: np.ndarray) -> np.ndarray:
    """Per-week mean of x over the wards sharing a group id (self included), (n,T) float32."""
    gid = np.asarray(group_id)
    order = np.argsort(gid, kind="stable")
    g_sorted = gid[order]
    starts = np.r_[0, np.nonzero(np.diff(g_sorted))[0] + 1]
    sizes = np.diff(np.r_[starts, len(g_sorted)])
    sums = np.add.reduceat(x[order].astype(np.float64), starts, axis=0)
    means = sums / sizes[:, None]
    group_of_sorted = np.repeat(np.arange(len(starts)), sizes)
    out = np.empty(x.shape, dtype=np.float32)
    out[order] = means[group_of_sorted].astype(np.float32)
    return out


# --------------------------------------------------------------------------- context
class FeatureContext:
    def __init__(self, panel, clim, static):
        self.panel = panel
        self.clim = clim
        self.static = static
        self._anom = {}
        self._hw = None

    def var(self, name):
        return self.panel.values[:, :, list(self.panel.variables).index(name)]

    def anom(self, name):
        if name not in self._anom:
            self._anom[name] = self.clim.anomaly(self.panel, name)
        return self._anom[name]

    def hw(self):
        if self._hw is None:
            self._hw = (self.var("heatwave_days") >= HW_DAYS_THRESHOLD).astype(np.float32)
        return self._hw

    def clear_cache(self):
        self._anom = {}
        self._hw = None


# --------------------------------------------------------------------------- season / static
def season_features(target_week_start):
    """sin/cos of the target week's mid-week (Monday + 3 d) day-of-year over 365.25."""
    mid = np.asarray(target_week_start).astype("datetime64[D]") + np.timedelta64(3, "D")
    doy = (mid - mid.astype("datetime64[Y]").astype("datetime64[D]")).astype(np.int64) + 1
    ang = 2.0 * np.pi * doy / 365.25
    return np.sin(ang).astype(np.float32), np.cos(ang).astype(np.float32)


STATIC_FEATURES = ("lat", "lon", "geozone_NWZ", "geozone_NEZ", "geozone_NCZ", "lga_average_ward")


def static_feature_matrix(static, names=None):
    from heatwave.forecast.static import GEOZONES

    names = tuple(STATIC_FEATURES if names is None else names)
    cols = []
    for nm in names:
        if nm == "lat":
            cols.append(static.lat.astype(np.float32))
        elif nm == "lon":
            cols.append(static.lon.astype(np.float32))
        elif nm == "lga_average_ward":
            cols.append(static.lga_average_ward.astype(np.float32))
        elif nm.startswith("geozone_") and nm[8:] in GEOZONES:
            cols.append(np.array([g == nm[8:] for g in static.geozone], dtype=np.float32))
        else:
            raise KeyError(f"unknown static feature {nm!r}")
    return np.stack(cols, axis=1).astype(np.float32)


# --------------------------------------------------------------------------- registry
_ANOM_VAR = {"mhi": "mean_heat_index", "xhi": "max_heat_index", "sm": "mean_soil_moisture",
             "pr": "total_precipitation_mm", "rh": "mean_relative_humidity"}
_RAW_VAR = {"hd": "heatwave_days", "hn": "hot_nights"}


def _src(ctx, key):
    if key in _ANOM_VAR:
        return ctx.anom(_ANOM_VAR[key])
    if key in _RAW_VAR:
        return ctx.var(_RAW_VAR[key])
    if key == "hw":
        return ctx.hw()
    raise KeyError(key)


def _lag_spec(reg, name, key, k, family, desc):
    reg.register(FeatureSpec(name, family, "panel", 0, k + 1, desc, lambda ctx, key=key, k=k: lag(_src(ctx, key), k)))


def _roll_spec(reg, name, key, w, family, desc, fn=trail_mean):
    reg.register(FeatureSpec(name, family, "panel", 0, w, desc, lambda ctx, key=key, w=w, fn=fn: fn(_src(ctx, key), w)))


def default_registry() -> Registry:
    reg = Registry()
    # recent_heat (35)
    for key in ("mhi", "xhi"):
        for k in range(4):
            _lag_spec(reg, f"{key}_anom_lag{k}", key, k, "recent_heat", f"{_ANOM_VAR[key]} anomaly, lag {k}")
    for key in ("mhi", "xhi"):
        for w in (2, 4, 8):
            _roll_spec(reg, f"{key}_anom_roll{w}", key, w, "recent_heat", f"{_ANOM_VAR[key]} anomaly, trailing {w}-week mean")
    for key in ("hd", "hn", "hw"):
        for k in range(4):
            _lag_spec(reg, f"{key}_lag{k}", key, k, "recent_heat", f"{key} lag {k}")
    for key in ("hd", "hn", "hw"):
        for w in (2, 4, 8):
            _roll_spec(reg, f"{key}_roll{w}", key, w, "recent_heat", f"{key} trailing {w}-week mean")
    # land_humidity (6)
    _lag_spec(reg, "sm_anom_lag0", "sm", 0, "land_humidity", "soil-moisture anomaly, lag 0")
    _roll_spec(reg, "sm_anom_roll4", "sm", 4, "land_humidity", "soil-moisture anomaly, 4-week mean")
    _roll_spec(reg, "pr_anom_sum4", "pr", 4, "land_humidity", "rainfall anomaly, 4-week sum", trail_sum)
    _roll_spec(reg, "pr_anom_sum8", "pr", 8, "land_humidity", "rainfall anomaly, 8-week sum", trail_sum)
    _lag_spec(reg, "rh_anom_lag0", "rh", 0, "land_humidity", "relative-humidity anomaly, lag 0")
    _roll_spec(reg, "rh_anom_roll4", "rh", 4, "land_humidity", "relative-humidity anomaly, 4-week mean")
    # trend (4)
    _roll_spec(reg, "hw_frac26", "hw", 26, "trend", "heatwave_week fraction, trailing 26 weeks")
    _roll_spec(reg, "hw_frac52", "hw", 52, "trend", "heatwave_week fraction, trailing 52 weeks")
    reg.register(FeatureSpec(
        "hw_base_rate_10y", "trend", "panel", 0, 52 * 3 + 5,
        "same-season heatwave_week rate over the prior 10 ISO years (+-2 weeks), needs >= 15 obs",
        lambda ctx: base_rate(ctx.hw(), ctx.panel.week_start)[0]))
    _roll_spec(reg, "mhi_anom_mean156", "mhi", LONGEST_FIXED_WINDOW_WEEKS, "trend", "trailing 3-year mean heat-index anomaly")
    # spatial (4), same week t only
    for nm, key, gname in (
        ("lga_mean_mhi_anom_lag0", "mhi", "lga_id"),
        ("state_mean_mhi_anom_lag0", "mhi", "state_id"),
        ("lga_mean_hd_lag0", "hd", "lga_id"),
        ("state_mean_hd_lag0", "hd", "state_id"),
    ):
        reg.register(FeatureSpec(
            nm, "spatial", "panel", 0, 1, f"same-week {gname[:-3]} mean of {key}",
            lambda ctx, key=key, gname=gname: group_mean(_src(ctx, key), getattr(ctx.static, gname))))
    # static (6)
    for nm in STATIC_FEATURES:
        reg.register(FeatureSpec(nm, "static", "static", 0, 0, f"static ward attribute {nm}", None))
    # calendar (3)
    reg.register(FeatureSpec("target_season_sin", "season", "calendar", 0, 0, "sin of target mid-week day-of-year", None))
    reg.register(FeatureSpec("target_season_cos", "season", "calendar", 0, 0, "cos of target mid-week day-of-year", None))
    reg.register(FeatureSpec("lead_weeks", "season", "calendar", 0, 0, "forecast lead in weeks", None))
    return reg


REGISTRY = default_registry()


# --------------------------------------------------------------------------- store
@dataclass(frozen=True, eq=False)
class FeatureStore:
    arrays: dict
    wards: tuple
    week_index: np.ndarray
    week_labels: tuple
    names: tuple
    clim_fit_range: dict
    data_sha256: str

    def __getitem__(self, name):
        return self.arrays[name]

    def __contains__(self, name):
        return name in self.arrays


def build_feature_store(panel, clim, static, *, registry=REGISTRY, names=None) -> FeatureStore:
    static = static.align(panel.wards)
    ctx = FeatureContext(panel, clim, static)
    n, T = panel.values.shape[:2]
    wanted = None
    if names is not None:
        wanted = set(names)
        for nm in wanted:
            if nm not in registry:
                raise KeyError(nm)
    arrays = {}
    for fam in FAMILIES:
        for spec in registry.specs(kind="panel", family=fam):
            if wanted is not None and spec.name not in wanted:
                continue
            arr = np.ascontiguousarray(spec.fn(ctx), dtype=np.float32)
            if arr.shape != (n, T):
                raise ValueError(f"{spec.name}: shape {arr.shape} != {(n, T)}")
            arr.flags.writeable = False
            arrays[spec.name] = arr
        ctx.clear_cache()
    order = tuple(s.name for s in registry.specs(kind="panel") if s.name in arrays)
    return FeatureStore(
        arrays={k: arrays[k] for k in order},
        wards=panel.wards,
        week_index=panel.week_index,
        week_labels=panel.week_labels,
        names=order,
        clim_fit_range=clim.fit_range(),
        data_sha256=panel.sha256,
    )
