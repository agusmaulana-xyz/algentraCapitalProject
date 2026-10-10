"""Load Algentra's worker key from the project .env and start the copier worker."""

from __future__ import annotations

import os
from pathlib import Path
import sys


COPY_TRADING_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = COPY_TRADING_ROOT.parent
WORKER_KEY_NAME = "COPIER_WORKER_API_KEY"


def main() -> None:
    key = os.environ.get(WORKER_KEY_NAME)
    if not key:
        try:
            from dotenv import dotenv_values
        except ImportError as exc:
            raise SystemExit("Pasang dependensi backend (python-dotenv) untuk membaca file .env.") from exc
        values = dotenv_values(PROJECT_ROOT / ".env")
        key = values.get(WORKER_KEY_NAME)

    if not key or len(key) < 32:
        raise SystemExit("COPIER_WORKER_API_KEY belum tersedia atau kurang dari 32 karakter.")

    # The worker itself reads the key from its process environment. Do not print it.
    os.environ[WORKER_KEY_NAME] = key
    source_dir = str(COPY_TRADING_ROOT / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = source_dir + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    sys.path.insert(0, source_dir)

    if len(sys.argv) == 1:
        sys.argv.append(str(COPY_TRADING_ROOT / "config" / "managed-worker.json"))

    from copytrade.managed_worker import main as worker_main

    worker_main()


if __name__ == "__main__":
    main()
