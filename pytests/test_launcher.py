from __future__ import annotations

from io import BytesIO
from itertools import count
from types import SimpleNamespace
from urllib.parse import urlsplit

import json

import psutil
import pytest

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


def test_start_existing_snowluma_restores_account_before_bot(monkeypatch) -> None:
    cfg = {"startup": {"order": ["snowluma", "bot"]}}
    calls = []
    monkeypatch.setattr(launcher, "read_pid", lambda cfg, name: 1234 if name == "snowluma" else None)
    monkeypatch.setattr(launcher, "is_component_running", lambda pid: pid == 1234)
    monkeypatch.setattr(launcher, "find_snowluma_pid", lambda cfg: 1234)
    monkeypatch.setattr(launcher, "ensure_snowluma_account", lambda cfg: calls.append("account"))
    monkeypatch.setattr(launcher, "clear_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "write_pid", lambda *args: None)
    monkeypatch.setitem(launcher.STARTERS, "snowluma", lambda *args: calls.append("snowluma") or 1234)
    monkeypatch.setitem(launcher.STARTERS, "bot", lambda *args: calls.append("bot") or 5678)

    assert launcher.cmd_start(cfg, launcher.parse_targets(["all"], cfg), set()) == 0
    assert calls == ["account", "bot"]


@pytest.mark.parametrize("mode", ["available", "online", "missing", "load-failed", "login-failed"])
def test_snowluma_account_recovery(monkeypatch, tmp_path, mode) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "bot_config.toml").write_text('[bot]\nqq_account = "123456"\n', encoding="utf-8")
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"password":"test-password"}', encoding="utf-8")
    cfg = {
        "paths": {"bot_root": str(tmp_path)},
        "snowluma": {"credentials_file": str(credentials), "ready_timeout": 1},
    }
    loaded = mode == "online"
    calls = []

    def respond(req, timeout):
        nonlocal loaded
        assert timeout == 1
        path = urlsplit(req.full_url).path
        calls.append(path)
        if path == "/api/login":
            assert json.loads(req.data) == {"password": "test-password"}
            reply = {"success": mode != "login-failed", "token": "test-token"}
        else:
            assert req.get_header("Authorization") == "Bearer test-token"
            if path == "/api/processes":
                reply = {"list": [
                    {"pid": 11, "uin": "654321", "status": "online", "connected": True, "loggedIn": True},
                    {"pid": 22, "uin": "123456" if loaded else "0", "status": "online" if loaded else "available",
                     "connected": loaded, "loggedIn": loaded},
                ]}
            elif path == "/api/processes/22/probe-login":
                reply = {"info": None if mode == "missing" else {"uin": "123456"}}
            elif path == "/api/processes/22/load":
                loaded = True
                reply = {"success": mode != "load-failed"}
            else:
                assert path == "/api/logout"
                reply = {"success": True}
        return BytesIO(json.dumps(reply).encode())

    ticks = count()
    monkeypatch.setattr(launcher, "build_opener", lambda *args: SimpleNamespace(open=respond))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(ticks) / 10)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    if mode in ("missing", "load-failed", "login-failed"):
        with pytest.raises(SystemExit, match="not online|failed to load|login failed"):
            launcher.ensure_snowluma_account(cfg)
    else:
        launcher.ensure_snowluma_account(cfg)
        launcher.ensure_snowluma_account(cfg)
        assert calls.count("/api/processes/22/load") == (1 if mode == "available" else 0)
    assert "/api/processes/11/load" not in calls
    if mode != "login-failed":
        assert calls[-1] == "/api/logout"


def test_find_snowluma_matches_distribution_and_entrypoint(monkeypatch, tmp_path) -> None:
    node = str(tmp_path / "node.exe")
    processes = [
        SimpleNamespace(pid=1, info={"exe": node, "cmdline": [node, "unrelated.mjs"]}),
        SimpleNamespace(pid=2, info={"exe": node, "cmdline": [node, str(tmp_path / "index.mjs")]}),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)
    monkeypatch.setattr(launcher, "is_component_running", lambda pid: True)
    assert launcher.find_snowluma_pid({"paths": {"snowluma": str(tmp_path)}}) == 2


@pytest.mark.parametrize("ready", [True, False])
def test_start_missing_snowluma_gates_bot(monkeypatch, ready) -> None:
    cfg = {"startup": {"order": ["snowluma", "bot"]}, "snowluma": {"ready_port": 5099, "ready_timeout": 1}}
    calls = []
    monkeypatch.setattr(launcher, "read_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "find_snowluma_pid", lambda cfg: None)
    monkeypatch.setattr(launcher, "is_component_running", lambda pid: False)
    monkeypatch.setattr(launcher, "is_alive", lambda pid: True)
    monkeypatch.setattr(launcher, "clear_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "write_pid", lambda *args: None)
    monkeypatch.setattr(launcher, "probe_port", lambda *args, **kwargs: ready)
    monkeypatch.setattr(launcher, "ensure_snowluma_account", lambda cfg: calls.append("account"))
    monkeypatch.setitem(launcher.STARTERS, "snowluma", lambda *args: calls.append("snowluma") or 1234)
    monkeypatch.setitem(launcher.STARTERS, "bot", lambda *args: calls.append("bot") or 5678)

    assert launcher.cmd_start(cfg, ["snowluma", "bot"], set()) == (0 if ready else 1)
    assert calls == (["snowluma", "account", "bot"] if ready else ["snowluma"])


@pytest.mark.parametrize("online", [True, False])
def test_bot_only_start_requires_configured_snowluma_account(monkeypatch, tmp_path, online) -> None:
    cfg = {"paths": {"bot_root": str(tmp_path)}, "bot": {"argv": ["python", "bot.py"]}}
    calls = []

    def ensure_account(cfg):
        calls.append("account")
        if not online:
            raise SystemExit("QQ not online")

    monkeypatch.setattr(launcher, "ensure_snowluma_account", ensure_account)
    monkeypatch.setattr(launcher, "spawn", lambda *args: calls.append("bot") or 5678)
    if online:
        assert launcher.start_bot(cfg, hidden=True) == 5678
        assert calls == ["account", "bot"]
    else:
        with pytest.raises(SystemExit, match="QQ not online"):
            launcher.start_bot(cfg, hidden=True)
        assert calls == ["account"]
