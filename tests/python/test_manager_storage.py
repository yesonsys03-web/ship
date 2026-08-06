from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from ship_common.models import FileEntry, ShipmentManifest
from ship_common import shipment_db
from ship_manager.storage import ShipmentStorage


def test_storage_saves_and_lists_by_year_month_folder_name(tmp_path: Path) -> None:
    storage = ShipmentStorage(tmp_path)
    manifest = ShipmentManifest(
        id="ship-test",
        source_path="/Users/example/Desktop/SHIP_A",
        folder_name="SHIP_A",
        created_at=datetime(2026, 6, 29, 9, 30, tzinfo=timezone.utc).isoformat(),
        note="arrived",
        files=[FileEntry(path="invoice.txt", size=12, is_dir=False)],
    )

    result = storage.save(manifest.to_dict())
    storage.save({**manifest.to_dict(), "id": "ship-test-repeat"})
    tree = storage.list_tree()
    loaded = storage.load("ship-test")

    assert result["ok"] is True
    assert result["id"] == "ship-test"
    assert result["folder_name"] == "SHIP_A"
    assert result["db_path"].endswith("shipments.sqlite3")
    assert tree["years"][0]["year"] == "2026"
    assert tree["years"][0]["months"][0]["month"] == "06"
    assert len(tree["years"][0]["months"][0]["shipments"]) == 2
    assert tree["years"][0]["months"][0]["shipments"][0]["label"] == "SHIP_A"
    assert tree["years"][0]["months"][0]["shipments"][0]["sent_at"] is not None
    assert loaded["note"] == "arrived"


def test_storage_lists_latest_transfer_before_newer_source_date(tmp_path: Path) -> None:
    storage = ShipmentStorage(tmp_path)
    older_source_manifest = ShipmentManifest(
        id="ship-older-source-latest-transfer",
        source_path="/Users/example/Desktop/2026_0520/FL_102.pdf",
        folder_name="2026_0520",
        created_at=datetime(2026, 5, 20, 9, 30, tzinfo=timezone.utc).isoformat(),
        note="sent second",
        files=[FileEntry(path="FL_102.pdf", size=12, is_dir=False)],
    )
    newer_source_manifest = ShipmentManifest(
        id="ship-newer-source-earlier-transfer",
        source_path="/Users/example/Desktop/2026_0629/FL_103.pdf",
        folder_name="2026_0629",
        created_at=datetime(2026, 6, 29, 9, 30, tzinfo=timezone.utc).isoformat(),
        note="sent first",
        files=[FileEntry(path="FL_103.pdf", size=12, is_dir=False)],
    )

    storage.save(newer_source_manifest.to_dict())
    storage.save(older_source_manifest.to_dict())

    tree = storage.list_tree()
    first_year = tree["years"][0]
    first_month = first_year["months"][0]
    first_shipment = first_month["shipments"][0]

    assert first_year["year"] == "2026"
    assert first_month["month"] == "05"
    assert first_shipment["id"] == "ship-older-source-latest-transfer"
    assert first_shipment["sent_at"] is not None


def test_storage_canonicalizes_short_year_first_source_date(tmp_path: Path) -> None:
    storage = ShipmentStorage(tmp_path)
    manifest = ShipmentManifest(
        id="ship-short-year-source-date",
        source_path="/Users/example/Desktop/Hazbin/260703/HH0305",
        folder_name="HH0305",
        created_at=datetime(2026, 6, 29, 9, 30, tzinfo=timezone.utc).isoformat(),
        files=[FileEntry(path="HH0305_010.mov", size=12, is_dir=False)],
    )

    storage.save(manifest.to_dict())

    tree = storage.list_tree()
    shipment = tree["years"][0]["months"][0]["shipments"][0]

    assert tree["years"][0]["year"] == "2026"
    assert tree["years"][0]["months"][0]["month"] == "07"
    assert shipment["day"] == "03"


def test_storage_summary_file_count_excludes_folders(tmp_path: Path) -> None:
    storage = ShipmentStorage(tmp_path)
    manifest = ShipmentManifest(
        id="ship-file-count-files-only",
        source_path="/Users/example/Desktop/SHIP_A",
        folder_name="SHIP_A",
        created_at=datetime(2026, 6, 29, 9, 30, tzinfo=timezone.utc).isoformat(),
        files=[
            FileEntry(path="SHIP_A", size=0, is_dir=True),
            FileEntry(path="SHIP_A/plates", size=0, is_dir=True),
            FileEntry(path="SHIP_A/plates/cut_a.mov", size=12, is_dir=False),
            FileEntry(path="SHIP_A/plates/cut_b.mov", size=12, is_dir=False),
        ],
    )

    storage.save(manifest.to_dict())
    shipment = storage.list_tree()["years"][0]["months"][0]["shipments"][0]

    assert shipment["file_count"] == 2


def test_storage_summary_content_signature_ignores_sent_at_and_tracks_manifest_content(tmp_path: Path) -> None:
    storage = ShipmentStorage(tmp_path)
    manifest = ShipmentManifest(
        id="ship-stable-signature",
        source_path="/Users/example/Desktop/SHIP_A",
        folder_name="SHIP_A",
        created_at=datetime(2026, 6, 29, 9, 30, tzinfo=timezone.utc).isoformat(),
        files=[FileEntry(path="cut.mov", size=12, is_dir=False)],
    )

    storage.save(manifest.to_dict())
    first_signature = storage.list_tree()["years"][0]["months"][0]["shipments"][0]["content_signature"]
    storage.save(manifest.to_dict())
    second_signature = storage.list_tree()["years"][0]["months"][0]["shipments"][0]["content_signature"]
    changed_manifest = ShipmentManifest(
        id="ship-stable-signature",
        source_path="/Users/example/Desktop/SHIP_A",
        folder_name="SHIP_A",
        created_at=manifest.created_at,
        files=[FileEntry(path="cut.mov", size=99, is_dir=False)],
    )
    storage.save(changed_manifest.to_dict())
    changed_signature = storage.list_tree()["years"][0]["months"][0]["shipments"][0]["content_signature"]

    assert first_signature == second_signature
    assert changed_signature != first_signature


def test_storage_read_paths_do_not_ensure_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "shipments.sqlite3"
    sqlite3.connect(db_file).close()
    storage = ShipmentStorage(tmp_path, db_file=db_file)
    monkeypatch.setattr(
        shipment_db,
        "_ensure_schema",
        lambda connection: (_ for _ in ()).throw(AssertionError("read ensured schema")),
    )

    assert storage.list_tree() == {"years": []}
    with pytest.raises(FileNotFoundError):
        storage.load("missing-shipment")


def test_storage_list_tree_returns_empty_when_shipments_table_is_missing(tmp_path: Path) -> None:
    db_file = tmp_path / "shipments.sqlite3"
    sqlite3.connect(db_file).close()
    storage = ShipmentStorage(tmp_path, db_file=db_file)

    assert storage.list_tree() == {"years": []}


def test_storage_load_raises_not_found_when_shipments_table_is_missing(tmp_path: Path) -> None:
    db_file = tmp_path / "shipments.sqlite3"
    sqlite3.connect(db_file).close()
    storage = ShipmentStorage(tmp_path, db_file=db_file)

    with pytest.raises(FileNotFoundError):
        storage.load("missing-shipment")
