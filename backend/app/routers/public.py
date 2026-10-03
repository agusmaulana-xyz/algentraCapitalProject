from collections import defaultdict
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT, get_settings
from ..database import get_db
from ..models import ClientUser, Trade


router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "app" / "templates"))


def _public_contact_context() -> dict[str, object]:
    settings = get_settings()
    whatsapp_digits = re.sub(r"\D", "", settings.contact_whatsapp or "")
    whatsapp = whatsapp_digits if 8 <= len(whatsapp_digits) <= 15 else None
    email = (settings.contact_email or "").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        email = ""

    social_settings = (
        ("Instagram", settings.contact_instagram, ("instagram.com",)),
        ("Telegram", settings.contact_telegram, ("t.me", "telegram.me")),
        ("Facebook", settings.contact_facebook, ("facebook.com", "fb.com")),
        ("LinkedIn", settings.contact_linkedin, ("linkedin.com",)),
        ("X", settings.contact_x, ("x.com", "twitter.com")),
        ("YouTube", settings.contact_youtube, ("youtube.com", "youtu.be")),
        ("TikTok", settings.contact_tiktok, ("tiktok.com",)),
    )
    socials = []
    for label, raw_url, allowed_hosts in social_settings:
        url = (raw_url or "").strip()
        safe_url = None
        try:
            parsed = urlsplit(url)
            hostname = (parsed.hostname or "").casefold()
        except ValueError:
            parsed = None
            hostname = ""
        if parsed and (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts)
        ):
            safe_url = url
        if safe_url:
            socials.append({"label": label, "url": safe_url})

    return {
        "contact_person": (settings.contact_person_name or "").strip(),
        "contact_whatsapp": whatsapp,
        "contact_email": email,
        "contact_socials": socials,
    }


@router.get("/api/public/performance")
def public_performance(db: Session = Depends(get_db)) -> dict[str, object]:
    registered_clients = db.execute(select(func.count(ClientUser.id))).scalar_one()
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
        "registered_clients": registered_clients,
        "closed_trades": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / decided * 100.0, 2) if decided else 0.0,
        "realized_pnl": round(total_profit, 2),
        "curve": curve[-180:],
        "last_updated": rows[-1][2].isoformat() if rows else None,
    }


@router.get("/musik.mp3", include_in_schema=False)
def site_music() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "musik.mp3", media_type="audio/mpeg")


@router.get("/", response_class=HTMLResponse)
def public_home(request: Request):
    return templates.TemplateResponse(request=request, name="public.html", context=_public_contact_context())


@router.get("/performance", response_class=HTMLResponse)
def public_performance_page(request: Request):
    return templates.TemplateResponse(request=request, name="public.html", context=_public_contact_context())
