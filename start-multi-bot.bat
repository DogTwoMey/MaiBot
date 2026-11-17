@echo off
setlocal
set "ROOT=%~dp0"
set "SOURCE=%ROOT%runtime\multi-bot-source"
set "PYTHON=%ROOT%runtime\multi-bot-env\Scripts\python.exe"
set "WORKSPACE=%ROOT%runtime\multi-bot-workspace"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist "%PYTHON%" (
  echo [multi-bot] Runtime environment is missing: %PYTHON%
  exit /b 1
)
if not exist "%WORKSPACE%\host\registry.sqlite3" (
  echo [multi-bot] Migrated workspace is missing: %WORKSPACE%
  exit /b 1
)
cd /d "%SOURCE%" || exit /b 1
"%PYTHON%" -m src.cli.tool host status -d "%WORKSPACE%" >nul 2>&1
if not errorlevel 1 (
  echo [multi-bot] Host is already running.
  exit /b 0
)
"%PYTHON%" -c "import psutil,sys; sys.exit(any(c.status == psutil.CONN_LISTEN and c.laddr.port in (8001,8101) for c in psutil.net_connections(kind='tcp')))"
if errorlevel 1 (
  echo [multi-bot] Bot ports are occupied. Stop the existing instances first.
  exit /b 1
)
call "%ROOT%start-services.bat"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%scripts\launcher.py" start snowluma --hide snowluma
if errorlevel 1 echo [multi-bot] SnowLuma account is not ready. Check desktop QQ login.
cd /d "%SOURCE%" || exit /b 1
"%PYTHON%" -m src.cli.tool run -d "%WORKSPACE%"
exit /b %ERRORLEVEL%
