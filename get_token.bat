@echo off
chcp 65001 >nul
cd /d "%~dp0"
python get_refresh_token.py client_secret.json
echo.
pause
