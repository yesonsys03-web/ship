from pathlib import Path

from ship_common.folder_scan import scan_folder


def test_scan_folder_lists_relative_paths_and_skips_macos_metadata(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "invoice.txt").write_text("abc", encoding="utf-8")
    (tmp_path / ".DS_Store").write_text("ignore", encoding="utf-8")

    entries = scan_folder(str(tmp_path))

    assert [entry.path for entry in entries] == ["docs", "docs/invoice.txt"]
    assert entries[0].is_dir is True
    assert entries[1].size == 3
