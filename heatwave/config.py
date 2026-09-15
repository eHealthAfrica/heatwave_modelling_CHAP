"""Loads config.yaml into a typed, importable settings object."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class ClimatologyConfig:
    baseline_start_year: int
    baseline_end_year: int
    percentile: int
    pooling_window_days: int
    min_consecutive_days: int

    def __post_init__(self):
        """Runtime validation (WR-03): dataclass field type annotations are
        not enforced at runtime, so without this check a malformed
        config.yaml would load without error and silently propagate
        nonsensical values into ee.Filter.calendarRange/percentile calls
        downstream instead of failing fast at startup."""
        if not (0 < self.percentile < 100):
            raise ValueError(f"percentile must be in (0, 100), got {self.percentile}")
        if self.baseline_start_year > self.baseline_end_year:
            raise ValueError("baseline_start_year must be <= baseline_end_year")
        if self.pooling_window_days < 0:
            raise ValueError("pooling_window_days must be >= 0")
        if self.min_consecutive_days < 1:
            raise ValueError("min_consecutive_days must be >= 1")


@dataclass(frozen=True)
class Bands:
    tmax: str
    tmean: str
    dewpoint: str


@dataclass(frozen=True)
class Settings:
    gcp_project_id: str
    ward_asset_id: str
    era5_land_collection: str
    bands: Bands
    start_date: str
    end_date: str
    climatology: ClimatologyConfig


def load_settings(path: Path = _CONFIG_PATH) -> Settings:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return Settings(
        gcp_project_id=raw["gcp_project_id"],
        ward_asset_id=raw["ward_asset_id"],
        era5_land_collection=raw["era5_land_collection"],
        bands=Bands(**raw["bands"]),
        start_date=raw["start_date"],
        end_date=raw["end_date"],
        climatology=ClimatologyConfig(**raw["climatology"]),
    )


settings = load_settings()
