from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT
from ..database import get_db
from ..models import Trade


router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "app" / "templates"))


@router.get("/api/public/performance")
def public_performance(db: Session = Depends(get_db)) -> dict[str, object]:
    rows = db.execute(
        select(Trade.profit, Trade.result, Trade.closed_at)
        .where(Trade.closed_at.is_not(None))
        .order_by(Trade.closed_at.asc(), Trade.id.asc())
    ).all()
    wins = sum(1 for _, result, _ in rows if (result or "").upper() == "WIN")
    losses = sum(1 for _, result, _ in rows if (result or "").upper() == "LOSS")
    total_profit = sum(float(profit or 0.0) for profit, _, _ in rows)

    daily: dict[str, float] = defaultdict(float)
    for profit, _, closed_at in rows:
        daily[closed_at.date().isoformat()] += float(profit or 0.0)
    cumulative = 0.0
    curve = []
    for day, profit in sorted(daily.items()):
        cumulative += profit
        curve.append({"date": day, "pnl": round(cumulative, 2)})

    decided = wins + losses
    return {
        "available": bool(rows),
        "scope": "aggregate",
        "closed_trades": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / decided * 100.0, 2) if decided else 0.0,
        "realized_pnl": round(total_profit, 2),
        "curve": curve[-180:],
        "last_updated": rows[-1][2].isoformat() if rows else None,
    }


@router.get("/", response_class=HTMLResponse)
def public_home(request: Request):
    return templates.TemplateResponse(request=request, name="public.html", context={})


@router.get("/performance", response_class=HTMLResponse)
def public_performance_page(request: Request):
    return templates.TemplateResponse(request=request, name="public.html", context={})
