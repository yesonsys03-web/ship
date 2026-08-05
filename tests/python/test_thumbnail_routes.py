from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ship_common.shipment_db import ShipmentDatabase
from ship_manager import server as manager_server
from ship_sender import server as sender_server


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize(
    ("server_module", "handler_class_name"),
    [
        (sender_server, "SenderHandler"),
        (manager_server, "ManagerHandler"),
    ],
)
def test_thumbnail_route_returns_png(monkeypatch: pytest.MonkeyPatch, server_module, handler_class_name: str) -> None:
    handler_class = getattr(server_module, handler_class_name)
    handler = object.__new__(handler_class)
    handler.path = "/thumbnail?source_path=/source&file_path=cut.mov"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)

    sent = {"bytes": None, "content_type": None, "status": None, "json": None}

    def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        sent["bytes"] = body
        sent["content_type"] = content_type
        sent["status"] = status

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    monkeypatch.setattr(server_module, "get_thumbnail_bytes", lambda source_path, file_path: b"png-bytes")
    monkeypatch.setattr(server_module, "get_persisted_thumbnail_bytes", lambda shipment_id, file_path: None)
    monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
    monkeypatch.setattr(handler_class, "_send_json", fake_send_json)

    handler_class.do_GET(handler)

    assert sent["bytes"] == b"png-bytes"
    assert sent["content_type"] == "image/png"
    assert sent["status"] == 200
    assert sent["json"] is None


def test_sender_thumbnail_route_uses_design_placeholder_without_source_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_class = sender_server.SenderHandler
    handler = object.__new__(handler_class)
    handler.path = "/thumbnail?shipment_id=legacy-1&file_path=poster.psd"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)

    sent = {"bytes": None, "content_type": None, "status": None, "json": None}

    def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        sent["bytes"] = body
        sent["content_type"] = content_type
        sent["status"] = status

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    monkeypatch.setattr(sender_server, "get_persisted_thumbnail_bytes", lambda shipment_id, file_path: None)
    monkeypatch.setattr(sender_server, "get_design_placeholder_thumbnail_bytes", lambda file_path: PNG_SIGNATURE + b"placeholder")
    monkeypatch.setattr(sender_server, "get_thumbnail_bytes", lambda source_path, file_path: (_ for _ in ()).throw(AssertionError("source thumbnail should not run without source_path")))
    monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
    monkeypatch.setattr(handler_class, "_send_json", fake_send_json)

    handler_class.do_GET(handler)

    assert sent["bytes"] == PNG_SIGNATURE + b"placeholder"
    assert sent["content_type"] == "image/png"
    assert sent["status"] == 200
    assert sent["json"] is None


def test_sender_thumbnail_route_rejects_invalid_design_file_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_class = sender_server.SenderHandler
    handler = object.__new__(handler_class)
    handler.path = "/thumbnail?source_path=/source&file_path=../poster.psd"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)

    sent = {"bytes": None, "content_type": None, "status": None, "json": None}

    def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        sent["bytes"] = body
        sent["content_type"] = content_type
        sent["status"] = status

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    def reject_thumbnail(source_path: str, file_path: str) -> bytes:
        raise ValueError("invalid file path")

    def unexpected_placeholder(file_path: str) -> bytes:
        raise AssertionError("invalid design paths must not become placeholders")

    monkeypatch.setattr(sender_server, "get_persisted_thumbnail_bytes", lambda shipment_id, file_path: None)
    monkeypatch.setattr(sender_server, "get_thumbnail_bytes", reject_thumbnail)
    monkeypatch.setattr(sender_server, "get_design_placeholder_thumbnail_bytes", unexpected_placeholder)
    monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
    monkeypatch.setattr(handler_class, "_send_json", fake_send_json)

    handler_class.do_GET(handler)

    assert sent["bytes"] is None
    assert sent["json"] == ({"error": "invalid file path"}, 404)


def test_sender_thumbnail_route_uses_design_placeholder_after_source_generation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_class = sender_server.SenderHandler
    handler = object.__new__(handler_class)
    handler.path = "/thumbnail?source_path=/source&file_path=poster.psb"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)

    sent = {"bytes": None, "content_type": None, "status": None, "json": None}

    def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        sent["bytes"] = body
        sent["content_type"] = content_type
        sent["status"] = status

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    def fail_thumbnail(source_path: str, file_path: str) -> bytes:
        raise RuntimeError("quick look failed")

    monkeypatch.setattr(sender_server, "get_persisted_thumbnail_bytes", lambda shipment_id, file_path: None)
    monkeypatch.setattr(sender_server, "get_thumbnail_bytes", fail_thumbnail)
    monkeypatch.setattr(sender_server, "get_design_placeholder_thumbnail_bytes", lambda file_path: PNG_SIGNATURE + b"placeholder")
    monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
    monkeypatch.setattr(handler_class, "_send_json", fake_send_json)

    handler_class.do_GET(handler)

    assert sent["bytes"] == PNG_SIGNATURE + b"placeholder"
    assert sent["content_type"] == "image/png"
    assert sent["status"] == 200
    assert sent["json"] is None


