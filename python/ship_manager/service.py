from __future__ import annotations

from typing import Any, Dict

from urllib.parse import parse_qs, urlparse

from ship_common.db_path import resolve_ship_db_file

from .config import MANAGER_DATA_DIR, SHIP_SCENE_ROOT
from .scene_validation import enrich_manifest_scene_validation
from .storage import ShipmentStorage


storage = ShipmentStorage(MANAGER_DATA_DIR, db_file=resolve_ship_db_file())


def receive(payload: Dict[str, Any]) -> Dict[str, Any]:
    return storage.save(payload)


def list_shipments() -> Dict[str, Any]:
    return storage.list_tree()


def get_shipment(path: str) -> Dict[str, Any]:
    query = parse_qs(urlparse(path).query)
    shipment_id = query.get("id", [""])[0]
    if not shipment_id:
        raise ValueError("missing id")
    manifest = storage.load(shipment_id)
    if query.get("scene_validation", [""])[0] == "0":
        return manifest
    return enrich_manifest_scene_validation(manifest, SHIP_SCENE_ROOT)
