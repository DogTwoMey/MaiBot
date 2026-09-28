from pathlib import Path

import os
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows 批处理测试")
@pytest.mark.parametrize(
    "has_dependencies,build_exit,has_output,expected_exit",
    [(True, 0, True, 0), (False, 0, True, 0), (True, 7, True, 7), (True, 0, False, 1)],
)
def test_restart_dashboard_build(tmp_path, has_dependencies, build_exit, has_output, expected_exit) -> None:
    # 隔离运行真实构建子程序，npm 使用桩命令，不触碰服务进程。
    script = (Path(__file__).resolve().parents[1] / "restart-all.bat").read_text(encoding="utf-8")
    helper = script[script.index("\n:build_dashboard\n") :]
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "package.json").write_text("{}", encoding="utf-8")
    (dashboard / "package-lock.json").write_text("{}", encoding="utf-8")
    if has_dependencies:
        (dashboard / "node_modules").mkdir()

    npm = (
        '@echo off\n'
        '>>"%~dp0npm-calls.txt" echo %*\n'
        'if "%1"=="ls" exit /b 0\n'
        'if "%1"=="ci" exit /b 0\n'
    )
    if has_output:
        npm += 'mkdir dist\necho built>dist\\index.html\n'
    npm += f"exit /b {build_exit}\n"
    (tmp_path / "npm.cmd").write_text(npm, encoding="utf-8", newline="\r\n")

    harness = (
        '@echo off\n'
        'chcp 65001 >nul\n'
        'setlocal EnableExtensions EnableDelayedExpansion\n'
        'set "REPO_ROOT=%~dp0"\n'
        'call :build_dashboard\n'
        'set "RESULT=!ERRORLEVEL!"\n'
        'echo(!MAIBOT_WEBUI_USE_LOCAL_DASHBOARD!>"%~dp0local-enabled.txt"\n'
        'exit /b !RESULT!\n'
    ) + helper
    (tmp_path / "test.cmd").write_text(harness, encoding="utf-8", newline="\r\n")
    env = os.environ.copy()
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    env.pop("MAIBOT_WEBUI_USE_LOCAL_DASHBOARD", None)
    result = subprocess.run(
        [env["COMSPEC"], "/d", "/c", "call test.cmd"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == expected_exit, (result.stdout, result.stderr)
    calls = (tmp_path / "npm-calls.txt").read_text().splitlines()
    assert calls == (["ls --depth=0"] if has_dependencies else ["ci --no-audit --no-fund"]) + ["run build"]
    enabled = (tmp_path / "local-enabled.txt").read_text().strip()
    assert enabled == ("1" if expected_exit == 0 else "")
