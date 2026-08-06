from __future__ import annotations

import hashlib
import shlex
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Optional, Union


IMAGE_THUMBNAIL_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "avif", "heic", "heif"}
GENERATED_THUMBNAIL_EXTENSIONS = {"mov", "mp4", "m4v", "webm", "psd", "psb"}
THUMBNAIL_EXTENSIONS = IMAGE_THUMBNAIL_EXTENSIONS | GENERATED_THUMBNAIL_EXTENSIONS
VIDEO_THUMBNAIL_EXTENSIONS = {"mov", "mp4", "m4v", "webm"}
DESIGN_THUMBNAIL_EXTENSIONS = {"psd", "psb"}
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "ship_sender_thumbnails"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def resolve_thumbnail_target(source_path: str, file_path: str) -> Path:
    root = Path(source_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(str(root))

    relative_path = Path(file_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("invalid file path")

    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("invalid file path")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(str(target))

    extension = target.suffix.lower().lstrip(".")
    if extension not in THUMBNAIL_EXTENSIONS:
        raise ValueError("unsupported thumbnail type")

    return target


def get_thumbnail_bytes(source_path: str, file_path: str) -> bytes:
    target = resolve_thumbnail_target(source_path, file_path)
    cached_thumbnail = _cache_path(target)
    if cached_thumbnail.exists():
        if _is_png_file(cached_thumbnail):
            return cached_thumbnail.read_bytes()
        cached_thumbnail.unlink()

    THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ship-thumb-") as output_dir:
        output_root = Path(output_dir)
        failures: list[str] = []
        try:
            generated_thumbnail = (
                _generate_design_thumbnail(target, output_root, failures)
                if _is_design_thumbnail(target)
                else _generate_quick_look_thumbnail(target, output_root, failures)
            )
        except RuntimeError as exc:
            if _is_video_thumbnail(target):
                generated_thumbnail = output_root / "video-placeholder.png"
                _write_video_placeholder_thumbnail(target, generated_thumbnail, failures or [str(exc)])
            elif _is_design_thumbnail(target):
                generated_thumbnail = output_root / "design-placeholder.png"
                _write_design_placeholder_thumbnail(target, generated_thumbnail, failures or [str(exc)])
            else:
                raise
        shutil.copyfile(generated_thumbnail, cached_thumbnail)
    return cached_thumbnail.read_bytes()


def get_design_placeholder_thumbnail_bytes(file_path: str) -> bytes:
    target = Path(file_path)
    with tempfile.TemporaryDirectory(prefix="ship-thumb-placeholder-") as output_dir:
        output_path = Path(output_dir) / "design-placeholder.png"
        _write_design_placeholder_thumbnail(target, output_path, [])
        return output_path.read_bytes()


def is_design_placeholder_thumbnail_bytes(thumbnail: bytes) -> bool:
    return thumbnail.startswith(PNG_SIGNATURE) and b"SHIP design thumbnail fallback" in thumbnail


def _generate_design_thumbnail(target: Path, output_root: Path, failures: list[str]) -> Path:
    try:
        return _generate_psd_tools_thumbnail(target, output_root / "psd-tools")
    except RuntimeError as exc:
        failures.append(f"psd-tools: {exc}")

    return _generate_quick_look_thumbnail(target, output_root, failures)


def _generate_psd_tools_thumbnail(target: Path, output_dir: Path) -> Path:
    try:
        from psd_tools import PSDImage
    except ImportError as exc:
        raise RuntimeError("psd-tools is not installed") from exc

    try:
        psd = PSDImage.open(target)
        image = psd.thumbnail() or psd.topil(apply_icc=True) or psd.composite(apply_icc=True)
        if image is None:
            raise RuntimeError("PSD has no embedded thumbnail, preview, or composite image")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{target.stem}.png"
        png_image = image.convert("RGBA")
        png_image.thumbnail((320, 320))
        png_image.save(output_path, format="PNG")
        if not _is_png_file(output_path):
            raise RuntimeError("psd-tools output was not PNG")
        return output_path
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc


def _cache_path(target: Path) -> Path:
    stat = target.stat()
    cache_key = hashlib.sha256(f"{target}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")).hexdigest()
    return THUMBNAIL_CACHE_DIR / f"{cache_key}.png"


def _generate_quick_look_thumbnail(target: Path, output_root: Path, failures: list[str]) -> Path:
    for label, command, output_dir in _quick_look_attempts(target, output_root):
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            _run_quick_look_command(command, output_dir, target)
            return _find_generated_thumbnail(output_dir)
        except (FileNotFoundError, RuntimeError) as exc:
            failures.append(f"{label}: {exc}")
    raise RuntimeError(_thumbnail_failure_message(target, failures))


def _quick_look_attempts(target: Path, output_root: Path) -> list[tuple[str, list[str], Path]]:
    attempts = [
        ("quick-look-160", _quick_look_command(target, output_root / "quick-look-160", "160"), output_root / "quick-look-160"),
    ]
    if _is_video_thumbnail(target):
        attempts.extend(
            [
                (
                    "quick-look-320",
                    _quick_look_command(target, output_root / "quick-look-320", "320"),
                    output_root / "quick-look-320",
                ),
                (
                    "quick-look-public-movie",
                    _quick_look_command(target, output_root / "quick-look-public-movie", "160", "public.movie"),
                    output_root / "quick-look-public-movie",
                ),
            ]
        )
    return attempts


def _quick_look_command(target: Path, output_dir: Path, size: str, content_type: Optional[str] = None) -> list[str]:
    command = ["qlmanage", "-t", "-s", size]
    if content_type is not None:
        command.extend(["-c", content_type])
    command.extend(["-o", str(output_dir), str(target)])
    return command


def _run_quick_look(target: Path, output_dir: Path) -> None:
    _run_quick_look_command(_quick_look_command(target, output_dir, "160"), output_dir, target)


def _run_quick_look_command(command: list[str], output_dir: Path, target: Path) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            _quick_look_failure_message(
                command,
                output_dir,
                target,
                f"exit code {exc.returncode}",
                exc.stdout,
                exc.stderr,
            )
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            _quick_look_failure_message(
                command,
                output_dir,
                target,
                f"timed out after {exc.timeout}s",
                exc.stdout,
                exc.stderr,
            )
        ) from exc


