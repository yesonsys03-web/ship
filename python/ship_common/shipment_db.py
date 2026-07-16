from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .models import ShipmentManifest
from .thumbnails import PNG_SIGNATURE, THUMBNAIL_EXTENSIONS, get_thumbnail_bytes


MAX_THUMBNAIL_ERROR_SAMPLES = 5


def _is_valid_date(year: int, month: int, day: int) -> bool:
    try:
        parsed = datetime(year, month, day)
    except ValueError:
        return False
    return parsed.year == year and parsed.month == month and parsed.day == day


def _date_from_label(value: str, year_context: int | None = None) -> tuple[int, int, int] | None:
    import re

    year_first = re.search(r"(?:^|_)(\d{4})_(\d{2})(\d{2})(?:_|$)", value)
    if year_first:
        year = int(year_first.group(1))
        month = int(year_first.group(2))
        day = int(year_first.group(3))
        if _is_valid_date(year, month, day):
            return year, month, day

    year_last = re.search(r"(?:^|_)(\d{2})(\d{2})_(\d{4})(?:_|$)", value)
    if year_last:
        year = int(year_last.group(3))
        month = int(year_last.group(1))
        day = int(year_last.group(2))
        return (year, month, day) if _is_valid_date(year, month, day) else None

    bare_month_day = re.fullmatch(r"(\d{2})(\d{2})", value)
    if bare_month_day and year_context is not None:
        month = int(bare_month_day.group(1))
        day = int(bare_month_day.group(2))
        return (year_context, month, day) if _is_valid_date(year_context, month, day) else None

    return None


