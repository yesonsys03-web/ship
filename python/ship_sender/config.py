from __future__ import annotations

import os


SENDER_HOST = os.getenv("SHIP_SENDER_HOST", "127.0.0.1")
SENDER_PORT = int(os.getenv("SHIP_SENDER_PORT", "8765"))
SHIP_DB_DIR = os.getenv("SHIP_DB_DIR", "")
SENDER_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv(
        "SHIP_SENDER_ALLOWED_ORIGINS",
        "http://127.0.0.1:1420,http://tauri.localhost,tauri://localhost",
    ).split(",")
    if origin.strip()
)
SENDER_MAX_REQUEST_BYTES = int(os.getenv("SHIP_SENDER_MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
