import hashlib
import hmac
import re
import secrets
import smtplib
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password
from ..config import get_settings
from ..database import get_db
from ..email_service import send_verification_code
from ..models import AdminUser, ClientUser, EmailVerification, utc_now
from ..security import (
    AUTH_EXPIRES_SESSION_KEY,
    REMEMBER_CLIENT_MAX_AGE,
    REMEMBER_SESSION_KEY,
    SESSION_DEFAULT_MAX_AGE,
    csrf_token,
    require_csrf,
)
from ..schemas import ClientLoginRequest, LoginRequest, RegisterRequest, VerifyEmailRequest


router = APIRouter(prefix="/api/auth", tags=["auth"])
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _set_session_expiry(request: Request, max_age: int, remember_client: bool = False) -> None:
    request.session[AUTH_EXPIRES_SESSION_KEY] = int(utc_now().timestamp()) + max_age
    request.session[REMEMBER_SESSION_KEY] = remember_client


def _normalized_email(value: str) -> str:
    email = value.strip().casefold()
    if not 3 <= len(email) <= 320 or not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(status_code=422, detail="Format email tidak valid")
    return email


def _verification_hash(email: str, code: str) -> str:
    secret = get_settings().app_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, f"{email}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.get(AdminUser, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username atau password salah")
    request.session.clear()
    request.session["admin_username"] = user.username
    _set_session_expiry(request, SESSION_DEFAULT_MAX_AGE)
    token = csrf_token(request)
    return {"status": "authenticated", "username": user.username, "csrf_token": token}


@router.post("/register", status_code=status.HTTP_202_ACCEPTED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    email = _normalized_email(payload.email)
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Kata sandi maksimal 72 byte")
    if db.execute(select(ClientUser.id).where(ClientUser.email == email)).first():
        return {"status": "verification_sent"}

    settings = get_settings()
    if not settings.email_configured:
        raise HTTPException(status_code=503, detail="Pendaftaran belum tersedia karena email SMTP belum dikonfigurasi")
    now = utc_now()
    pending = db.get(EmailVerification, email)
    if pending and _utc(pending.resend_after) > now:
        return {"status": "verification_sent"}

    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        send_verification_code(settings, email, code)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(status_code=503, detail="Email verifikasi gagal dikirim; coba lagi nanti") from exc

    if pending is None:
        pending = EmailVerification(email=email, code_hash=_verification_hash(email, code), password_hash=hash_password(payload.password),
                                    expires_at=now + timedelta(minutes=10), resend_after=now + timedelta(seconds=60))
        db.add(pending)
    else:
        pending.code_hash = _verification_hash(email, code)
        pending.password_hash = hash_password(payload.password)
        pending.expires_at = now + timedelta(minutes=10)
        pending.resend_after = now + timedelta(seconds=60)
        pending.attempts = 0
    db.commit()
    return {"status": "verification_sent"}


def _utc(value):
    return value.replace(tzinfo=utc_now().tzinfo) if value.tzinfo is None else value


@router.post("/resend-code", status_code=status.HTTP_202_ACCEPTED)
def resend_code(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    email = _normalized_email(payload.email)
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Kata sandi maksimal 72 byte")
    pending = db.get(EmailVerification, email)
    if pending is None or db.execute(select(ClientUser.id).where(ClientUser.email == email)).first():
        return {"status": "verification_sent"}
    now = utc_now()
    if _utc(pending.resend_after) > now:
        raise HTTPException(status_code=429, detail="Tunggu sebelum meminta kode baru")
    settings = get_settings()
    if not settings.email_configured:
        raise HTTPException(status_code=503, detail="Pendaftaran belum tersedia karena email SMTP belum dikonfigurasi")
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        send_verification_code(settings, email, code)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(status_code=503, detail="Email verifikasi gagal dikirim; coba lagi nanti") from exc
    pending.code_hash = _verification_hash(email, code)
    pending.password_hash = hash_password(payload.password)
    pending.expires_at = now + timedelta(minutes=10)
    pending.resend_after = now + timedelta(seconds=60)
    pending.attempts = 0
    db.commit()
    return {"status": "verification_sent"}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    email = _normalized_email(payload.email)
    pending = db.get(EmailVerification, email)
    now = utc_now()
    if pending is None or _utc(pending.expires_at) <= now or pending.attempts >= 5:
        if pending is not None:
            db.delete(pending)
            db.commit()
        raise HTTPException(status_code=400, detail="Kode tidak valid atau kedaluwarsa")
    if not hmac.compare_digest(pending.code_hash, _verification_hash(email, payload.code)):
        pending.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Kode tidak valid atau kedaluwarsa")

    user = db.execute(select(ClientUser).where(ClientUser.email == email)).scalar_one_or_none()
    if user is None:
        user = ClientUser(email=email, password_hash=pending.password_hash, verified_at=now)
        db.add(user)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Akun dengan email tersebut sudah dibuat") from exc
    db.delete(pending)
    db.commit()
    request.session.clear()
    request.session["client_user_id"] = user.id
    _set_session_expiry(request, SESSION_DEFAULT_MAX_AGE)
    return {"status": "verified", "user_id": user.id, "csrf_token": csrf_token(request)}


@router.post("/client-login")
def client_login(payload: ClientLoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    email = _normalized_email(payload.email)
    user = db.execute(select(ClientUser).where(ClientUser.email == email)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email atau kata sandi salah")
    request.session.clear()
    request.session["client_user_id"] = user.id
    max_age = REMEMBER_CLIENT_MAX_AGE if payload.remember_me else SESSION_DEFAULT_MAX_AGE
    _set_session_expiry(request, max_age, remember_client=payload.remember_me)
    return {"status": "authenticated", "user_id": user.id, "csrf_token": csrf_token(request)}


@router.post("/logout")
def logout(request: Request) -> dict[str, str]:
    require_csrf(request)
    request.session.clear()
    return {"status": "logged_out"}
