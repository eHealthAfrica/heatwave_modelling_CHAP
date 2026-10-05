"""Hash-verified loader for the frozen covariate dataset (DATA-01, DATA-02).

Training only ever sees the byte-exact ``covariates-vN.N`` parquet. Files are
opened read-only ("rb"); nothing in this module writes or chmods anything.
"""

from __future__ import annotations

import hashlib

PARQUET_NAME = "covariate_table.parquet"
MANIFEST_NAME = "MANIFEST.json"
ID_COLUMNS = ("time_period", "location")
VARIABLES = (
    "heatwave_days",
    "mean_heat_index",
    "max_heat_index",
    "heatwave_event_count",
    "hot_nights",
    "total_precipitation_mm",
    "mean_relative_humidity",
    "mean_soil_moisture",
)
EXPECTED_COLUMNS = ID_COLUMNS + VARIABLES
INTEGER_VARIABLES = ("heatwave_days", "heatwave_event_count", "hot_nights")
EXPECTED_ARROW_TYPES = {
    "time_period": "string",
    "location": "string",
    "heatwave_days": "int64",
    "mean_heat_index": "double",
    "max_heat_index": "double",
    "heatwave_event_count": "int64",
    "hot_nights": "int64",
    "total_precipitation_mm": "double",
    "mean_relative_humidity": "double",
    "mean_soil_moisture": "double",
}


class FrozenDataError(RuntimeError):
    """Raised when the frozen dataset fails any integrity or provenance check."""


def sha256_file(path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of the raw bytes of ``path``, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
