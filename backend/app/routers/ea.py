import hmac
import json
import math
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..gemini_parser import SignalClassification
from ..models import AppSetting, EAExecution, EAStatus, Signal, SystemLog, Trade, utc_now
from ..risk_controls import risk_state


router = APIRouter(prefix="/api/ea", tags=["ea"])
FINAL_SIGNAL_STATES = {"EXECUTED", "REJECTED", "FAILED", "DRY_RUN", "EXPIRED"}
CLAIM_LEASE_SECONDS = 90
MAX_SIGNAL_TARGETS = 20


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
    lots: float | None = Field(default=None, ge=0, le=1000)
    exec_price: float | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=1000)
    leg: int | None = Field(default=None, ge=0, le=MAX_SIGNAL_TARGETS)

    @model_validator(mode="after")
    def validate_execution_fields(self):
        ticket = str(self.ticket).strip() if self.ticket is not None else ""
        if self.status == "EXECUTED" and ticket in {"", "0"}:
            raise ValueError("Ticket wajib diisi untuk status EXECUTED")
        if self.lots is not None and not math.isfinite(self.lots):
            raise ValueError("Lot harus finite")
        if self.exec_price is not None and not math.isfinite(self.exec_price):
            raise ValueError("Harga eksekusi harus finite")
        if self.status == "EXECUTED":
            if self.lots is not None and self.lots <= 0:
                raise ValueError("Lot harus lebih besar dari 0 untuk status EXECUTED")
            if self.exec_price is not None and self.exec_price <= 0:
                raise ValueError("Harga eksekusi harus lebih besar dari 0 untuk status EXECUTED")
        else:
            # Older EA builds report zero values when no order was sent.
            if self.ticket is not None and ticket in {"", "0"}:
                self.ticket = None
            if self.lots == 0:
                self.lots = None
            if self.exec_price == 0:
                self.exec_price = None
        return self


class TradeResultReport(BaseModel):
    ticket: str | int
    profit: float
    result: Literal["WIN", "LOSS", "BE", "EXPIRED"]
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


def _take_profit_prices(parsed: dict) -> list[float]:
    raw_targets = parsed.get("tp")
    if not isinstance(raw_targets, list):
        return []
    targets = [
        float(value)
        for value in raw_targets
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    ]
    return targets[:MAX_SIGNAL_TARGETS]


def _expected_signal_legs(parsed: dict) -> int:
    targets = _take_profit_prices(parsed)
    if targets:
        return len(targets)
    if parsed.get("entry_low") is not None and parsed.get("entry_high") is not None:
        return 2
    return 1


def _sync_signal_execution_status(db: Session, signal: Signal, expected_legs: int) -> None:
    executions = list(db.execute(
        select(EAExecution).where(EAExecution.signal_id == signal.id)
    ).scalars())
    expected = {0} if expected_legs == 1 else set(range(1, expected_legs + 1))
    by_leg = {execution.leg: execution for execution in executions}
    if not expected.issubset(by_leg):
        signal.status = "CLAIMED"
        return

    leg_statuses = [by_leg[leg].status for leg in expected]
    if "EXECUTED" not in leg_statuses:
        signal.status = "FAILED" if "FAILED" in leg_statuses else "REJECTED"
        return

    open_trade = db.execute(
        select(Trade.id).where(Trade.signal_id == signal.id, Trade.closed_at.is_(None)).limit(1)
    ).scalar_one_or_none()
    if open_trade is not None:
        signal.status = "EXECUTED"
        return

    results = list(db.execute(
        select(Trade.result, Trade.profit).where(Trade.signal_id == signal.id)
    ).all())
    if results and all(result == "EXPIRED" for result, _ in results):
        signal.status = "EXPIRED"
    elif results:
        total_profit = sum(profit for _, profit in results)
        signal.status = "BE" if abs(total_profit) < 0.005 else "WIN" if total_profit > 0 else "LOSS"
    else:
        signal.status = "EXECUTED"


