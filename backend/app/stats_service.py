from collections import Counter
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Signal, Trade


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
    return {
        "signals_total": sum(status_counts.values()),
        "signals_executed": status_counts["EXECUTED"],
        "signals_rejected": status_counts["REJECTED"] + status_counts["FAILED"],
        "signals_ignored": status_counts["IGNORED"],
        **trade_stats,
    }
