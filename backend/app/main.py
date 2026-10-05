from contextlib import asynccontextmanager
import asyncio
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from urllib.parse import urlsplit

from .auth import seed_admin
from .config import PROJECT_ROOT, get_settings
from .database import Base, SessionLocal, engine, migrate_schema
from .models import AppSetting, Signal, utc_now
from .public_realtime import public_performance_hub
from .routers import auth, dashboard, ea, mt5 as mt5_router, parser as parser_router, public as public_router, settings, tg as tg_router
from .routers.mt5 import require_client_id
from .signal_service import SignalService
from .security import (
    DatabaseSessionMiddleware,
    RateLimitMiddleware,
    SessionExpiryMiddleware,
    csrf_token,
    require_csrf,
)
from .stats_service import get_dashboard_stats
from .time_utils import wib_iso


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate_schema()
    Base.metadata.create_all(bind=engine)
    config = get_settings()
    with SessionLocal() as db:
        seed_admin(db, config)
        defaults = (
            ("demo_mode", "true"),
            ("confidence_threshold", "0.75"),
            ("default_symbol", '"XAUUSD"'),
            ("kill_switch", "false"),
            ("max_daily_loss_money", "100.0"),
            ("max_lot", "5.0"),
            ("max_open_trades", "3"),
            ("max_signal_age_seconds", "120"),
            ("max_market_deviation_pct", "5.0"),
            ("allowed_symbols", "[]"),
            ("allow_updates", "false"),
            ("symbol_mapping", '{"GOLD":"XAUUSD","XAU":"XAUUSD","EMAS":"XAUUSD"}'),
        )
        for key, value in defaults:
            if db.get(AppSetting, key) is None:
                db.add(AppSetting(key=key, value=value))
        db.commit()
    await telegram_manager.startup()
    try:
        yield
    finally:
        await telegram_manager.shutdown()


app = FastAPI(
    title="Algentra Capital",
    version="0.3.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
config = get_settings()
app.add_middleware(SessionExpiryMiddleware)
app.add_middleware(
    DatabaseSessionMiddleware,
    secret_key=config.app_secret_key.get_secret_value(),
    https_only=config.cookie_secure,
)
app.add_middleware(RateLimitMiddleware)


class SecurityHeadersMiddleware:
    """Add browser security protections to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        nonce = secrets.token_urlsafe(18)
        scope.setdefault("state", {})["csp_nonce"] = nonce

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"content-security-policy", f"default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; font-src 'self' data:; connect-src 'self' ws: wss:; script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; style-src 'self' 'nonce-{nonce}'; form-action 'self'".encode("ascii")),
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ])
                if config.cookie_secure:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error_response(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo submitted passwords, API keys, Telegram OTPs, or 2FA values.
    errors = [
        {"loc": error.get("loc", ()), "msg": error.get("msg", "Input tidak valid"), "type": error.get("type", "value_error")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "app" / "templates"))


@app.exception_handler(StarletteHTTPException)
async def http_exception_response(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"requested_path": request.url.path},
            status_code=404,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


signal_service = SignalService()
telegram_manager = tg_router.telegram_manager
telegram_manager.set_processor(signal_service)


def require_admin(request: Request) -> str:
    username = request.session.get("admin_username")
    if not username:
        raise HTTPException(status_code=401, detail="Login admin diperlukan")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request)
    else:
        csrf_token(request)
    return username


app.include_router(auth.router)
app.include_router(public_router.router)
app.include_router(dashboard.router, dependencies=[Depends(require_admin)])
app.include_router(settings.router, dependencies=[Depends(require_admin)])
app.include_router(parser_router.router, dependencies=[Depends(require_admin)])
app.include_router(tg_router.router, dependencies=[Depends(require_admin)])
app.include_router(ea.router)
app.include_router(mt5_router.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "algentra-capital"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if isinstance(request.session.get("client_user_id"), int):
        return RedirectResponse("/account", status_code=303)
    if request.session.get("admin_username"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.get("/loginAdmin", response_class=HTMLResponse, include_in_schema=False)
def admin_login_page(request: Request):
    if request.session.get("admin_username"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="admin_login.html", context={})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="register.html", context={})


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={})


@app.get("/account", response_class=HTMLResponse)
def client_account_page(request: Request, _: int = Depends(require_client_id)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="account.html",
        context={"csrf_token": request.session["csrf_token"]},
    )


@app.get("/downloads/MT5FollowerCopyEA.ex5", response_class=FileResponse, include_in_schema=False)
def download_mt5_follower_copy_ea(_: int = Depends(require_client_id)) -> FileResponse:
    return FileResponse(
        path=PROJECT_ROOT / "mt5" / "MT5FollowerCopyEA.ex5",
        filename="MT5FollowerCopyEA.ex5",
        media_type="application/octet-stream",
    )


@app.get("/downloads/TelegramSignalEA.ex5", response_class=FileResponse, include_in_schema=False)
def download_telegram_signal_ea(_: str = Depends(require_admin)) -> FileResponse:
    return FileResponse(
        path=PROJECT_ROOT / "mt5" / "TelegramSignalEA.ex5",
        filename="TelegramSignalEA.ex5",
        media_type="application/octet-stream",
    )


@app.get("/parser-test", response_class=HTMLResponse)
def parser_test_page(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="parser_test.html", context={"csrf_token": request.session["csrf_token"]})


@app.get("/telegram-setup", response_class=HTMLResponse)
def telegram_setup_page(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="telegram_setup.html", context={"csrf_token": request.session["csrf_token"]})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"csrf_token": request.session["csrf_token"]})


@app.websocket("/ws")
async def dashboard_websocket(websocket: WebSocket) -> None:
    if not websocket.scope.get("session", {}).get("admin_username"):
        await websocket.close(code=1008)
        return
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and urlsplit(origin).netloc.casefold() != host.casefold():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            with SessionLocal() as db:
                stats = get_dashboard_stats(db)
                latest = db.execute(
                    select(Signal.id, Signal.status, Signal.created_at)
                    .order_by(Signal.created_at.desc(), Signal.id.desc())
                    .limit(1)
                ).first()
            await websocket.send_json({
                "type": "dashboard_refresh",
                "stats": stats,
                "latest_signal_id": latest.id if latest else None,
                "server_time": wib_iso(utc_now()),
            })
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return


@app.websocket("/ws/public/performance")
async def public_performance_websocket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and urlsplit(origin).netloc.casefold() != host.casefold():
        await websocket.close(code=1008)
        return

    await public_performance_hub.connect(websocket)
    try:
        with SessionLocal() as db:
            initial_payload = public_router.public_performance_payload(db)
        await websocket.send_json(initial_payload)
        public_performance_hub.mark_history_published()
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        public_performance_hub.disconnect(websocket)
