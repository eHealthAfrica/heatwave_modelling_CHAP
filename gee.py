"""Google Earth Engine connection."""
from __future__ import annotations

GEE_PROJECT = "continual-apex-435201-h6"


def init_ee():
    """Return an initialised Earth Engine module, authenticating on first run."""
    import ee
    try:
        ee.Initialize(project=GEE_PROJECT)
    except Exception:
        ee.Authenticate(auth_mode="localhost", force=False)
        ee.Initialize(project=GEE_PROJECT)
    return ee


if __name__ == "__main__":
    ee = init_ee()
    print("Earth Engine ready:", ee.Number(1).add(1).getInfo() == 2)
