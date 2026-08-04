from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict

from .bobs_catalog import bobs_catalog_job, bobs_catalog_jobs
from .bobs_retake_pdf import parse_bobs_retake_pdf
from ship_common.audit_log import write_manifest_audit_event
from ship_common.db_path import resolve_ship_db_file
from ship_common.manifest import create_manifest
from ship_common.models import ShipmentManifest
from ship_common.shipment_db import ShipmentDatabase


def scan(path: str, note: str = "") -> Dict[str, Any]:
    return create_manifest(path, note=note).to_dict()


def parse_bobs_pdf(
    path: str,
    *,
    excel_paths: str | list[str] | None = None,
    due_date_path: str | list[str] | None = None,
) -> Dict[str, Any]:
    return parse_bobs_retake_pdf(path, excel_paths=excel_paths, due_date_path=due_date_path)


def send(manifest_payload: Dict[str, Any]) -> Dict[str, Any]:
    manifest = ShipmentManifest.from_dict(manifest_payload)
    result = ShipmentDatabase(resolve_ship_db_file()).save(manifest.to_dict())
    write_manifest_audit_event("send", manifest.to_dict())
    return result


def log_generate(manifest_payload: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    manifest = ShipmentManifest.from_dict(manifest_payload)
    write_manifest_audit_event("generate", manifest.to_dict(), **(metadata or {}))
    return {"ok": True}


def sent_history() -> list[Dict[str, Any]]:
    db_file = resolve_ship_db_file()
    _debug_history(
        f"/history start cwd={os.getcwd()} SHIP_DB_DIR={os.getenv('SHIP_DB_DIR', '')!r} "
        f"db_path={db_file} parent={db_file.parent} parent_exists={db_file.parent.exists()} "
        f"exists={db_file.exists()} is_file={db_file.is_file()} size={_file_size(db_file)}"
    )
    _debug_history(f"/history probe={_probe_history_db(db_file)}")
    try:
        history = ShipmentDatabase(db_file).list_manifests()
    except Exception as exc:
        _debug_history(f"/history error type={type(exc).__name__} message={exc}")
        raise
    _debug_history(f"/history result count={len(history)} ids={[str(item.get('id', '')) for item in history[:5]]}")
    return history


def db_status() -> Dict[str, Any]:
    db_file = resolve_ship_db_file()
    _debug_history(
        f"/health db_status SHIP_DB_DIR={os.getenv('SHIP_DB_DIR', '')!r} db_path={db_file} "
        f"parent_exists={db_file.parent.exists()} exists={db_file.exists()} size={_file_size(db_file)}"
    )
    status: Dict[str, Any] = {
        "path": str(db_file),
        "exists": db_file.exists(),
        "parent_exists": db_file.parent.exists(),
    }
    if not db_file.exists():
        status["history_count"] = 0
        return status

    try:
        status["history_count"] = len(ShipmentDatabase(db_file).list_manifests())
    except Exception as exc:
        status["error"] = str(exc)
    return status


def bobs_jobs() -> Dict[str, Any]:
    return bobs_catalog_jobs()


def bobs_job(job: str) -> Dict[str, Any]:
    return bobs_catalog_job(job)


def _debug_history(message: str) -> None:
    print(f"[HISTORY-DEBUG] {message}", flush=True)


def _file_size(db_file: Path) -> int | str:
    try:
        return db_file.stat().st_size
    except OSError as exc:
        return f"unavailable:{exc}"


def _probe_history_db(db_file: Path) -> Dict[str, Any]:
    probe: Dict[str, Any] = {"opened": False, "tables": [], "shipments_count": None, "error": ""}
    if not db_file.exists() or not db_file.is_file():
        return probe
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(db_file, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma query_only = on")
        probe["opened"] = True
        probe["tables"] = [
            str(row[0])
            for row in connection.execute("select name from sqlite_master where type = 'table' order by name").fetchall()
        ]
        if "shipments" in probe["tables"]:
            probe["shipments_count"] = connection.execute("select count(*) from shipments").fetchone()[0]
    except Exception as exc:
        probe["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error as exc:
                if not probe["error"]:
                    probe["error"] = f"close {type(exc).__name__}: {exc}"
    return probe
