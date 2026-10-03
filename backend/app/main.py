from contextlib import asynccontextmanager
import asyncio

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware
from urllib.parse import urlsplit

from .auth import seed_admin
from .config import PROJECT_ROOT, get_settings
from .database import Base, SessionLocal, engine, migrate_schema
from .models import AppSetting, Signal
from .routers import auth, dashboard, ea, parser as parser_router, public as public_router, settings, tg as tg_router
from .signal_service import SignalService
from .security import RateLimitMiddleware, csrf_token, require_csrf
from .stats_service import get_dashboard_stats


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


app = FastAPI(title="Algentra Capital", version="0.2.0", lifespan=lifespan)
config = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=config.app_secret_key.get_secret_value(),
    session_cookie="copytrade_admin_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=config.cookie_secure,
)
app.add_middleware(RateLimitMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error_response(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not echo submitted passwords, API keys, Telegram OTPs, or 2FA values.
    errors = [
        {"loc": error.get("loc", ()), "msg": error.get("msg", "Input tidak valid"), "type": error.get("type", "value_error")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "app" / "templates"))
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "algentra-capital"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="login.html", context={})


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
                "server_time": asyncio.get_running_loop().time(),
            })
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
