from ship_manager.config import MANAGER_ALLOWED_ORIGINS
from ship_sender.config import SENDER_ALLOWED_ORIGINS


def test_manager_default_allowed_origins_include_tauri_localhost() -> None:
    assert MANAGER_ALLOWED_ORIGINS == (
        "http://127.0.0.1:1430",
        "http://tauri.localhost",
        "tauri://localhost",
    )


def test_sender_default_allowed_origins_include_tauri_localhost() -> None:
    assert SENDER_ALLOWED_ORIGINS == (
        "http://127.0.0.1:1420",
        "http://tauri.localhost",
        "tauri://localhost",
    )
