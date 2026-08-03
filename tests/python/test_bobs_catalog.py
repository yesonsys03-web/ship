from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ship_sender import server as sender_server
from ship_sender.bobs_catalog import BOBS_CATALOG_ROOTS, bobs_catalog_job, bobs_catalog_jobs, read_scene_names, sequences_for_scenes


def test_bobs_catalog_roots_include_windows_network_share() -> None:
    assert Path("//Mserver/USA_DB") in BOBS_CATALOG_ROOTS


def test_bobs_catalog_jobs_uses_first_available_root_and_filters_sorted_jobs(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    root = tmp_path / "mounted"
    jobs_root = root / "db_jobs"
    for job in ["FASA10", "1510", "FASA02", "HAZA01", "GARF_TEST", "FASA01", "BB"]:
        (jobs_root / job).mkdir(parents=True)

    payload = bobs_catalog_jobs((missing_root, root))

    assert payload == {
        "environment": "Bobs_Burgers",
        "root": str(root),
        "jobs_db_path": str(root / "online_jobs" / "jobs.db"),
        "jobs_source": "db_jobs",
        "jobs": ["FASA01", "FASA02", "FASA10", "HAZA01"],
        "warnings": [],
    }


def test_bobs_catalog_jobs_unions_db_jobs_and_jobs_db_with_prefix_filtering(tmp_path: Path) -> None:
    jobs_root = tmp_path / "db_jobs"
    for job in ["FASA10", "FASA01", "BAD01", "GASA02"]:
        (jobs_root / job).mkdir(parents=True)
    create_jobs_db(
        tmp_path / "online_jobs" / "jobs.db",
        [
            ("FASA02", "01A_S01"),
            ("HAZA01", "02A_S01"),
            ("XXSA01", "03A_S01"),
            ("GASA02", "04A_S01"),
            ("GARF_TEST", "05A_S01"),
        ],
    )

    payload = bobs_catalog_jobs((tmp_path,))

    assert payload["jobs"] == ["FASA01", "FASA02", "FASA10", "GASA02", "HAZA01"]
    assert payload["jobs_db_path"] == str(tmp_path / "online_jobs" / "jobs.db")
    assert payload["jobs_source"] == "db_jobs+jobs_db"
    assert payload["warnings"] == []


def test_bobs_catalog_jobs_filters_internal_binary_jobs_db_tokens(tmp_path: Path) -> None:
    (tmp_path / "db_jobs" / "FASA01").mkdir(parents=True)
    jobs_db = tmp_path / "online_jobs" / "jobs.db"
    jobs_db.parent.mkdir(parents=True)
    jobs_db.write_bytes(b"custom FASA02 GARF_TEST HAZA_INTERNAL GASA03")

    payload = bobs_catalog_jobs((tmp_path,))

    assert payload["jobs"] == ["FASA01", "FASA02", "GASA03"]
    assert "jobs.db scanned as custom binary data for embedded job names" in payload["warnings"]


def test_bobs_catalog_job_prefers_jobs_db_scenes_when_present(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "FASA01" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    write_scene_db(scene_db, ["99A_S01"])
    create_jobs_db(
        tmp_path / "online_jobs" / "jobs.db",
        [
            ("FASA01", "01A_S02"),
            ("FASA01", "01A_S01"),
            ("FASA01", "not_a_scene"),
        ],
    )

    payload = bobs_catalog_job("FASA01", (tmp_path,))

    assert payload["status"] == "jobs_db"
    assert payload["scene_source"] == "jobs_db"
    assert payload["jobs_db_path"] == str(tmp_path / "online_jobs" / "jobs.db")
    assert payload["scene_db_path"] == str(scene_db)
    assert payload["scenes"] == ["01A_S01", "01A_S02"]
    assert payload["sequences"] == {"01A": ["01A_S01", "01A_S02"]}
    assert payload["warnings"] == []


def test_bobs_catalog_job_falls_back_to_scene_db_when_jobs_db_lacks_job_scenes(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "FASA01" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    write_scene_db(scene_db, ["01B_S01", "01A_S01"])
    create_jobs_db(tmp_path / "online_jobs" / "jobs.db", [("FASA01", "not_a_scene")])

    payload = bobs_catalog_job("FASA01", (tmp_path,))

    assert payload["status"] == "ok"
    assert payload["scene_source"] == "scene_db"
    assert payload["scenes"] == ["01A_S01", "01B_S01"]
    assert payload["warnings"] == []


def test_bobs_catalog_jobs_handles_missing_jobs_db_gracefully(tmp_path: Path) -> None:
    (tmp_path / "db_jobs" / "FASA01").mkdir(parents=True)

    payload = bobs_catalog_jobs((tmp_path,))

    assert payload["jobs"] == ["FASA01"]
    assert payload["jobs_source"] == "db_jobs"
    assert payload["warnings"] == []


def test_bobs_catalog_jobs_handles_unreadable_jobs_db_gracefully(tmp_path: Path) -> None:
    (tmp_path / "db_jobs" / "FASA01").mkdir(parents=True)
    jobs_db = tmp_path / "online_jobs" / "jobs.db"
    jobs_db.parent.mkdir(parents=True)
    jobs_db.write_bytes(b"not sqlite and no job tokens")

    payload = bobs_catalog_jobs((tmp_path,))

    assert payload["jobs"] == ["FASA01"]
    assert payload["jobs_source"] == "db_jobs+jobs_db"
    assert "jobs.db is not readable SQLite" in payload["warnings"][0]
    assert "found no job-name-like values" in payload["warnings"][1]


def test_bobs_catalog_job_reads_sqlite_scene_names_and_derives_sequences(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "FASA01" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    write_scene_db(scene_db, ["01A_S02", "01A_S01", "not_a_scene", "01B_S05", "02A_S01"])

    payload = bobs_catalog_job("FASA01", (tmp_path,))

    assert payload["environment"] == "Bobs_Burgers"
    assert payload["job"] == "FASA01"
    assert payload["scene_db_path"] == str(scene_db)
    assert payload["status"] == "ok"
    assert payload["scenes"] == ["01A_S01", "01A_S02", "01B_S05", "02A_S01"]
    assert payload["sequences"] == {"01A": ["01A_S01", "01A_S02"], "01B": ["01B_S05"], "02A": ["02A_S01"]}
    assert payload["warnings"] == []


def test_bobs_catalog_job_includes_numeric_and_non_letter_sequences(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "FASA26" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    write_scene_db(
        scene_db,
        [
            "07A_S01",
            "03B_S02",
            "12_S01",
            "08-ALT_S03",
            "not_a_scene",
            "unbounded/path/12_S02",
            "08-ALT_S003",
        ],
    )

    payload = bobs_catalog_job("FASA26", (tmp_path,))

    assert payload["scenes"] == ["03B_S02", "07A_S01", "08-ALT_S03", "12_S01"]
    assert payload["sequences"] == {
        "03B": ["03B_S02"],
        "07A": ["07A_S01"],
        "08-ALT": ["08-ALT_S03"],
        "12": ["12_S01"],
    }
    assert payload["warnings"] == []


def test_bobs_catalog_job_scans_non_sqlite_scene_db_for_binary_scene_tokens(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "GASA01" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    scene_db.write_bytes(
        b"custom-db\x08 01A_S02\x00"
        b"duplicate 01A_S01\x00"
        b"other 01A_S02\x00"
        b"next 01B_S05\x00"
        b"numeric 12_S01\x00"
        b"hyphen 08-ALT_S03\x00"
        b"ignore NOT_A_SCENE 1A_S01 123_S01 01AA_S01 01A_S001 /12_S04 08-ALT_S003"
    )

    payload = bobs_catalog_job("GASA01", (tmp_path,))

    assert payload["status"] == "scene_db_binary_scan"
    assert payload["scenes"] == ["01A_S01", "01A_S02", "01B_S05", "08-ALT_S03", "12_S01"]
    assert payload["sequences"] == {
        "01A": ["01A_S01", "01A_S02"],
        "01B": ["01B_S05"],
        "08-ALT": ["08-ALT_S03"],
        "12": ["12_S01"],
    }
    assert "not readable SQLite" in payload["warnings"][0]
    assert "custom binary" in payload["warnings"][1]


def test_bobs_catalog_job_reports_unrecognized_binary_scene_db(tmp_path: Path) -> None:
    scene_db = tmp_path / "db_jobs" / "GASA01" / "scene.db"
    scene_db.parent.mkdir(parents=True)
    scene_db.write_bytes(b"not sqlite and no conservative scene tokens")

    payload = bobs_catalog_job("GASA01", (tmp_path,))

    assert payload["status"] == "scene_db_binary_unrecognized"
    assert payload["scenes"] == []
    assert payload["sequences"] == {}
    assert "not readable SQLite" in payload["warnings"][0]
    assert "found no scene-name-like values" in payload["warnings"][1]


def test_read_scene_names_scans_raw_binary_scene_tokens(tmp_path: Path) -> None:
    scene_db = tmp_path / "scene.db"
    scene_db.write_bytes(
        b"\x08 01A_S01\x00\x08 01A_S02\x00\x08 01B_S05\x00\x08 01A_S01\x00"
        b"\x08 12_S01\x00\x08 08-ALT_S03\x00 ignore /12_S04 08-ALT_S003"
    )

    scenes, warnings, status = read_scene_names(scene_db)

    assert status == "scene_db_binary_scan"
    assert scenes == ["01A_S01", "01A_S02", "01B_S05", "08-ALT_S03", "12_S01"]
    assert "not readable SQLite" in warnings[0]
    assert "custom binary" in warnings[1]


def test_read_scene_names_includes_letter_suffix_scenes_and_excludes_old_or_model_entries(tmp_path: Path) -> None:
    scene_db = tmp_path / "scene.db"
    connection = sqlite3.connect(scene_db)
    try:
        connection.execute("create table scenes (name text)")
        connection.executemany(
            "insert into scenes (name) values (?)",
            [
                ("24B_S22",),
                ("24B_S23B",),
                ("24B_S24.old",),
                ("scene-24A_S14_old",),
                ("scene-00_Sub_Model",),
                ("00_Sub_Model",),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    scenes, warnings, status = read_scene_names(scene_db)

    assert status == "ok"
    assert scenes == ["24B_S22", "24B_S23B"]
    assert warnings == []


def test_read_scene_names_reports_unrecognized_binary_scene_db(tmp_path: Path) -> None:
    scene_db = tmp_path / "scene.db"
    scene_db.write_bytes(b"custom bytes with 01A_S001 but no exact scene token")

    scenes, warnings, status = read_scene_names(scene_db)

    assert scenes == []
    assert status == "scene_db_binary_unrecognized"
    assert "not readable SQLite" in warnings[0]
    assert warnings[1] == "scene.db custom binary scan found no scene-name-like values"


def test_bobs_catalog_job_returns_warning_for_missing_scene_db(tmp_path: Path) -> None:
    (tmp_path / "db_jobs" / "FASA02").mkdir(parents=True)

    payload = bobs_catalog_job("FASA02", (tmp_path,))

    assert payload["status"] == "scene_db_missing"
    assert payload["scene_db_path"] == str(tmp_path / "db_jobs" / "FASA02" / "scene.db")
    assert payload["scenes"] == []
    assert payload["sequences"] == {}
    assert "scene.db missing" in payload["warnings"][0]


def test_read_scene_names_reports_no_scene_like_values(tmp_path: Path) -> None:
    scene_db = tmp_path / "scene.db"
    connection = sqlite3.connect(scene_db)
    try:
        connection.execute("create table metadata (name text)")
        connection.execute("insert into metadata (name) values ('hello')")
        connection.commit()
    finally:
        connection.close()

    scenes, warnings, status = read_scene_names(scene_db)

    assert scenes == []
    assert status == "no_scenes_found"
    assert warnings == ["scene.db opened as SQLite but no scene-name-like values were found"]


def test_sequences_for_scenes_groups_by_prefix_before_s_marker() -> None:
    assert sequences_for_scenes(["01A_S02", "01B_S05", "01A_S01"]) == {
        "01A": ["01A_S01", "01A_S02"],
        "01B": ["01B_S05"],
    }


def test_sender_route_returns_bobs_catalog_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"environment": "Bobs_Burgers", "root": "/tmp/root", "jobs": ["FASA01"], "warnings": []}
    monkeypatch.setattr(sender_server, "bobs_jobs", lambda: payload)

    sent = run_sender_get("/bobs/catalog/jobs", monkeypatch)

    assert sent["json"] == (payload, 200)


def test_sender_route_returns_bobs_catalog_job_with_scene_status(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "environment": "Bobs_Burgers",
        "job": "FASA01",
        "status": "scene_db_binary_scan",
        "scenes": ["01A_S01"],
        "sequences": {"01A": ["01A_S01"]},
        "warnings": ["scene.db scanned as custom binary data for embedded scene names"],
    }
    monkeypatch.setattr(sender_server, "bobs_job", lambda job: payload | {"job": job})

    sent = run_sender_get("/bobs/catalog/job?job=FASA01", monkeypatch)

    assert sent["json"] == (payload, 200)


def test_sender_route_requires_bobs_catalog_job_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = run_sender_get("/bobs/catalog/job", monkeypatch)

    assert sent["json"] == ({"error": "missing job"}, 400)


def create_jobs_db(jobs_db: Path, rows: list[tuple[str, str]]) -> None:
    jobs_db.parent.mkdir(parents=True)
    connection = sqlite3.connect(jobs_db)
    try:
        connection.execute("create table online_catalog (job_code text, scene_name text, notes text)")
        connection.executemany(
            "insert into online_catalog (job_code, scene_name, notes) values (?, ?, ?)",
            [(job, scene, f"{job}/{scene}") for job, scene in rows],
        )
        connection.commit()
    finally:
        connection.close()


def write_scene_db(scene_db: Path, scenes: list[str]) -> None:
    connection = sqlite3.connect(scene_db)
    try:
        connection.execute("create table scene_catalog (id integer primary key, scene_name text, notes text)")
        connection.executemany(
            "insert into scene_catalog (scene_name, notes) values (?, ?)",
            [(scene, "ignore") for scene in scenes],
        )
        connection.commit()
    finally:
        connection.close()


def run_sender_get(path: str, monkeypatch: pytest.MonkeyPatch) -> dict:
    handler = object.__new__(sender_server.SenderHandler)
    handler.path = path
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)
    sent = {"json": None}

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    monkeypatch.setattr(sender_server.SenderHandler, "_send_json", fake_send_json)
    sender_server.SenderHandler.do_GET(handler)
    return sent
