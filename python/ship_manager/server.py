from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import BaseServer
from typing import Any, Dict, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

from .config import MANAGER_ALLOWED_ORIGINS, MANAGER_HOST, MANAGER_MAX_REQUEST_BYTES, MANAGER_PORT
from .service import get_shipment, list_shipments, receive
from ship_common.db_path import resolve_ship_db_file
from ship_common.shipment_db import ShipmentDatabase
from ship_common.thumbnails import get_thumbnail_bytes


class ManagerHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        if not self._origin_allowed():
            self._send_json({"error": "origin not allowed"}, status=403)
            return
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        try:
            if self.path == "/health":
                self._send_json({"ok": True, "role": "manager"})
                return
            parsed_path = urlparse(self.path)
            if parsed_path.path == "/thumbnail":
                try:
                    query = parse_qs(parsed_path.query)
                    file_path = _required_query_value(query, "file_path")
                    shipment_id = _optional_query_value(query, "shipment_id")
                    thumbnail = get_persisted_thumbnail_bytes(shipment_id, file_path) if shipment_id else None
                    if thumbnail is None:
                        thumbnail = get_thumbnail_bytes(_required_query_value(query, "source_path"), file_path)
                        if shipment_id:
                            save_persisted_thumbnail_bytes(shipment_id, file_path, thumbnail)
                    self._send_bytes(thumbnail, "image/png")
                except Exception as exc:
                    self._send_json({"error": str(exc)}, status=404)
                return
            if self.path == "/shutdown":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self._send_json({"error": "forbidden"}, status=403)
                    return
                self._send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == "/shipments":
                self._send_json(list_shipments())
                return
            if self.path.startswith("/shipment"):
                self._send_json(get_shipment(self.path))
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def do_POST(self) -> None:
        try:
            if self.path == "/shipments":
                self._send_json(receive(self._read_json()))
                return
            self._send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _read_json(self) -> Dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            raise ValueError("content type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MANAGER_MAX_REQUEST_BYTES:
            raise ValueError("request body too large")
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if origin in MANAGER_ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if origin in MANAGER_ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in MANAGER_ALLOWED_ORIGINS

    def log_message(self, format: str, *args: Tuple[Any, ...]) -> None:
        return


def parse_parent_pid(argv: Sequence[str] | None = None) -> int | None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-pid", type=int, default=None)
    return parser.parse_args(argv).parent_pid


def _required_query_value(query: Dict[str, list[str]], key: str) -> str:
    value = query.get(key, [""])[0]
    if value == "":
        raise ValueError(f"missing {key}")
    return value


def _optional_query_value(query: Dict[str, list[str]], key: str) -> str:
    return query.get(key, [""])[0]


def get_persisted_thumbnail_bytes(shipment_id: str, file_path: str) -> bytes | None:
    return ShipmentDatabase(resolve_ship_db_file()).get_thumbnail_bytes(shipment_id, file_path)


def save_persisted_thumbnail_bytes(shipment_id: str, file_path: str, thumbnail: bytes) -> bool:
    try:
        return ShipmentDatabase(resolve_ship_db_file()).save_thumbnail_bytes(shipment_id, file_path, thumbnail)
    except Exception as persistence_error:
        print(f"thumbnail persistence skipped: {persistence_error}", file=sys.stderr)
        return False


def watch_parent_process(server: BaseServer, parent_pid: int, interval: float = 1.0) -> None:
    while True:
        if not parent_process_exists(parent_pid):
            server.shutdown()
            return
        time.sleep(interval)


def parent_process_exists(parent_pid: int) -> bool:
    if sys.platform == "win32":
        return windows_process_exists(parent_pid)
    try:
        os.kill(parent_pid, 0)
    except OSError:
        return False
    return True


def windows_process_exists(parent_pid: int) -> bool:
    access_denied = 5
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        return ctypes.get_last_error() == access_denied
    try:
        return kernel32.WaitForSingleObject(handle, 0) != wait_object_0
    finally:
        kernel32.CloseHandle(handle)


def start_parent_watchdog(server: BaseServer, parent_pid: int | None) -> threading.Thread | None:
    if parent_pid is None:
        return None
    thread = threading.Thread(target=watch_parent_process, args=(server, parent_pid), daemon=True)
    thread.start()
    return thread


def main(argv: Sequence[str] | None = None) -> None:
    parent_pid = parse_parent_pid(argv)
    server = ThreadingHTTPServer((MANAGER_HOST, MANAGER_PORT), ManagerHandler)
    start_parent_watchdog(server, parent_pid)
    print(f"ship manager backend listening on http://{MANAGER_HOST}:{MANAGER_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
