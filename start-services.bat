@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
:: start-services.bat - 基于 scripts/services.json 启动本地服务
:: ============================================================

set "REPO_ROOT=%~dp0"
set "CONFIG=%REPO_ROOT%\scripts\services.json"

echo [services] 正在读取服务配置: %CONFIG%

if not exist "%CONFIG%" (
    echo [services] WARNING: 服务配置文件不存在: %CONFIG%
    echo [services] 跳过本地服务启动。
    exit /b 0
)

:: 使用 Python 解析 JSON 并启动服务
"%REPO_ROOT%\.venv\Scripts\python.exe" "%REPO_ROOT%\scripts\start_services.py" %*
if %ERRORLEVEL% neq 0 (
    echo [services] WARNING: 服务启动脚本返回错误码 %ERRORLEVEL%，但不阻塞后续流程。
)

exit /b 0
