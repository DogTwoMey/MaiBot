@echo off
chcp 65001 >nul 2>&1
setlocal

:: ============================================================
:: start-all.bat - 启动本地服务 + MaiBot 全套组件
:: 双击即可运行，按顺序启动：本地服务 → NapCat → Adapter → Bot
:: ============================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 一键启动                     ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Step 1: 启动本地依赖服务
echo [1/2] 启动本地依赖服务...
echo ─────────────────────────────────────────────
call "%REPO_ROOT%start-services.bat"
echo.

:: Step 2: 启动 MaiBot 组件 (NapCat + Adapter + Bot)
echo [2/2] 启动 MaiBot 组件...
echo ─────────────────────────────────────────────

:: 检查 .venv 是否存在
if not exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    echo [ERROR] .venv 不存在，请先运行 uv sync 初始化环境。
    pause
    exit /b 1
)

:: 检查 psutil 是否可用
"%REPO_ROOT%.venv\Scripts\python.exe" -c "import psutil" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] psutil 未安装，正在安装...
    "%REPO_ROOT%.venv\Scripts\python.exe" -m pip install psutil -q
)

:: 调用 launcher.py start
"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" start
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] MaiBot 启动失败，错误码: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ╔══════════════════════════════════════════════╗
echo ║         MaiBot 已全部启动                   ║
echo ╚══════════════════════════════════════════════╝
echo.
pause