@router.get("/pending", dependencies=[Depends(require_ea_key)])
def pending(
    limit: int = Query(default=1, ge=1, le=10),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = utc_now()
    expired_lease = now - timedelta(seconds=CLAIM_LEASE_SECONDS)
    controls = risk_state(db)
    response_controls = {
        key: controls[key]
        for key in (
            "demo_mode", "kill_switch", "daily_loss", "max_daily_loss_money", "daily_loss_reached",
            "max_lot", "max_open_trades", "open_trades", "max_open_reached",
            "max_signal_age_seconds", "max_market_deviation_pct",
        )
    }
    if controls["trading_paused"]:
        return {"items": [], **response_controls, "server_time": now.isoformat()}

    eligible = or_(
        Signal.status == "PENDING",
        and_(Signal.status == "CLAIMED", or_(Signal.claimed_at.is_(None), Signal.claimed_at < expired_lease)),
    )
    candidate_ids = list(db.execute(
        select(Signal.id).where(eligible).order_by(Signal.created_at.asc(), Signal.id.asc()).limit(limit)
    ).scalars())
    if not candidate_ids:
        return {"items": [], **response_controls, "server_time": now.isoformat()}

    # Conditional update makes claiming safe when multiple EA clients poll together.
    db.execute(
        update(Signal).where(Signal.id.in_(candidate_ids), eligible).values(status="CLAIMED", claimed_at=now)
    )
    rows = list(db.execute(
        select(Signal).where(Signal.id.in_(candidate_ids), Signal.status == "CLAIMED", Signal.claimed_at == now)
    ).scalars())
    items = []
    for row in rows:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=now.tzinfo)
        max_age = int(controls["max_signal_age_seconds"])
        if max_age > 0 and (now - created_at).total_seconds() > max_age:
            row.status = "REJECTED"
            db.add(SystemLog(level="WARN", source="EA", message=f"Signal {row.id} ditolak karena kedaluwarsa"))
            continue
        try:
            parsed = SignalClassification.model_validate_json(row.parsed_json or "{}")
        except Exception:
            row.status = "FAILED"
            db.add(SystemLog(level="ERROR", source="EA", message=f"Signal {row.id} memiliki parsed_json tidak valid"))
            continue
        allowed_symbols = controls["allowed_symbols"]
        if allowed_symbols:
            symbol = (parsed.symbol or "").upper()
            symbol_allowed = any(
                symbol == allowed or (symbol.startswith(allowed) and len(symbol) > len(allowed) and symbol[len(allowed)] in ".0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                for allowed in allowed_symbols
            )
            if not symbol_allowed:
                row.status = "REJECTED"
                db.add(SystemLog(level="WARN", source="EA", message=f"Signal {row.id} ditolak karena symbol tidak diizinkan"))
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
            "entry_low": parsed.entry_low,
            "entry_high": parsed.entry_high,
            "sl": parsed.sl,
            "tp": parsed.tp or [],
            "confidence": parsed.confidence,
            "created_at": row.created_at.isoformat(),
            # SQLite returns naive datetimes for UTC values; normalize before
            # converting to Unix time so the host's local timezone is ignored.
            "created_epoch": int(created_at.timestamp()),
        })
    db.commit()
    return {"items": items, **response_controls, "server_time": now.isoformat()}


