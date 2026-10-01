import json
from datetime import datetime, time, timezone
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AppSetting, Trade


DEFAULT_CONTROLS = {
    "demo_mode": True,
    "kill_switch": False,
    "max_daily_loss_money": 100.0,
    "max_lot": 5.0,
    "max_open_trades": 3,
    "max_signal_age_seconds": 120,
    "max_market_deviation_pct": 5.0,
    "allowed_symbols": [],
}


def setting_value(db: Session, key: str, default):
    row = db.get(AppSetting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return default


def risk_state(db: Session, now: datetime | None = None) -> dict[str, object]:
    controls = {key: setting_value(db, key, value) for key, value in DEFAULT_CONTROLS.items()}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start_of_day = datetime.combine(now.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    daily_profit = float(db.execute(
        select(func.coalesce(func.sum(Trade.profit), 0.0)).where(
            Trade.closed_at.is_not(None),
            Trade.closed_at >= start_of_day,
        )
    ).scalar_one() or 0.0)
    open_trades = int(db.execute(
        select(func.count(Trade.id)).where(Trade.opened_at.is_not(None), Trade.closed_at.is_(None))
    ).scalar_one() or 0)

    max_daily_loss = controls["max_daily_loss_money"]
    max_daily_loss = float(max_daily_loss) if isinstance(max_daily_loss, (int, float)) and not isinstance(max_daily_loss, bool) and math.isfinite(max_daily_loss) and 0 <= max_daily_loss <= 10_000_000 else 100.0
    max_open_trades = controls["max_open_trades"]
    max_open_trades = int(max_open_trades) if isinstance(max_open_trades, int) and not isinstance(max_open_trades, bool) and 1 <= max_open_trades <= 100 else 3
    raw_max_lot = controls["max_lot"]
    max_lot = float(raw_max_lot) if isinstance(raw_max_lot, (int, float)) and not isinstance(raw_max_lot, bool) and math.isfinite(raw_max_lot) and 0.01 <= raw_max_lot <= 1000 else 5.0
    raw_max_age = controls["max_signal_age_seconds"]
    max_signal_age = int(raw_max_age) if isinstance(raw_max_age, int) and not isinstance(raw_max_age, bool) and 0 <= raw_max_age <= 86400 else 120
    raw_deviation = controls["max_market_deviation_pct"]
    max_deviation = float(raw_deviation) if isinstance(raw_deviation, (int, float)) and not isinstance(raw_deviation, bool) and math.isfinite(raw_deviation) and 0.1 <= raw_deviation <= 100 else 5.0
    allowed = controls["allowed_symbols"]
    allowed = sorted({symbol.upper() for symbol in allowed if isinstance(symbol, str)}) if isinstance(allowed, list) else []
    kill_switch = controls["kill_switch"] is True
    demo_mode = controls["demo_mode"] is not False
    daily_loss = max(0.0, -daily_profit)
    daily_loss_reached = max_daily_loss > 0 and daily_loss >= max_daily_loss
    max_open_reached = max_open_trades > 0 and open_trades >= max_open_trades

    controls.update({
        "demo_mode": demo_mode,
        "kill_switch": kill_switch,
        "max_daily_loss_money": max_daily_loss,
        "daily_profit": round(daily_profit, 2),
        "daily_loss": round(daily_loss, 2),
        "daily_loss_reached": daily_loss_reached,
        "max_lot": max_lot,
        "max_open_trades": max_open_trades,
        "open_trades": open_trades,
        "max_open_reached": max_open_reached,
        "max_signal_age_seconds": max_signal_age,
        "max_market_deviation_pct": max_deviation,
        "allowed_symbols": allowed,
        "trading_paused": kill_switch or daily_loss_reached or max_open_reached,
    })
    return controls
