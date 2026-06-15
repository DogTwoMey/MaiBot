"""基于 scripts/services.json 启动本地依赖服务。

支持的服务类型：
- docker: 通过 docker run 启动容器
- process: 通过命令行启动本地进程

容错策略：服务启动失败时输出 WARNING 并继续，不阻塞后续流程。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "scripts" / "services.json"


def load_config() -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        print(f"[services] WARNING: 配置文件不存在: {CONFIG_PATH}")
        return []
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("services", [])


def is_docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_container_running(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "true" in result.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def container_exists(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def start_docker_service(service: dict[str, Any]) -> bool:
    """启动 Docker 容器服务。"""
    container_name = service.get("container_name", "")
    image = service.get("image", "")
    name = service.get("name", container_name)

    if not container_name or not image:
        print(f"  [services] WARNING: 服务 '{name}' 缺少 container_name 或 image 配置，跳过。")
        return False

    if is_container_running(container_name):
        print(f"  [services] '{name}' 已在运行中，跳过启动。")
        return True

    # 容器存在但已停止，直接 start
    if container_exists(container_name):
        print(f"  [services] '{name}' 容器已存在但未运行，正在启动...")
        try:
            result = subprocess.run(
                ["docker", "start", container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                print(f"  [services] '{name}' 启动成功。")
                return True
            print(f"  [services] WARNING: '{name}' 启动失败: {result.stderr.strip()}")
            return False
        except subprocess.TimeoutExpired:
            print(f"  [services] WARNING: '{name}' 启动超时。")
            return False

    # 容器不存在，docker run 创建并启动
    print(f"  [services] '{name}' 容器不存在，正在创建并启动...")
    cmd = ["docker", "run", "-d", "--name", container_name]

    for port_mapping in service.get("ports", []):
        cmd.extend(["-p", port_mapping])

    for key, value in service.get("environment", {}).items():
        cmd.extend(["-e", f"{key}={value}"])

    for volume in service.get("volumes", []):
        cmd.extend(["-v", volume])

    cmd.append(image)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            print(f"  [services] '{name}' 创建并启动成功。")
            return True
        print(f"  [services] WARNING: '{name}' 创建失败: {result.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [services] WARNING: '{name}' 创建超时（可能正在拉取镜像）。")
        return False
    except FileNotFoundError:
        print(f"  [services] WARNING: docker 命令不可用。")
        return False


def start_process_service(service: dict[str, Any]) -> bool:
    """启动本地进程服务。"""
    name = service.get("name", "unknown")
    command = service.get("command", "")
    cwd = service.get("cwd", "")

    if not command:
        print(f"  [services] WARNING: 服务 '{name}' 缺少 command 配置，跳过。")
        return False

    work_dir = Path(cwd) if cwd else REPO_ROOT
    if not work_dir.exists():
        print(f"  [services] WARNING: 服务 '{name}' 工作目录不存在: {work_dir}，跳过。")
        return False

    print(f"  [services] 正在启动进程服务 '{name}': {command}")
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                command,
                cwd=str(work_dir),
                shell=True,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        else:
            subprocess.Popen(
                command,
                cwd=str(work_dir),
                shell=True,
                start_new_session=True,
            )
        print(f"  [services] '{name}' 进程已启动。")
        return True
    except Exception as e:
        print(f"  [services] WARNING: '{name}' 启动失败: {e}")
        return False


def health_check(service: dict[str, Any]) -> bool:
    """检查服务健康状态。"""
    check_config = service.get("health_check")
    if not check_config:
        return True

    url = check_config.get("url", "")
    timeout_sec = check_config.get("timeout_sec", 15)

    if not url:
        return True

    name = service.get("name", "unknown")
    print(f"  [services] 正在等待 '{name}' 就绪 ({url}, 超时 {timeout_sec}s)...")

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            urllib.request.urlopen(req, timeout=2)
            print(f"  [services] '{name}' 已就绪。")
            return True
        except Exception:
            time.sleep(1)

    print(f"  [services] WARNING: '{name}' 在 {timeout_sec}s 内未就绪，但不阻塞后续流程。")
    return False


def stop_docker_service(service: dict[str, Any]) -> bool:
    """停止 Docker 容器服务。"""
    container_name = service.get("container_name", "")
    name = service.get("name", container_name)

    if not container_name:
        return False

    if not is_container_running(container_name):
        print(f"  [services] '{name}' 未在运行。")
        return True

    print(f"  [services] 正在停止 '{name}'...")
    try:
        result = subprocess.run(
            ["docker", "stop", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print(f"  [services] '{name}' 已停止。")
            return True
        print(f"  [services] WARNING: '{name}' 停止失败: {result.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [services] WARNING: '{name}' 停止超时。")
        return False


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    services = load_config()

    if not services:
        print("[services] 没有配置任何服务。")
        return

    enabled_services = [s for s in services if s.get("enabled", True)]
    if not enabled_services:
        print("[services] 所有服务均已禁用。")
        return

    if action == "start":
        # Docker 服务需要 docker 可用
        docker_services = [s for s in enabled_services if s.get("type") == "docker"]
        process_services = [s for s in enabled_services if s.get("type") == "process"]

        if docker_services and not is_docker_available():
            print("[services] WARNING: Docker 不可用，将跳过所有 Docker 类型的服务。")
            docker_services = []

        print(f"[services] 准备启动 {len(docker_services) + len(process_services)} 个服务...")

        for service in docker_services:
            name = service.get("name", "unknown")
            print(f"\n[services] === {name} ({service.get('description', '')}) ===")
            if start_docker_service(service):
                health_check(service)

        for service in process_services:
            name = service.get("name", "unknown")
            print(f"\n[services] === {name} ({service.get('description', '')}) ===")
            if start_process_service(service):
                health_check(service)

    elif action == "stop":
        print(f"[services] 准备停止 {len(enabled_services)} 个服务...")
        for service in reversed(enabled_services):
            stype = service.get("type", "")
            name = service.get("name", "unknown")
            print(f"\n[services] === 停止 {name} ===")
            if stype == "docker":
                stop_docker_service(service)
            elif stype == "process":
                print(f"  [services] WARNING: 进程类型服务 '{name}' 需手动停止。")

    elif action == "status":
        print("[services] 服务状态:")
        for service in enabled_services:
            stype = service.get("type", "")
            name = service.get("name", "unknown")
            if stype == "docker":
                container_name = service.get("container_name", "")
                running = is_container_running(container_name) if container_name else False
                status = "运行中" if running else "未运行"
            else:
                status = "未知"
            print(f"  {name}: {status}")

    else:
        print(f"[services] 未知操作: {action}")
        print("  用法: start_services.py [start|stop|status]")


if __name__ == "__main__":
    main()
