@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
:: stop-all.bat - 停止 MaiBot 全套组件 + 本地服务
:: ============================================================

set "REPO_ROOT=%~dp0"
set "STOP_EXIT_CODE=0"
cd /d "%REPO_ROOT%"

:: 使用 ASCII 框线，避免部分 cmd.exe 环境错误解析 UTF-8 制表字符。
echo +----------------------------------------------+
echo ^|         MaiBot 一键停止                     ^|
echo +----------------------------------------------+
echo.

:: Step 1: 停止 MaiBot 组件
echo [1/2] 停止 MaiBot 组件...
echo -----------------------------------------------

if not exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    echo [WARNING] .venv 不存在，跳过 MaiBot 组件和本地服务停止。
    goto done
)

"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" stop
if errorlevel 1 (
    set "STOP_EXIT_CODE=!ERRORLEVEL!"
    echo [WARNING] MaiBot 组件停止脚本返回错误码 !STOP_EXIT_CODE!，继续停止本地服务。
)
echo.

:: Step 2: 停止本地依赖服务
echo [2/2] 停止本地依赖服务...
echo -----------------------------------------------

if not exist "%REPO_ROOT%scripts\start_services.py" (
    echo [WARNING] start_services.py 不存在，跳过服务停止。
    goto done
)

"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\start_services.py" stop
if errorlevel 1 (
    set "SERVICE_EXIT_CODE=!ERRORLEVEL!"
    echo [WARNING] 本地服务停止脚本返回错误码 !SERVICE_EXIT_CODE!。
    if "!STOP_EXIT_CODE!"=="0" set "STOP_EXIT_CODE=!SERVICE_EXIT_CODE!"
)
echo.

:done
echo.
echo +----------------------------------------------+
echo ^|         MaiBot 已全部停止                   ^|
echo +----------------------------------------------+
echo.
exit /b !STOP_EXIT_CODE!
