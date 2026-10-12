@echo off
cd /d "%~dp0"
docker compose --env-file .env -f compose.yaml down
pause
