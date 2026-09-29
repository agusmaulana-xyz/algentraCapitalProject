from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import seed_admin
from .config import PROJECT_ROOT, get_settings
from .database import Base, SessionLocal, engine, migrate_schema
from .models import AppSetting
from .routers import auth, dashboard, parser as parser_router, settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate_schema()
    Base.metadata.create_all(bind=engine)
    config = get_settings()
    with SessionLocal() as db:
        seed_admin(db, config)
        defaults = (("demo_mode", "true"), ("confidence_threshold", "0.75"), ("default_symbol", '"XAUUSD"'))
        for key, value in defaults:
            if db.get(AppSetting, key) is None:
                db.add(AppSetting(key=key, value=value))
        db.commit()
    yield


app = FastAPI(title="Telegram Copy Trading Backend", version="0.1.0", lifespan=lifespan)
config = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=config.app_secret_key.get_secret_value(),
    session_cookie="copytrade_admin_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=config.cookie_secure,
)
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "backend" / "app" / "templates"))


def require_admin(request: Request) -> str:
    username = request.session.get("admin_username")
    if not username:
        raise HTTPException(status_code=401, detail="Login admin diperlukan")
    return username


app.include_router(auth.router)
app.include_router(dashboard.router, dependencies=[Depends(require_admin)])
app.include_router(settings.router, dependencies=[Depends(require_admin)])
app.include_router(parser_router.router, dependencies=[Depends(require_admin)])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "telegram-copy-trading"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.get("/parser-test", response_class=HTMLResponse)
def parser_test_page(request: Request, _: str = Depends(require_admin)) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="parser_test.html", context={})


@app.get("/")
def root(_: str = Depends(require_admin)) -> dict[str, str]:
    return {"status": "authenticated", "message": "Backend M1 siap. Dashboard lengkap menyusul pada M5."}
