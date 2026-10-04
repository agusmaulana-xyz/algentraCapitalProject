import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MT5Account, MT5AccountState, MT5HistoryDeal
from .time_utils import as_wib, wib_iso


CLOSING_ENTRIES = {"OUT", "OUT_BY", "INOUT"}
LIVE_REPORT_MAX_AGE_SECONDS = 30


def _open_positions(raw: str) -> set[str]:
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return set()
    return {str(value) for value in values} if isinstance(values, list) else set()


def get_mt5_performance(db: Session, account_ids: list[int]) -> dict[str, object]:
    if not account_ids:
        return {
            "available": False,
            "accounts_total": 0,
            "balance_groups": [],
            "performance_groups": [],
            "updated_at": None,
        }

    now = datetime.now(timezone.utc)
    account_states = db.execute(
        select(MT5Account, MT5AccountState)
        .outerjoin(MT5AccountState, MT5AccountState.account_id == MT5Account.id)
        .where(MT5Account.id.in_(account_ids))
    ).all()
    states_by_id: dict[int, MT5AccountState] = {}
    balance_groups: dict[tuple[str, str], dict[str, object]] = {}
    latest_report: datetime | None = None

    for account, state in account_states:
        if state is None:
            continue
        states_by_id[account.id] = state
        key = (state.trade_mode, state.currency.upper())
        group = balance_groups.setdefault(key, {
            "trade_mode": state.trade_mode,
            "currency": state.currency.upper(),
            "balance": 0.0,
            "equity": 0.0,
            "floating_profit": 0.0,
            "reported_accounts": 0,
            "online_accounts": 0,
            "accounts_total": 0,
            "updated_at": None,
        })
        group["balance"] = float(group["balance"]) + state.balance
        group["equity"] = float(group["equity"]) + state.equity
        group["floating_profit"] = float(group["floating_profit"]) + state.floating_profit
        group["reported_accounts"] = int(group["reported_accounts"]) + 1
        group["accounts_total"] = int(group["accounts_total"]) + 1
        observed_at = state.observed_at.replace(tzinfo=timezone.utc) if state.observed_at.tzinfo is None else state.observed_at.astimezone(timezone.utc)
        account_seen = account.last_seen_at
        if account_seen is not None and account_seen.tzinfo is None:
            account_seen = account_seen.replace(tzinfo=timezone.utc)
        if (
            account.active
            and (now - observed_at).total_seconds() <= LIVE_REPORT_MAX_AGE_SECONDS
            and account_seen is not None
            and (now - account_seen.astimezone(timezone.utc)).total_seconds() <= LIVE_REPORT_MAX_AGE_SECONDS
        ):
            group["online_accounts"] = int(group["online_accounts"]) + 1
        stamp = as_wib(state.observed_at)
        if group["updated_at"] is None or stamp > group["updated_at"]:
            group["updated_at"] = stamp
        if latest_report is None or state.observed_at > latest_report:
            latest_report = state.observed_at

    deals = db.execute(
        select(MT5HistoryDeal)
        .where(MT5HistoryDeal.account_id.in_(account_ids))
        .order_by(MT5HistoryDeal.deal_time_msc.asc(), MT5HistoryDeal.id.asc())
    ).scalars()
    positions: dict[tuple[int, str], list[MT5HistoryDeal]] = defaultdict(list)
    for deal in deals:
        positions[(deal.account_id, deal.position_id)].append(deal)

    performance_groups: dict[tuple[str, str], dict[str, object]] = {}
    for (account_id, position_id), position_deals in positions.items():
        state = states_by_id.get(account_id)
        if state is None or position_id in _open_positions(state.open_position_ids_json):
            continue
        closing = [deal for deal in position_deals if deal.entry in CLOSING_ENTRIES]
        if not closing:
            continue
        net_profit = sum(
            deal.profit + deal.commission + deal.swap + deal.fee
            for deal in position_deals
        )
        key = (state.trade_mode, state.currency.upper())
        group = performance_groups.setdefault(key, {
            "trade_mode": state.trade_mode,
            "currency": state.currency.upper(),
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "break_even": 0,
            "realized_pnl": 0.0,
            "last_closed_at": None,
            "daily_pnl": defaultdict(float),
        })
        closed_at = max(closing, key=lambda deal: deal.deal_time_msc).deal_time
        closed_at_wib = as_wib(closed_at)
        group["closed_trades"] = int(group["closed_trades"]) + 1
        group["realized_pnl"] = float(group["realized_pnl"]) + net_profit
        daily_pnl = group["daily_pnl"]
        daily_pnl[closed_at_wib.date().isoformat()] += net_profit
        if net_profit > 0:
            group["wins"] = int(group["wins"]) + 1
        elif net_profit < 0:
            group["losses"] = int(group["losses"]) + 1
        else:
            group["break_even"] = int(group["break_even"]) + 1
        last_closed_at = group["last_closed_at"]
        if last_closed_at is None or closed_at_wib > last_closed_at:
            group["last_closed_at"] = closed_at_wib

    rendered_performance = []
    for key in sorted(performance_groups):
        group = performance_groups[key]
        wins, losses = int(group["wins"]), int(group["losses"])
        decided = wins + losses
        cumulative = 0.0
        curve = []
        for day, pnl in sorted(group["daily_pnl"].items()):
            cumulative += pnl
            curve.append({"date": day, "pnl": round(cumulative, 2)})
        rendered_performance.append({
            "trade_mode": group["trade_mode"],
            "currency": group["currency"],
            "closed_trades": group["closed_trades"],
            "wins": wins,
            "losses": losses,
            "break_even": group["break_even"],
            "win_rate": round(wins / decided * 100, 2) if decided else 0.0,
            "realized_pnl": round(float(group["realized_pnl"]), 2),
            "last_closed_at": wib_iso(group["last_closed_at"]),
            "curve": curve[-180:],
        })

    rendered_balances = []
    for key in sorted(balance_groups):
        group = balance_groups[key]
        group["balance"] = round(float(group["balance"]), 2)
        group["equity"] = round(float(group["equity"]), 2)
        group["floating_profit"] = round(float(group["floating_profit"]), 2)
        group["updated_at"] = wib_iso(group["updated_at"])
        rendered_balances.append(group)

    return {
        "available": bool(rendered_balances or rendered_performance),
        "accounts_total": len(account_ids),
        "accounts_reporting": sum(int(group["reported_accounts"]) for group in rendered_balances),
        "balance_groups": rendered_balances,
        "performance_groups": rendered_performance,
        "updated_at": wib_iso(latest_report),
    }
