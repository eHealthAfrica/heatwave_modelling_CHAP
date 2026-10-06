"""Reusable leakage checks (FEAT-04). Later phases run them on any new feature.

All checks raise ``LeakageError`` (an AssertionError) naming the offending feature and
origin. Comparisons are bit-exact by default (``atol=0.0``, NaN-aware). Integer and
indicator features are exact by construction. If a non-integer rolling/spatial feature
ever flakes on float summation order, pass a small ``atol`` (e.g. 1e-6): a real leak is an
O(1) difference, far above it, and the mutation tests must still fail under any tolerance
used. Never loosen a tolerance to hide a genuine difference.
"""

from __future__ import annotations

import numpy as np

from heatwave.forecast import fixtures
from heatwave.forecast.registry import FORBIDDEN_EXACT_NAMES, FORBIDDEN_NAME_PATTERN


class LeakageError(AssertionError):
    """A feature, fitted statistic, split or label depends on information it must not see."""


def _same(a, b, atol: float) -> bool:
    a = np.asarray(a)
    b = np.asarray(b)
    if a.shape != b.shape:
        return False
    if atol == 0.0:
        return bool(np.array_equal(a, b, equal_nan=True))
    return bool(np.allclose(a, b, rtol=0.0, atol=atol, equal_nan=True))


def _origin_label(panel, t: int) -> str:
    return f"{panel.week_labels[t]} (position {t})"


def _compare_at(full, part, t, panel, atol, what):
    if set(part) != set(full):
        raise LeakageError(f"{what}: feature sets differ ({sorted(set(part) ^ set(full))})")
    bad = [nm for nm in full if not _same(part[nm][:, t], full[nm][:, t], atol)]
    if bad:
        raise LeakageError(f"{what} at origin {_origin_label(panel, t)}: features changed: {bad}")


def check_truncation_invariance(build, panel, origins, *, atol: float = 0.0) -> None:
    """Features at origin t equal those from a panel truncated after t. ``build(panel) -> {name: (n,T)}``."""
    full = build(panel)
    for t in origins:
        part = build(fixtures.truncate_panel(panel, int(t)))
        _compare_at(full, part, int(t), panel, atol, "truncation")


def check_poison_invariance(build, panel, origins, *, modes=("garbage", "nan"), seed: int = 0, atol: float = 0.0) -> None:
    """Features at origin t are unchanged when every week > t is garbage or NaN."""
    full = build(panel)
    for t in origins:
        for mode in modes:
            part = build(fixtures.poison_future(panel, int(t), mode=mode, seed=seed))
            _compare_at(full, part, int(t), panel, atol, f"poison[{mode}]")


def check_row_truncation_invariance(build_rows, panel, origins, *, exclude_prefixes=("heatwave_week", "has_label"), atol: float = 0.0) -> None:
    """Row-level: feature and timing columns of a truncated build equal the full build.

    ``build_rows(panel, origin_positions) -> DataFrame`` ordered by origin then ward.
    Label columns are excluded (they read t+k by definition).
    """
    origins = [int(t) for t in origins]
    n = len(panel.wards)
    full = build_rows(panel, origins)
    cols = [c for c in full.columns if not c.startswith(tuple(exclude_prefixes))]
    for i, t in enumerate(origins):
        part = build_rows(fixtures.truncate_panel(panel, t), [t])
        sl = full.iloc[i * n : (i + 1) * n]
        bad = []
        for c in cols:
            a, b = sl[c].to_numpy(), part[c].to_numpy()
            if a.dtype.kind == "f" or b.dtype.kind == "f":
                ok = _same(a.astype(float), b.astype(float), atol)
            else:
                ok = bool(np.array_equal(a, b))
            if not ok:
                bad.append(c)
        if bad:
            raise LeakageError(f"row truncation at origin {_origin_label(panel, t)}: columns changed: {bad}")


def check_train_only_statistics(fit, panel, end, *, modes=("garbage", "nan"), seed: int = 0) -> None:
    """Fitted statistics at ``end`` ignore every week at or after ``end``. ``fit(panel) -> Climatology``."""
    base = fit(panel)
    last_start = np.datetime64(base.last_week_start.isoformat(), "D")
    if not last_start < np.datetime64(end, "D"):
        raise LeakageError(f"fit uses week starting {base.last_week_start} which is not before {end}")
    pos = np.nonzero(panel.week_start < np.datetime64(end, "D"))[0]
    if pos.size == 0:
        raise LeakageError(f"no weeks before {end}")
    last_pos = int(pos[-1])
    ref_range = {k: v for k, v in base.fit_range().items() if k != "data_sha256"}
    for mode in modes:
        poisoned = fixtures.poison_future(panel, last_pos, mode=mode, seed=seed)
        alt = fit(poisoned)
        for field in ("mean", "std", "std_floor"):
            if not np.array_equal(getattr(base, field), getattr(alt, field), equal_nan=True):
                raise LeakageError(f"statistic {field!r} changed when weeks >= {end} were poisoned ({mode})")
        alt_range = {k: v for k, v in alt.fit_range().items() if k != "data_sha256"}
        if alt_range != ref_range:
            raise LeakageError(f"fit range changed under poisoning ({mode}): {ref_range} vs {alt_range}")
        del poisoned, alt


def check_registry(registry) -> None:
    """Every spec declares the int 0 lookahead, has an allowed name, and panel specs have fn."""
    for spec in registry:
        if type(spec.max_lookahead) is not int or spec.max_lookahead != 0:
            raise LeakageError(f"{spec.name}: max_lookahead {spec.max_lookahead!r} is not 0")
        if spec.name in FORBIDDEN_EXACT_NAMES or FORBIDDEN_NAME_PATTERN.search(spec.name):
            raise LeakageError(f"{spec.name}: forbidden feature name")
        if spec.kind == "panel" and spec.fn is None:
            raise LeakageError(f"{spec.name}: panel feature has no fn")


__all__ = [
    "LeakageError",
    "check_truncation_invariance",
    "check_poison_invariance",
    "check_train_only_statistics",
    "check_registry",
    "check_row_truncation_invariance",
]
