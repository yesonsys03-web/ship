from __future__ import annotations

import os
from pathlib import Path


MANAGER_HOST = os.getenv("SHIP_MANAGER_HOST", "0.0.0.0")
MANAGER_PORT = int(os.getenv("SHIP_MANAGER_PORT", "8770"))
MANAGER_DATA_DIR = Path(os.getenv("SHIP_MANAGER_DATA_DIR", "data/manager_shipments"))
SHIP_SCENE_ROOT = Path(os.getenv("SHIP_SCENE_ROOT", "/Volumes/shipping"))
SHIP_DB_DIR = os.getenv("SHIP_DB_DIR", "")
MANAGER_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv(
        "SHIP_MANAGER_ALLOWED_ORIGINS",
        "http://127.0.0.1:1430,http://tauri.localhost,tauri://localhost",
    ).split(",")
    if origin.strip()
)
MANAGER_MAX_REQUEST_BYTES = int(os.getenv("SHIP_MANAGER_MAX_REQUEST_BYTES", str(5 * 1024 * 1024)))
