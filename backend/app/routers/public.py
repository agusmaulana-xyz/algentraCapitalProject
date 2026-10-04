import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT, get_settings
from ..database import get_db
from ..models import ClientUser, MT5Account
from ..mt5_performance import get_mt5_performance


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
    account_ids = list(db.execute(select(MT5Account.id)).scalars())
    return {
        **get_mt5_performance(db, account_ids),
        "scope": "all_client_mt5_accounts",
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
