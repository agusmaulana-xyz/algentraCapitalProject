from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    database_url = get_settings().database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    is_memory_database = database_url in {"sqlite://", "sqlite:///:memory:"}
    if database_url.startswith("sqlite:///"):
        database_path = database_url.removeprefix("sqlite:///")
        if not is_memory_database and database_path != ":memory:":
            path = Path(database_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)
    engine_options = {"poolclass": StaticPool} if is_memory_database else {}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, **engine_options)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def migrate_schema() -> None:
    """Apply the small additive SQLite changes needed between early milestones."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "signals" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("signals")}
        additions = {
            "content_hash": "VARCHAR(64)",
            "sender_id": "VARCHAR(128)",
            "sender_name": "VARCHAR(255)",
        }
        missing = {name: sql_type for name, sql_type in additions.items() if name not in columns}
        if missing:
            with engine.begin() as connection:
                for name, sql_type in missing.items():
                    connection.execute(text(f"ALTER TABLE signals ADD COLUMN {name} {sql_type}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
