"""Create and rotate online SQLite backups for the production database."""

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3

from .config import get_settings


BACKUP_NAME = re.compile(r"^algentra-app-\d{8}T\d{6}Z\.db$")
BACKUP_RETENTION = 14


def create_backup() -> Path:
    settings = get_settings()
    database_url = settings.resolved_database_url
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Backup hanya mendukung SQLite")

    database_path = Path(database_url.removeprefix("sqlite:///"))
    backup_dir_value = os.environ.get("BACKUP_DIR", "").strip()
    if not database_path.is_absolute():
        raise RuntimeError("DATABASE_URL harus berupa jalur absolut")
    if not backup_dir_value:
        raise RuntimeError("BACKUP_DIR wajib diarahkan ke lokasi backup persisten")

    backup_dir = Path(backup_dir_value).expanduser().resolve()
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise RuntimeError("Database SQLite belum ada; backup tidak dibuat")
    if backup_dir == database_path.parent or backup_dir in database_path.parents:
        raise RuntimeError("BACKUP_DIR harus berada di luar folder database")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"algentra-app-{timestamp}.db"
    with sqlite3.connect(database_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        integrity = target.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            destination.unlink(missing_ok=True)
            raise RuntimeError("Pemeriksaan integritas backup gagal")

    backups = sorted(
        (path for path in backup_dir.iterdir() if BACKUP_NAME.fullmatch(path.name)),
        key=lambda path: path.name,
        reverse=True,
    )
    for expired in backups[BACKUP_RETENTION:]:
        expired.unlink()
    return destination


if __name__ == "__main__":
    print(create_backup())
