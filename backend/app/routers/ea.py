import hmac
import json
import math
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..gemini_parser import SignalClassification
from ..models import AppSetting, EAStatus, Signal, SystemLog, Trade, utc_now


router = APIRouter(prefix="/api/ea", tags=["ea"])
FINAL_SIGNAL_STATES = {"EXECUTED", "REJECTED", "FAILED", "DRY_RUN"}
CLAIM_LEASE_SECONDS = 90


def require_ea_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    configured = get_settings().ea_api_key
    if configured is None or not configured.get_secret_value():
        raise HTTPException(status_code=503, detail="EA_API_KEY belum dikonfigurasi")
    if not x_api_key or not hmac.compare_digest(x_api_key, configured.get_secret_value()):
        raise HTTPException(status_code=401, detail="API key EA tidak valid")


class ExecutionReport(BaseModel):
    signal_id: int = Field(gt=0)
    status: Literal["EXECUTED", "REJECTED", "FAILED", "DRY_RUN"]
    ticket: str | int | None = None
    symbol: str | None = Field(default=None, max_length=64)
    action: Literal["BUY", "SELL"] | None = None
    lots: float | None = Field(default=None, gt=0, le=1000)
    exec_price: float | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_ticket_for_execution(self):
        if self.status == "EXECUTED" and not self.ticket:
            raise ValueError("Ticket wajib diisi untuk status EXECUTED")
        if self.exec_price is not None and not math.isfinite(self.exec_price):
            raise ValueError("Harga eksekusi harus finite")
        return self


class TradeResultReport(BaseModel):
    ticket: str | int
    profit: float
    result: Literal["WIN", "LOSS", "BE"]
    closed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if not math.isfinite(self.profit):
            raise ValueError("Profit harus finite")
        return self


class HeartbeatReport(BaseModel):
    active: bool = True
    terminal: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    symbol: str | None = Field(default=None, max_length=64)


def _demo_mode(db: Session) -> bool:
    setting = db.get(AppSetting, "demo_mode")
    if setting is None:
        return True
    try:
        return bool(json.loads(setting.value))
    except (TypeError, json.JSONDecodeError):
        return True


@router.get("/pending", dependencies=[Depends(require_ea_key)])
def pending(
    limit: int = Query(default=1, ge=1, le=10),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = utc_now()
    expired_lease = now - timedelta(seconds=CLAIM_LEASE_SECONDS)
    query = (
        select(Signal)
        .where(
            or_(
                Signal.status == "PENDING",
                and_(Signal.status == "CLAIMED", Signal.claimed_at < expired_lease),
            )
        )
        .order_by(Signal.created_at.asc(), Signal.id.asc())
        .limit(limit)
    )
    rows = list(db.execute(query).scalars())
    items = []
    for row in rows:
        row.status = "CLAIMED"
        row.claimed_at = now
        try:
            parsed = SignalClassification.model_validate_json(row.parsed_json or "{}")
        except Exception:
            row.status = "FAILED"
            db.add(SystemLog(level="ERROR", source="EA", message=f"Signal {row.id} memiliki parsed_json tidak valid"))
            continue
        items.append({
            "signal_id": row.id,
            "group_id": row.group_id,
            "group_name": row.group_name,
            "raw_text": row.raw_text,
            "action": parsed.action,
            "order_type": parsed.order_type,
            "symbol": parsed.symbol,
            "entry": parsed.entry,
            "sl": parsed.sl,
            "tp": parsed.tp or [],
            "confidence": parsed.confidence,
            "created_at": row.created_at.isoformat(),
            "created_epoch": int(row.created_at.timestamp()),
        })
    db.commit()
    return {"items": items, "demo_mode": _demo_mode(db), "server_time": now.isoformat()}


@router.post("/report", dependencies=[Depends(require_ea_key)])
def report(payload: ExecutionReport, db: Session = Depends(get_db)) -> dict[str, object]:
    signal = db.get(Signal, payload.signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal tidak ditemukan")
    if signal.status in FINAL_SIGNAL_STATES:
        return {"status": signal.status, "duplicate": True}

    signal.status = payload.status
    parsed = {}
    try:
        parsed = json.loads(signal.parsed_json or "{}")
    except json.JSONDecodeError:
        pass
    ticket = str(payload.ticket) if payload.ticket is not None else None
    if payload.status == "EXECUTED" and ticket:
        trade = db.execute(select(Trade).where(Trade.ticket == ticket)).scalar_one_or_none()
        if trade is not None and trade.signal_id != signal.id:
            raise HTTPException(status_code=409, detail="Ticket sudah terhubung ke signal lain")
        if trade is None:
            trade = Trade(ticket=ticket, signal_id=signal.id, opened_at=utc_now())
            db.add(trade)
        trade.symbol = payload.symbol or parsed.get("symbol")
        trade.action = payload.action or parsed.get("action")
        trade.entry = parsed.get("entry")
        trade.sl = parsed.get("sl")
        trade.tp = json.dumps(parsed.get("tp") or [])
        trade.lots = payload.lots
        trade.exec_price = payload.exec_price
    db.add(SystemLog(
        level="INFO" if payload.status in {"EXECUTED", "DRY_RUN"} else "WARN",
        source="EA",
        message=f"Signal {signal.id}: {payload.status}" + (f" — {payload.reason}" if payload.reason else ""),
    ))
    db.commit()
    return {"status": payload.status, "signal_id": signal.id, "duplicate": False}


@router.post("/result", dependencies=[Depends(require_ea_key)])
def result(payload: TradeResultReport, db: Session = Depends(get_db)) -> dict[str, object]:
    ticket = str(payload.ticket)
    trade = db.execute(select(Trade).where(Trade.ticket == ticket)).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade/ticket tidak ditemukan")
    if trade.closed_at is not None:
        return {"status": trade.result, "duplicate": True}
    if (payload.result == "WIN" and payload.profit <= 0) or (payload.result == "LOSS" and payload.profit >= 0):
        raise HTTPException(status_code=422, detail="Hasil trade tidak sesuai tanda profit")
    trade.profit = payload.profit
    trade.result = payload.result
    trade.closed_at = payload.closed_at or utc_now()
    if trade.signal_id is not None:
        signal = db.get(Signal, trade.signal_id)
        if signal is not None:
            signal.status = payload.result
    db.add(SystemLog(level="INFO", source="EA", message=f"Ticket {ticket} ditutup: {payload.result}, profit {payload.profit:g}"))
    db.commit()
    return {"status": payload.result, "ticket": ticket, "duplicate": False}


@router.post("/heartbeat", dependencies=[Depends(require_ea_key)])
def heartbeat(payload: HeartbeatReport, db: Session = Depends(get_db)) -> dict[str, object]:
    status = db.get(EAStatus, 1)
    if status is None:
        status = EAStatus(id=1)
        db.add(status)
    status.active = payload.active
    status.last_heartbeat = utc_now()
    status.terminal = payload.terminal
    status.version = payload.version
    status.symbol = payload.symbol
    db.commit()
    return {"status": "ok", "active": status.active, "last_heartbeat": status.last_heartbeat.isoformat()}
