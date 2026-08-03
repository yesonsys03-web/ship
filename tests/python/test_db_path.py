import os
from pathlib import Path

from ship_common.db_path import SHIP_DB_DIR_CANDIDATES, WINDOWS_SHIP_DB_DIR_CANDIDATES, resolve_ship_db_file


def test_default_ship_db_candidates_match_approved_mount_paths() -> None:
    posix_candidates = (
        Path("/System/Volumes/Data/USA_DB/test_jn/ship_db"),
        Path("/USA_DB/test_jn/ship_db"),
        Path("//Mserver/USA_DB/test_jn/ship_db"),
        Path("/System/Volumes/Data/mnt/USA_DB/test_jn/ship_db"),
    )
    expected = WINDOWS_SHIP_DB_DIR_CANDIDATES + posix_candidates if os.name == "nt" else posix_candidates + WINDOWS_SHIP_DB_DIR_CANDIDATES

    assert SHIP_DB_DIR_CANDIDATES == expected


def test_windows_ship_db_candidate_uses_unc_path() -> None:
    assert WINDOWS_SHIP_DB_DIR_CANDIDATES == (
        Path("//Mserver/USA_DB/test_jn/ship_db"),
        Path(r"\\Mserver\USA_DB\test_jn\ship_db"),
    )


def test_windows_ship_db_candidate_prefers_forward_slash_unc_path() -> None:
    assert WINDOWS_SHIP_DB_DIR_CANDIDATES[0] == Path("//Mserver/USA_DB/test_jn/ship_db")


def test_resolve_ship_db_file_uses_env_directory(monkeypatch, tmp_path: Path) -> None:
    db_dir = tmp_path / "ship_db"
    monkeypatch.setenv("SHIP_DB_DIR", str(db_dir))

    db_file = resolve_ship_db_file()

    assert db_file == db_dir / "shipments.sqlite3"
    assert not db_dir.exists()


def test_resolve_ship_db_file_uses_first_existing_candidate(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "missing"
    second = tmp_path / "mounted" / "ship_db"
    second.mkdir(parents=True)
    monkeypatch.delenv("SHIP_DB_DIR", raising=False)

    db_file = resolve_ship_db_file((first, second))

    assert db_file == second / "shipments.sqlite3"


def test_resolve_ship_db_file_prefers_candidate_with_existing_db(monkeypatch, tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty" / "ship_db"
    mounted_dir = tmp_path / "Volumes" / "USA_DB" / "test_jn" / "ship_db"
    empty_dir.mkdir(parents=True)
    mounted_dir.mkdir(parents=True)
    (mounted_dir / "shipments.sqlite3").write_bytes(b"db")
    monkeypatch.delenv("SHIP_DB_DIR", raising=False)

    db_file = resolve_ship_db_file((empty_dir, mounted_dir))

    assert db_file == mounted_dir / "shipments.sqlite3"