@router.post("/report", dependencies=[Depends(require_ea_key)])
def report(payload: ExecutionReport, db: Session = Depends(get_db)) -> dict[str, object]:
    signal = db.get(Signal, payload.signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal tidak ditemukan")
    parsed = {}
    try:
        parsed = json.loads(signal.parsed_json or "{}")
    except json.JSONDecodeError:
        pass
    expected_legs = _expected_signal_legs(parsed)
    leg = payload.leg if payload.leg is not None else 0
    multi_leg_report = expected_legs > 1 and 1 <= leg <= expected_legs
    if payload.status == "EXECUTED" and (
        (expected_legs > 1 and not multi_leg_report) or (expected_legs == 1 and leg != 0)
    ):
        raise HTTPException(status_code=422, detail="Nomor entry tidak sesuai jumlah TP pada signal")

    execution = db.execute(
        select(EAExecution).where(EAExecution.signal_id == signal.id, EAExecution.leg == leg)
    ).scalar_one_or_none()
    if execution is not None and execution.status == payload.status:
        if payload.status != "EXECUTED" or str(execution.ticket) == str(payload.ticket):
            return {"status": signal.status, "duplicate": True}
    if execution is not None and execution.status == "EXECUTED" and payload.status != "EXECUTED":
        return {"status": signal.status, "duplicate": True}

    is_execution = payload.status == "EXECUTED"
    if signal.status in FINAL_SIGNAL_STATES:
        can_upgrade_failed_leg = is_execution and execution is not None and execution.status in {"FAILED", "REJECTED"}
        if not can_upgrade_failed_leg:
            return {"status": signal.status, "duplicate": True}
    elif signal.status != "CLAIMED":
        raise HTTPException(status_code=409, detail="Signal belum diklaim oleh EA")
    if is_execution and _demo_mode(db):
        raise HTTPException(status_code=409, detail="Backend masih dalam demo mode; eksekusi live ditolak")

    ticket = str(payload.ticket) if payload.ticket is not None else None
    if is_execution and ticket:
        trade = db.execute(select(Trade).where(Trade.ticket == ticket)).scalar_one_or_none()
        if trade is not None and trade.signal_id != signal.id:
            raise HTTPException(status_code=409, detail="Ticket sudah terhubung ke signal lain")
        if execution is None:
            execution = EAExecution(signal_id=signal.id, leg=leg, status=payload.status)
            db.add(execution)
        execution.status = payload.status
        execution.ticket = ticket
        execution.lots = payload.lots
        execution.exec_price = payload.exec_price
        execution.reason = payload.reason
        if trade is None:
            trade = Trade(ticket=ticket, signal_id=signal.id, opened_at=utc_now())
            db.add(trade)
        trade.symbol = payload.symbol or parsed.get("symbol")
        trade.action = payload.action or parsed.get("action")
        trade.entry = parsed.get("entry") if parsed.get("entry") is not None else payload.exec_price
        trade.sl = parsed.get("sl")
        take_profits = _take_profit_prices(parsed)
        if expected_legs > 1:
            take_profits = [take_profits[leg - 1]] if leg <= len(take_profits) else []
        trade.tp = json.dumps(take_profits)
        trade.lots = payload.lots
        trade.exec_price = payload.exec_price
        db.flush()
        _sync_signal_execution_status(db, signal, expected_legs)
    elif multi_leg_report:
        if execution is None:
            execution = EAExecution(signal_id=signal.id, leg=leg, status=payload.status)
            db.add(execution)
        execution.status = payload.status
        execution.ticket = None
        execution.lots = payload.lots
        execution.exec_price = payload.exec_price
        execution.reason = payload.reason
        db.flush()
        _sync_signal_execution_status(db, signal, expected_legs)
    else:
        signal.status = payload.status
    db.add(SystemLog(
        level="INFO" if payload.status in {"EXECUTED", "DRY_RUN"} else "WARN",
        source="EA",
        message=f"Signal {signal.id}: {payload.status}" + (f" — {payload.reason}" if payload.reason else ""),
    ))
    db.commit()
    return {"status": payload.status, "signal_id": signal.id, "leg": leg, "duplicate": False}


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
            parsed = {}
            try:
                parsed = json.loads(signal.parsed_json or "{}")
            except json.JSONDecodeError:
                pass
            expected_legs = _expected_signal_legs(parsed)
            execution_count = db.execute(
                select(EAExecution.id).where(EAExecution.signal_id == signal.id).limit(1)
            ).scalar_one_or_none()
            if execution_count is not None:
                _sync_signal_execution_status(db, signal, expected_legs)
            else:
                open_ticket = db.execute(
                    select(Trade.id).where(Trade.signal_id == signal.id, Trade.closed_at.is_(None)).limit(1)
                ).scalar_one_or_none()
                if open_ticket is None:
                    results = list(db.execute(
                        select(Trade.result, Trade.profit).where(Trade.signal_id == signal.id)
                    ).all())
                    if results and all(result == "EXPIRED" for result, _ in results):
                        signal.status = "EXPIRED"
                    else:
                        total_profit = sum(profit for _, profit in results)
                        signal.status = "BE" if abs(total_profit) < 0.005 else "WIN" if total_profit > 0 else "LOSS"
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
