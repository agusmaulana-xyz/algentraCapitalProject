import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Signal, SystemLog, Trade
from ..routers.tg import telegram_manager
from ..risk_controls import risk_state
from ..schemas import LogResponse, SignalResponse
from ..stats_service import get_dashboard_stats, get_group_stats
from ..time_utils import wib_datetime_to_utc_naive, wib_iso


router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
async def stats(db: Session = Depends(get_db)) -> dict[str, object]:
    payload: dict[str, object] = get_dashboard_stats(db)
    payload.update(risk_state(db))
    telegram = await telegram_manager.status()
    settings = get_settings()
    payload.update({
        "telegram_connected": bool(telegram["connected"]),
        "telegram_status": telegram["state"],
        "telegram_account": telegram["account_name"],
        "gemini_configured": bool(settings.gemini_api_key and settings.gemini_api_key.get_secret_value()),
        "gemini_model": settings.gemini_model,
    })
    return payload


@router.get("/signals", response_model=list[SignalResponse])
def signals(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    group_id: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    query = select(Signal, Trade.ticket, Trade.profit).outerjoin(Trade, Trade.signal_id == Signal.id)
    if status:
        query = query.where(Signal.status == status.upper())
    if group_id:
        query = query.where(Signal.group_id == group_id)
    query = query.order_by(Signal.created_at.desc(), Signal.id.desc()).offset(offset).limit(limit)
    items = []
    for signal, ticket, profit in db.execute(query).all():
        item = SignalResponse.model_validate(signal).model_dump()
        item["created_at"] = wib_iso(signal.created_at)
        item.update({"ticket": ticket, "profit": profit})
        items.append(item)
    return items


def _logs_query(level: str | None, search: str | None):
    query = select(SystemLog)
    if level:
        query = query.where(SystemLog.level == level.upper())
    if search:
        query = query.where(SystemLog.message.contains(search, autoescape=True))
    return query


def _csv_text(value: str | None) -> str:
    text = value or ""
    if text.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
        return "'" + text
    return text


@router.get("/logs", response_model=list[LogResponse])
def logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    level: str | None = Query(default=None, min_length=1, max_length=16),
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    query = _logs_query(level, search).order_by(SystemLog.created_at.desc(), SystemLog.id.desc()).offset(offset).limit(limit)
    rows = db.execute(query).scalars()
    return [
        {**LogResponse.model_validate(row).model_dump(), "created_at": wib_iso(row.created_at)}
        for row in rows
    ]


@router.get("/logs/export.csv")
def export_logs(
    level: str | None = Query(default=None, max_length=16),
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    rows = db.execute(_logs_query(level, search).order_by(SystemLog.created_at.desc()).limit(10000)).scalars()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "level", "source", "message"])
    for row in rows:
        writer.writerow([row.id, wib_iso(row.created_at), _csv_text(row.level), _csv_text(row.source), _csv_text(row.message)])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=logs.csv"})


@router.get("/groups/stats")
def group_stats(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return get_group_stats(db)


def _trades_query(
    date_from: datetime | None,
    date_to: datetime | None,
    group_id: str | None,
    symbol: str | None,
    result: str | None,
):
    date_from = wib_datetime_to_utc_naive(date_from) if date_from else None
    date_to = wib_datetime_to_utc_naive(date_to) if date_to else None
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from harus sebelum atau sama dengan date_to")
    query = select(Trade, Signal.group_id, Signal.group_name).outerjoin(Signal, Signal.id == Trade.signal_id)
    if date_from:
        query = query.where(Trade.opened_at >= date_from)
    if date_to:
        query = query.where(Trade.opened_at <= date_to)
    if group_id:
        query = query.where(Signal.group_id == group_id)
    if symbol:
        query = query.where(Trade.symbol == symbol.upper())
    if result:
        query = query.where(Trade.result == result.upper())
    return query.order_by(Trade.opened_at.desc(), Trade.id.desc())


def _trade_dict(trade: Trade, group_id: str | None, group_name: str | None) -> dict[str, object]:
    return {
        "id": trade.id,
        "signal_id": trade.signal_id,
        "ticket": trade.ticket,
        "group_id": group_id,
        "group_name": group_name,
        "symbol": trade.symbol,
        "action": trade.action,
        "lots": trade.lots,
        "entry": trade.entry,
        "sl": trade.sl,
        "tp": trade.tp,
        "exec_price": trade.exec_price,
        "profit": trade.profit,
        "result": trade.result,
        "opened_at": wib_iso(trade.opened_at),
        "closed_at": wib_iso(trade.closed_at),
    }


@router.get("/trades")
def trades(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    group_id: str | None = Query(default=None, max_length=128),
    symbol: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.execute(_trades_query(date_from, date_to, group_id, symbol, result).offset(offset).limit(limit)).all()
    return [_trade_dict(trade, group_id_value, group_name) for trade, group_id_value, group_name in rows]


@router.get("/trades/export.csv")
def export_trades(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    group_id: str | None = Query(default=None, max_length=128),
    symbol: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=16),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    rows = db.execute(_trades_query(date_from, date_to, group_id, symbol, result).limit(10000)).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ticket", "group", "symbol", "action", "lots", "entry", "exec_price", "profit", "result", "opened_at", "closed_at"])
    for trade, _, group_name in rows:
        writer.writerow([
            _csv_text(trade.ticket), _csv_text(group_name), _csv_text(trade.symbol), _csv_text(trade.action), trade.lots, trade.entry,
            trade.exec_price, trade.profit, trade.result,
            wib_iso(trade.opened_at) or "",
            wib_iso(trade.closed_at) or "",
        ])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=trades.csv"})
