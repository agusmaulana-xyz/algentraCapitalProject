import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT, get_settings
from ..database import get_db
from ..models import (
    ClientUser,
    MasterCopyState,
    MT5MasterAccountState,
    MT5MasterEquitySample,
    MT5MasterMarketState,
    utc_now,
)
from ..time_utils import as_utc, wib_iso


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
        ("Instagram", settings.contact_instagram, ("instagram.com",), "instagram"),
        ("Grup Telegram", settings.contact_telegram, ("t.me", "telegram.me"), "telegram"),
        ("Admin Telegram", settings.contact_telegram_admin, ("t.me", "telegram.me"), "telegram"),
        ("Facebook", settings.contact_facebook, ("facebook.com", "fb.com"), "facebook"),
        ("LinkedIn", settings.contact_linkedin, ("linkedin.com",), "linkedin"),
        ("X", settings.contact_x, ("x.com", "twitter.com"), "x"),
        ("YouTube", settings.contact_youtube, ("youtube.com", "youtu.be"), "youtube"),
        ("TikTok", settings.contact_tiktok, ("tiktok.com",), "tiktok"),
        ("Website", settings.contact_website, ("algentracapital.my.id",), "website"),
    )
    socials = []
    for label, raw_url, allowed_hosts, icon in social_settings:
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
            path = parsed.path.strip("/")
            if label in {"Instagram", "TikTok", "Admin Telegram"}:
                display = f"@{path.lstrip('@')}"
            elif label == "Website":
                display = parsed.netloc.casefold()
            else:
                display = path
            socials.append({"label": label, "url": safe_url, "icon": icon, "display": display})

    return {
        "contact_person": (settings.contact_person_name or "").strip(),
        "contact_whatsapp": whatsapp,
        "contact_email": email,
        "contact_socials": socials,
    }


@router.get("/api/public/performance")
def public_performance(db: Session = Depends(get_db)) -> dict[str, object]:
    registered_clients = db.execute(select(func.count(ClientUser.id))).scalar_one()
    master_account = db.get(MT5MasterAccountState, 1)
    master_copy_state = db.get(MasterCopyState, 1)
    market_state = db.get(MT5MasterMarketState, 1)
    now = utc_now()
    master_online = bool(
        master_account
        and master_copy_state
        and master_copy_state.last_snapshot_at
        and now - as_utc(master_copy_state.last_snapshot_at) <= timedelta(seconds=20)
        and now - as_utc(master_account.observed_at) <= timedelta(seconds=30)
    )
    market_quotes: list[dict[str, object]] = []
    if market_state is not None:
        try:
            decoded_quotes = json.loads(market_state.quotes_json)
            if isinstance(decoded_quotes, list):
                for quote in decoded_quotes:
                    if not isinstance(quote, dict) or quote.get("symbol") not in {"XAUUSD", "EURUSD", "USDJPY", "GBPUSD"}:
                        continue
                    try:
                        tick_time = datetime.fromtimestamp(int(quote["time_msc"]) / 1000, timezone.utc)
                        market_quotes.append({
                            "symbol": quote["symbol"],
                            "bid": float(quote["bid"]),
                            "ask": float(quote["ask"]),
                            "updated_at": wib_iso(tick_time),
                        })
                    except (KeyError, TypeError, ValueError, OverflowError, OSError):
                        continue
        except (TypeError, json.JSONDecodeError):
            market_quotes = []
    market_quotes_online = bool(
        master_online
        and market_state
        and now - as_utc(market_state.observed_at) <= timedelta(seconds=30)
    )
    equity_samples = db.execute(
        select(MT5MasterEquitySample)
        .where(MT5MasterEquitySample.sample_hour >= now - timedelta(hours=24))
        .order_by(MT5MasterEquitySample.sample_hour.asc())
    ).scalars()
    return {
        "master_account": {
            "available": master_account is not None,
            "online": master_online,
            "equity": master_account.equity if master_account else None,
            "floating_profit": master_account.floating_profit if master_account else None,
            "currency": master_account.currency if master_account else None,
            "trade_mode": master_account.trade_mode if master_account else None,
            "updated_at": wib_iso(master_account.observed_at) if master_account else None,
        },
        "market_quotes": market_quotes,
        "market_quotes_online": market_quotes_online,
        "market_quotes_reported_at": wib_iso(market_state.observed_at) if market_state else None,
        "equity_curve": [{
            "hour": wib_iso(sample.sample_hour),
            "equity": round(sample.equity, 2),
            "currency": sample.currency,
        } for sample in equity_samples],
        "registered_clients": registered_clients,
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
