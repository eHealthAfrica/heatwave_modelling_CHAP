"""Single entry point for Earth Engine authentication.

Consolidates what used to be two separate, inconsistent auth paths:
the inline credential block in nigeria_heat_index.py (service-account
only) and gee.py's standalone init_ee() (interactive auth, now removed).

Credential sources are tried in order, first match wins:
  1. Streamlit secrets  -> st.secrets["earthengine"]
  2. CI / GitHub Actions -> EE_SA_JSON env var (JSON string)
  3. Local development  -> keys/service_account.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import ee
from google.oauth2 import service_account

from heatwave.config import settings

EE_SCOPES = ["https://www.googleapis.com/auth/earthengine"]
_LOCAL_KEY_FILE = Path(__file__).resolve().parent.parent / "keys" / "service_account.json"


def _load_credentials() -> service_account.Credentials:
    try:
        import streamlit as st
        has_earthengine_secret = "earthengine" in st.secrets
    except Exception:
        # Covers both a missing streamlit install and
        # StreamlitSecretNotFoundError when no secrets.toml exists at all.
        has_earthengine_secret = False

    if has_earthengine_secret:
        sa_info = dict(st.secrets["earthengine"])
        return service_account.Credentials.from_service_account_info(
            sa_info, scopes=EE_SCOPES
        )

    if os.getenv("EE_SA_JSON"):
        sa_info = json.loads(os.getenv("EE_SA_JSON"))
        return service_account.Credentials.from_service_account_info(
            sa_info, scopes=EE_SCOPES
        )

    return service_account.Credentials.from_service_account_file(
        str(_LOCAL_KEY_FILE), scopes=EE_SCOPES
    )


def init_ee() -> None:
    """Authenticate and initialize the Earth Engine client. Idempotent."""
    credentials = _load_credentials()
    ee.Initialize(credentials, project=settings.gcp_project_id)


if __name__ == "__main__":
    init_ee()
    print("Earth Engine ready:", ee.Number(1).add(1).getInfo() == 2)