def _find_generated_thumbnail(output_dir: Path) -> Path:
    thumbnails = sorted(
        (
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".png" and _is_png_file(path)
        ),
        key=lambda path: path.name,
    )
    if not thumbnails:
        raise FileNotFoundError(
            f"no png thumbnail was generated in {output_dir}; outputs={_describe_output_dir(output_dir)}"
        )
    return thumbnails[0]


def _quick_look_failure_message(
    command: list[str],
    output_dir: Path,
    target: Path,
    reason: str,
    stdout: Optional[Union[str, bytes]],
    stderr: Optional[Union[str, bytes]],
) -> str:
    return (
        "Quick Look thumbnail generation failed: "
        f"{reason}; target={target.name}; suffix={target.suffix.lower()}; "
        f"command={_format_command(command)}; output_dir={output_dir}; "
        f"outputs={_describe_output_dir(output_dir)}; stdout={_format_process_output(stdout)}; "
        f"stderr={_format_process_output(stderr)}"
    )


def _thumbnail_failure_message(target: Path, failures: list[str]) -> str:
    return (
        "thumbnail generation failed: "
        f"target={target.name}; suffix={target.suffix.lower()}; attempts={_format_attempts(failures)}"
    )


def _format_attempts(failures: list[str]) -> str:
    if not failures:
        return "<none>"
    return " | ".join(failures)[-4000:]


def _is_video_thumbnail(target: Path) -> bool:
    return target.suffix.lower().lstrip(".") in VIDEO_THUMBNAIL_EXTENSIONS


def _is_design_thumbnail(target: Path) -> bool:
    return target.suffix.lower().lstrip(".") in DESIGN_THUMBNAIL_EXTENSIONS


def _is_png_file(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


def _write_video_placeholder_thumbnail(target: Path, output_path: Path, failures: list[str]) -> None:
    del failures
    _write_placeholder_thumbnail(target, output_path, "SHIP video thumbnail fallback", 160, 90)


def _write_design_placeholder_thumbnail(target: Path, output_path: Path, failures: list[str]) -> None:
    del failures
    _write_placeholder_thumbnail(target, output_path, "SHIP design thumbnail fallback", 160, 120)


def _write_placeholder_thumbnail(target: Path, output_path: Path, title: str, width: int, height: int) -> None:
    digest = hashlib.sha256(f"{target.name}:{target.suffix.lower()}".encode("utf-8")).digest()
    primary = (40 + digest[0] // 2, 60 + digest[1] // 3, 90 + digest[2] // 3)
    accent = (180 + digest[3] // 4, 120 + digest[4] // 5, 40 + digest[5] // 4)
    raw_rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            border = x < 4 or y < 4 or x >= width - 4 or y >= height - 4
            diagonal = abs((x * height // width) - y) < 3 or abs(((width - x) * height // width) - y) < 3
            stripe = ((x // 12) + (y // 12)) % 2 == 0
            if border or diagonal:
                color = accent
            elif stripe:
                color = primary
            else:
                color = (24, 28, 36)
            row.extend(color)
        raw_rows.append(bytes(row))

    label = f"{title}: {target.name}; suffix={target.suffix.lower()}"
    png = b"".join(
        [
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _png_chunk(b"tEXt", f"Title\0{label}".encode("latin-1", errors="replace")),
            _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows), level=9)),
            _png_chunk(b"IEND", b""),
        ]
    )
    output_path.write_bytes(png)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_process_output(output: Optional[Union[str, bytes]]) -> str:
    if output is None:
        return "<none>"
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    output = output.strip()
    if not output:
        return "<empty>"
    return output[-2000:]


def _describe_output_dir(output_dir: Path) -> str:
    if not output_dir.exists():
        return "<missing>"
    entries = []
    for path in sorted(output_dir.iterdir(), key=lambda entry: entry.name):
        if path.is_file():
            entries.append(f"file:{path.name}:{path.stat().st_size}B")
        elif path.is_dir():
            entries.append(f"dir:{path.name}")
        else:
            entries.append(f"other:{path.name}")
    return ",".join(entries) if entries else "<empty>"
