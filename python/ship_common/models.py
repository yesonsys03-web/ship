from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    is_dir: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "size": self.size, "is_dir": self.is_dir}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "FileEntry":
        return cls(path=str(value["path"]), size=int(value["size"]), is_dir=bool(value["is_dir"]))


@dataclass(frozen=True)
class ShipmentManifest:
    id: str
    source_path: str
    folder_name: str
    created_at: str
    files: List[FileEntry]
    note: str = ""
    sent_at: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "source_path": self.source_path,
            "folder_name": self.folder_name,
            "created_at": self.created_at,
            "note": self.note,
            "files": [entry.to_dict() for entry in self.files],
        }
        if self.sent_at is not None:
            payload["sent_at"] = self.sent_at
        return payload

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ShipmentManifest":
        return cls(
            id=str(value["id"]),
            source_path=str(value["source_path"]),
            folder_name=str(value["folder_name"]),
            created_at=str(value["created_at"]),
            note=str(value.get("note", "")),
            sent_at=str(value["sent_at"]) if value.get("sent_at") is not None else None,
            files=[FileEntry.from_dict(entry) for entry in value.get("files", [])],
        )
