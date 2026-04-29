"""Unified launcher for MaiBot + Adapter + NapCatQQ.

Default behavior: open three separate cmd windows (bot / adapter / napcat),
each showing its own live log. Flags control which components are hidden
(run in background with output redirected to log files).

Commands:
    python scripts/launcher.py start              # start all (three visible windows)
    python scripts/launcher.py start --hide napcat
    python scripts/launcher.py start --hide napcat --hide adapter
    python scripts/launcher.py start bot          # start only bot
    python scripts/launcher.py stop               # stop all
    python scripts/launcher.py stop adapter
    python scripts/launcher.py status
    python scripts/launcher.py restart [target]
    python scripts/launcher.py logs <name> [--tail N]

Config: scripts/launcher.toml (falls back to launcher.toml.example).
Requires: Python 3.11+ (tomllib) and psutil.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    print("[launcher] WARNING: this launcher targets Windows. Non-Windows behavior is limited.",
          file=sys.stderr)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    import psutil
except ModuleNotFoundError:
    print("[launcher] psutil is required. Install: pip install psutil", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "scripts" / "launcher.toml"
CONFIG_EXAMPLE = REPO_ROOT / "scripts" / "launcher.toml.example"

# Windows creation flags
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------------------
# Config

def load_config() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE
    if not path.exists():
        raise SystemExit(f"[launcher] neither {CONFIG_PATH} nor {CONFIG_EXAMPLE} found")
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve(cfg: dict[str, Any], base: str) -> Path:
    raw = cfg["paths"][base]
    p = Path(raw)
    return (p if p.is_absolute() else (REPO_ROOT / p)).resolve()


# ---------------------------------------------------------------------------
# PID file management

def state_dir(cfg: dict[str, Any]) -> Path:
    raw = cfg.get("logs", {}).get("dir", "runtime/launcher-logs")
    d = Path(raw)
    d = (d if d.is_absolute() else (REPO_ROOT / d)).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_file(cfg: dict[str, Any], name: str) -> Path:
    return state_dir(cfg) / f"{name}.pid"


def log_file(cfg: dict[str, Any], name: str) -> Path:
    return state_dir(cfg) / f"{name}.log"


def write_pid(cfg: dict[str, Any], name: str, pid: int) -> None:
    pid_file(cfg, name).write_text(str(pid), encoding="utf-8")


def read_pid(cfg: dict[str, Any], name: str) -> int | None:
    p = pid_file(cfg, name)
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def clear_pid(cfg: dict[str, Any], name: str) -> None:
    p = pid_file(cfg, name)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Process helpers

def is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def kill_tree(pid: int, timeout: float = 5.0) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    try:
        parent.terminate()
    except psutil.NoSuchProcess:
        pass
    gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def probe_port(port: int, timeout: float) -> bool:
    if port <= 0:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return True
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Spawning

def spawn(cfg: dict[str, Any], name: str, argv: list[str], cwd: Path, hidden: bool) -> int:
    """Spawn a component. Visible = new console window; hidden = detached + log file."""
    if hidden:
        log = open(log_file(cfg, name), "ab", buffering=0)
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0,
            close_fds=True,
        )
        return proc.pid
    if sys.platform == "win32":
        # Wrap with cmd /k so window stays open after the child exits (for reading the error).
        title = cfg.get(name, {}).get("title", name)
        # Build: cmd /k "title X && <argv...>"
        quoted = " ".join(_quote_win(a) for a in argv)
        cmd_line = f'cmd /k "title {title} && {quoted}"'
        proc = subprocess.Popen(
            cmd_line,
            cwd=str(cwd),
            creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return proc.pid
    # Non-Windows fallback: just run in foreground of caller's terminal.
    proc = subprocess.Popen(argv, cwd=str(cwd))
    return proc.pid


def _quote_win(arg: str) -> str:
    if not arg or any(c in arg for c in ' \t"'):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


# ---------------------------------------------------------------------------
# Component start functions

def start_napcat(cfg: dict[str, Any], hidden: bool) -> int:
    cwd = resolve(cfg, "napcat")
    launcher_bat = cfg["napcat"].get("launcher", "launcher-win10.bat")
    bat_path = cwd / launcher_bat
    if not bat_path.exists():
        raise SystemExit(f"[launcher] NapCat launcher not found: {bat_path}")
    # Use cmd /c for bat so path resolution works reliably.
    argv = ["cmd", "/c", launcher_bat]
    return spawn(cfg, "napcat", argv, cwd, hidden)


def _resolve_argv(cfg: dict[str, Any], section: str, default: list[str]) -> list[str]:
    argv = cfg.get(section, {}).get("argv", default)
    if not isinstance(argv, list) or not argv:
        raise SystemExit(f"[launcher] {section}.argv must be a non-empty list in launcher.toml")
    return [str(x) for x in argv]


def start_adapter(cfg: dict[str, Any], hidden: bool) -> int:
    cwd = resolve(cfg, "adapter")
    argv = _resolve_argv(cfg, "adapter", ["uv", "run", "python", "main.py"])
    return spawn(cfg, "adapter", argv, cwd, hidden)


def start_bot(cfg: dict[str, Any], hidden: bool) -> int:
    cwd = resolve(cfg, "bot_root")
    argv = _resolve_argv(cfg, "bot", ["uv", "run", "python", "bot.py"])
    return spawn(cfg, "bot", argv, cwd, hidden)


STARTERS = {
    "napcat": start_napcat,
    "adapter": start_adapter,
    "bot": start_bot,
}


# ---------------------------------------------------------------------------
# Commands

def cmd_start(cfg: dict[str, Any], targets: list[str], hidden_set: set[str]) -> int:
    order = cfg.get("startup", {}).get("order", ["napcat", "adapter", "bot"])
    to_start = [t for t in order if t in targets]
    rc = 0
    for name in to_start:
        existing = read_pid(cfg, name)
        if is_alive(existing):
            print(f"[launcher] {name} already running (pid={existing})")
            continue
        hidden = name in hidden_set
        print(f"[launcher] starting {name} ({'hidden' if hidden else 'window'})...")
        pid = STARTERS[name](cfg, hidden)
        write_pid(cfg, name, pid)
        # Readiness probe
        section = cfg.get(name, {})
        port = int(section.get("ready_port", 0) or 0)
        timeout = float(section.get("ready_timeout", 0) or 0)
        if port > 0 and timeout > 0:
            print(f"[launcher]   waiting for {name} on :{port} (up to {timeout:.0f}s)...")
            if not probe_port(port, timeout):
                print(f"[launcher]   WARN: {name} port {port} not ready within {timeout:.0f}s — continuing")
                rc = max(rc, 1)
            else:
                print(f"[launcher]   {name} ready")
    return rc


def cmd_stop(cfg: dict[str, Any], targets: list[str]) -> int:
    # Reverse of startup order.
    order = cfg.get("startup", {}).get("order", ["napcat", "adapter", "bot"])
    for name in reversed(order):
        if name not in targets:
            continue
        pid = read_pid(cfg, name)
        if not is_alive(pid):
            print(f"[launcher] {name}: not running")
            clear_pid(cfg, name)
            continue
        print(f"[launcher] stopping {name} (pid={pid})...")
        kill_tree(pid)  # type: ignore[arg-type]
        clear_pid(cfg, name)
    return 0


def cmd_status(cfg: dict[str, Any]) -> int:
    order = cfg.get("startup", {}).get("order", ["napcat", "adapter", "bot"])
    print(f"{'component':<10} {'status':<10} {'pid':<8}  detail")
    for name in order:
        pid = read_pid(cfg, name)
        alive = is_alive(pid)
        state = "running" if alive else ("stale" if pid else "stopped")
        detail = ""
        if alive:
            try:
                p = psutil.Process(pid)  # type: ignore[arg-type]
                detail = f"cmd={p.name()}  started={time.strftime('%H:%M:%S', time.localtime(p.create_time()))}"
            except psutil.NoSuchProcess:
                pass
        print(f"{name:<10} {state:<10} {str(pid or '-'):<8}  {detail}")
    return 0


def cmd_logs(cfg: dict[str, Any], name: str, tail: int) -> int:
    log = log_file(cfg, name)
    if not log.exists():
        print(f"[launcher] no log file for {name} at {log} (logs only exist for hidden runs)")
        return 1
    # Windows-friendly tail.
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        print(f"[launcher] failed to read {log}: {e}")
        return 1
    for line in lines[-tail:]:
        print(line)
    return 0


# ---------------------------------------------------------------------------
# CLI

def parse_targets(raw: list[str]) -> list[str]:
    if not raw or raw == ["all"]:
        return ["napcat", "adapter", "bot"]
    unknown = [t for t in raw if t not in STARTERS]
    if unknown:
        raise SystemExit(f"[launcher] unknown target(s): {unknown}. Valid: {list(STARTERS)}")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified launcher for MaiBot stack.")
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("start", help="Start components")
    sp.add_argument("targets", nargs="*", default=["all"],
                    help="Any of: all, napcat, adapter, bot (default: all)")
    sp.add_argument("--hide", action="append", default=[], choices=list(STARTERS),
                    help="Run the named component hidden (no window). Repeatable.")

    st = sub.add_parser("stop", help="Stop components")
    st.add_argument("targets", nargs="*", default=["all"])

    sub.add_parser("status", help="Show component status")

    rs = sub.add_parser("restart", help="Stop then start")
    rs.add_argument("targets", nargs="*", default=["all"])
    rs.add_argument("--hide", action="append", default=[], choices=list(STARTERS))

    lg = sub.add_parser("logs", help="Tail log file (hidden-mode runs only)")
    lg.add_argument("name", choices=list(STARTERS))
    lg.add_argument("--tail", type=int, default=100)

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "start":
        return cmd_start(cfg, parse_targets(args.targets), set(args.hide))
    if args.command == "stop":
        return cmd_stop(cfg, parse_targets(args.targets))
    if args.command == "status":
        return cmd_status(cfg)
    if args.command == "restart":
        targets = parse_targets(args.targets)
        cmd_stop(cfg, targets)
        time.sleep(1.5)
        return cmd_start(cfg, targets, set(args.hide))
    if args.command == "logs":
        return cmd_logs(cfg, args.name, args.tail)
    return 2


if __name__ == "__main__":
    sys.exit(main())
