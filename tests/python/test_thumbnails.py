from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ship_common import thumbnails


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_find_generated_thumbnail_prefers_png_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "ql"
    output_dir.mkdir()
    (output_dir / "cut.tiff").write_bytes(b"not-png")
    (output_dir / "z-preview.png").write_bytes(PNG_SIGNATURE + b"png-z")
    (output_dir / "a-preview.png").write_bytes(PNG_SIGNATURE + b"png-a")
    (output_dir / "nested.png").mkdir()

    assert thumbnails._find_generated_thumbnail(output_dir) == output_dir / "a-preview.png"


def test_find_generated_thumbnail_ignores_invalid_png_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "ql"
    output_dir.mkdir()
    (output_dir / "cut.png").write_bytes(b"not-png")

    with pytest.raises(FileNotFoundError, match="no png thumbnail was generated") as exc_info:
        thumbnails._find_generated_thumbnail(output_dir)

    assert "cut.png" in str(exc_info.value)


def test_find_generated_thumbnail_reports_non_png_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "ql"
    output_dir.mkdir()
    (output_dir / "cut.tiff").write_bytes(b"not-png")

    with pytest.raises(FileNotFoundError, match="no png thumbnail was generated") as exc_info:
        thumbnails._find_generated_thumbnail(output_dir)

    message = str(exc_info.value)
    assert "cut.tiff" in message
    assert str(output_dir) in message


def test_get_thumbnail_bytes_reports_quick_look_stderr_for_non_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    psd = source_dir / "art.psd"
    psd.write_bytes(b"psd")

    def fail_quick_look(*args, **kwargs):
        raise subprocess.CalledProcessError(
            64,
            kwargs.get("args") or args[0],
            output="ql stdout",
            stderr="ql stderr",
        )

    monkeypatch.setattr(thumbnails, "THUMBNAIL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(thumbnails.subprocess, "run", fail_quick_look)

    with pytest.raises(RuntimeError) as exc_info:
        thumbnails.get_thumbnail_bytes(str(source_dir), "art.psd")

    message = str(exc_info.value)
    assert "qlmanage" in message
    assert "exit code 64" in message
    assert "ql stderr" in message
    assert "ql stdout" in message
    assert "output_dir=" in message
    assert "art.psd" in message
    assert "suffix=.psd" in message


def test_get_thumbnail_bytes_reports_quick_look_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    psd = source_dir / "art.psd"
    psd.write_bytes(b"psd")

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            kwargs.get("args") or args[0],
            timeout=15,
            output="late stdout",
            stderr="late stderr",
        )

    monkeypatch.setattr(thumbnails, "THUMBNAIL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(thumbnails.subprocess, "run", time_out)

    with pytest.raises(RuntimeError) as exc_info:
        thumbnails.get_thumbnail_bytes(str(source_dir), "art.psd")

    message = str(exc_info.value)
    assert "timed out after 15s" in message
    assert "late stderr" in message
    assert "output_dir=" in message


def test_get_thumbnail_bytes_uses_video_placeholder_after_quick_look_no_png(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    movie = source_dir / "cut.mov"
    movie.write_bytes(b"movie")

    def no_png(command, **kwargs):
        output_dir = Path(command[command.index("-o") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "cut.tiff").write_bytes(b"not-png")
        return subprocess.CompletedProcess(command, 0, stdout="ql stdout", stderr="ql stderr")

    monkeypatch.setattr(thumbnails, "THUMBNAIL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(thumbnails.subprocess, "run", no_png)

    body = thumbnails.get_thumbnail_bytes(str(source_dir), "cut.mov")

    assert body.startswith(PNG_SIGNATURE)
    assert len(list(cache_dir.glob("*.png"))) == 1


def test_get_thumbnail_bytes_uses_video_placeholder_after_quick_look_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    movie = source_dir / "cut.mp4"
    movie.write_bytes(b"movie")

    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=15, output="late stdout", stderr="late stderr")

    monkeypatch.setattr(thumbnails, "THUMBNAIL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(thumbnails.subprocess, "run", time_out)

    body = thumbnails.get_thumbnail_bytes(str(source_dir), "cut.mp4")

    assert body.startswith(PNG_SIGNATURE)
    assert thumbnails.get_thumbnail_bytes(str(source_dir), "cut.mp4") == body


def test_get_thumbnail_bytes_uses_video_placeholder_after_quick_look_non_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()
    movie = source_dir / "cut.webm"
    movie.write_bytes(b"movie")

    def fail_quick_look(command, **kwargs):
        raise subprocess.CalledProcessError(64, command, output="ql stdout", stderr="ql stderr")

    monkeypatch.setattr(thumbnails, "THUMBNAIL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(thumbnails.subprocess, "run", fail_quick_look)

    body = thumbnails.get_thumbnail_bytes(str(source_dir), "cut.webm")

    assert body.startswith(PNG_SIGNATURE)
    assert len(list(cache_dir.glob("*.png"))) == 1


def test_video_placeholder_png_is_deterministic_and_labeled(tmp_path: Path) -> None:
    target = tmp_path / "clip.m4v"
    target.write_bytes(b"movie")
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"

    thumbnails._write_video_placeholder_thumbnail(target, first, ["quick-look failed"])
    thumbnails._write_video_placeholder_thumbnail(target, second, ["different diagnostics"])

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(PNG_SIGNATURE)
    assert b"clip.m4v" in first.read_bytes()
    assert b"suffix=.m4v" in first.read_bytes()
