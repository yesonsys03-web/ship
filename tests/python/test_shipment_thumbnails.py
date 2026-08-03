from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ship_common import shipment_db
from ship_common.shipment_db import ShipmentDatabase


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _manifest(source_path: Path) -> dict:
    return {
        "id": "shipment-1",
        "source_path": str(source_path),
        "folder_name": source_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "",
        "files": [
            {"path": "poster.jpg", "size": 12, "is_dir": False},
            {"path": "nested", "size": 0, "is_dir": True},
            {"path": "notes.txt", "size": 5, "is_dir": False},
        ],
    }


def test_save_persists_previewable_png_thumbnail_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "poster.jpg").write_bytes(b"jpeg")
    (source / "notes.txt").write_text("notes")
    database = ShipmentDatabase(tmp_path / "shipments.sqlite3")

    calls: list[tuple[str, str]] = []

    def fake_get_thumbnail_bytes(source_path: str, file_path: str) -> bytes:
        calls.append((source_path, file_path))
        return PNG_SIGNATURE + b"persisted-poster"

    monkeypatch.setattr(shipment_db, "get_thumbnail_bytes", fake_get_thumbnail_bytes)

    result = database.save(_manifest(source))

    assert result["thumbnail_count"] == 1
    assert result["thumbnail_error_count"] == 0
    assert calls == [(str(source), "poster.jpg")]
    assert database.get_thumbnail_bytes("shipment-1", "poster.jpg") == PNG_SIGNATURE + b"persisted-poster"
    assert database.get_thumbnail_bytes("shipment-1", "notes.txt") is None


def test_thumbnail_persistence_is_best_effort(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "poster.jpg").write_bytes(b"jpeg")
    database = ShipmentDatabase(tmp_path / "shipments.sqlite3")

    def fail_thumbnail(source_path: str, file_path: str) -> bytes:
        raise RuntimeError(f"cannot thumbnail {file_path}")

    monkeypatch.setattr(shipment_db, "get_thumbnail_bytes", fail_thumbnail)

    result = database.save(_manifest(source))

    assert result["ok"] is True
    assert result["thumbnail_count"] == 0
    assert result["thumbnail_error_count"] == 1
    assert result["thumbnail_errors"] == ["poster.jpg: cannot thumbnail poster.jpg"]
    assert database.load("shipment-1")["id"] == "shipment-1"


def test_save_thumbnail_bytes_validates_png_signature(tmp_path: Path) -> None:
    database = ShipmentDatabase(tmp_path / "shipments.sqlite3")

    assert database.save_thumbnail_bytes("shipment-1", "poster.jpg", b"not-png") is False
    assert database.get_thumbnail_bytes("shipment-1", "poster.jpg") is None

    assert database.save_thumbnail_bytes("shipment-1", "poster.jpg", PNG_SIGNATURE + b"png") is True
    assert database.get_thumbnail_bytes("shipment-1", "poster.jpg") == PNG_SIGNATURE + b"png"


def test_existing_database_migrates_thumbnail_table(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy.sqlite3"
    database = ShipmentDatabase(db_file)
    database.save(_manifest(tmp_path))

    with database._connect() as connection:
        shipment_db._ensure_schema(connection)
        table = connection.execute(
            "select name from sqlite_master where type = 'table' and name = 'shipment_thumbnails'"
        ).fetchone()

    assert table is not None


def test_database_does_not_force_wal_journal_mode(tmp_path: Path) -> None:
    database = ShipmentDatabase(tmp_path / "shipments.sqlite3")

    with database._connect() as connection:
        journal_mode = connection.execute("pragma journal_mode").fetchone()[0]

    assert journal_mode != "wal"


def test_read_thumbnail_does_not_ensure_schema(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_file = tmp_path / "shipments.sqlite3"
    sqlite3.connect(db_file).close()
    database = ShipmentDatabase(db_file)
    monkeypatch.setattr(
        shipment_db,
        "_ensure_schema",
        lambda connection: (_ for _ in ()).throw(AssertionError("thumbnail read ensured schema")),
    )

    assert database.get_thumbnail_bytes("shipment-1", "poster.jpg") is None


def test_read_thumbnail_returns_none_when_thumbnail_table_is_missing(tmp_path: Path) -> None:
    db_file = tmp_path / "shipments.sqlite3"
    sqlite3.connect(db_file).close()

    assert ShipmentDatabase(db_file).get_thumbnail_bytes("shipment-1", "poster.jpg") is None
