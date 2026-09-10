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
