import sqlite3
from types import SimpleNamespace

from app import backup_database


def test_backup_uses_sqlite_online_backup_and_checks_integrity(tmp_path, monkeypatch):
    source_path = tmp_path / "app.db"
    backup_dir = tmp_path / "backups"
    with sqlite3.connect(source_path) as db:
        db.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        db.execute("INSERT INTO sample VALUES ('persisted')")

    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(
        backup_database,
        "get_settings",
        lambda: SimpleNamespace(resolved_database_url=f"sqlite:///{source_path.as_posix()}"),
    )

    backup_path = backup_database.create_backup()
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT value FROM sample").fetchone()[0] == "persisted"
