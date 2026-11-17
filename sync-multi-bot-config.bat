@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%ROOT%runtime\multi-bot-env\Scripts\python.exe" "%ROOT%scripts\multi_bot_workspace.py" sync-config %*
exit /b %ERRORLEVEL%
