from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


BOBS_ENVIRONMENT = "Bobs_Burgers"
BOBS_CATALOG_ROOTS = (
    Path("/USA_DB"),
    Path("/System/Volumes/Data/mnt/USA_DB"),
)
BOBS_JOB_PREFIXES = ("FA", "GA", "HA")
BOBS_JOB_PREFIX_PATTERN = r"(?:(?:[A-Z0-9]ASA)|FA|GA|HA)"
JOBS_DB_RELATIVE_PATH = Path("online_jobs") / "jobs.db"
JOB_NAME_PATTERN = re.compile(rf"^{BOBS_JOB_PREFIX_PATTERN}[A-Za-z0-9_]*$")
JOB_TOKEN_PATTERN = re.compile(rf"(?<![A-Za-z0-9_])({BOBS_JOB_PREFIX_PATTERN}[A-Za-z0-9_]*)(?![A-Za-z0-9_])")
SCENE_SEQUENCE_KEY_PATTERN = r"[0-9]{2}(?:[A-Z][0-9-]*|-[A-Za-z0-9][A-Za-z0-9-]*)?"
SCENE_NAME_PATTERN = re.compile(rf"^{SCENE_SEQUENCE_KEY_PATTERN}_S[0-9]{{2}}[A-Za-z]*$")
SCENE_TOKEN_PATTERN = re.compile(rf"(?<![A-Za-z0-9_/-])(?:scene-)?({SCENE_SEQUENCE_KEY_PATTERN}_S[0-9]{{2}}[A-Za-z]*)(?![A-Za-z0-9_./-])", re.IGNORECASE)
BINARY_SCENE_TOKEN_PATTERN = re.compile(rb"(?<![A-Za-z0-9_/-])(?:scene-)?([0-9]{2}(?:[A-Z][0-9-]*|-[A-Za-z0-9][A-Za-z0-9-]*)?_S[0-9]{2}[A-Za-z]*)(?![A-Za-z0-9_./-])", re.IGNORECASE)
BINARY_JOB_TOKEN_PATTERN = re.compile(rb"(?<![A-Za-z0-9_])((?:(?:[A-Z0-9]ASA)|FA|GA|HA)[A-Za-z0-9_]*)(?![A-Za-z0-9_])")
NATURAL_SORT_PATTERN = re.compile(r"(\d+)")
INTERNAL_JOB_NAME_MARKERS = ("_TEST", "_INTERNAL")
INTERNAL_JOB_NAME_SUFFIXES = ("TEST", "INTERNAL")


def bobs_catalog_jobs(roots: Iterable[Path] = BOBS_CATALOG_ROOTS) -> Dict[str, Any]:
    root, warnings = resolve_bobs_catalog_root(roots)
    jobs_db_path = root / JOBS_DB_RELATIVE_PATH if root is not None else None
    jobs = list_bobs_jobs(root, warnings) if root is not None else []
    return {
        "environment": BOBS_ENVIRONMENT,
        "root": str(root) if root is not None else None,
        "jobs_db_path": str(jobs_db_path) if jobs_db_path is not None else None,
        "jobs_source": "db_jobs+jobs_db" if root is not None and jobs_db_path is not None and jobs_db_path.exists() else "db_jobs",
        "jobs": jobs,
        "warnings": warnings,
    }