def _parse_created_at(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _date_from_manifest(manifest: ShipmentManifest) -> tuple[int, int, int]:
    created_at = _parse_created_at(manifest.created_at)
    sources = [manifest.folder_name, manifest.source_path, *(entry.path for entry in manifest.files)]
    for source in sources:
        parts = source.replace("\\", "/").split("/")
        for part in reversed([part for part in parts if part]):
            date_parts = _date_from_label(part, created_at.year)
            if date_parts:
                return date_parts
        date_parts = _date_from_label(source, created_at.year)
        if date_parts:
            return date_parts

    return created_at.year, created_at.month, created_at.day


def _manifest_content_signature(manifest_json: Dict[str, Any]) -> str:
    signature_payload = {
        "id": manifest_json.get("id", ""),
        "source_path": manifest_json.get("source_path", ""),
        "folder_name": manifest_json.get("folder_name", ""),
        "created_at": manifest_json.get("created_at", ""),
        "note": manifest_json.get("note", ""),
        "files": manifest_json.get("files", []),
    }
    encoded = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest_file_count(manifest_json: Dict[str, Any]) -> int:
    files = manifest_json.get("files", [])
    if not isinstance(files, list):
        return 0
    return sum(1 for entry in files if isinstance(entry, dict) and not bool(entry.get("is_dir")))


class ShipmentDatabase:
    def __init__(self, db_file: Path) -> None:
        self.db_file = db_file

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        manifest = ShipmentManifest.from_dict(payload)
        sent_at = datetime.now(timezone.utc).isoformat()
        stored_manifest = replace(manifest, sent_at=sent_at)
        year, month, day = _date_from_manifest(manifest)
        persisted_thumbnails: list[tuple[str, bytes]] = []
        thumbnail_errors: list[str] = []
        thumbnail_error_count = 0
        for entry in manifest.files:
            if not _is_previewable_file(entry):
                continue
            try:
                thumbnail = get_thumbnail_bytes(manifest.source_path, entry.path)
            except Exception as exc:
                thumbnail_error_count += 1
                if len(thumbnail_errors) < MAX_THUMBNAIL_ERROR_SAMPLES:
                    thumbnail_errors.append(f"{entry.path}: {exc}")
                continue
            if thumbnail.startswith(PNG_SIGNATURE):
                persisted_thumbnails.append((entry.path, thumbnail))
            else:
                thumbnail_error_count += 1
                if len(thumbnail_errors) < MAX_THUMBNAIL_ERROR_SAMPLES:
                    thumbnail_errors.append(f"{entry.path}: generated thumbnail was not PNG")
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            _ensure_schema(connection)
            connection.execute(
                """
                insert into shipments (
                    id, folder_name, source_path, created_at, year, month, day,
                    note, file_count, manifest_json, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    folder_name = excluded.folder_name,
                    source_path = excluded.source_path,
                    created_at = excluded.created_at,
                    year = excluded.year,
                    month = excluded.month,
                    day = excluded.day,
                    note = excluded.note,
                    file_count = excluded.file_count,
                    manifest_json = excluded.manifest_json,
                    updated_at = excluded.updated_at
                """,
                (
                    manifest.id,
                    manifest.folder_name,
                    manifest.source_path,
                    manifest.created_at,
                    f"{year:04d}",
                    f"{month:02d}",
                    f"{day:02d}",
                    manifest.note,
                    sum(1 for entry in manifest.files if not entry.is_dir),
                    json.dumps(stored_manifest.to_dict(), ensure_ascii=False),
                    sent_at,
                ),
            )
            self._upsert_thumbnails(connection, manifest.id, persisted_thumbnails)
        return {
            "ok": True,
            "id": manifest.id,
            "folder_name": manifest.folder_name,
            "db_path": str(self.db_file),
            "thumbnail_count": len(persisted_thumbnails),
            "thumbnail_error_count": thumbnail_error_count,
            "thumbnail_errors": thumbnail_errors,
        }

    def list_manifests(self) -> List[Dict[str, Any]]:
        if not self.db_file.exists():
            return []

        with self._connect() as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                """
                select manifest_json
                from shipments
                order by updated_at desc, year desc, month desc, day desc, folder_name collate nocase asc
                """
            ).fetchall()

        return [json.loads(row["manifest_json"]) for row in rows]

    def list_tree(self) -> Dict[str, Any]:
        if not self.db_file.exists():
            return {"years": []}

        with self._connect() as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                """
                select id, folder_name, created_at, year, month, day, file_count, manifest_json
                from shipments
                order by updated_at desc, year desc, month desc, day desc, folder_name collate nocase asc
                """
            ).fetchall()

        years: List[Dict[str, Any]] = []
        year_map: Dict[str, Dict[str, Any]] = {}
        month_map: Dict[tuple[str, str], Dict[str, Any]] = {}

        for row in rows:
            manifest_json = json.loads(row["manifest_json"])
            year = str(row["year"])
            month = str(row["month"])
            year_entry = year_map.get(year)
            if year_entry is None:
                year_entry = {"year": year, "months": []}
                year_map[year] = year_entry
                years.append(year_entry)

            key = (year, month)
            month_entry = month_map.get(key)
            if month_entry is None:
                month_entry = {"month": month, "shipments": []}
                month_map[key] = month_entry
                year_entry["months"].append(month_entry)

            month_entry["shipments"].append(
                {
                    "id": row["id"],
                    "label": row["folder_name"],
                    "day": row["day"],
                    "created_at": row["created_at"],
                    "sent_at": manifest_json.get("sent_at"),
                    "content_signature": _manifest_content_signature(manifest_json),
                    "file_count": _manifest_file_count(manifest_json),
                }
            )

        return {"years": years}

    def load(self, shipment_id: str) -> Dict[str, Any]:
        if not self.db_file.exists():
            raise FileNotFoundError(shipment_id)

        with self._connect() as connection:
            _ensure_schema(connection)
            row = connection.execute("select manifest_json from shipments where id = ?", (shipment_id,)).fetchone()
        if row is None:
            raise FileNotFoundError(shipment_id)
        return json.loads(row["manifest_json"])

    def get_thumbnail_bytes(self, shipment_id: str, file_path: str) -> bytes | None:
        if not self.db_file.exists():
            return None

        with self._connect() as connection:
            _ensure_schema(connection)
            row = connection.execute(
                """
                select png_bytes
                from shipment_thumbnails
                where shipment_id = ? and file_path = ?
                """,
                (shipment_id, file_path),
            ).fetchone()
        if row is None:
            return None
        thumbnail = bytes(row["png_bytes"])
        return thumbnail if thumbnail.startswith(PNG_SIGNATURE) else None

    def save_thumbnail_bytes(self, shipment_id: str, file_path: str, thumbnail: bytes) -> bool:
        if not thumbnail.startswith(PNG_SIGNATURE):
            return False

        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            _ensure_schema(connection)
            self._upsert_thumbnails(connection, shipment_id, [(file_path, thumbnail)])
        return True

    def _upsert_thumbnails(
        self,
        connection: sqlite3.Connection,
        shipment_id: str,
        thumbnails: list[tuple[str, bytes]],
    ) -> None:
        connection.executemany(
            """
            insert into shipment_thumbnails (shipment_id, file_path, png_bytes, updated_at)
            values (?, ?, ?, ?)
            on conflict(shipment_id, file_path) do update set
                png_bytes = excluded.png_bytes,
                updated_at = excluded.updated_at
            """,
            [
                (shipment_id, file_path, sqlite3.Binary(thumbnail), datetime.now(timezone.utc).isoformat())
                for file_path, thumbnail in thumbnails
            ],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma journal_mode = wal")
        connection.execute("pragma busy_timeout = 5000")
        return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists shipments (
            id text primary key,
            folder_name text not null,
            source_path text not null,
            created_at text not null,
            year text not null,
            month text not null,
            day text not null,
            note text not null,
            file_count integer not null,
            manifest_json text not null,
            updated_at text not null
        )
        """
    )
    connection.execute("create index if not exists idx_shipments_date on shipments(year, month, day)")
    connection.execute(
        """
        create table if not exists shipment_thumbnails (
            shipment_id text not null,
            file_path text not null,
            png_bytes blob not null,
            updated_at text not null,
            primary key (shipment_id, file_path)
        )
        """
    )
    connection.execute("create index if not exists idx_shipment_thumbnails_shipment on shipment_thumbnails(shipment_id)")


def _is_previewable_file(entry: Any) -> bool:
    if entry.is_dir:
        return False
    extension = Path(entry.path).suffix.lower().lstrip(".")
    return extension in THUMBNAIL_EXTENSIONS
