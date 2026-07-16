from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .folder_scan import scan_folder
from .models import ShipmentManifest


def create_manifest(folder_path: str, note: str = "") -> ShipmentManifest:
    root = Path(folder_path).expanduser().resolve()
    created_at = datetime.now(timezone.utc).isoformat()
    return ShipmentManifest(
        id=f"ship-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
        source_path=str(root),
        folder_name=root.name,
        created_at=created_at,
        note=note,
        files=scan_folder(str(root)),
    )