def bobs_catalog_job(job: str, roots: Iterable[Path] = BOBS_CATALOG_ROOTS) -> Dict[str, Any]:
    root, warnings = resolve_bobs_catalog_root(roots)
    if root is None:
        return _empty_job_detail(job, None, "catalog_root_missing", warnings)

    jobs_db_path = root / JOBS_DB_RELATIVE_PATH
    jobs_db_catalog, jobs_db_warnings = read_jobs_db_catalog(jobs_db_path)
    warnings.extend(jobs_db_warnings)
    jobs = set(_list_db_jobs_directory(root)) | jobs_db_catalog["jobs"]
    if job not in jobs:
        warnings.append(f"job not found in Bobs catalog: {job}")
        payload = _empty_job_detail(job, root / "db_jobs" / job / "scene.db", "job_not_found", warnings)
        payload["jobs_db_path"] = str(jobs_db_path)
        payload["scene_source"] = None
        return payload

    scene_db_path = root / "db_jobs" / job / "scene.db"
    jobs_db_scenes = jobs_db_catalog["scenes_by_job"].get(job, [])
    if jobs_db_scenes:
        scenes = jobs_db_scenes
        status = "jobs_db"
        scene_source = "jobs_db"
    else:
        scenes, scene_warnings, status = read_scene_names(scene_db_path)
        warnings.extend(scene_warnings)
        scene_source = "scene_db"
    return {
        "environment": BOBS_ENVIRONMENT,
        "job": job,
        "root": str(root),
        "scene_db_path": str(scene_db_path),
        "jobs_db_path": str(jobs_db_path),
        "scene_source": scene_source,
        "status": status,
        "scenes": scenes,
        "sequences": sequences_for_scenes(scenes),
        "warnings": warnings,
    }


def resolve_bobs_catalog_root(roots: Iterable[Path] = BOBS_CATALOG_ROOTS) -> Tuple[Path | None, List[str]]:
    checked_roots: List[str] = []
    for root in roots:
        checked_roots.append(str(root))
        if (root / "db_jobs").is_dir() or (root / JOBS_DB_RELATIVE_PATH).is_file():
            return root, []
    return None, [f"Bobs catalog root not found; checked: {', '.join(checked_roots)}"]


def list_bobs_jobs(root: Path, warnings: List[str] | None = None) -> List[str]:
    db_jobs = set(_list_db_jobs_directory(root))
    jobs_db_catalog, jobs_db_warnings = read_jobs_db_catalog(root / JOBS_DB_RELATIVE_PATH)
    if warnings is not None:
        warnings.extend(jobs_db_warnings)
    return sorted(db_jobs | jobs_db_catalog["jobs"], key=natural_sort_key)


def _list_db_jobs_directory(root: Path) -> List[str]:
    jobs_root = root / "db_jobs"
    if not jobs_root.is_dir():
        return []
    jobs = [path.name for path in jobs_root.iterdir() if path.is_dir() and is_bobs_job_name(path.name)]
    return sorted(jobs, key=natural_sort_key)


