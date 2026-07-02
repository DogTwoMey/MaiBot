@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================
:: start-all.bat - 启动本地服务 + MaiBot 全套组件
:: 双击即可运行，按顺序执行：构建前端 → 本地服务 → NapCat → Adapter → Bot
:: ============================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

:: 使用 ASCII 框线，避免部分 cmd.exe 环境错误解析 UTF-8 制表字符。
echo +----------------------------------------------+
echo ^|         MaiBot 一键启动                     ^|
echo +----------------------------------------------+
echo.

:: 检查 .venv 是否存在
if not exist "%REPO_ROOT%.venv\Scripts\python.exe" (
    echo [ERROR] .venv 不存在，请先运行 uv sync 初始化环境。
    pause
    exit /b 1
)

:: 检查 psutil 是否可用
"%REPO_ROOT%.venv\Scripts\python.exe" -c "import psutil" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 当前 .venv 缺少 psutil，请先运行 uv sync 同步 pyproject.toml 依赖。
    pause
    exit /b 1
)

:: Step 1: 构建 Dashboard
echo [1/3] 构建 Dashboard...
echo -----------------------------------------------
call :build_dashboard
if errorlevel 1 (
    echo.
    echo [ERROR] 前端构建失败，已取消启动。
    pause
    exit /b 1
)
echo.

:: Step 2: 启动本地依赖服务
echo [2/3] 启动本地依赖服务...
echo -----------------------------------------------
call "%REPO_ROOT%start-services.bat"
echo.

:: Step 3: 启动 MaiBot 组件 (NapCat + Adapter + Bot)
echo [3/3] 启动 MaiBot 组件...
echo -----------------------------------------------

:: 调用 launcher.py start
"%REPO_ROOT%.venv\Scripts\python.exe" "%REPO_ROOT%scripts\launcher.py" start
if errorlevel 1 (
    set "LAUNCH_EXIT_CODE=!ERRORLEVEL!"
    echo.
    echo [ERROR] MaiBot 启动失败，错误码: !LAUNCH_EXIT_CODE!
    pause
    exit /b !LAUNCH_EXIT_CODE!
)

echo.
echo +----------------------------------------------+
echo ^|         MaiBot 已全部启动                   ^|
echo +----------------------------------------------+
echo.
exit /b 0

:build_dashboard
set "DASHBOARD_DIR=%REPO_ROOT%dashboard"

if not exist "%DASHBOARD_DIR%\package.json" (
    echo [ERROR] Dashboard 项目不存在: %DASHBOARD_DIR%
    exit /b 1
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 npm.cmd，请先安装 Node.js 并加入 PATH。
    exit /b 1
)

pushd "%DASHBOARD_DIR%" >nul

set "DASHBOARD_INSTALL_REQUIRED=0"
if not exist "node_modules\" (
    set "DASHBOARD_INSTALL_REQUIRED=1"
) else (
    call npm.cmd ls --depth=0 >nul 2>&1
    if errorlevel 1 set "DASHBOARD_INSTALL_REQUIRED=1"
)

if "!DASHBOARD_INSTALL_REQUIRED!"=="1" (
    if not exist "package-lock.json" (
        echo [ERROR] Dashboard 依赖缺失或不完整，且缺少 package-lock.json，无法执行 npm ci。
        popd >nul
        exit /b 1
    )

    echo [dashboard] 依赖缺失或与 package-lock.json 不一致，正在执行 npm ci...
    call npm.cmd ci --no-audit --no-fund
    if errorlevel 1 (
        set "BUILD_EXIT_CODE=!ERRORLEVEL!"
        popd >nul
        echo [ERROR] Dashboard 依赖安装失败，错误码: !BUILD_EXIT_CODE!
        exit /b !BUILD_EXIT_CODE!
    )
)

echo [dashboard] 正在构建前端...
call npm.cmd run build
set "BUILD_EXIT_CODE=!ERRORLEVEL!"
popd >nul

if not "!BUILD_EXIT_CODE!"=="0" (
    echo [ERROR] Dashboard 构建失败，错误码: !BUILD_EXIT_CODE!
    exit /b !BUILD_EXIT_CODE!
)

echo [dashboard] 前端构建完成: dashboard\dist
exit /b 0
