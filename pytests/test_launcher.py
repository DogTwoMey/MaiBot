from __future__ import annotations

from types import SimpleNamespace

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


def test_snowluma_startup_order_and_explicit_rollback_target(monkeypatch, tmp_path) -> None:
    cfg = {"startup": {"order": ["snowluma", "bot"]}, "paths": {"snowluma": str(tmp_path)}}
    assert launcher.parse_targets(["all"], cfg) == ["snowluma", "bot"]
    assert launcher.parse_targets(["napcat"], cfg) == ["napcat"]
    (tmp_path / "node.exe").touch()
    (tmp_path / "index.mjs").touch()
    calls = []
    monkeypatch.setattr(launcher, "spawn", lambda *args: calls.append(args) or 1234)
    assert launcher.start_snowluma(cfg, hidden=True) == 1234
    assert calls[0][1:4] == ("snowluma", [str(tmp_path / "node.exe"), str(tmp_path / "index.mjs")], tmp_path)
    monkeypatch.setattr(launcher, "read_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "clear_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "write_pid", lambda *args: None)
    monkeypatch.setitem(launcher.STARTERS, "napcat", lambda *args: calls.append("napcat") or 1234)
    assert launcher.cmd_start(cfg, ["napcat"], set()) == 0
    assert calls[-1] == "napcat"
    monkeypatch.setattr(launcher, "read_pid", lambda cfg, name: 1234 if name == "bot" else 5678)
    monkeypatch.setattr(launcher, "is_alive", lambda pid: True)
    monkeypatch.setattr(launcher, "kill_tree", lambda pid: calls.append(pid))
    assert launcher.cmd_stop(cfg, ["bot"]) == 0
    assert calls[-1] == 1234 and 5678 not in calls


def test_spawn_enables_utf8_for_child_process(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_popen(*args, **kwargs):
        del args
        captured_kwargs.update(kwargs)
        return SimpleNamespace(pid=4321)

    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    assert launcher.spawn({}, "bot", ["python", "bot.py"], launcher.REPO_ROOT, hidden=False) == 4321
    child_env = captured_kwargs["env"]
    assert isinstance(child_env, dict)
    assert child_env["PYTHONUTF8"] == "1"
    assert child_env["PYTHONIOENCODING"] == "utf-8"
