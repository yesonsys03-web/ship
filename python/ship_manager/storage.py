from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ship_common.shipment_db import ShipmentDatabase


class ShipmentStorage:
    def __init__(self, data_dir: Path, db_file: Path | None = None) -> None:
        self.data_dir = data_dir
        self.database = ShipmentDatabase(db_file or data_dir / "shipments.sqlite3")

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.database.save(payload)

    def list_tree(self) -> Dict[str, Any]:
        return self.database.list_tree()

    def load(self, shipment_id: str) -> Dict[str, Any]:
        return self.database.load(shipment_id)
