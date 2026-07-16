from __future__ import annotations

import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

from .bobs_catalog import BOBS_JOB_PREFIX_PATTERN, JOB_TOKEN_PATTERN, is_bobs_job_name


BOBS_RETAKE_TITLE_PATTERN_TEXT = r"(?:Tech\s*)?Creative\s*Retakes|Creatives|Technical\s*Retakes"
BOBS_RETAKE_TITLE_PATTERN = re.compile(rf"(?<![A-Za-z])(?:{BOBS_RETAKE_TITLE_PATTERN_TEXT})(?![A-Za-z])", re.IGNORECASE)
XLS_TEXT_ENCODINGS = ("utf-16le", "utf-16be", "cp949", "latin-1")
XLS_RETAKE_MARKER_PATTERN = r"BOB'?S\s+BURGERS|Creatives|Creative\s+Retakes|Technical\s+Retakes|FASA\d+"
DUE_DATE_PATTERN = re.compile(r"\bDue\s+Date\s+(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", re.IGNORECASE)
RETAKE_ROW_PATTERN = re.compile(
    r"\bSeq\s*([0-9]{1,3}(?:[A-Za-z][0-9A-Za-z-]*)?)\s+Sc\s*([0-9]{1,3}(?:[A-Za-z][0-9A-Za-z-]*)?)\s+Tk\s*([0-9]{1,3})\b",
    re.IGNORECASE,
)
EXCEL_YEAR_FIRST_DATE_PATTERN = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b")
EXCEL_DAY_FIRST_DATE_PATTERN = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")
EXCEL_FILENAME_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
EXCEL_CELL_REF_PATTERN = re.compile(r"^([A-Z]+)(\d+)$", re.IGNORECASE)
CFB_FREE_SECTOR = 0xFFFFFFFF
CFB_END_OF_CHAIN = 0xFFFFFFFE
PDF_LITERAL_PATTERN = re.compile(rb"\((?:\\.|[^\\()])*\)", re.DOTALL)
PDF_HEX_STRING_PATTERN = re.compile(rb"(?<!<)<([0-9A-Fa-f\s]{4,})>(?!>)")
PDF_STREAM_PATTERN = re.compile(rb"<<(.*?)>>\s*stream\r?\n?(.*?)\r?\n?endstream", re.DOTALL)
PDF_OBJECT_PATTERN = re.compile(rb"(\d+)\s+\d+\s+obj\s*(.*?)\s*endobj", re.DOTALL)
PDF_TO_UNICODE_PATTERN = re.compile(rb"/ToUnicode\s+(\d+)\s+0\s+R")
PDF_FONT_RESOURCE_PATTERN = re.compile(rb"/(F\d+)\s+(\d+)\s+0\s+R")
PDF_TEXT_TOKEN_PATTERN = re.compile(
    rb"/(F\d+)\s+[+-]?(?:\d+(?:\.\d+)?|\.\d+)\s+Tf|<([0-9A-Fa-f\s]+)>\s*Tj|\[(.*?)\]\s*TJ|\bET\b",
    re.DOTALL,
)
PDF_CMAP_BFCHAR_BLOCK_PATTERN = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
PDF_CMAP_BFRANGE_BLOCK_PATTERN = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
PDF_CMAP_HEX_PAIR_PATTERN = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
PDF_CMAP_RANGE_HEX_PATTERN = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
PDF_CMAP_RANGE_ARRAY_PATTERN = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", re.DOTALL)


@dataclass(frozen=True)
class BobsRetakeDate:
    year: int
    month: int
    day: int

    def to_dict(self) -> dict[str, int]:
        return {"year": self.year, "month": self.month, "day": self.day}


@dataclass(frozen=True)
class BobsRetakeRow:
    sequence: str
    scene_number: str
    scene_label: str
    tk: str

    def to_dict(self) -> dict[str, str]:
        return {"sequence": self.sequence, "scene_number": self.scene_number, "scene_label": self.scene_label, "tk": self.tk}


@dataclass(frozen=True)
class ExcelCell:
    row: int
    column: int
    value: str


def parse_bobs_retake_pdf(
    path: str,
    *,
    excel_paths: str | Iterable[str] | None = None,
    due_date_path: str | Iterable[str] | None = None,
) -> dict[str, Any]:
    pdf_path = Path(path)
    if pdf_path.suffix.lower() != ".pdf":
        return _non_match("not a PDF path")
    try:
        data = pdf_path.read_bytes()
    except OSError as exc:
        return _non_match(f"PDF 파일을 읽지 못했습니다: {exc}")
    text = "\n".join([pdf_path.name, extract_pdf_text(data)])
    normalized_text = normalize_text(text)
    fallback_due_date = None
    fallback_rows = None
    excel_path_values = iter_excel_paths(excel_paths, due_date_path)
    if find_due_date(normalized_text) is None:
        fallback_due_date = find_excel_due_date(excel_path_values)
    fallback_rows = find_excel_retake_rows(excel_path_values)
    return parse_bobs_retake_text(text, fallback_due_date=fallback_due_date, fallback_rows=fallback_rows)


def parse_bobs_retake_pdf_bytes(data: bytes) -> dict[str, Any]:
    return parse_bobs_retake_text(extract_pdf_text(data))


def parse_bobs_retake_text(
    text: str,
    *,
    fallback_due_date: BobsRetakeDate | None = None,
    fallback_rows: list[BobsRetakeRow] | None = None,
) -> dict[str, Any]:
    normalized_text = normalize_text(text)
    if not BOBS_RETAKE_TITLE_PATTERN.search(normalized_text):
        return _non_match("Bobs retake 문서를 찾지 못했습니다.")

    job = find_bobs_job(normalized_text)
    if job is None:
        return _non_match("Bobs job 코드를 찾지 못했습니다.", recognized=True)

    due_date = find_due_date(normalized_text) or fallback_due_date
    if due_date is None:
        return _non_match("Due Date를 찾지 못했습니다.", recognized=True)

    rows = find_retake_rows(normalized_text)
    if not rows and fallback_rows:
        rows = fallback_rows
    if not rows:
        return _non_match("Seq/Sc/Tk 행을 찾지 못했습니다.", recognized=True)

    return {
        "matched": True,
        "recognized": True,
        "job": job,
        "due_date": due_date.to_dict(),
        "rows": [row.to_dict() for row in rows],
        "error": "",
    }


