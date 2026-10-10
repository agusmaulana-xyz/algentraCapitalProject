@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"
cd /d "%PROJECT_ROOT%"
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m copytrade.launcher config\launcher.json
) else (
    python -m copytrade.launcher config\launcher.json
)
endlocal
