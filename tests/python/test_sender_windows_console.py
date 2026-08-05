from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
SENDER_TAURI_MAIN = REPO_ROOT / "apps" / "sender" / "src-tauri" / "src" / "main.rs"
WINDOWS_BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_apps_windows.ps1"


def test_sender_tauri_release_uses_windows_gui_subsystem() -> None:
    main_source = SENDER_TAURI_MAIN.read_text(encoding="utf-8")

    assert main_source.startswith('#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]')


def test_windows_sidecar_build_uses_and_verifies_gui_subsystem() -> None:
    build_source = WINDOWS_BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '"--windowed"' in build_source
    assert "Assert-WindowsGuiSubsystem $tauriBinary" in build_source