def extract_pdf_text(data: bytes) -> str:
    chunks = [decode_bytes(data), extract_pdf_strings(data), extract_tounicode_text(data)]
    for stream in iter_pdf_streams(data):
        chunks.append(decode_bytes(stream))
        chunks.append(extract_pdf_strings(stream))
    return "\n".join(chunk for chunk in chunks if chunk)


def iter_pdf_streams(data: bytes) -> Iterable[bytes]:
    for match in PDF_STREAM_PATTERN.finditer(data):
        stream_dict = match.group(1)
        stream_data = match.group(2).strip(b"\r\n")
        if b"FlateDecode" in stream_dict:
            decompressed = try_decompress(stream_data)
            if decompressed is not None:
                yield decompressed
            continue
        yield stream_data
        decompressed = try_decompress(stream_data)
        if decompressed is not None:
            yield decompressed


def try_decompress(data: bytes) -> bytes | None:
    try:
        return zlib.decompress(data)
    except zlib.error:
        return None


def extract_tounicode_text(data: bytes) -> str:
    objects = parse_pdf_objects(data)
    if not objects:
        return ""

    font_resources = parse_font_resources(data)
    font_cmaps = parse_font_cmaps(objects)
    if not font_resources or not font_cmaps:
        return ""

    chunks: list[str] = []
    for object_data in objects.values():
        stream = extract_object_stream(object_data)
        if not stream or (b"Tj" not in stream and b"TJ" not in stream):
            continue
        decoded = extract_tounicode_text_stream(stream, font_resources, font_cmaps)
        if decoded:
            chunks.append(decoded)
    return "\n".join(chunks)


def parse_pdf_objects(data: bytes) -> dict[int, bytes]:
    return {int(match.group(1)): match.group(2) for match in PDF_OBJECT_PATTERN.finditer(data)}


def extract_object_stream(object_data: bytes) -> bytes:
    match = PDF_STREAM_PATTERN.search(object_data)
    if not match:
        return b""
    stream_data = match.group(2).strip(b"\r\n")
    if b"FlateDecode" in match.group(1):
        decompressed = try_decompress(stream_data)
        return decompressed if decompressed is not None else b""
    decompressed = try_decompress(stream_data)
    return decompressed if decompressed is not None else stream_data


def parse_font_resources(data: bytes) -> dict[str, int]:
    return {match.group(1).decode("ascii"): int(match.group(2)) for match in PDF_FONT_RESOURCE_PATTERN.finditer(data)}


def parse_font_cmaps(objects: dict[int, bytes]) -> dict[int, dict[bytes, str]]:
    font_cmaps: dict[int, dict[bytes, str]] = {}
    for object_number, object_data in objects.items():
        match = PDF_TO_UNICODE_PATTERN.search(object_data)
        if not match:
            continue
        cmap_stream = extract_object_stream(objects.get(int(match.group(1)), b""))
        cmap = parse_tounicode_cmap(cmap_stream)
        if cmap:
            font_cmaps[object_number] = cmap
    return font_cmaps


def parse_tounicode_cmap(cmap_stream: bytes) -> dict[bytes, str]:
    cmap: dict[bytes, str] = {}
    for block in PDF_CMAP_BFCHAR_BLOCK_PATTERN.finditer(cmap_stream):
        for source_hex, target_hex in PDF_CMAP_HEX_PAIR_PATTERN.findall(block.group(1)):
            source = parse_hex_bytes(source_hex)
            target = decode_cmap_unicode_hex(target_hex)
            if source and target:
                cmap[source] = target

    for block in PDF_CMAP_BFRANGE_BLOCK_PATTERN.finditer(cmap_stream):
        block_data = block.group(1)
        for start_hex, end_hex, target_hex in PDF_CMAP_RANGE_HEX_PATTERN.findall(block_data):
            add_cmap_range(cmap, start_hex, end_hex, target_hex)
        for start_hex, end_hex, target_array in PDF_CMAP_RANGE_ARRAY_PATTERN.findall(block_data):
            add_cmap_range_array(cmap, start_hex, end_hex, target_array)
    return cmap


def add_cmap_range(cmap: dict[bytes, str], start_hex: bytes, end_hex: bytes, target_hex: bytes) -> None:
    source_width = len(parse_hex_bytes(start_hex))
    start = int(start_hex, 16)
    end = int(end_hex, 16)
    target = int(target_hex, 16)
    for offset, source_code in enumerate(range(start, end + 1)):
        cmap[source_code.to_bytes(source_width, "big")] = chr(target + offset)


def add_cmap_range_array(cmap: dict[bytes, str], start_hex: bytes, end_hex: bytes, target_array: bytes) -> None:
    source_width = len(parse_hex_bytes(start_hex))
    start = int(start_hex, 16)
    end = int(end_hex, 16)
    targets = re.findall(rb"<([0-9A-Fa-f]+)>", target_array)
    for source_code, target_hex in zip(range(start, end + 1), targets):
        target = decode_cmap_unicode_hex(target_hex)
        if target:
            cmap[source_code.to_bytes(source_width, "big")] = target


def parse_hex_bytes(value: bytes) -> bytes:
    compact = re.sub(rb"\s+", b"", value)
    if len(compact) % 2 == 1:
        compact += b"0"
    try:
        return bytes.fromhex(compact.decode("ascii"))
    except ValueError:
        return b""


