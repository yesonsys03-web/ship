from pathlib import Path

from ship_common.manifest import create_manifest


def test_create_manifest_uses_last_folder_name(tmp_path: Path) -> None:
    folder = tmp_path / "SHIP_2026_001"
    folder.mkdir()
    (folder / "packing-list.txt").write_text("packed", encoding="utf-8")

    manifest = create_manifest(str(folder), note="urgent")

    assert manifest.id.startswith("ship-")
    assert manifest.folder_name == "SHIP_2026_001"
    assert manifest.note == "urgent"
    assert manifest.files[0].path == "packing-list.txt"


def test_create_manifest_keeps_fl_files_inside_dragged_date_folder(tmp_path: Path) -> None:
    folder = tmp_path / "2026_0703"
    folder.mkdir()
    (folder / "FL0101_main.psd").write_text("art", encoding="utf-8")

    manifest = create_manifest(str(folder))

    assert manifest.folder_name == "2026_0703"
    assert manifest.files[0].path == "FL0101_main.psd"
