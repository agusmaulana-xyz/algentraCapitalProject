from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_created_at", "created_at"),
        Index("ux_signals_content_hash", "content_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parsed_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    ticket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lots: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp: Mapped[str | None] = mapped_column(Text, nullable=True)
    exec_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatGroup(Base):
    __tablename__ = "groups"

    chat_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)


class SystemLog(Base):
    __tablename__ = "logs"
    __table_args__ = (Index("ix_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class AdminUser(Base):
    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
