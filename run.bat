@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --reload --reload-dir backend
) else (
  python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 --reload --reload-dir backend
)