def read_jobs_db_catalog(jobs_db_path: Path) -> Tuple[Dict[str, Any], List[str]]:
    empty_catalog: Dict[str, Any] = {"jobs": set(), "scenes_by_job": {}}
    if not jobs_db_path.exists():
        return empty_catalog, []
    if not jobs_db_path.is_file():
        return empty_catalog, [f"jobs.db path is not a file: {jobs_db_path}"]

    try:
        connection = sqlite3.connect(jobs_db_path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        jobs = _read_binary_job_names(jobs_db_path)
        if jobs:
            return {"jobs": jobs, "scenes_by_job": {}}, [f"jobs.db is not readable SQLite: {exc}", "jobs.db scanned as custom binary data for embedded job names"]
        return empty_catalog, [f"jobs.db is not readable SQLite: {exc}", "jobs.db custom binary scan found no job-name-like values"]
    except sqlite3.Error as exc:
        return empty_catalog, [f"jobs.db could not be opened read-only: {exc}"]

    try:
        connection.row_factory = sqlite3.Row
        catalog = _discover_jobs_db_catalog(connection)
    except sqlite3.DatabaseError as exc:
        jobs = _read_binary_job_names(jobs_db_path)
        if jobs:
            return {"jobs": jobs, "scenes_by_job": {}}, [f"jobs.db is not readable SQLite: {exc}", "jobs.db scanned as custom binary data for embedded job names"]
        return empty_catalog, [f"jobs.db is not readable SQLite: {exc}", "jobs.db custom binary scan found no job-name-like values"]
    except sqlite3.Error as exc:
        return empty_catalog, [f"jobs.db could not be queried: {exc}"]
    finally:
        connection.close()

    if not catalog["jobs"] and not catalog["scenes_by_job"]:
        return catalog, ["jobs.db opened as SQLite but no job/scene rows were found"]
    return catalog, []


def read_scene_names(scene_db_path: Path) -> Tuple[List[str], List[str], str]:
    if not scene_db_path.exists():
        return [], [f"scene.db missing: {scene_db_path}"], "scene_db_missing"
    if not scene_db_path.is_file():
        return [], [f"scene.db path is not a file: {scene_db_path}"], "scene_db_invalid"

    try:
        connection = sqlite3.connect(scene_db_path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.DatabaseError as exc:
        return _read_binary_scene_names(scene_db_path, f"scene.db is not readable SQLite: {exc}")
    except sqlite3.Error as exc:
        return [], [f"scene.db could not be opened read-only: {exc}"], "scene_db_unreadable"

    try:
        connection.row_factory = sqlite3.Row
        scenes = sorted(_discover_scene_names(connection), key=natural_sort_key)
    except sqlite3.DatabaseError as exc:
        return _read_binary_scene_names(scene_db_path, f"scene.db is not readable SQLite: {exc}")
    except sqlite3.Error as exc:
        return [], [f"scene.db could not be queried: {exc}"], "scene_db_query_failed"
    finally:
        connection.close()

    if not scenes:
        return [], ["scene.db opened as SQLite but no scene-name-like values were found"], "no_scenes_found"
    return scenes, [], "ok"


def _read_binary_scene_names(scene_db_path: Path, sqlite_warning: str) -> Tuple[List[str], List[str], str]:
    try:
        data = scene_db_path.read_bytes()
    except OSError as exc:
        return [], [sqlite_warning, f"scene.db binary scan failed: {exc}"], "scene_db_unreadable"

    scenes = sorted(
        {
            scene
            for match in BINARY_SCENE_TOKEN_PATTERN.finditer(data)
            for scene in [_normalize_scene_name(match.group(1).decode("ascii"))]
            if scene is not None
        },
        key=natural_sort_key,
    )
    if scenes:
        return scenes, [sqlite_warning, "scene.db scanned as custom binary data for embedded scene names"], "scene_db_binary_scan"
    return [], [sqlite_warning, "scene.db custom binary scan found no scene-name-like values"], "scene_db_binary_unrecognized"


def sequences_for_scenes(scenes: Iterable[str]) -> Dict[str, List[str]]:
    sequences: Dict[str, List[str]] = {}
    for scene in scenes:
        sequence = scene.split("_S", 1)[0]
        sequences.setdefault(sequence, []).append(scene)
    return {sequence: sorted(scene_names, key=natural_sort_key) for sequence, scene_names in sorted(sequences.items(), key=lambda item: natural_sort_key(item[0]))}


def is_bobs_job_name(value: str) -> bool:
    job_name = value.strip()
    if not JOB_NAME_PATTERN.match(job_name):
        return False

    upper_job_name = job_name.upper()
    if any(marker in upper_job_name for marker in INTERNAL_JOB_NAME_MARKERS):
        return False
    return not any(upper_job_name.endswith(suffix) for suffix in INTERNAL_JOB_NAME_SUFFIXES)


def natural_sort_key(value: str) -> List[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in NATURAL_SORT_PATTERN.split(value)]


def _discover_jobs_db_catalog(connection: sqlite3.Connection) -> Dict[str, Any]:
    jobs: set[str] = set()
    scenes_by_job: Dict[str, set[str]] = {}
    for table_name in _catalog_relation_names(connection):
        column_names = _text_column_names(connection, table_name)
        if not column_names:
            continue
        query = f"select {', '.join(_quote_identifier(column_name) for column_name in column_names)} from {_quote_identifier(table_name)}"
        for row in connection.execute(query):
            row_jobs: set[str] = set()
            row_scenes: set[str] = set()
            for value in row:
                if not isinstance(value, str):
                    continue
                row_jobs.update(_job_tokens(value))
                row_scenes.update(_scene_tokens(value))
            jobs.update(row_jobs)
            for row_job in row_jobs:
                if row_scenes:
                    scenes_by_job.setdefault(row_job, set()).update(row_scenes)
    return {
        "jobs": jobs,
        "scenes_by_job": {
            job: sorted(scenes, key=natural_sort_key)
            for job, scenes in sorted(scenes_by_job.items(), key=lambda item: natural_sort_key(item[0]))
        },
    }


def _catalog_relation_names(connection: sqlite3.Connection) -> List[str]:
    rows = connection.execute("select name from sqlite_master where type in ('table', 'view') and name not like 'sqlite_%'").fetchall()
    return [str(row[0]) for row in rows]


def _job_tokens(value: str) -> set[str]:
    return {match.group(1) for match in JOB_TOKEN_PATTERN.finditer(value.strip()) if is_bobs_job_name(match.group(1))}


def _scene_tokens(value: str) -> set[str]:
    return {
        scene
        for match in SCENE_TOKEN_PATTERN.finditer(value.strip())
        for scene in [_normalize_scene_name(match.group(1))]
        if scene is not None
    }


def _read_binary_job_names(jobs_db_path: Path) -> set[str]:
    try:
        data = jobs_db_path.read_bytes()
    except OSError:
        return set()
    return {match.group(1).decode("ascii") for match in BINARY_JOB_TOKEN_PATTERN.finditer(data) if is_bobs_job_name(match.group(1).decode("ascii"))}


def _discover_scene_names(connection: sqlite3.Connection) -> List[str]:
    scene_names: set[str] = set()
    for table_name in _table_names(connection):
        for column_name in _text_column_names(connection, table_name):
            scene_names.update(_scene_values_from_column(connection, table_name, column_name))
    return list(scene_names)


def _table_names(connection: sqlite3.Connection) -> List[str]:
    rows = connection.execute("select name from sqlite_master where type = 'table' and name not like 'sqlite_%'").fetchall()
    return [str(row[0]) for row in rows]


def _text_column_names(connection: sqlite3.Connection, table_name: str) -> List[str]:
    rows = connection.execute(f"pragma table_info({_quote_identifier(table_name)})").fetchall()
    return [str(row[1]) for row in rows if _is_text_affinity(str(row[2]))]


def _is_text_affinity(declared_type: str) -> bool:
    upper_type = declared_type.upper()
    return upper_type == "" or any(token in upper_type for token in ("CHAR", "CLOB", "TEXT", "VARCHAR"))


def _scene_values_from_column(connection: sqlite3.Connection, table_name: str, column_name: str) -> List[str]:
    query = f"select distinct {_quote_identifier(column_name)} from {_quote_identifier(table_name)} where typeof({_quote_identifier(column_name)}) = 'text'"
    rows = connection.execute(query).fetchall()
    return [scene for row in rows for scene in [_normalize_scene_name(str(row[0]).strip())] if scene is not None]


def _normalize_scene_name(value: str) -> str | None:
    scene = value.removeprefix("scene-").strip()
    if scene == "" or ".old" in scene.lower() or scene.lower().endswith("_old") or "sub_model" in scene.lower():
        return None
    return scene if SCENE_NAME_PATTERN.match(scene) else None


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _empty_job_detail(job: str, scene_db_path: Path | None, status: str, warnings: List[str]) -> Dict[str, Any]:
    return {
        "environment": BOBS_ENVIRONMENT,
        "job": job,
        "root": None if scene_db_path is None else str(scene_db_path.parents[2]),
        "scene_db_path": None if scene_db_path is None else str(scene_db_path),
        "status": status,
        "scenes": [],
        "sequences": {},
        "warnings": warnings,
    }
