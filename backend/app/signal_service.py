import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .gemini_parser import GeminiParser, SignalClassification
from .models import AppSetting, Signal, SystemLog, utc_now


DEFAULT_SYMBOL_MAPPING = {"XAUUSD": "XAUUSD", "GOLD": "XAUUSD", "XAU": "XAUUSD", "EMAS": "XAUUSD"}


@dataclass
class ValidationResult:
    status: str
    classification: SignalClassification
    symbol: str | None
    normalized_text: str | None
    reason: str


@dataclass
class ProcessResult:
    status: str
    signal_id: int | None
    classification: SignalClassification | None
    normalized_text: str | None
    reason: str
    duplicate: bool = False


def _setting(db: Session, key: str, default):
    item = db.get(AppSetting, key)
    if item is None:
        return default
    try:
        return json.loads(item.value)
    except (TypeError, json.JSONDecodeError):
        return default


def normalize_symbol(symbol: str | None, mapping: dict[str, str] | None = None, default_symbol: str = "XAUUSD") -> str:
    if not symbol:
        return default_symbol.upper()
    original = re.sub(r"\s+", "", symbol)
    candidate = original.upper()
    aliases = {**DEFAULT_SYMBOL_MAPPING, **{str(key).upper(): str(value).upper() for key, value in (mapping or {}).items()}}
    for alias in sorted(aliases, key=len, reverse=True):
        if candidate == alias:
            return aliases[alias]
        if candidate.startswith(alias):
            suffix = candidate[len(alias) :]
            if suffix and (suffix.isalnum() or suffix.startswith(".")):
                return f"{aliases[alias]}{original[len(alias) :]}"
    return candidate


def validate_classification(
    classification: SignalClassification,
    *,
    default_symbol: str = "XAUUSD",
    confidence_threshold: float = 0.75,
    symbol_mapping: dict[str, str] | None = None,
    allow_updates: bool = False,
    market_price: float | None = None,
    max_market_deviation_pct: float = 5.0,
) -> ValidationResult:
    if not classification.is_signal or classification.type == "NOT_SIGNAL":
        return ValidationResult("IGNORED", classification, None, None, classification.reason or "Bukan sinyal")
    if classification.type == "UPDATE" and not allow_updates:
        return ValidationResult("IGNORED", classification, None, None, "Signal UPDATE dinonaktifkan di settings")
    if classification.type != "NEW_SIGNAL":
        return ValidationResult("REJECTED", classification, None, None, "Jenis signal tidak dikenal")
    if classification.confidence < confidence_threshold:
        return ValidationResult("REJECTED", classification, None, None, "Confidence di bawah threshold")
    if classification.action not in {"BUY", "SELL"}:
        return ValidationResult("REJECTED", classification, None, None, "Action BUY/SELL tidak valid")
    if classification.order_type not in {"MARKET", "LIMIT", "STOP"}:
        return ValidationResult("REJECTED", classification, None, None, "Order type tidak valid")
    if classification.order_type in {"LIMIT", "STOP"} and classification.entry is None:
        return ValidationResult("REJECTED", classification, None, None, "Pending order wajib memiliki harga entry")

    action = classification.action
    entry = classification.entry
    stop_loss = classification.sl
    take_profits = classification.tp or []
    if any(price <= 0 for price in take_profits) or (stop_loss is not None and stop_loss <= 0) or (entry is not None and entry <= 0):
        return ValidationResult("REJECTED", classification, None, None, "Harga harus lebih besar dari nol")

    if entry is not None:
        if action == "BUY" and ((stop_loss is not None and stop_loss >= entry) or any(tp <= entry for tp in take_profits)):
            return ValidationResult("REJECTED", classification, None, None, "BUY mensyaratkan SL < entry < setiap TP")
        if action == "SELL" and ((stop_loss is not None and stop_loss <= entry) or any(tp >= entry for tp in take_profits)):
            return ValidationResult("REJECTED", classification, None, None, "SELL mensyaratkan setiap TP < entry < SL")
        if market_price and market_price > 0:
            deviation_pct = abs(entry - market_price) / market_price * 100.0
            if deviation_pct > max_market_deviation_pct:
                return ValidationResult("REJECTED", classification, None, None, "Entry terlalu jauh dari harga pasar")
    elif stop_loss is not None and take_profits:
        if action == "BUY" and stop_loss >= min(take_profits):
            return ValidationResult("REJECTED", classification, None, None, "BUY mensyaratkan SL di bawah TP")
        if action == "SELL" and max(take_profits) >= stop_loss:
            return ValidationResult("REJECTED", classification, None, None, "SELL mensyaratkan TP di bawah SL")

    symbol = normalize_symbol(classification.symbol, symbol_mapping, default_symbol)
    levels = []
    if entry is not None:
        levels.append(f"{entry:g}")
    elif classification.order_type == "MARKET":
        levels.append("MARKET")
    if take_profits:
        levels.append("TP : " + ", ".join(f"{price:g}" for price in take_profits))
    if stop_loss is not None:
        levels.append(f"SL : {stop_loss:g}")
    normalized = f"{action} : " + " | ".join(levels)
    return ValidationResult("PENDING", classification, symbol, normalized, "Signal valid")


