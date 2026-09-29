#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
fi
exec python3 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
