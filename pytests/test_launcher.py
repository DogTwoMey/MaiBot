from __future__ import annotations

import psutil

from scripts import launcher


class _FakeProcess:
    def __init__(
        self,
        *,
        name: str,
        children: list[_FakeProcess] | None = None,
        running: bool = True,
        status: str = psutil.STATUS_RUNNING,
    ) -> None:
        self._name = name
        self._children = children or []
        self._running = running
        self._status = status

    def name(self) -> str:
        return self._name

    def children(self, recursive: bool = False) -> list[_FakeProcess]:
        del recursive
        return self._children

    def is_running(self) -> bool:
        return self._running

    def status(self) -> str:
        return self._status


def test_visible_cmd_without_workload_is_not_running(monkeypatch) -> None:
    cmd = _FakeProcess(name="cmd.exe", children=[_FakeProcess(name="conhost.exe")])
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: cmd)

    assert launcher.is_component_running(1234) is False


def test_visible_cmd_with_python_child_is_running(monkeypatch) -> None:
    cmd = _FakeProcess(name="cmd.exe", children=[_FakeProcess(name="python.exe")])
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: cmd)

    assert launcher.is_component_running(1234) is True


def test_hidden_direct_process_is_running(monkeypatch) -> None:
    python = _FakeProcess(name="python.exe")
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: python)

    assert launcher.is_component_running(1234) is True


def test_all_targets_only_include_external_processes() -> None:
    assert launcher.parse_targets(["all"]) == ["napcat", "bot"]
