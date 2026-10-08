"""Feature registry with the ``max_lookahead = 0`` guard (FEAT-04 d).

Every feature must declare ``max_lookahead == 0``: the value at origin week t may use
panel weeks <= t only. The declaration is a promise; the truncation/poison tests (a)/(b)
in the leakage suite are the proof. Names that identify a ward, a raw year index, the
event count or the label are rejected outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

FAMILIES = ("recent_heat", "land_humidity", "season", "trend", "spatial", "static")
KINDS = ("panel", "static", "calendar")

FORBIDDEN_NAME_PATTERN = re.compile(
    r"^(ward(_id|code)?|location)(_|$)|(^|_)(year|years|iso_year|year_index|week_of_year|iso_week|heatwave_event_count)(_|$)"
)
FORBIDDEN_EXACT_NAMES = ("heatwave_week", "label", "target")


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    family: str
    kind: str
    max_lookahead: int
    window_weeks: int
    description: str
    fn: Optional[Callable] = None


class Registry:
    def __init__(self):
        self._specs: dict = {}

    def register(self, spec: FeatureSpec) -> FeatureSpec:
        if not isinstance(spec, FeatureSpec):
            raise ValueError("register() needs a FeatureSpec")
        name = spec.name
        if not isinstance(name, str) or not name:
            raise ValueError("feature name must be a non-empty string")
        if type(spec.max_lookahead) is not int or spec.max_lookahead != 0:
            raise ValueError(f"{name}: max_lookahead must be the int 0, got {spec.max_lookahead!r}")
        if name in self._specs:
            raise ValueError(f"duplicate feature name {name!r}")
        if spec.family not in FAMILIES:
            raise ValueError(f"{name}: unknown family {spec.family!r}")
        if spec.kind not in KINDS:
            raise ValueError(f"{name}: unknown kind {spec.kind!r}")
        if name in FORBIDDEN_EXACT_NAMES or FORBIDDEN_NAME_PATTERN.search(name):
            raise ValueError(f"forbidden feature name {name!r}")
        if spec.kind == "panel":
            if spec.fn is None:
                raise ValueError(f"{name}: panel feature needs fn")
            if type(spec.window_weeks) is not int or spec.window_weeks < 1:
                raise ValueError(f"{name}: panel feature needs window_weeks >= 1")
        self._specs[name] = spec
        return spec

    def get(self, name: str) -> FeatureSpec:
        return self._specs[name]

    def specs(self, kind=None, family=None) -> tuple:
        return tuple(
            s
            for s in self._specs.values()
            if (kind is None or s.kind == kind) and (family is None or s.family == family)
        )

    def names(self, kind=None, family=None) -> tuple:
        return tuple(s.name for s in self.specs(kind, family))

    def copy(self) -> "Registry":
        r = Registry()
        r._specs = dict(self._specs)
        return r

    def __len__(self):
        return len(self._specs)

    def __iter__(self):
        return iter(self._specs.values())

    def __contains__(self, name):
        return name in self._specs
