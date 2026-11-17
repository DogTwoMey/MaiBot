@echo off
setlocal
set "ROOT=%~dp0"
call "%ROOT%stop-multi-bot.bat"
if not "%ERRORLEVEL%"=="0" exit /b %ERRORLEVEL%
call "%ROOT%start-multi-bot.bat"
exit /b %ERRORLEVEL%
