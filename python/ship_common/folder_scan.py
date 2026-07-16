from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from .models import FileEntry


IGNORED_NAMES = {".DS_Store"}


def scan_folder(folder_path: str) -> List[FileEntry]:
    root = Path(folder_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    entries: List[FileEntry] = []
    for path in _walk(root):
        relative_path = path.relative_to(root).as_posix()
        entries.append(FileEntry(path=relative_path, size=_safe_size(path), is_dir=path.is_dir()))
    return entries


def _walk(root: Path) -> Iterable[Path]:
    for child in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().lower()):
        if child.name in IGNORED_NAMES:
            continue
        yield child


def _safe_size(path: Path) -> int:
    if path.is_dir():
        return 0
    return path.stat().st_size
