@echo off
REM Double-click: local test of the Phase 1 stack on Docker Desktop.
REM Output is saved to local-test-output.txt in this folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local.ps1"
echo.
pause
