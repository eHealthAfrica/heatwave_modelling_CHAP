"""Ward (admin-3) boundary asset access."""
from __future__ import annotations

import ee

from heatwave.config import settings


def load_ward_boundary() -> ee.FeatureCollection:
    """Return the nationwide ward boundary FeatureCollection configured in config.yaml."""
    return ee.FeatureCollection(settings.ward_asset_id)
