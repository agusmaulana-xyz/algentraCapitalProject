import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ClientUser, MasterCopyPosition, MasterCopyState, MT5Account, utc_now
from ..schemas import MT5AccountActive, MT5AccountCreate, MT5AccountUpdate
from ..security import csrf_token, require_csrf


router = APIRouter(prefix="/api/mt5", tags=["mt5"])
MAX_ACCOUNTS_PER_USER = 10
MASTER_SNAPSHOT_MAX_AGE = timedelta(seconds=20)
FOLLOWER_ONLINE_MAX_AGE = timedelta(seconds=30)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _master_source_is_online(db: Session, now: datetime | None = None) -> bool:
    now = now or utc_now()
    state = db.get(MasterCopyState, 1)
    return bool(
        state
        and state.last_snapshot_at
        and now - _aware(state.last_snapshot_at) <= MASTER_SNAPSHOT_MAX_AGE
    )


def _account_payload(account: MT5Account, master_online: bool = False) -> dict[str, object]:
    now = utc_now()
    follower_online = bool(
        account.active
        and account.last_seen_at
        and now - _aware(account.last_seen_at) <= FOLLOWER_ONLINE_MAX_AGE
    )
    if not account.active:
        connection_status = "disabled"
    elif not follower_online:
        connection_status = "offline"
    elif not master_online:
        connection_status = "waiting_for_source"
    else:
        connection_status = "ready"
    return {
        "id": account.id,
        "label": account.label,
        "server": account.server,
        "login": account.login,
        "role": "follower",
        "active": account.active,
        "last_seen_at": account.last_seen_at.isoformat() if account.last_seen_at else None,
        "connection_status": connection_status,
        "created_at": account.created_at.isoformat(),
    }


def _owned_account(db: Session, owner_id: int, account_id: int) -> MT5Account:
    account = db.execute(
        select(MT5Account).where(MT5Account.id == account_id, MT5Account.owner_id == owner_id)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Akun MT5 tidak ditemukan")
    return account


def require_client_id(request: Request, db: Session = Depends(get_db)) -> int:
    user_id = request.session.get("client_user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Login pengguna diperlukan")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request)
    else:
        csrf_token(request)
    user = db.get(ClientUser, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Login pengguna diperlukan")
    return user.id


def _account_from_token(
    x_account_token: str | None = Header(default=None, alias="X-Account-Token"),
    x_mt5_login: str | None = Header(default=None, alias="X-MT5-Login"),
    x_mt5_server: str | None = Header(default=None, alias="X-MT5-Server"),
    db: Session = Depends(get_db),
) -> MT5Account:
    if not x_account_token or len(x_account_token) < 32:
        raise HTTPException(status_code=401, detail="Token akun tidak valid")
    account = db.execute(
        select(MT5Account).where(MT5Account.token_hash == _token_hash(x_account_token))
    ).scalar_one_or_none()
    if account is None or not account.active:
        raise HTTPException(status_code=401, detail="Token akun tidak valid atau dinonaktifkan")
    if (x_mt5_login or "").strip() != account.login or (x_mt5_server or "").strip().casefold() != account.server.casefold():
        raise HTTPException(status_code=403, detail="Server atau nomor login terminal tidak sesuai dengan akun terdaftar")
    account.last_seen_at = utc_now()
    return account


@router.get("/accounts")
def list_accounts(owner_id: int = Depends(require_client_id), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    # The owner id is taken from the signed client session, never from query input.
    master_online = _master_source_is_online(db)
    return [_account_payload(row, master_online) for row in db.execute(
        select(MT5Account).where(MT5Account.owner_id == owner_id).order_by(MT5Account.id.asc())
    ).scalars()]


@router.post("/accounts")
def create_account(payload: MT5AccountCreate, owner_id: int = Depends(require_client_id), db: Session = Depends(get_db)) -> dict[str, object]:
    count = db.execute(select(MT5Account.id).where(MT5Account.owner_id == owner_id)).all()
    if len(count) >= MAX_ACCOUNTS_PER_USER:
        raise HTTPException(status_code=409, detail=f"Maksimal {MAX_ACCOUNTS_PER_USER} akun MT5 per pengguna")
    token = secrets.token_urlsafe(32)
    label = payload.label.strip()
    server = payload.server.strip()
    login = payload.login.strip()
    if not label or not server or not login:
        raise HTTPException(status_code=422, detail="Nama, server, dan nomor login wajib diisi")
    account = MT5Account(
        owner_id=owner_id,
        label=label,
        server=server,
        login=login,
        role=payload.role,
        token_hash=_token_hash(token),
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Server dan nomor akun tersebut sudah terdaftar") from exc
    db.refresh(account)
    return {"account": _account_payload(account, _master_source_is_online(db)), "token": token}


@router.post("/accounts/{account_id}/rotate-token")
def rotate_token(account_id: int, owner_id: int = Depends(require_client_id), db: Session = Depends(get_db)) -> dict[str, str]:
    account = _owned_account(db, owner_id, account_id)
    token = secrets.token_urlsafe(32)
    account.token_hash = _token_hash(token)
    account.last_seen_at = None
    db.commit()
    return {"token": token}


@router.put("/accounts/{account_id}/active")
def set_active(account_id: int, payload: MT5AccountActive, owner_id: int = Depends(require_client_id), db: Session = Depends(get_db)) -> dict[str, object]:
    account = _owned_account(db, owner_id, account_id)
    if account.active != payload.active:
        account.last_seen_at = None
    account.active = payload.active
    db.commit()
    return _account_payload(account, _master_source_is_online(db))


@router.put("/accounts/{account_id}")
def update_account(
    account_id: int,
    payload: MT5AccountUpdate,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    account = _owned_account(db, owner_id, account_id)
    label, server, login = payload.label.strip(), payload.server.strip(), payload.login.strip()
    if not label or not server or not login:
        raise HTTPException(status_code=422, detail="Nama, server, dan nomor login wajib diisi")
    if account.server.casefold() != server.casefold() or account.login != login:
        account.last_seen_at = None
    account.label, account.server, account.login = label, server, login
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Server dan nomor akun tersebut sudah terdaftar") from exc
    return _account_payload(account, _master_source_is_online(db))


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    account = _owned_account(db, owner_id, account_id)
    db.delete(account)
    db.commit()
    return {"status": "deleted", "id": account_id}


@router.get("/follower/positions")
def follower_positions(
    account: MT5Account = Depends(_account_from_token),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = utc_now()
    fresh = _master_source_is_online(db, now)
    positions: list[dict[str, object]] = []
    if fresh:
        rows = db.execute(select(MasterCopyPosition).where(
            MasterCopyPosition.is_open.is_(True),
        ).order_by(MasterCopyPosition.id.asc())).scalars()
        positions = [{
            "ticket": row.source_ticket,
            "symbol": row.symbol,
            "action": row.action,
            "lots": row.lots,
            "entry_price": row.entry_price,
            "sl": row.sl,
            "tp": row.tp,
        } for row in rows]
    db.commit()
    return {
        "active": fresh,
        "master_label": "Algentra Telegram EA" if fresh else None,
        "positions": positions,
        "server_time": now.isoformat(),
    }


def _aware(value):
    return value.replace(tzinfo=utc_now().tzinfo) if value.tzinfo is None else value