@pytest.mark.parametrize(
    ("server_module", "handler_class_name"),
    [
        (sender_server, "SenderHandler"),
        (manager_server, "ManagerHandler"),
    ],
)
def test_thumbnail_route_backfills_generated_png_after_persisted_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_module,
    handler_class_name: str,
) -> None:
    handler_class = getattr(server_module, handler_class_name)
    db_file = tmp_path / "shipments.sqlite3"
    generated_png = PNG_SIGNATURE + b"generated-fallback"

    def run_thumbnail_request(path: str) -> dict:
        handler = object.__new__(handler_class)
        handler.path = path
        handler.headers = SimpleNamespace(get=lambda key, default=None: default)
        handler.client_address = ("127.0.0.1", 12345)
        sent = {"bytes": None, "content_type": None, "status": None, "json": None}

        def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
            sent["bytes"] = body
            sent["content_type"] = content_type
            sent["status"] = status

        def fake_send_json(self, payload, status: int = 200) -> None:
            sent["json"] = (payload, status)

        monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
        monkeypatch.setattr(handler_class, "_send_json", fake_send_json)
        handler_class.do_GET(handler)
        return sent

    monkeypatch.setattr(server_module, "resolve_ship_db_file", lambda: db_file)
    monkeypatch.setattr(server_module, "get_thumbnail_bytes", lambda source_path, file_path: generated_png)

    first_response = run_thumbnail_request(
        "/thumbnail?shipment_id=legacy-1&source_path=/legacy-source&file_path=poster.jpg"
    )

    assert first_response["bytes"] == generated_png
    assert first_response["content_type"] == "image/png"
    assert first_response["status"] == 200
    assert first_response["json"] is None
    assert ShipmentDatabase(db_file).get_thumbnail_bytes("legacy-1", "poster.jpg") == generated_png

    def unexpected_source_thumbnail(source_path: str, file_path: str) -> bytes:
        raise AssertionError("source fallback should not run after route backfills DB thumbnail")

    monkeypatch.setattr(server_module, "get_thumbnail_bytes", unexpected_source_thumbnail)

    second_response = run_thumbnail_request("/thumbnail?shipment_id=legacy-1&file_path=poster.jpg")

    assert second_response["bytes"] == generated_png
    assert second_response["content_type"] == "image/png"
    assert second_response["status"] == 200
    assert second_response["json"] is None


@pytest.mark.parametrize(
    ("server_module", "handler_class_name"),
    [
        (sender_server, "SenderHandler"),
        (manager_server, "ManagerHandler"),
    ],
)
def test_thumbnail_route_prefers_persisted_png_without_source_path(
    monkeypatch: pytest.MonkeyPatch,
    server_module,
    handler_class_name: str,
) -> None:
    handler_class = getattr(server_module, handler_class_name)
    handler = object.__new__(handler_class)
    handler.path = "/thumbnail?shipment_id=shipment-1&file_path=poster.jpg"
    handler.headers = SimpleNamespace(get=lambda key, default=None: default)
    handler.client_address = ("127.0.0.1", 12345)

    sent = {"bytes": None, "content_type": None, "status": None, "json": None}

    def fake_send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        sent["bytes"] = body
        sent["content_type"] = content_type
        sent["status"] = status

    def fake_send_json(self, payload, status: int = 200) -> None:
        sent["json"] = (payload, status)

    def unexpected_source_thumbnail(source_path: str, file_path: str) -> bytes:
        raise AssertionError("source fallback should not run when DB thumbnail exists")

    monkeypatch.setattr(server_module, "get_persisted_thumbnail_bytes", lambda shipment_id, file_path: b"persisted-png")
    monkeypatch.setattr(server_module, "get_thumbnail_bytes", unexpected_source_thumbnail)
    monkeypatch.setattr(handler_class, "_send_bytes", fake_send_bytes)
    monkeypatch.setattr(handler_class, "_send_json", fake_send_json)

    handler_class.do_GET(handler)

    assert sent["bytes"] == b"persisted-png"
    assert sent["content_type"] == "image/png"
    assert sent["status"] == 200
    assert sent["json"] is None
