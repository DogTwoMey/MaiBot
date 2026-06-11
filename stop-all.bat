@echo off
chcp 65001 >nul 2>&1
setlocal

:: ============================================================
:: stop-all.bat - 停止 MaiBot 全套组件 + 本地服务
:: ============================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 一键停止                     ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Step 1: 停止 MaiBot 组件
echo [1/2] 停止 MaiBot 组件...
echo ─────────────────────────────────────────────

if not exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    echo [WARNING] .venv 不存在，跳过 MaiBot 组件停止。
    goto stop_services
)

"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" stop
echo.

:stop_services
:: Step 2: 停止本地依赖服务
echo [2/2] 停止本地依赖服务...
echo ─────────────────────────────────────────────

if not exist "%REPO_ROOT%scripts\start_services.py" (
    echo [WARNING] start_services.py 不存在，跳过服务停止。
    goto done
)

"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\start_services.py" stop
echo.

:done
echo.
echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 已全部停止                   ║
echo ╚══════════════════════════════════════════════╝
echo.
pause
