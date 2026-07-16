from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Sequence


SHIPMENT_TYPES = ("batch", "retake")
SHOW_CODES = ("BB", "HH", "FL", "KOTH")
MAX_VISITED_DIRECTORIES_PER_ROOT = 2000
MAX_SEARCH_DEPTH = 10
MAX_FAST_SEARCH_DEPTH = 6
JOB_TOKEN_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9]*\d{2,}\b")
CONTEXT_TOKEN_RE = re.compile(r"(?:batch\s*\d+|tk\s*\d+|HH_?\d{3,}|FL_?\d{3,}|KOTH_?(?:15|16)\d{2}(?:_PROMO)?|(?:15|16)\d{2}(?:_PROMO)?)", re.IGNORECASE)
TRAILING_TK_RE = re.compile(r"[._-]TK\d+$", re.IGNORECASE)
TRAILING_VERSION_RE = re.compile(r"[_-]v\d+$", re.IGNORECASE)
HH_SCENE_STEM_RE = re.compile(r"^HH\d{4}_\d{3}_\d{4}_[A-Z0-9]+(?:_v\d+)?$", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class SceneExpectation:
    expected_folder_name: str
    candidate_folder_names: tuple[str, ...]
    job_tokens: tuple[str, ...] = ()
    context_tokens: tuple[str, ...] = ()


def enrich_manifest_scene_validation(manifest: Dict[str, Any], shipping_root: Path) -> Dict[str, Any]:
    files = manifest.get("files")
    if not isinstance(files, list):
        return dict(manifest)

    context_values = _manifest_context_values(manifest, files)
    root_context_values = _manifest_root_context_values(manifest)
    job_tokens = _extract_job_tokens(context_values)
    root_context_tokens = _extract_context_tokens(root_context_values)
    ordered_roots = _ordered_bounded_roots(shipping_root, context_values, job_tokens, root_context_tokens)
    expectations_by_path = {}
    for entry in files:
        if not isinstance(entry, dict) or bool(entry.get("is_dir")):
            continue
        path_value = str(entry.get("path", ""))
        expectation = _scene_expectation(path_value, _file_context_values(manifest, path_value))
        if expectation:
            expectations_by_path[path_value] = expectation
    scene_validation_by_path = _validate_scene_files(expectations_by_path, ordered_roots)

    enriched_files: list[Any] = []
    for entry in files:
        if not isinstance(entry, dict):
            enriched_files.append(entry)
            continue
        enriched_entry = dict(entry)
        path_value = str(enriched_entry.get("path", ""))
        if path_value in scene_validation_by_path:
            enriched_entry["scene_validation"] = scene_validation_by_path[path_value]
        enriched_files.append(enriched_entry)

    enriched_manifest = dict(manifest)
    enriched_manifest["files"] = enriched_files
    return enriched_manifest


def validate_scene_file(
    file_path: str,
    bounded_roots: Sequence[Path],
    job_tokens: Sequence[str],
) -> Dict[str, Any]:
    expected_folder_name = _scene_folder_name(_normalized_scene_stem(file_path))
    expectation = SceneExpectation(expected_folder_name, (expected_folder_name,), tuple(job_tokens), ())
    return _validate_scene_files({file_path: expectation}, bounded_roots)[file_path]


def _validate_scene_files(
    expectations_by_path: Dict[str, SceneExpectation],
    bounded_roots: Sequence[Path],
) -> Dict[str, Dict[str, Any]]:
    existing_roots = [root for root in bounded_roots if root.is_dir()]
    if not existing_roots:
        return {
            file_path: _result(expectation.expected_folder_name, None, "bounded_roots_missing")
            for file_path, expectation in expectations_by_path.items()
        }

    results: Dict[str, Dict[str, Any]] = {}
    for file_path, expectation in expectations_by_path.items():
        alias_groups = {candidate: expectation.candidate_folder_names for candidate in expectation.candidate_folder_names}
        matched_paths = _find_scene_folder_matches(
            expectation.candidate_folder_names,
            existing_roots,
            expectation.job_tokens,
            expectation.context_tokens,
            alias_groups,
        )
        matched_path = next((matched_paths[candidate] for candidate in expectation.candidate_folder_names if candidate in matched_paths), None)
        results[file_path] = _result(
            expectation.expected_folder_name,
            matched_path,
            "matched_expected_folder" if matched_path is not None else "expected_folder_not_found",
        )
    return results


def _result(expected_folder_name: str, matched_path: Path | None, reason: str) -> Dict[str, Any]:
    return {
        "checked": True,
        "exists": matched_path is not None,
        "expected_folder_name": expected_folder_name,
        "matched_path": str(matched_path) if matched_path is not None else None,
        "reason": reason,
    }


def _find_scene_folder(expected_folder_name: str, roots: Sequence[Path], job_tokens: Sequence[str]) -> Path | None:
    return _find_scene_folder_matches([expected_folder_name], roots, job_tokens, []).get(expected_folder_name)


def _find_scene_folder_matches(
    expected_folder_names: Iterable[str],
    roots: Sequence[Path],
    job_tokens: Sequence[str],
    context_tokens: Sequence[str],
    alias_groups: Dict[str, Sequence[str]] | None = None,
) -> Dict[str, Path]:
    remaining = set(expected_folder_names)
    matches: Dict[str, Path] = {}

    for root in roots:
        for expected_folder_name in list(remaining):
            direct_match = root / expected_folder_name
            if direct_match.is_dir() and _scene_candidate_matches_context(
                expected_folder_name,
                direct_match,
                job_tokens,
                context_tokens,
            ):
                matches[expected_folder_name] = direct_match
                _remove_matched_candidate(remaining, expected_folder_name, alias_groups)

    if not remaining:
        return matches

    for root in roots:
        if not remaining:
            break
        for current_dir, child_names in _walk_prioritized_dirs(root, MAX_FAST_SEARCH_DEPTH):
            for expected_folder_name in list(remaining):
                if expected_folder_name in child_names:
                    candidate = current_dir / expected_folder_name
                    if _scene_candidate_matches_context(expected_folder_name, candidate, job_tokens, context_tokens):
                        matches[expected_folder_name] = candidate
                        _remove_matched_candidate(remaining, expected_folder_name, alias_groups)
            if not remaining:
                break

    if not remaining:
        return matches

    for root in roots:
        if not remaining:
            break
        for current_dir, child_names in _walk_bounded(root):
            if current_dir.name in remaining and _scene_candidate_matches_context(current_dir.name, current_dir, job_tokens, context_tokens):
                matches[current_dir.name] = current_dir
                _remove_matched_candidate(remaining, current_dir.name, alias_groups)
            for expected_folder_name in list(remaining):
                if expected_folder_name in child_names:
                    candidate = current_dir / expected_folder_name
                    if _scene_candidate_matches_context(expected_folder_name, candidate, job_tokens, context_tokens):
                        matches[expected_folder_name] = candidate
                        _remove_matched_candidate(remaining, expected_folder_name, alias_groups)
            if not remaining:
                break
    return matches


def _remove_matched_candidate(remaining: set[str], matched_candidate: str, alias_groups: Dict[str, Sequence[str]] | None) -> None:
    for candidate in alias_groups.get(matched_candidate, (matched_candidate,)) if alias_groups is not None else (matched_candidate,):
        remaining.discard(candidate)


def _walk_prioritized_dirs(root: Path, max_depth: int) -> Iterator[tuple[Path, list[str]]]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current_dir, depth = stack.pop()
        try:
            child_dirs = [child.name for child in current_dir.iterdir() if child.is_dir()]
        except OSError:
            continue
        ordered_child_names = _ordered_child_dirs(child_dirs)
        yield current_dir, ordered_child_names
        if depth >= max_depth or _is_scene_folder_name(current_dir.name):
            continue
        for child_name in reversed([name for name in ordered_child_names if not _is_scene_folder_name(name)]):
            stack.append((current_dir / child_name, depth + 1))


def _walk_bounded(root: Path) -> Iterator[tuple[Path, list[str]]]:
    root_depth = len(root.parts)
    visited = 0
    for current, dir_names, _file_names in os.walk(root):
        current_dir = Path(current)
        depth = len(current_dir.parts) - root_depth
        ordered_child_names = _ordered_child_dirs(dir_names)
        if depth >= MAX_SEARCH_DEPTH or _is_scene_folder_name(current_dir.name):
            dir_names[:] = []
        else:
            dir_names[:] = [name for name in ordered_child_names if not _is_scene_folder_name(name)]
        visited += 1
        if visited > MAX_VISITED_DIRECTORIES_PER_ROOT:
            dir_names[:] = []
            break
        yield current_dir, ordered_child_names


def _ordered_child_dirs(dir_names: list[str]) -> list[str]:
    return sorted(dir_names, key=lambda name: (0 if name == "jobs" else 1 if "harmony" in name.lower() else 2, name.upper()))


def _ordered_bounded_roots(
    shipping_root: Path,
    context_values: Sequence[str],
    job_tokens: Sequence[str],
    context_tokens: Sequence[str],
) -> list[Path]:
    preferred_type_values = _preferred_shipment_types(context_values)
    preferred_show_values = _preferred_show_codes(context_values)
    preferred_types = preferred_type_values or list(SHIPMENT_TYPES)
    preferred_shows = preferred_show_values or list(SHOW_CODES)
    show_roots = [shipping_root / shipment_type / show for shipment_type in preferred_types for show in preferred_shows]
    child_roots = [child_root for root in show_roots for child_root in _matching_child_roots(root, job_tokens, context_tokens)]
    if child_roots:
        return _unique_paths(child_roots)
    return show_roots


def _matching_child_roots(root: Path, job_tokens: Sequence[str], context_tokens: Sequence[str]) -> list[Path]:
    if not root.is_dir() or not context_tokens:
        return []
    return [
        child
        for child in _ordered_child_paths(root)
        if child.is_dir() and _path_matches_context(child, job_tokens, context_tokens)
    ]


def _ordered_child_paths(root: Path) -> list[Path]:
    return sorted(root.iterdir(), key=lambda path: path.name.upper())


def _ordered_values(values: Sequence[str], preferred: Iterable[str]) -> list[str]:
    ordered_preferred = [value for value in preferred if value in values]
    return [*ordered_preferred, *(value for value in values if value not in ordered_preferred)]


def _preferred_shipment_types(context_values: Sequence[str]) -> list[str]:
    text = _context_text(context_values)
    preferred: list[str] = []

    tk_number = _tk_context_number(text)
    if "retake" in text or (tk_number is not None and (tk_number > 1 or _is_bobs_context(text))):
        preferred.append("retake")
    if _has_explicit_batch_context(text) or tk_number == 1:
        preferred.append("batch")
    return preferred


def _tk_context_number(text: str) -> int | None:
    match = re.search(r"(?:^|[\s/_-])tk\s*(\d+)(?=$|[\s/_-])", text)
    return int(match.group(1)) if match else None


def _is_bobs_context(text: str) -> bool:
    return "bobs" in text or "fasa" in text or "밥스버거" in text


def _has_explicit_batch_context(text: str) -> bool:
    return re.search(r"(?:^|[\s/_-])batch\s*\d+(?=$|[\s/_-])", text) is not None


def _preferred_show_codes(context_values: Sequence[str]) -> list[str]:
    text = _context_text(context_values)
    preferred: list[str] = []
    if "bobs" in text or "fasa" in text:
        preferred.append("BB")
    if "koth" in text or "king" in text:
        preferred.append("KOTH")
    if "florida" in text or "/fl" in text or " fl_" in text:
        preferred.append("FL")
    if "harmony" in text or "/hh" in text or " hh_" in text:
        preferred.append("HH")
    return preferred


def _extract_job_tokens(context_values: Sequence[str]) -> list[str]:
    tokens: list[str] = []
    for value in context_values:
        for match in JOB_TOKEN_RE.findall(value.upper()):
            if match not in tokens:
                tokens.append(match)
    return tokens


def _extract_context_tokens(context_values: Sequence[str]) -> list[str]:
    tokens: list[str] = []
    for value in context_values:
        if re.fullmatch(r"\d{6}", value) and value not in tokens:
            tokens.append(value)
        for token in _date_context_tokens_from_value(value):
            if token not in tokens:
                tokens.append(token)
        for match in CONTEXT_TOKEN_RE.findall(value):
            token = _normalize_context_token(match)
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def _date_context_tokens_from_value(value: str) -> list[str]:
    tokens: list[str] = []
    for month, day, year in re.findall(r"(?:^|[^0-9])(\d{2})(\d{2})_(\d{4})(?=$|[^0-9])", value):
        if _is_valid_month_day(month, day):
            tokens.append(f"{month}{day}{year[-2:]}")
    for year, month, day in re.findall(r"(?:^|[^0-9])(\d{4})_(\d{2})(\d{2})(?=$|[^0-9])", value):
        if _is_valid_month_day(month, day):
            tokens.append(f"{month}{day}{year[-2:]}")
    return tokens


def _is_valid_month_day(month: str, day: str) -> bool:
    month_number = int(month)
    day_number = int(day)
    return 1 <= month_number <= 12 and 1 <= day_number <= 31


def _manifest_context_values(manifest: Dict[str, Any], files: Sequence[Any]) -> list[str]:
    values = [str(manifest.get("source_path", "")), str(manifest.get("folder_name", ""))]
    values.extend(str(entry.get("path", "")) for entry in files if isinstance(entry, dict))
    return values


def _file_context_values(manifest: Dict[str, Any], file_path: str) -> list[str]:
    return [str(manifest.get("source_path", "")), str(manifest.get("folder_name", "")), file_path]


def _manifest_root_context_values(manifest: Dict[str, Any]) -> list[str]:
    values = [
        str(manifest.get("source_path", "")),
        str(manifest.get("folder_name", "")),
    ]
    if not _is_bobs_retake_context(values) and not any(_date_context_tokens_from_value(value) for value in values):
        values.extend(_manifest_date_tokens(manifest))
    return values


def _is_bobs_retake_context(context_values: Sequence[str]) -> bool:
    text = _context_text(context_values)
    return _is_bobs_context(text) and re.search(r"(?:^|[\s/_-])retake(?=$|[\s/_-])", text) is not None


def _manifest_date_tokens(manifest: Dict[str, Any]) -> list[str]:
    created_token = _date_context_token(str(manifest.get("created_at", "")))
    return [created_token] if created_token else []


def _date_context_token(value: str) -> str:
    match = ISO_DATE_RE.match(value)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{month}{day}{year[-2:]}"


def _context_text(context_values: Sequence[str]) -> str:
    return " ".join(context_values).replace("\\", "/").lower()


def _is_bobs_scene(file_path: str) -> bool:
    return Path(file_path).suffix.lower() == ".bobs-scene"


def _scene_expectation(file_path: str, context_values: Sequence[str]) -> SceneExpectation | None:
    job_tokens = tuple(_extract_job_tokens(context_values))
    context_tokens = tuple(_extract_context_tokens(context_values))
    if _is_bobs_scene(file_path):
        folder_name = _scene_folder_name(Path(file_path).stem)
        return SceneExpectation(folder_name, (folder_name,), job_tokens, context_tokens)

    if not _is_supported_show_scene(file_path, context_values):
        return None

    raw_stem = Path(file_path).stem
    normalized_stem = _normalized_scene_stem(file_path)
    shows = set(_preferred_show_codes(context_values))
    if "HH" in shows:
        return _hh_scene_expectation(raw_stem, normalized_stem, job_tokens, context_tokens)

    expected_folder_name = _scene_folder_name(normalized_stem)
    task_folder_name = _task_folder_name(normalized_stem)
    shot_folder_name = _koth_shot_folder_name(normalized_stem) if "KOTH" in shows else ""
    candidates = _unique_values([task_folder_name, shot_folder_name, expected_folder_name, _scene_folder_name(raw_stem)])
    return SceneExpectation(expected_folder_name, tuple(candidates), job_tokens, context_tokens)


def _hh_scene_expectation(
    raw_stem: str,
    normalized_stem: str,
    job_tokens: Sequence[str],
    context_tokens: Sequence[str],
) -> SceneExpectation | None:
    if not _is_hh_scene_stem(raw_stem):
        return None
    return SceneExpectation(raw_stem, (raw_stem,), tuple(job_tokens), tuple(context_tokens))


def _normalized_scene_stem(file_path: str) -> str:
    return TRAILING_VERSION_RE.sub("", TRAILING_TK_RE.sub("", Path(file_path).stem))


def _task_folder_name(stem: str) -> str:
    match = re.search(r"(?:^|[_-])((?:T)\d{3,})(?=$|[_-])", stem, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _koth_shot_folder_name(stem: str) -> str:
    match = re.search(r"(?:^|[_-])(?:15|16)\d{2}(?:_PROMO)?_(\d{3,})(?=$|[_-])", stem, re.IGNORECASE)
    return match.group(1) if match else ""


def _scene_folder_name(stem: str) -> str:
    return f"scene-{stem}"


def _is_scene_folder_name(value: str) -> bool:
    return value.startswith("scene-") or re.fullmatch(r"T\d{3,}", value, re.IGNORECASE) is not None or _is_hh_scene_stem(value)


def _is_hh_scene_stem(value: str) -> bool:
    return HH_SCENE_STEM_RE.fullmatch(value) is not None


def _is_supported_show_scene(file_path: str, context_values: Sequence[str]) -> bool:
    stem = _normalized_scene_stem(file_path)
    shows = set(_preferred_show_codes(context_values))
    if "HH" in shows and re.search(r"\bHH_?\d{3,}", stem, re.IGNORECASE):
        return True
    if "FL" in shows and re.search(r"\bFL_?\d{3,}", stem, re.IGNORECASE):
        return True
    if "KOTH" in shows and re.search(r"(?:^|[^0-9])(?:KOTH[_-]?)?(?:15|16)\d{2}(?=$|[^0-9])", stem, re.IGNORECASE):
        return True
    return False


def _path_matches_context(path: Path, job_tokens: Sequence[str], context_tokens: Sequence[str]) -> bool:
    text = _normalize_context_token(path.as_posix())
    required_tokens = [_normalize_context_token(token) for token in job_tokens]
    required_tokens.extend(context_tokens)
    required_tokens = _unique_values([token for token in required_tokens if token])
    return all(_context_token_matches_path_text(token, text) for token in required_tokens)


def _context_token_matches_path_text(token: str, path_text: str) -> bool:
    if token in path_text:
        return True
    if re.fullmatch(r"\d{6}", token):
        full_year_token = f"{token[:4]}20{token[4:]}"
        year_first_token = f"20{token[4:]}{token[:4]}"
        return full_year_token in path_text or year_first_token in path_text
    if re.fullmatch(r"tk\d+", token):
        tk_number = int(token[2:])
        return f"tk{tk_number}" in path_text or f"take{tk_number}" in path_text
    return False


def _scene_path_matches_context(path: Path, job_tokens: Sequence[str], context_tokens: Sequence[str]) -> bool:
    return _path_matches_context(path, job_tokens, context_tokens) and _has_job_token_path_part(path, job_tokens)


def _scene_candidate_matches_context(
    candidate_name: str,
    path: Path,
    job_tokens: Sequence[str],
    context_tokens: Sequence[str],
) -> bool:
    if not _scene_path_matches_context(path, job_tokens, context_tokens):
        return False
    if re.fullmatch(r"T\d{3,}", candidate_name, re.IGNORECASE):
        return _is_valid_task_folder_path(path, context_tokens)
    if _is_hh_scene_stem(candidate_name):
        return _is_valid_hh_scene_folder_path(candidate_name, path)
    if not re.fullmatch(r"\d{3,}", candidate_name):
        return True
    return _is_valid_koth_numeric_shot_path(candidate_name, path, context_tokens)


def _is_valid_task_folder_path(path: Path, context_tokens: Sequence[str]) -> bool:
    parent_token = _normalize_context_token(path.parent.name)
    episode_tokens = [
        token
        for token in context_tokens
        if re.fullmatch(r"(?:fl|hh)\d{3,}|(?:15|16)\d{2}(?:promo)?", token, re.IGNORECASE)
    ]
    return parent_token in episode_tokens


def _is_valid_hh_scene_folder_path(scene_name: str, path: Path) -> bool:
    expected_parent_token = _hh_scene_parent_token(scene_name)
    return expected_parent_token != "" and _normalize_context_token(path.parent.name) == expected_parent_token


def _hh_scene_parent_token(scene_name: str) -> str:
    match = re.match(r"^HH(\d{2})(\d{2})_", scene_name, re.IGNORECASE)
    if not match:
        return ""
    season, episode = match.groups()
    return f"hh{int(season)}{episode}"


def _is_valid_koth_numeric_shot_path(shot_name: str, path: Path, context_tokens: Sequence[str]) -> bool:
    parent_name = path.parent.name
    parent_token = _normalize_context_token(parent_name)
    if "harmony" in parent_name.lower():
        return True
    if _is_koth_episode_context_token(parent_token, context_tokens):
        return True
    return _shot_range_parent_contains(parent_name, int(shot_name))


def _is_koth_episode_context_token(parent_token: str, context_tokens: Sequence[str]) -> bool:
    episode_tokens = [
        token
        for token in context_tokens
        if re.fullmatch(r"(?:15|16)\d{2}(?:promo)?", token, re.IGNORECASE)
    ]
    return parent_token in episode_tokens


def _shot_range_parent_contains(parent_name: str, shot_number: int) -> bool:
    range_match = re.search(r"(?<!\d)(\d{3,})(?:thru|through|to|-)(\d{3,})(?!\d)", parent_name, re.IGNORECASE)
    if not range_match:
        return False
    start, end = (int(value) for value in range_match.groups())
    return start <= shot_number <= end


def _has_job_token_path_part(path: Path, job_tokens: Sequence[str]) -> bool:
    if not job_tokens:
        return True
    path_parts = {part.upper() for part in path.parts}
    return any(_path_part_matches_job_token(path_parts, token) for token in job_tokens)


def _path_part_matches_job_token(path_parts: set[str], token: str) -> bool:
    normalized_token = token.upper()
    if normalized_token in path_parts:
        return True
    if re.fullmatch(r"HH\d{4}", normalized_token):
        return any(part.startswith(f"{normalized_token}_") and _is_hh_scene_stem(part) for part in path_parts)
    return False


def _normalize_context_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _unique_values(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def _unique_paths(paths: Sequence[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique
