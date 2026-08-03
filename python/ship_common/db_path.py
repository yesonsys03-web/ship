from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


SHIP_DB_FILENAME = "shipments.sqlite3"
WINDOWS_SHIP_DB_DIR_CANDIDATES = (
    Path(r"\\Mserver\USA_DB\test_jn\ship_db"),
)
POSIX_SHIP_DB_DIR_CANDIDATES = (
    Path("/System/Volumes/Data/USA_DB/test_jn/ship_db"),
    Path("/USA_DB/test_jn/ship_db"),
    Path("//Mserver/USA_DB/test_jn/ship_db"),
    Path("/System/Volumes/Data/mnt/USA_DB/test_jn/ship_db"),
)
SHIP_DB_DIR_CANDIDATES = (
    WINDOWS_SHIP_DB_DIR_CANDIDATES + POSIX_SHIP_DB_DIR_CANDIDATES
    if os.name == "nt"
    else POSIX_SHIP_DB_DIR_CANDIDATES + WINDOWS_SHIP_DB_DIR_CANDIDATES
)


def resolve_ship_db_file(candidates: Iterable[Path] = SHIP_DB_DIR_CANDIDATES) -> Path:
    env_dir = os.getenv("SHIP_DB_DIR")
    if env_dir:
        directory = Path(env_dir).expanduser()
        return directory / SHIP_DB_FILENAME

    existing_directories: list[Path] = []
    for directory in candidates:
        if directory.exists():
            existing_directories.append(directory)
            db_file = directory / SHIP_DB_FILENAME
            if db_file.exists():
                return db_file

    if existing_directories:
        return existing_directories[0] / SHIP_DB_FILENAME

    fallback = Path("data/ship_db")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / SHIP_DB_FILENAME
