from __future__ import annotations

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
    return ShipmentDatabase(resolve_ship_db_file()).list_manifests()


def db_status() -> Dict[str, Any]:
    db_file = resolve_ship_db_file()
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
