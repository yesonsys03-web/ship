from __future__ import annotations

from types import ModuleType

import pytest

from ship_manager import server as manager_server
from ship_sender import server as sender_server


class RecordingServer:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.parametrize("server_module", [sender_server, manager_server])
def test_parse_parent_pid_is_optional(server_module: ModuleType) -> None:
    assert server_module.parse_parent_pid([]) is None


@pytest.mark.parametrize("server_module", [sender_server, manager_server])
def test_parse_parent_pid_reads_argument(server_module: ModuleType) -> None:
    assert server_module.parse_parent_pid(["--parent-pid", "12345"]) == 12345


@pytest.mark.parametrize("server_module", [sender_server, manager_server])
def test_watchdog_shuts_down_when_parent_pid_is_missing(monkeypatch: pytest.MonkeyPatch, server_module: ModuleType) -> None:
    server = RecordingServer()

    monkeypatch.setattr(server_module, "parent_process_exists", lambda parent_pid: False)

    server_module.watch_parent_process(server, 12345, interval=0)

    assert server.shutdown_calls == 1


@pytest.mark.parametrize("server_module", [sender_server, manager_server])
def test_watchdog_keeps_running_when_parent_pid_exists_after_reparent(monkeypatch: pytest.MonkeyPatch, server_module: ModuleType) -> None:
    server = RecordingServer()
    parent_pids = iter([12345, 1])

    monkeypatch.setattr(server_module.os, "getppid", lambda: next(parent_pids))
    monkeypatch.setattr(server_module, "parent_process_exists", lambda parent_pid: True)
    monkeypatch.setattr(server_module.time, "sleep", lambda interval: (_ for _ in ()).throw(StopIteration))

    with pytest.raises(StopIteration):
        server_module.watch_parent_process(server, 12345, interval=0)

    assert server.shutdown_calls == 0


@pytest.mark.parametrize("server_module", [sender_server, manager_server])
def test_parent_process_exists_uses_windows_handle_check(monkeypatch: pytest.MonkeyPatch, server_module: ModuleType) -> None:
    monkeypatch.setattr(server_module.sys, "platform", "win32")
    monkeypatch.setattr(server_module, "windows_process_exists", lambda parent_pid: parent_pid == 12345)

    assert server_module.parent_process_exists(12345) is True
    assert server_module.parent_process_exists(54321) is False
