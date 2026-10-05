@echo off
setlocal
cd /d "%~dp0backend"
if not exist "..\.venv\Scripts\python.exe" exit /b 1
"..\.venv\Scripts\python.exe" -m app.backup_database