def decode_cmap_unicode_hex(value: bytes) -> str:
    data = parse_hex_bytes(value)
    if not data:
        return ""
    if len(data) % 2 == 1:
        data = b"\x00" + data
    return "".join(chr(int.from_bytes(data[index : index + 2], "big")) for index in range(0, len(data), 2))


def extract_tounicode_text_stream(
    stream: bytes,
    font_resources: dict[str, int],
    font_cmaps: dict[int, dict[bytes, str]],
) -> str:
    current_font = ""
    chunks: list[str] = []
    for match in PDF_TEXT_TOKEN_PATTERN.finditer(stream):
        if match.group(1):
            current_font = match.group(1).decode("ascii")
            continue
        if match.group(2) and current_font:
            chunks.append(decode_tounicode_hex_string(match.group(2), current_font, font_resources, font_cmaps))
            continue
        if match.group(3) and current_font:
            for hex_string in re.findall(rb"<([0-9A-Fa-f\s]+)>", match.group(3)):
                chunks.append(decode_tounicode_hex_string(hex_string, current_font, font_resources, font_cmaps))
            continue
        if match.group(0) == b"ET":
            chunks.append("\n")
    return "".join(chunks)


def decode_tounicode_hex_string(
    value: bytes,
    font_name: str,
    font_resources: dict[str, int],
    font_cmaps: dict[int, dict[bytes, str]],
) -> str:
    raw = parse_hex_bytes(value)
    cmap = font_cmaps.get(font_resources.get(font_name, -1), {})
    if not raw or not cmap:
        return decode_pdf_hex_string(value)

    token_lengths = sorted({len(token) for token in cmap}, reverse=True)
    output: list[str] = []
    index = 0
    while index < len(raw):
        for token_length in token_lengths:
            token = raw[index : index + token_length]
            if token in cmap:
                output.append(cmap[token])
                index += token_length
                break
        else:
            output.append(chr(raw[index]))
            index += 1
    return "".join(output)


def extract_pdf_strings(data: bytes) -> str:
    literal_strings = [decode_pdf_literal(match.group(0)) for match in PDF_LITERAL_PATTERN.finditer(data)]
    hex_strings = [decode_pdf_hex_string(match.group(1)) for match in PDF_HEX_STRING_PATTERN.finditer(data)]
    return " ".join(value for value in [*literal_strings, *hex_strings] if value)


def decode_pdf_literal(value: bytes) -> str:
    content = value[1:-1]
    output = bytearray()
    index = 0
    while index < len(content):
        current = content[index]
        if current != 0x5C:
            output.append(current)
            index += 1
            continue

        index += 1
        if index >= len(content):
            break
        escaped = content[index]
        if escaped in b"nrtbf":
            output.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}[escaped])
            index += 1
            continue
        if escaped in b"()\\":
            output.append(escaped)
            index += 1
            continue
        if 48 <= escaped <= 55:
            octal = bytes([escaped])
            index += 1
            while index < len(content) and len(octal) < 3 and 48 <= content[index] <= 55:
                octal += bytes([content[index]])
                index += 1
            output.append(int(octal, 8) & 0xFF)
            continue
        if escaped in b"\r\n":
            index += 1
            if escaped == 13 and index < len(content) and content[index] == 10:
                index += 1
            continue
        output.append(escaped)
        index += 1
    return decode_bytes(bytes(output))


def decode_pdf_hex_string(value: bytes) -> str:
    decoded = parse_hex_bytes(value)
    if not decoded:
        return ""
    return decode_bytes(decoded)


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16-be", "latin-1"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return decoded.replace("\x00", " ")
    return data.decode("latin-1", errors="ignore").replace("\x00", " ")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def find_bobs_job(text: str) -> str | None:
    title_match = re.search(rf"\b({BOBS_JOB_PREFIX_PATTERN}[A-Za-z0-9]*)[\s_-]+(?:{BOBS_RETAKE_TITLE_PATTERN_TEXT})(?![A-Za-z])", text, re.IGNORECASE)
    if title_match and is_bobs_job_name(title_match.group(1)):
        return title_match.group(1).upper()
    for match in JOB_TOKEN_PATTERN.finditer(text):
        job = match.group(1)
        if is_bobs_job_name(job):
            return job.upper()
    return None


def find_due_date(text: str) -> BobsRetakeDate | None:
    match = DUE_DATE_PATTERN.search(text)
    if not match:
        return None
    first = int(match.group(1))
    second = int(match.group(2))
    raw_year = int(match.group(3))
    return parse_month_day_retake_date(first, second, raw_year)


def iter_excel_paths(
    excel_paths: str | Iterable[str] | None,
    due_date_path: str | Iterable[str] | None,
) -> list[str]:
    paths: list[str] = []
    for value in (excel_paths, due_date_path):
        if value is None:
            continue
        if isinstance(value, str):
            paths.append(value)
            continue
        paths.extend(str(path) for path in value)
    return paths


def find_excel_due_date(paths: Iterable[str]) -> BobsRetakeDate | None:
    for raw_path in paths:
        excel_path = Path(raw_path)
        suffix = excel_path.suffix.lower()
        if suffix == ".xlsx":
            due_date = parse_xlsx_ship_date(excel_path)
        elif suffix == ".xls":
            due_date = parse_xls_ship_date(excel_path)
        else:
            continue
        if due_date is not None:
            return due_date
    return None


def parse_xlsx_ship_date(path: Path) -> BobsRetakeDate | None:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = read_xlsx_shared_strings(archive)
            for sheet_name in sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml")):
                due_date = find_sheet_ship_date(read_xlsx_sheet_cells(archive, sheet_name, shared_strings))
                if due_date is not None:
                    return due_date
    except (OSError, zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError, TypeError, OverflowError):
        return None
    return None


