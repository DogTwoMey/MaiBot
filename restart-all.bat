@echo off
chcp 65001 >nul 2>&1
setlocal

:: ============================================================
:: restart-all.bat - 重启 MaiBot 全套组件 + 本地服务
:: ============================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 一键重启                     ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Step 1: 停止所有
echo [1/3] 停止 MaiBot 组件...
echo ─────────────────────────────────────────────

if exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    "%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" stop
) else (
    echo [WARNING] .venv 不存在，跳过组件停止。
)
echo.

:: Step 2: 重启本地服务（先停后启）
echo [2/3] 重启本地依赖服务...
echo ─────────────────────────────────────────────

if exist "%REPO_ROOT%scripts\start_services.py" (
    "%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\start_services.py" stop
    echo.
    "%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\start_services.py" start
) else (
    echo [WARNING] start_services.py 不存在，跳过服务重启。
)
echo.

:: Step 3: 启动 MaiBot 组件
echo [3/3] 启动 MaiBot 组件...
echo ─────────────────────────────────────────────

if exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    :: 等待 2 秒让服务完全就绪
    timeout /t 2 /nobreak >nul
    "%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" start
) else (
    echo [ERROR] .venv 不存在，无法启动 MaiBot。
    pause
    exit /b 1
)

echo.
echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 已全部重启                   ║
echo ╚══════════════════════════════════════════════╝
echo.
pause
