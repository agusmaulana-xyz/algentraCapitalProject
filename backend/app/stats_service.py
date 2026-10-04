from collections import Counter
from collections.abc import Iterable
from typing import Any

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import ClientUser, EAStatus, Signal, Trade
from .time_utils import as_utc, wib_iso


def calculate_trade_stats(trades: Iterable[Any]) -> dict[str, int | float]:
    wins = 0
    losses = 0
    total_profit = 0.0
    for trade in trades:
        result = (getattr(trade, "result", None) or "").upper()
        profit = getattr(trade, "profit", 0.0)
        total_profit += float(profit or 0.0)
        if result == "WIN":
            wins += 1
        elif result == "LOSS":
            losses += 1

    decided_trades = wins + losses
    winrate = (wins / decided_trades * 100.0) if decided_trades else 0.0
    return {
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 2),
        "total_profit": round(total_profit, 2),
    }


def get_dashboard_stats(db: Session) -> dict[str, int | float]:
    signal_rows = db.execute(select(Signal.status)).scalars().all()
    status_counts = Counter(status.upper() for status in signal_rows)
    trade_stats = calculate_trade_stats(db.execute(select(Trade)).scalars())
    active_clients = db.execute(select(func.count(ClientUser.id))).scalar_one()
    ea = db.get(EAStatus, 1)
    heartbeat = ea.last_heartbeat if ea else None
    if heartbeat is not None:
        heartbeat = as_utc(heartbeat)
        ea_online = bool(ea.active and (datetime.now(timezone.utc) - heartbeat).total_seconds() <= 90)
    else:
        ea_online = False
    return {
        "signals_total": sum(status_counts.values()),
        "signals_executed": status_counts["EXECUTED"],
        "signals_simulated": status_counts["DRY_RUN"],
        "signals_pending": status_counts["PENDING"] + status_counts["CLAIMED"],
        "signals_rejected": status_counts["REJECTED"] + status_counts["FAILED"],
        "signals_ignored": status_counts["IGNORED"],
        "active_clients": active_clients,
        "ea_online": ea_online,
        "ea_last_heartbeat": wib_iso(heartbeat),
        **trade_stats,
    }


def get_group_stats(db: Session) -> list[dict[str, int | float | str | None]]:
    signal_counts = db.execute(
        select(Signal.group_id, Signal.group_name, func.count(Signal.id))
        .group_by(Signal.group_id, Signal.group_name)
    ).all()
    trades = db.execute(
        select(Signal.group_id, Trade.result, Trade.profit)
        .join(Trade, Trade.signal_id == Signal.id)
    ).all()
    grouped: dict[str | None, dict[str, float | int]] = {}
    for group_id, result, profit in trades:
        stats = grouped.setdefault(group_id, {"wins": 0, "losses": 0, "profit": 0.0})
        result = (result or "").upper()
        if result == "WIN":
            stats["wins"] += 1
        elif result == "LOSS":
            stats["losses"] += 1
        stats["profit"] += float(profit or 0.0)

    output = []
    for group_id, group_name, total in signal_counts:
        stats = grouped.get(group_id, {"wins": 0, "losses": 0, "profit": 0.0})
        decided = int(stats["wins"]) + int(stats["losses"])
        output.append({
            "group_id": group_id,
            "group_name": group_name or "Unknown",
            "signals_total": total,
            "wins": int(stats["wins"]),
            "losses": int(stats["losses"]),
            "winrate": round(int(stats["wins"]) / decided * 100.0, 2) if decided else 0.0,
            "profit": round(float(stats["profit"]), 2),
        })
    return sorted(output, key=lambda row: row["signals_total"], reverse=True)