def parse_xls_ship_date(path: Path) -> BobsRetakeDate | None:
    decoded_texts = read_xls_decoded_texts(path)
    for text in decoded_texts:
        due_date = find_xls_ship_date_near_title_marker(text)
        if due_date is not None:
            return due_date
    biff_due_date, biff_has_ship_label = parse_xls_biff_ship_date(path)
    if biff_due_date is not None:
        return biff_due_date
    for text in decoded_texts:
        due_date = find_xls_ship_date_near_label(text)
        if due_date is not None:
            return due_date
    for text in decoded_texts:
        due_date = find_xls_ship_date_near_retake_marker(text)
        if due_date is not None:
            return due_date
    if biff_has_ship_label or any("선적일" in text for text in decoded_texts):
        return None
    due_date = find_excel_date_in_filename(path.name)
    if due_date is not None:
        return due_date
    for text in decoded_texts:
        due_date = find_excel_date_in_text(text)
        if due_date is not None:
            return due_date
    return None


def parse_xls_biff_ship_date(path: Path) -> tuple[BobsRetakeDate | None, bool]:
    try:
        data = path.read_bytes()
    except OSError:
        return (None, False)
    workbook = read_cfb_stream(data, "Workbook") or read_cfb_stream(data, "Book")
    if workbook is None:
        return (None, False)
    return find_biff_workbook_ship_date(workbook)


