import json
from datetime import datetime, timezone
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AppSetting, Trade
from .time_utils import WIB, as_utc, wib_day_start_utc_naive


DEFAULT_CONTROLS = {
    "kill_switch": False,
    "max_market_deviation_pct": 5.0,
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
    now = as_utc(now)
    start_of_day = wib_day_start_utc_naive(now.astimezone(WIB).date())
    daily_profit = float(db.execute(
        select(func.coalesce(func.sum(Trade.profit), 0.0)).where(
            Trade.closed_at.is_not(None),
            Trade.closed_at >= start_of_day,
        )
    ).scalar_one() or 0.0)
    open_trades = int(db.execute(
        select(func.count(Trade.id)).where(Trade.opened_at.is_not(None), Trade.closed_at.is_(None))
    ).scalar_one() or 0)

    raw_deviation = controls["max_market_deviation_pct"]
    max_deviation = float(raw_deviation) if isinstance(raw_deviation, (int, float)) and not isinstance(raw_deviation, bool) and math.isfinite(raw_deviation) and 0.1 <= raw_deviation <= 100 else 5.0
    kill_switch = controls["kill_switch"] is True
    daily_loss = max(0.0, -daily_profit)

    controls.update({
        "kill_switch": kill_switch,
        "daily_profit": round(daily_profit, 2),
        "daily_loss": round(daily_loss, 2),
        "open_trades": open_trades,
        "max_market_deviation_pct": max_deviation,
        "trading_paused": kill_switch,
    })
    return controls
