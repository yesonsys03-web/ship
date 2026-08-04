from __future__ import annotations

import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .models import ShipmentManifest


DEFAULT_HOSTS_FILE = Path("/etc/hosts")
APP_DATA_DIR_NAME = "Ship"
AUDIT_LOG_DIR_NAME = "audit_logs"


def write_manifest_audit_event(
    action: str,
    manifest_payload: Dict[str, Any],
    *,
    db_file: Path | None = None,
    **metadata: Any,
) -> None:
    try:
        manifest = ShipmentManifest.from_dict(manifest_payload)
        entry = build_manifest_audit_entry(action, manifest, metadata)
        log_dir = audit_log_dir(db_file)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{entry['date']}.jsonl"
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception as audit_error:
        print(f"audit logging skipped: {audit_error}", file=sys.stderr)


def build_manifest_audit_entry(action: str, manifest: ShipmentManifest, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
    metadata = metadata or {}
    now = datetime.now(timezone.utc)
    host = detect_current_host()
    job = string_or_empty(metadata.get("job")) or infer_bobs_job(manifest)
    tk = string_or_empty(metadata.get("tk")) or infer_bobs_tk(manifest)
    batch = string_or_empty(metadata.get("batch"))
    files = [entry.path for entry in manifest.files if not entry.is_dir]
    return {
        "schema_version": 1,
        "timestamp": now.isoformat(),
        "date": now.date().isoformat(),
        "action": action,
        "manifest_id": manifest.id,
        "folder_name": manifest.folder_name,
        "source_path": manifest.source_path,
        "file_count": len(files),
        "files": files,
        "note": manifest.note,
        "job": job,
        "tk": tk,
        "batch": batch,
        "ip": host["ip"],
        "hostname": host["hostname"],
        "hostname_source": host["hostname_source"],
    }


def audit_log_dir(db_file: Path | None = None) -> Path:
    configured = os.environ.get("SHIP_AUDIT_LOG_DIR", "").strip()
    if configured:
        return Path(configured)
    shared_dir = shared_audit_log_dir(db_file)
    if shared_dir is not None:
        return shared_dir
    return local_audit_log_dir()


def shared_audit_log_dir(db_file: Path | None = None) -> Path | None:
    if db_file is not None:
        return db_file.parent
    configured_db_dir = os.environ.get("SHIP_DB_DIR", "").strip()
    if configured_db_dir:
        return Path(configured_db_dir).expanduser()
    return None


def local_audit_log_dir() -> Path:
    if os.name == "nt":
        app_data = os.environ.get("LOCALAPPDATA", "").strip() or os.environ.get("APPDATA", "").strip()
        if app_data:
            return Path(app_data) / APP_DATA_DIR_NAME / AUDIT_LOG_DIR_NAME

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_DATA_DIR_NAME / AUDIT_LOG_DIR_NAME

    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if data_home:
        return Path(data_home) / APP_DATA_DIR_NAME / AUDIT_LOG_DIR_NAME
    return home / ".local" / "share" / APP_DATA_DIR_NAME / AUDIT_LOG_DIR_NAME


def detect_current_host() -> Dict[str, str]:
    ip = detect_local_ip()
    if ip:
        hosts_name = hostname_from_hosts(ip)
        if hosts_name:
            return {"ip": ip, "hostname": hosts_name, "hostname_source": "hosts"}
    fallback_hostname = socket.gethostname()
    return {"ip": ip or "unknown", "hostname": fallback_hostname or "unknown", "hostname_source": "socket"}


def detect_local_ip() -> str:
    probe_ip = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            probe_ip = str(probe.getsockname()[0])
    except OSError:
        probe_ip = ""

    if probe_ip:
        return probe_ip

    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return ""


def hostname_from_hosts(ip: str) -> str:
    hosts_file = Path(os.environ.get("SHIP_AUDIT_HOSTS_FILE", str(DEFAULT_HOSTS_FILE)))
    try:
        for line in hosts_file.read_text(encoding="utf-8").splitlines():
            host_name = host_name_from_hosts_line(ip, line)
            if host_name:
                return host_name
    except OSError:
        return ""
    return ""


def host_name_from_hosts_line(ip: str, line: str) -> str:
    content = line.split("#", 1)[0].strip()
    if not content:
        return ""
    parts = content.split()
    if len(parts) < 2 or parts[0] != ip:
        return ""
    return parts[1]


def infer_bobs_job(manifest: ShipmentManifest) -> str:
    sources = [manifest.source_path, manifest.folder_name, *(entry.path for entry in manifest.files)]
    for source in sources:
        match = re.search(r"\b(FASA\d+|GASA\d*)\b", source, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def infer_bobs_tk(manifest: ShipmentManifest) -> str:
    sources = [manifest.folder_name, manifest.source_path, *(entry.path for entry in manifest.files)]
    for source in sources:
        match = re.search(r"\bTK\s*(\d+)\b", source, re.IGNORECASE)
        if match:
            return f"TK{match.group(1)}"
    return ""


def string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