def read_cfb_stream(data: bytes, stream_name: str) -> bytes | None:
    if len(data) < 512 or data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return None
    sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
    first_directory_sector = struct.unpack_from("<I", data, 48)[0]
    difat_sectors = struct.unpack_from("<109I", data, 76)
    fat: list[int] = []
    for sector_index in difat_sectors:
        if sector_index in (CFB_FREE_SECTOR, CFB_END_OF_CHAIN):
            continue
        sector_data = read_cfb_sector(data, sector_index, sector_size)
        if len(sector_data) == sector_size:
            fat.extend(struct.unpack("<" + "I" * (sector_size // 4), sector_data))

    def read_chain(start_sector: int, byte_count: int) -> bytes:
        chunks: list[bytes] = []
        current = start_sector
        seen_sectors: set[int] = set()
        while current not in (CFB_FREE_SECTOR, CFB_END_OF_CHAIN) and current < len(fat) and current not in seen_sectors:
            seen_sectors.add(current)
            chunks.append(read_cfb_sector(data, current, sector_size))
            current = fat[current]
        return b"".join(chunks)[:byte_count]

    directory = read_chain(first_directory_sector, len(data))
    for offset in range(0, len(directory), 128):
        entry = directory[offset : offset + 128]
        if len(entry) < 128:
            break
        name_length = struct.unpack_from("<H", entry, 64)[0]
        if name_length < 2:
            continue
        name = entry[: name_length - 2].decode("utf-16le", errors="ignore")
        entry_type = entry[66]
        start_sector = struct.unpack_from("<I", entry, 116)[0]
        stream_size = struct.unpack_from("<Q", entry, 120)[0]
        if entry_type == 2 and name == stream_name:
            return read_chain(start_sector, stream_size)
    return None


def read_cfb_sector(data: bytes, sector_index: int, sector_size: int) -> bytes:
    start = (sector_index + 1) * sector_size
    return data[start : start + sector_size]


def find_biff_workbook_ship_date(workbook: bytes) -> tuple[BobsRetakeDate | None, bool]:
    records = list(iter_biff_records(workbook))
    shared_strings = read_biff_shared_strings(records)
    sheet_ranges = read_biff_sheet_ranges(records, len(workbook))
    cells = read_biff_cells(records, shared_strings)
    has_ship_label = any(normalize_excel_label(cell.value).rstrip(":") == "선적일" for cell in cells if isinstance(cell.value, str))
    candidates: list[BobsRetakeDate] = []
    for sheet_start, sheet_end in sheet_ranges:
        sheet_cells = [cell for cell in cells if sheet_start <= cell.row_offset < sheet_end]
        candidates.extend(find_biff_sheet_ship_dates(sheet_cells))
    if not sheet_ranges:
        candidates.extend(find_biff_sheet_ship_dates(cells))
    if not candidates:
        return (None, has_ship_label)
    return (sorted(candidates, key=lambda value: (value.year, value.month, value.day))[-1], has_ship_label)


@dataclass(frozen=True)
class BiffRecord:
    offset: int
    record_type: int
    data: bytes


@dataclass(frozen=True)
class BiffCell:
    row_offset: int
    row: int
    column: int
    value: str | float


def iter_biff_records(workbook: bytes) -> Iterable[BiffRecord]:
    offset = 0
    while offset + 4 <= len(workbook):
        record_type, length = struct.unpack_from("<HH", workbook, offset)
        data = workbook[offset + 4 : offset + 4 + length]
        yield BiffRecord(offset=offset, record_type=record_type, data=data)
        offset += 4 + length


def read_biff_shared_strings(records: list[BiffRecord]) -> list[str]:
    strings: list[str] = []
    for record in records:
        if record.record_type != 0x00FC or len(record.data) < 8:
            continue
        offset = 8
        unique_count = struct.unpack_from("<I", record.data, 4)[0]
        for _ in range(unique_count):
            try:
                value, offset = read_biff_unicode_string(record.data, offset)
            except (struct.error, ValueError):
                break
            strings.append(value)
            if offset >= len(record.data):
                break
    return strings


def read_biff_unicode_string(data: bytes, offset: int) -> tuple[str, int]:
    character_count = struct.unpack_from("<H", data, offset)[0]
    flags = data[offset + 2]
    offset += 3
    if flags & 0x08:
        offset += 2
    if flags & 0x04:
        offset += 4
    if flags & 0x01:
        byte_count = character_count * 2
        value = data[offset : offset + byte_count].decode("utf-16le", errors="ignore")
        return (value, offset + byte_count)
    value = data[offset : offset + character_count].decode("latin-1", errors="ignore")
    return (value, offset + character_count)


def read_biff_sheet_ranges(records: list[BiffRecord], workbook_size: int) -> list[tuple[int, int]]:
    starts: list[int] = []
    for record in records:
        if record.record_type == 0x0085 and len(record.data) >= 4:
            starts.append(struct.unpack_from("<I", record.data, 0)[0])
    starts = sorted(start for start in starts if 0 <= start < workbook_size)
    return [(start, starts[index + 1] if index + 1 < len(starts) else workbook_size) for index, start in enumerate(starts)]


def read_biff_cells(records: list[BiffRecord], shared_strings: list[str]) -> list[BiffCell]:
    cells: list[BiffCell] = []
    pending_formula_string: tuple[int, int, int] | None = None
    for record in records:
        data = record.data
        if record.record_type != 0x0207:
            pending_formula_string = None
        if record.record_type == 0x00FD and len(data) >= 10:
            row, column, _, string_index = struct.unpack_from("<HHHI", data, 0)
            value = shared_strings[string_index] if 0 <= string_index < len(shared_strings) else ""
            cells.append(BiffCell(record.offset, row, column, value))
        elif record.record_type == 0x0204 and len(data) >= 8:
            row, column, _ = struct.unpack_from("<HHH", data, 0)
            try:
                value, _ = read_biff_unicode_string(data, 6)
            except (struct.error, ValueError):
                value = ""
            cells.append(BiffCell(record.offset, row, column, value))
        elif record.record_type == 0x0203 and len(data) >= 14:
            row, column, _ = struct.unpack_from("<HHH", data, 0)
            cells.append(BiffCell(record.offset, row, column, struct.unpack_from("<d", data, 6)[0]))
        elif record.record_type == 0x027E and len(data) >= 10:
            row, column, _ = struct.unpack_from("<HHH", data, 0)
            cells.append(BiffCell(record.offset, row, column, decode_biff_rk_number(struct.unpack_from("<I", data, 6)[0])))
        elif record.record_type == 0x00BD and len(data) >= 6:
            row, first_column, last_column = struct.unpack_from("<HHH", data, 0)
            offset = 6
            for column in range(first_column, last_column + 1):
                if offset + 6 > len(data):
                    break
                value = decode_biff_rk_number(struct.unpack_from("<I", data, offset + 2)[0])
                cells.append(BiffCell(record.offset, row, column, value))
                offset += 6
        elif record.record_type == 0x0006 and len(data) >= 14:
            row, column, _ = struct.unpack_from("<HHH", data, 0)
            result = data[6:14]
            if result == b"\x00\x00\x00\x00\x00\x00\xff\xff":
                pending_formula_string = (record.offset, row, column)
                continue
            cells.append(BiffCell(record.offset, row, column, struct.unpack_from("<d", data, 6)[0]))
        elif record.record_type == 0x0207 and pending_formula_string is not None:
            row_offset, row, column = pending_formula_string
            try:
                value, _ = read_biff_unicode_string(data, 0)
            except (struct.error, ValueError):
                value = ""
            cells.append(BiffCell(row_offset, row, column, value))
            pending_formula_string = None
    return cells


def decode_biff_rk_number(raw_value: int) -> float:
    if raw_value & 0x02:
        value = raw_value >> 2
        if value & 0x20000000:
            value -= 0x40000000
        number = float(value)
    else:
        number = struct.unpack("<d", struct.pack("<II", 0, raw_value & 0xFFFFFFFC))[0]
    return number / 100 if raw_value & 0x01 else number


def find_biff_sheet_ship_dates(cells: list[BiffCell]) -> list[BobsRetakeDate]:
    label_cells = [cell for cell in cells if isinstance(cell.value, str) and normalize_excel_label(cell.value).rstrip(":") == "선적일"]
    due_dates: list[BobsRetakeDate] = []
    for label_cell in label_cells:
        for candidate in cells:
            if not isinstance(candidate.value, float) or candidate.value != candidate.value:
                continue
            if abs(candidate.row - label_cell.row) > 8 or abs(candidate.column - label_cell.column) > 12:
                continue
            due_date = parse_excel_serial_date(candidate.value)
            if due_date is not None:
                due_dates.append(due_date)
    return due_dates


def parse_excel_serial_date(value: float) -> BobsRetakeDate | None:
    serial = int(value)
    if abs(value - serial) > 0.000001 or not 1 <= serial <= 60000:
        return None
    parsed_date = date(1899, 12, 30) + timedelta(days=serial)
    return valid_retake_date(parsed_date.year, parsed_date.month, parsed_date.day)


def read_xls_decoded_texts(path: Path) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return []

    decoded_texts: list[str] = []
    seen_texts: set[str] = set()
    for encoding in XLS_TEXT_ENCODINGS:
        text = normalize_xls_scan_text(data.decode(encoding, errors="ignore"))
        if text and text not in seen_texts:
            decoded_texts.append(text)
            seen_texts.add(text)
    return decoded_texts


def normalize_xls_scan_text(value: str) -> str:
    clean_characters = [character if character in "\t\n\r" or ord(character) >= 32 else " " for character in value.replace("\x00", " ")]
    return re.sub(r"\s+", " ", "".join(clean_characters)).strip()


def find_xls_ship_date_near_label(text: str) -> BobsRetakeDate | None:
    label_index = text.find("선적일")
    while label_index != -1:
        window = text[max(0, label_index - 160) : label_index + 260]
        due_date = find_excel_date_in_text(window)
        if due_date is not None:
            return due_date
        label_index = text.find("선적일", label_index + len("선적일"))
    return None


def find_xls_ship_date_near_retake_marker(text: str) -> BobsRetakeDate | None:
    marker_indexes = [match.start() for match in re.finditer(XLS_RETAKE_MARKER_PATTERN, text, re.IGNORECASE)]
    for marker_index in marker_indexes:
        window = text[max(0, marker_index - 240) : marker_index + 360]
        due_date = find_excel_date_in_text(window)
        if due_date is not None:
            return due_date
    return None


def find_xls_ship_date_near_title_marker(text: str) -> BobsRetakeDate | None:
    title_pattern = re.compile(
        rf"(?:({BOBS_JOB_PREFIX_PATTERN}[A-Za-z0-9]*)\s+(?:{BOBS_RETAKE_TITLE_PATTERN_TEXT})|(?:{BOBS_RETAKE_TITLE_PATTERN_TEXT})\s+({BOBS_JOB_PREFIX_PATTERN}[A-Za-z0-9]*))\s+",
        re.IGNORECASE,
    )
    for match in title_pattern.finditer(text):
        job = match.group(1) or match.group(2)
        if not is_bobs_job_name(job):
            continue
        window = text[match.end() : match.end() + 64]
        due_date = find_excel_date_in_text(window)
        if due_date is not None:
            return due_date
    return None


def find_excel_date_in_text(text: str) -> BobsRetakeDate | None:
    candidates: list[tuple[int, BobsRetakeDate]] = []
    for match in EXCEL_YEAR_FIRST_DATE_PATTERN.finditer(text):
        if is_unsafe_excel_date_context(text, match.start(), match.end()):
            continue
        due_date = valid_retake_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if due_date is not None:
            candidates.append((match.start(), due_date))
    for match in EXCEL_DAY_FIRST_DATE_PATTERN.finditer(text):
        if is_unsafe_excel_date_context(text, match.start(), match.end()):
            continue
        due_date = parse_month_day_retake_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if due_date is not None:
            candidates.append((match.start(), due_date))
    if not candidates:
        return None
    return sorted(candidates, key=lambda candidate: candidate[0])[0][1]


def find_excel_date_in_filename(filename: str) -> BobsRetakeDate | None:
    for match in EXCEL_FILENAME_DATE_PATTERN.finditer(filename):
        due_date = valid_retake_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if due_date is not None:
            return due_date
    return None


def is_unsafe_excel_date_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 24) : start].lower()
    after = text[end : end + 40].lower()
    if re.search(r"(?:https?://|www\.|xmlns[:=]|rdf[:/-]|xmp[:/-]|adobe:ns|purl\.org)", before + after):
        return True
    next_character = text[end : end + 1]
    if next_character and next_character in "#-_/:" and re.match(r"[A-Za-z]", text[end + 1 : end + 2]):
        return True
    previous_character = text[start - 1 : start]
    if previous_character and previous_character in ":/_-" and re.match(r"[A-Za-z]", text[start - 2 : start - 1]):
        return True
    return False


def read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(text_node.text or "" for text_node in item.iter() if local_name(text_node.tag) == "t") for item in root.iter() if local_name(item.tag) == "si"]


