import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ship_common import audit_log
from ship_common.db_path import SHIP_DB_FILENAME, resolve_ship_db_file
from ship_common.models import FileEntry, ShipmentManifest
from ship_sender import service
from ship_sender import server as sender_server
from ship_sender.thumbnails import resolve_thumbnail_target


@pytest.fixture(autouse=True)
def isolate_audit_logs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHIP_AUDIT_LOG_DIR", str(tmp_path / "audit-logs"))


def test_send_writes_manifest_to_shared_db(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-test",
        source_path="/tmp/SHIP_A",
        folder_name="SHIP_A",
        created_at=datetime(2026, 6, 29, tzinfo=timezone.utc).isoformat(),
        files=[],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    result = service.send(manifest.to_dict())

    assert result["ok"] is True
    assert result["folder_name"] == "SHIP_A"
    assert (tmp_path / "shipments.sqlite3").exists()


def test_send_writes_host_ip_audit_log(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="bobs-send-audit",
        source_path="bobs://Bobs_Burgers/FASA03/batch/TK7/03A_S01",
        folder_name="밥스버거 FASA03 TK7 1개 씬",
        created_at=datetime(2026, 7, 9, tzinfo=timezone.utc).isoformat(),
        note="ready",
        files=[FileEntry(path="FASA03/TK7/03A_S01.bobs-scene", size=0, is_dir=False)],
    )
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("10.20.30.40 sender-pc sender-alias\n", encoding="utf-8")
    log_dir = tmp_path / "logs"

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path / "db"))
    monkeypatch.setenv("SHIP_AUDIT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("SHIP_AUDIT_HOSTS_FILE", str(hosts_file))
    monkeypatch.setattr(audit_log, "detect_local_ip", lambda: "10.20.30.40")

    service.send(manifest.to_dict())

    entries = read_audit_entries(log_dir)
    assert len(entries) == 1
    assert entries[0]["action"] == "send"
    assert entries[0]["manifest_id"] == "bobs-send-audit"
    assert entries[0]["folder_name"] == "밥스버거 FASA03 TK7 1개 씬"
    assert entries[0]["source_path"] == "bobs://Bobs_Burgers/FASA03/batch/TK7/03A_S01"
    assert entries[0]["file_count"] == 1
    assert entries[0]["files"] == ["FASA03/TK7/03A_S01.bobs-scene"]
    assert entries[0]["note"] == "ready"
    assert entries[0]["job"] == "FASA03"
    assert entries[0]["tk"] == "TK7"
    assert entries[0]["ip"] == "10.20.30.40"
    assert entries[0]["hostname"] == "sender-pc"
    assert entries[0]["hostname_source"] == "hosts"


def test_default_audit_log_dir_follows_resolved_ship_db_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SHIP_AUDIT_LOG_DIR", raising=False)
    first_candidate = tmp_path / "System" / "Volumes" / "Data" / "USA_DB" / "test_jn" / "ship_db"
    second_candidate = tmp_path / "USA_DB" / "test_jn" / "ship_db"
    first_candidate.mkdir(parents=True)
    second_candidate.mkdir(parents=True)
    (first_candidate / SHIP_DB_FILENAME).write_text("db", encoding="utf-8")
    (second_candidate / SHIP_DB_FILENAME).write_text("db", encoding="utf-8")

    candidates = (first_candidate, second_candidate)

    assert resolve_ship_db_file(candidates).parent == first_candidate
    assert audit_log.audit_log_dir(candidates) == first_candidate


def test_log_generate_writes_metadata_and_falls_back_without_hosts_entry(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="bobs-generate-audit",
        source_path="bobs://Bobs_Burgers/FASA12/batch/09_S02",
        folder_name="밥스버거 FASA12 1개 씬",
        created_at="2026-07-09T01:02:03.000Z",
        files=[FileEntry(path="FASA12/09_S02.bobs-scene", size=0, is_dir=False)],
    )
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    log_dir = tmp_path / "logs"

    monkeypatch.setenv("SHIP_AUDIT_LOG_DIR", str(log_dir))
    monkeypatch.setenv("SHIP_AUDIT_HOSTS_FILE", str(hosts_file))
    monkeypatch.setattr(audit_log, "detect_local_ip", lambda: "10.99.0.8")
    monkeypatch.setattr(audit_log.socket, "gethostname", lambda: "socket-host")

    result = service.log_generate(manifest.to_dict(), {"job": "FASA12", "batch": "42"})

    entries = read_audit_entries(log_dir)
    assert result == {"ok": True}
    assert entries[0]["action"] == "generate"
    assert entries[0]["manifest_id"] == "bobs-generate-audit"
    assert entries[0]["file_count"] == 1
    assert entries[0]["files"] == ["FASA12/09_S02.bobs-scene"]
    assert entries[0]["job"] == "FASA12"
    assert entries[0]["batch"] == "42"
    assert entries[0]["ip"] == "10.99.0.8"
    assert entries[0]["hostname"] == "socket-host"
    assert entries[0]["hostname_source"] == "socket"


def test_generate_audit_logging_failure_is_non_fatal(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="bobs-audit-nonfatal",
        source_path="bobs://Bobs_Burgers/FASA03/batch/03A_S01",
        folder_name="밥스버거 FASA03 1개 씬",
        created_at=datetime(2026, 7, 9, tzinfo=timezone.utc).isoformat(),
        files=[FileEntry(path="FASA03/03A_S01.bobs-scene", size=0, is_dir=False)],
    )
    not_a_directory = tmp_path / "logs-file"
    not_a_directory.write_text("occupied", encoding="utf-8")

    monkeypatch.setenv("SHIP_AUDIT_LOG_DIR", str(not_a_directory))
    monkeypatch.setattr(audit_log, "detect_local_ip", lambda: "")

    result = service.log_generate(manifest.to_dict())

    assert result == {"ok": True}


def test_send_accepts_javascript_utc_created_at(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-js-z",
        source_path="/tmp/Bobs_Burgers/FASA03",
        folder_name="밥스버거 FASA03 12 scenes",
        created_at="2026-07-07T07:03:41.824Z",
        files=[FileEntry(path="01A_S01.bobs-scene", size=0, is_dir=False)],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    result = service.send(manifest.to_dict())
    history = service.sent_history()

    assert result["ok"] is True
    assert history[0]["id"] == "ship-js-z"
    assert history[0]["created_at"] == "2026-07-07T07:03:41.824Z"


def test_send_persists_backend_sent_at_without_changing_created_at(monkeypatch, tmp_path: Path) -> None:
    selected_shipment_date = "2026-06-01T00:00:00+00:00"
    frontend_supplied_sent_at = "1999-01-01T00:00:00+00:00"
    manifest = ShipmentManifest(
        id="ship-actual-sent-at",
        source_path="/tmp/Bobs_Burgers/FASA03",
        folder_name="밥스버거 FASA03 14개 씬",
        created_at=selected_shipment_date,
        sent_at=frontend_supplied_sent_at,
        files=[FileEntry(path="03A_S01.bobs-scene", size=0, is_dir=False)],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    before_send = datetime.now(timezone.utc)
    result = service.send(manifest.to_dict())
    after_send = datetime.now(timezone.utc)
    history = service.sent_history()
    stored_manifest = history[0]
    stored_sent_at = datetime.fromisoformat(stored_manifest["sent_at"])

    assert result["ok"] is True
    assert stored_manifest["id"] == "ship-actual-sent-at"
    assert stored_manifest["created_at"] == selected_shipment_date
    assert stored_manifest["sent_at"] != frontend_supplied_sent_at
    assert before_send <= stored_sent_at <= after_send


def test_sent_history_returns_empty_when_shared_db_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    history = service.sent_history()

    assert history == []
    assert not (tmp_path / "shipments.sqlite3").exists()


def test_ready_endpoint_does_not_touch_shared_db(monkeypatch) -> None:
    payloads = []
    handler = object.__new__(sender_server.SenderHandler)
    handler.path = "/ready"
    handler._send_json = lambda payload, status=200: payloads.append((status, payload))
    monkeypatch.setattr(
        sender_server,
        "db_status",
        lambda: (_ for _ in ()).throw(AssertionError("ready touched db")),
    )

    sender_server.SenderHandler.do_GET(handler)

    assert payloads == [(200, {"ok": True, "role": "sender"})]


def test_sent_history_reads_saved_manifests_newest_first(monkeypatch, tmp_path: Path) -> None:
    older_manifest = ShipmentManifest(
        id="ship-older",
        source_path="/tmp/SHIP_OLDER",
        folder_name="SHIP_OLDER",
        created_at=datetime(2026, 6, 28, tzinfo=timezone.utc).isoformat(),
        files=[],
    )
    newer_manifest = ShipmentManifest(
        id="ship-newer",
        source_path="/tmp/1510_PROMO-TK1_0701_2026",
        folder_name="1510_PROMO-TK1_0701_2026",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc).isoformat(),
        note="sent",
        files=[FileEntry(path="cut.mov", size=12, is_dir=False)],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))
    service.send(older_manifest.to_dict())
    service.send(newer_manifest.to_dict())

    history = service.sent_history()

    assert [manifest["id"] for manifest in history] == ["ship-newer", "ship-older"]
    assert history[0]["folder_name"] == "1510_PROMO-TK1_0701_2026"
    assert history[0]["note"] == "sent"
    assert history[0]["files"] == [{"path": "cut.mov", "size": 12, "is_dir": False}]


def test_db_status_reports_shared_db_path_and_history_count(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-status",
        source_path="/tmp/SHIP_STATUS",
        folder_name="SHIP_STATUS",
        created_at=datetime(2026, 6, 30, tzinfo=timezone.utc).isoformat(),
        files=[],
    )
    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    service.send(manifest.to_dict())

    status = service.db_status()

    assert status["path"] == str(tmp_path / "shipments.sqlite3")
    assert status["exists"] is True
    assert status["parent_exists"] is True
    assert status["history_count"] == 1


def test_send_groups_shared_db_by_folder_label_date(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-folder-date",
        source_path="/tmp/KOTH/2026/1510_PROMO-TK1_0701_2026",
        folder_name="1510_PROMO-TK1_0701_2026",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
        files=[],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    service.send(manifest.to_dict())

    tree = service.ShipmentDatabase(service.resolve_ship_db_file()).list_tree()

    assert tree["years"][0]["year"] == "2026"
    assert tree["years"][0]["months"][0]["month"] == "07"
    assert tree["years"][0]["months"][0]["shipments"][0]["day"] == "01"


def test_send_groups_shared_db_by_year_first_folder_label_date(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-year-first-folder-date",
        source_path="/tmp/KOTH/2026_0703/1510_PROMO-TK1",
        folder_name="1510_PROMO-TK1",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
        files=[],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    service.send(manifest.to_dict())

    tree = service.ShipmentDatabase(service.resolve_ship_db_file()).list_tree()

    assert tree["years"][0]["year"] == "2026"
    assert tree["years"][0]["months"][0]["month"] == "07"
    assert tree["years"][0]["months"][0]["shipments"][0]["day"] == "03"


def test_send_groups_shared_db_by_bare_mmdd_with_created_at_year(monkeypatch, tmp_path: Path) -> None:
    manifest = ShipmentManifest(
        id="ship-bare-folder-date",
        source_path="/tmp/KOTH/0703",
        folder_name="0703",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
        files=[FileEntry(path="art.psd", size=12, is_dir=False)],
    )

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    service.send(manifest.to_dict())

    tree = service.ShipmentDatabase(service.resolve_ship_db_file()).list_tree()

    assert tree["years"][0]["year"] == "2026"
    assert tree["years"][0]["months"][0]["month"] == "07"
    assert tree["years"][0]["months"][0]["shipments"][0]["day"] == "03"


def test_send_rejects_invalid_bare_mmdd_folder_dates(monkeypatch, tmp_path: Path) -> None:
    manifests = [
        ShipmentManifest(
            id="ship-invalid-1332",
            source_path="/tmp/KOTH/1332",
            folder_name="1332",
            created_at=datetime(2026, 6, 15, tzinfo=timezone.utc).isoformat(),
            files=[],
        ),
        ShipmentManifest(
            id="ship-invalid-0000",
            source_path="/tmp/KOTH/0000",
            folder_name="0000",
            created_at=datetime(2026, 6, 16, tzinfo=timezone.utc).isoformat(),
            files=[],
        ),
        ShipmentManifest(
            id="ship-invalid-title",
            source_path="/tmp/KOTH/1510",
            folder_name="1510",
            created_at=datetime(2026, 6, 17, tzinfo=timezone.utc).isoformat(),
            files=[],
        ),
    ]

    monkeypatch.setenv("SHIP_DB_DIR", str(tmp_path))

    for manifest in manifests:
        service.send(manifest.to_dict())

    tree = service.ShipmentDatabase(service.resolve_ship_db_file()).list_tree()

    assert tree["years"][0]["year"] == "2026"
    assert [month["month"] for month in tree["years"][0]["months"]] == ["06"]
    assert [shipment["day"] for shipment in tree["years"][0]["months"][0]["shipments"]] == ["17", "16", "15"]


def test_thumbnail_target_rejects_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    try:
        resolve_thumbnail_target(str(source), "../secret.mov")
    except ValueError as exc:
        assert str(exc) == "invalid file path"
    else:
        raise AssertionError("path traversal should be rejected")


def test_thumbnail_target_accepts_supported_relative_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    movie = source / "cut.mov"
    movie.write_bytes(b"movie")

    assert resolve_thumbnail_target(str(source), "cut.mov") == movie.resolve()


def read_audit_entries(log_dir: Path) -> list[dict[str, object]]:
    log_files = sorted(log_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    return [json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines()]