class SignalService:
    def __init__(self, parser: GeminiParser | None = None) -> None:
        self.parser = parser or GeminiParser()

    async def process_message(
        self,
        db: Session,
        *,
        group_id: str,
        group_name: str,
        message_id: str,
        raw_text: str,
        created_at: datetime | None = None,
        context: str | None = None,
    ) -> ProcessResult:
        stamp = created_at or utc_now()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        existing = db.execute(
            select(Signal).where(Signal.group_id == str(group_id), Signal.message_id == str(message_id))
        ).scalar_one_or_none()
        if existing:
            return ProcessResult(existing.status, existing.id, None, existing.normalized_text, "Message sudah diproses", True)

        content = re.sub(r"\s+", " ", raw_text).strip().casefold()
        time_bucket = stamp.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        content_hash = hashlib.sha256(f"{group_id}|{time_bucket}|{content}".encode("utf-8")).hexdigest()
        duplicate = db.execute(select(Signal).where(Signal.content_hash == content_hash)).scalar_one_or_none()
        if duplicate:
            return ProcessResult(duplicate.status, duplicate.id, None, duplicate.normalized_text, "Signal identik dalam jendela waktu yang sama", True)

        try:
            classification = await self.parser.parse(raw_text, context)
        except Exception as exc:
            row = Signal(
                group_id=str(group_id),
                group_name=group_name,
                message_id=str(message_id),
                raw_text=raw_text[:12000],
                content_hash=content_hash,
                status="FAILED",
                created_at=stamp,
            )
            db.add(row)
            db.add(SystemLog(level="ERROR", source="Gemini", message=f"Parser gagal: {exc}"[:2000], created_at=utc_now()))
            db.commit()
            db.refresh(row)
            return ProcessResult("FAILED", row.id, None, None, "Parser tidak tersedia")

        mapping = _setting(db, "symbol_mapping", {})
        if not isinstance(mapping, dict):
            mapping = {}
        default_symbol = str(_setting(db, "default_symbol", "XAUUSD"))
        confidence_threshold = float(_setting(db, "confidence_threshold", 0.75))
        allow_updates = bool(_setting(db, "allow_updates", False))
        max_deviation = float(_setting(db, "max_market_deviation_pct", 5.0))
        validation = validate_classification(
            classification,
            default_symbol=default_symbol,
            confidence_threshold=confidence_threshold,
            symbol_mapping=mapping,
            allow_updates=allow_updates,
            max_market_deviation_pct=max_deviation,
        )
        saved_classification = classification.model_copy(update={"symbol": validation.symbol or classification.symbol})
        row = Signal(
            group_id=str(group_id),
            group_name=group_name,
            message_id=str(message_id),
            raw_text=raw_text[:12000],
            parsed_json=saved_classification.model_dump_json(),
            normalized_text=validation.normalized_text,
            confidence=classification.confidence,
            content_hash=content_hash,
            status=validation.status,
            created_at=stamp,
        )
        db.add(row)
        db.add(SystemLog(
            level="INFO" if validation.status in {"PENDING", "IGNORED"} else "WARN",
            source="Signal",
            message=f"{group_name}: {validation.status} — {validation.reason}"[:2000],
            created_at=utc_now(),
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            duplicate = db.execute(select(Signal).where(Signal.content_hash == content_hash)).scalar_one_or_none()
            if duplicate:
                return ProcessResult(duplicate.status, duplicate.id, None, duplicate.normalized_text, "Signal duplikat", True)
            raise
        db.refresh(row)
        return ProcessResult(validation.status, row.id, saved_classification, validation.normalized_text, validation.reason)