def read_xlsx_sheet_cells(archive: zipfile.ZipFile, sheet_name: str, shared_strings: list[str]) -> list[ExcelCell]:
    root = ElementTree.fromstring(archive.read(sheet_name))
    cells: list[ExcelCell] = []
    for cell in root.iter():
        if local_name(cell.tag) != "c":
            continue
        row, column = parse_excel_cell_ref(cell.attrib.get("r", ""))
        if row == 0 or column == 0:
            continue
        value = read_xlsx_cell_value(cell, shared_strings)
        if value.strip() != "":
            cells.append(ExcelCell(row=row, column=column, value=value.strip()))
    return cells


def read_xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(text_node.text or "" for text_node in cell.iter() if local_name(text_node.tag) == "t")
    value_node = next((child for child in cell if local_name(child.tag) == "v"), None)
    raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
    if cell_type == "s":
        index = int(raw_value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    return raw_value


def find_sheet_ship_date(cells: list[ExcelCell]) -> BobsRetakeDate | None:
    label_cells = [cell for cell in cells if normalize_excel_label(cell.value) == "선적일"]
    for label_cell in label_cells:
        for candidate in sorted(cells, key=lambda cell: excel_date_candidate_key(label_cell, cell)):
            if candidate == label_cell or not is_near_excel_label(label_cell, candidate):
                continue
            due_date = parse_excel_date_value(candidate.value)
            if due_date is not None:
                return due_date
    return None


def normalize_excel_label(value: str) -> str:
    return re.sub(r"\s+", "", value)


def excel_date_candidate_key(label_cell: ExcelCell, candidate: ExcelCell) -> tuple[int, int, int, int]:
    same_row_right = 0 if candidate.row == label_cell.row and candidate.column > label_cell.column else 1
    row_distance = abs(candidate.row - label_cell.row)
    column_distance = abs(candidate.column - label_cell.column)
    return (same_row_right, row_distance + column_distance, row_distance, column_distance)


def is_near_excel_label(label_cell: ExcelCell, candidate: ExcelCell) -> bool:
    return abs(candidate.row - label_cell.row) <= 3 and abs(candidate.column - label_cell.column) <= 3


def parse_excel_date_value(value: str) -> BobsRetakeDate | None:
    text = value.strip()
    year_first_match = EXCEL_YEAR_FIRST_DATE_PATTERN.search(text)
    if year_first_match:
        return valid_retake_date(int(year_first_match.group(1)), int(year_first_match.group(2)), int(year_first_match.group(3)))
    day_first_match = EXCEL_DAY_FIRST_DATE_PATTERN.search(text)
    if day_first_match:
        return parse_month_day_retake_date(
            int(day_first_match.group(1)),
            int(day_first_match.group(2)),
            int(day_first_match.group(3)),
        )
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        serial = int(float(text))
        if 1 <= serial <= 60000:
            parsed_date = date(1899, 12, 30) + timedelta(days=serial)
            return BobsRetakeDate(year=parsed_date.year, month=parsed_date.month, day=parsed_date.day)
    return None


def parse_month_day_retake_date(first: int, second: int, raw_year: int) -> BobsRetakeDate | None:
    year = 2000 + raw_year if raw_year < 100 else raw_year
    for month, day in ((first, second), (second, first)):
        due_date = valid_retake_date(year, month, day)
        if due_date is not None:
            return due_date
    return None


def valid_retake_date(year: int, month: int, day: int) -> BobsRetakeDate | None:
    if year < 2010 or year > 2035:
        return None
    try:
        date(year, month, day)
    except ValueError:
        return None
    return BobsRetakeDate(year=year, month=month, day=day)


def parse_excel_cell_ref(value: str) -> tuple[int, int]:
    match = EXCEL_CELL_REF_PATTERN.match(value)
    if not match:
        return (0, 0)
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - ord("A") + 1
    return (int(match.group(2)), column)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_excel_retake_rows(paths: Iterable[str]) -> list[BobsRetakeRow]:
    for raw_path in paths:
        excel_path = Path(raw_path)
        if excel_path.suffix.lower() != ".xls":
            continue
        rows = parse_xls_retake_rows(excel_path)
        if rows:
            return rows
    return []


def parse_xls_retake_rows(path: Path) -> list[BobsRetakeRow]:
    biff_rows = parse_xls_biff_retake_rows(path)
    if biff_rows:
        return biff_rows
    for text in read_xls_decoded_texts(path):
        rows = find_xls_retake_rows_in_text(text)
        if rows:
            return rows
    return []


def parse_xls_biff_retake_rows(path: Path) -> list[BobsRetakeRow]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    workbook = read_cfb_stream(data, "Workbook") or read_cfb_stream(data, "Book")
    if workbook is None:
        return []
    return find_biff_workbook_retake_rows(workbook)


def find_biff_workbook_retake_rows(workbook: bytes) -> list[BobsRetakeRow]:
    records = list(iter_biff_records(workbook))
    shared_strings = read_biff_shared_strings(records)
    sheet_ranges = read_biff_sheet_ranges(records, len(workbook))
    cells = read_biff_cells(records, shared_strings)
    rows: list[BobsRetakeRow] = []
    for sheet_start, sheet_end in sheet_ranges or [(0, len(workbook))]:
        sheet_cells = [cell for cell in cells if sheet_start <= cell.row_offset < sheet_end]
        rows.extend(find_biff_sheet_retake_rows(sheet_cells))
    return dedupe_retake_rows(rows)


def find_biff_sheet_retake_rows(cells: list[BiffCell]) -> list[BobsRetakeRow]:
    return dedupe_retake_rows([*find_biff_header_table_retake_rows(cells), *find_biff_legacy_card_retake_rows(cells)])


def find_biff_header_table_retake_rows(cells: list[BiffCell]) -> list[BobsRetakeRow]:
    rows: list[BobsRetakeRow] = []
    cells_by_row = group_biff_cells_by_row(cells)
    for header_row in sorted(cells_by_row):
        columns = find_biff_retake_header_columns(cells_by_row[header_row])
        if columns is None:
            continue
        blank_rows = 0
        for row_index in sorted(row for row in cells_by_row if row > header_row):
            row_cells = cells_by_row[row_index]
            if find_biff_retake_header_columns(row_cells) is not None:
                break
            row = build_biff_retake_row(
                biff_cell_text(row_cells.get(columns["sequence"])),
                biff_cell_text(row_cells.get(columns["scene"])),
                biff_cell_text(row_cells.get(columns["take"])),
            )
            if row is None:
                if not any(biff_cell_text(cell) for cell in row_cells.values()):
                    blank_rows += 1
                    if blank_rows >= 5:
                        break
                continue
            blank_rows = 0
            rows.append(row)
    return dedupe_retake_rows(rows)


def find_biff_legacy_card_retake_rows(cells: list[BiffCell]) -> list[BobsRetakeRow]:
    rows: list[BobsRetakeRow] = []
    cells_by_row = group_biff_cells_by_row(cells)
    for header_row, row_cells in cells_by_row.items():
        card_columns = find_biff_legacy_card_columns(row_cells)
        for take_column, sequence_column, scene_column in card_columns:
            for value_row_index in (header_row - 2, header_row - 1, header_row + 1):
                value_cells = cells_by_row.get(value_row_index, {})
                row = build_biff_retake_row(
                    biff_cell_text(value_cells.get(sequence_column)),
                    biff_cell_text(value_cells.get(scene_column)),
                    biff_cell_text(value_cells.get(take_column)),
                )
                if row is not None:
                    rows.append(row)
                    break
    return dedupe_retake_rows(rows)


def group_biff_cells_by_row(cells: list[BiffCell]) -> dict[int, dict[int, BiffCell]]:
    cells_by_row: dict[int, dict[int, BiffCell]] = {}
    for cell in cells:
        cells_by_row.setdefault(cell.row, {})[cell.column] = cell
    return cells_by_row


def find_biff_retake_header_columns(row_cells: dict[int, BiffCell]) -> dict[str, int] | None:
    columns: dict[str, int] = {}
    for column, cell in row_cells.items():
        label = normalize_biff_retake_header(biff_cell_text(cell))
        if label in {"시퀀스", "seq", "sequence"}:
            columns.setdefault("sequence", column)
        elif label in {"씬", "sc", "scene", "scno", "scnumber"}:
            columns.setdefault("scene", column)
        elif label in {"take", "tk"}:
            columns.setdefault("take", column)
    return columns if {"sequence", "scene", "take"}.issubset(columns) else None


def find_biff_legacy_card_columns(row_cells: dict[int, BiffCell]) -> list[tuple[int, int, int]]:
    columns: list[tuple[int, int, int]] = []
    sorted_columns = sorted(row_cells)
    for take_header_column in sorted_columns:
        if normalize_biff_retake_header(biff_cell_text(row_cells[take_header_column])) not in {"take", "tk"}:
            continue
        sequence_header_column = next(
            (column for column in sorted_columns if take_header_column < column <= take_header_column + 3 and normalize_biff_retake_header(biff_cell_text(row_cells[column])) in {"seq", "sequence", "시퀀스"}),
            None,
        )
        scene_header_column = next(
            (column for column in sorted_columns if sequence_header_column is not None and sequence_header_column < column <= sequence_header_column + 2 and normalize_biff_retake_header(biff_cell_text(row_cells[column])) in {"sc", "scno", "scnumber", "scene", "씬"}),
            None,
        )
        if sequence_header_column is None or scene_header_column is None:
            continue
        columns.append((take_header_column - 4, sequence_header_column - 1, scene_header_column))
    return columns


def normalize_biff_retake_header(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).lower()


def biff_cell_text(cell: BiffCell | None) -> str:
    if cell is None:
        return ""
    value = cell.value
    if isinstance(value, float):
        if value != value or abs(value - round(value)) > 0.000001:
            return ""
        return str(int(round(value)))
    return value.replace("\x00", "").strip()


def build_biff_retake_row(raw_sequence: str, raw_scene: str, raw_take: str) -> BobsRetakeRow | None:
    sequence_value = normalize_biff_retake_value(raw_sequence, allow_suffix=True)
    scene_value = normalize_biff_retake_value(raw_scene, allow_suffix=True)
    take_value = normalize_biff_retake_value(raw_take, allow_suffix=False)
    if sequence_value is None or scene_value is None or take_value is None:
        return None
    sequence = normalize_sequence(sequence_value)
    scene_label = normalize_scene_label(scene_value)
    return BobsRetakeRow(sequence=sequence, scene_number=normalize_scene_number(scene_label), scene_label=scene_label, tk=take_value.zfill(2))


def normalize_biff_retake_value(value: str, *, allow_suffix: bool) -> str | None:
    text = value.strip().upper()
    if not text:
        return None
    pattern = r"(\d{1,3}(?:[A-Z][0-9A-Z-]*)?)" if allow_suffix else r"(\d{1,3})"
    match = re.fullmatch(pattern, text)
    if not match:
        return None
    if int(re.match(r"\d+", match.group(1)).group(0)) == 0:
        return None
    return match.group(1)


def dedupe_retake_rows(rows: list[BobsRetakeRow]) -> list[BobsRetakeRow]:
    deduped: list[BobsRetakeRow] = []
    seen_rows: set[tuple[str, str, str]] = set()
    for row in rows:
        row_key = (row.sequence, row.scene_label, row.tk)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        deduped.append(row)
    return deduped


def find_xls_retake_rows_in_text(text: str) -> list[BobsRetakeRow]:
    rows: list[BobsRetakeRow] = []
    seen_rows: set[tuple[str, str, str]] = set()
    explicit_rows = find_retake_rows(text)
    if explicit_rows:
        return explicit_rows
    for date_match in EXCEL_DAY_FIRST_DATE_PATTERN.finditer(text):
        context_before = text[max(0, date_match.start() - 300) : date_match.start()]
        if not re.search(XLS_RETAKE_MARKER_PATTERN, context_before, re.IGNORECASE):
            continue
        tk_matches = list(re.finditer(r"\bTk\s*(\d{1,3})\b", context_before, re.IGNORECASE))
        if not tk_matches:
            continue
        tk_match = tk_matches[-1]
        token_window = text[date_match.end() : date_match.end() + 160]
        next_marker = re.search(XLS_RETAKE_MARKER_PATTERN, token_window, re.IGNORECASE)
        if next_marker:
            token_window = token_window[: next_marker.start()]
        tokens = re.findall(r"\b\d{1,3}[A-Za-z][0-9A-Za-z-]*\b", token_window)
        if len(tokens) < 2:
            continue
        sequence = normalize_sequence(tokens[0])
        tk = tk_match.group(1).zfill(2)
        for raw_scene in tokens[1:]:
            scene_label = normalize_scene_label(raw_scene)
            row_key = (sequence, scene_label, tk)
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append(BobsRetakeRow(sequence=sequence, scene_number=normalize_scene_number(scene_label), scene_label=scene_label, tk=tk))
    return rows


def find_retake_rows(text: str) -> list[BobsRetakeRow]:
    rows: list[BobsRetakeRow] = []
    seen_rows: set[tuple[str, str, str]] = set()
    for match in RETAKE_ROW_PATTERN.finditer(text):
        sequence = normalize_sequence(match.group(1))
        scene_label = normalize_scene_label(match.group(2))
        scene_number = normalize_scene_number(scene_label)
        tk = match.group(3).zfill(2)
        row_key = (sequence, scene_label, tk)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        rows.append(BobsRetakeRow(sequence=sequence, scene_number=scene_number, scene_label=scene_label, tk=tk))
    return rows


def normalize_sequence(value: str) -> str:
    match = re.match(r"^(\d+)(.*)$", value.strip().upper())
    if not match:
        return value.strip().upper()
    return f"{match.group(1).zfill(2)}{match.group(2)}"


def normalize_scene_number(value: str) -> str:
    match = re.match(r"^(\d+)", value.strip())
    if not match:
        return value.strip().upper()
    return match.group(1).zfill(2)


def normalize_scene_label(value: str) -> str:
    match = re.match(r"^(\d+)(.*)$", value.strip().upper())
    if not match:
        return value.strip().upper()
    return f"{match.group(1).zfill(2)}{match.group(2)}"


def _non_match(error: str, recognized: bool = False) -> dict[str, Any]:
    return {"matched": False, "recognized": recognized, "job": "", "due_date": None, "rows": [], "error": error}
