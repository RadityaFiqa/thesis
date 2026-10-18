@echo off
REM Stops the local test containers. Data is kept (volumes are not removed).
REM To wipe the local test completely, run in this folder's parent:
REM   cd nextcloud ^&^& docker compose --env-file .env.local down -v
REM   cd ..\siem   ^&^& docker compose --env-file .env.local down -v
cd /d "%~dp0..\nextcloud" && docker compose --env-file .env.local stop
cd /d "%~dp0..\siem" && docker compose --env-file .env.local stop
echo.
echo Local test stopped.
pause
