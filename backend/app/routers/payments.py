import logging
import mimetypes
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..client_plans import CLIENT_PLANS
from ..config import PROJECT_ROOT
from ..database import get_db
from ..models import ClientUser, MT5Account, PaymentOrder, utc_now
from ..payment_bot import MAX_PROOF_BYTES, payment_proof_path, payment_review_bot
from ..routers.mt5 import _managed_worker_online, require_client_id
from ..time_utils import wib_iso


logger = logging.getLogger("copytrade.payments")
router = APIRouter(prefix="/api/payments", tags=["payments"])
ACTIVE_ORDER_STATUSES = ("PENDING_PAYMENT", "PAYMENT_SUBMITTED")
MAX_ACCOUNTS_PER_USER = 10


class PaymentOrderCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    server: str = Field(min_length=1, max_length=128)
    login: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    plan: str = Field(pattern=r"^(ZERO|PRO|EXPERT)$")
    execution_mode: Literal["EA", "MANAGED"] = "EA"


def _order_payload(order: PaymentOrder) -> dict[str, object]:
    return {
        "id": order.id,
        "email": order.email,
        "label": order.label,
        "server": order.server,
        "login": order.login,
        "plan": order.plan,
        "execution_mode": order.execution_mode,
        "total_idr": order.total_idr,
        "status": order.status,
        "has_proof": order.proof_filename is not None,
        "account_id": order.account_id,
        "notification_sent": order.admin_notified_at is not None,
        "created_at": wib_iso(order.created_at),
        "updated_at": wib_iso(order.updated_at),
    }


def _proof_kind(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/orders")
def list_payment_orders(owner_id: int = Depends(require_client_id), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    orders = db.execute(
        select(PaymentOrder)
        .where(PaymentOrder.owner_id == owner_id)
        .order_by(PaymentOrder.id.desc())
        .limit(20)
    ).scalars()
    return [_order_payload(order) for order in orders]


@router.get("/orders/{order_id}/proof")
def view_payment_proof(
    order_id: int,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> FileResponse:
    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.owner_id == owner_id)
    ).scalar_one_or_none()
    if order is None or not order.proof_filename:
        raise HTTPException(status_code=404, detail="Nota atau bukti pembayaran tidak ditemukan")
    proof_path = payment_proof_path(order.proof_filename)
    if not proof_path.is_file():
        raise HTTPException(status_code=404, detail="File bukti pembayaran tidak tersedia")
    media_type = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        proof_path.suffix.casefold(), "application/octet-stream"
    )
    return FileResponse(
        proof_path,
        media_type=media_type,
        headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"},
    )


@router.post("/orders", status_code=201)
def create_payment_order(
    payload: PaymentOrderCreate,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    label, server, login = payload.label.strip(), payload.server.strip(), payload.login.strip()
    if not label or not server or not login:
        raise HTTPException(status_code=422, detail="Nama akun, server, dan nomor login wajib diisi")
    plan = CLIENT_PLANS[payload.plan]

    # Serialize order creation so simultaneous tabs cannot exceed the account limit.
    db.execute(text("BEGIN IMMEDIATE"))
    if payload.execution_mode == "MANAGED" and not _managed_worker_online(db):
        db.rollback()
        raise HTTPException(status_code=409, detail="Layanan managed copy belum tersedia atau worker sedang offline")
    user = db.get(ClientUser, owner_id)
    if user is None:
        db.rollback()
        raise HTTPException(status_code=401, detail="Login pengguna diperlukan")
    account_count = db.execute(
        select(func.count(MT5Account.id)).where(MT5Account.owner_id == owner_id)
    ).scalar_one()
    open_order_count = db.execute(
        select(func.count(PaymentOrder.id)).where(
            PaymentOrder.owner_id == owner_id,
            PaymentOrder.status.in_(ACTIVE_ORDER_STATUSES),
        )
    ).scalar_one()
    if account_count + open_order_count >= MAX_ACCOUNTS_PER_USER:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Maksimal {MAX_ACCOUNTS_PER_USER} akun atau pesanan aktif per pengguna")

    duplicate_account = db.execute(
        select(MT5Account.id).where(
            MT5Account.owner_id == owner_id,
            func.lower(MT5Account.server) == server.casefold(),
            MT5Account.login == login,
        )
    ).scalar_one_or_none()
    duplicate_order = db.execute(
        select(PaymentOrder.id).where(
            PaymentOrder.owner_id == owner_id,
            func.lower(PaymentOrder.server) == server.casefold(),
            PaymentOrder.login == login,
            PaymentOrder.status.in_(ACTIVE_ORDER_STATUSES),
        )
    ).scalar_one_or_none()
    if payload.execution_mode == "MANAGED":
        duplicate_managed_account = db.execute(
            select(MT5Account.id).where(
                MT5Account.execution_mode == "MANAGED",
                func.lower(MT5Account.server) == server.casefold(),
                MT5Account.login == login,
            )
        ).scalar_one_or_none()
        if duplicate_managed_account is not None:
            db.rollback()
            raise HTTPException(status_code=409, detail="Akun broker ini sudah terdaftar untuk layanan copy server")
        duplicate_managed_order = db.execute(
            select(PaymentOrder.id).where(
                PaymentOrder.execution_mode == "MANAGED",
                func.lower(PaymentOrder.server) == server.casefold(),
                PaymentOrder.login == login,
                PaymentOrder.status.in_(ACTIVE_ORDER_STATUSES),
            )
        ).scalar_one_or_none()
        if duplicate_managed_order is not None:
            db.rollback()
            raise HTTPException(status_code=409, detail="Akun broker ini sudah memiliki pesanan layanan copy server")
    if duplicate_account is not None or duplicate_order is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Server dan nomor login ini sudah terdaftar atau memiliki pesanan aktif")

    order = PaymentOrder(
        owner_id=owner_id,
        email=user.email,
        label=label,
        server=server,
        login=login,
        plan=payload.plan,
        execution_mode=payload.execution_mode,
        total_idr=plan["price_idr"],
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pesanan tidak dapat dibuat. Periksa server dan nomor login.") from exc
    db.refresh(order)
    return _order_payload(order)


@router.post("/orders/{order_id}/cancel")
def cancel_payment_order(
    order_id: int,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    db.execute(text("BEGIN IMMEDIATE"))
    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.owner_id == owner_id)
    ).scalar_one_or_none()
    if order is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order.status not in ACTIVE_ORDER_STATUSES:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pesanan ini tidak bisa dibatalkan")
    old_proof = payment_proof_path(order.proof_filename) if order.proof_filename else None
    order.status = "CANCELLED"
    order.updated_at = utc_now()
    db.commit()
    if old_proof is not None:
        try:
            old_proof.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove cancelled payment proof (%s)", type(exc).__name__)
    return _order_payload(order)


@router.post("/orders/{order_id}/proof")
async def submit_payment_proof(
    order_id: int,
    file: UploadFile = File(...),
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.owner_id == owner_id)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order.status != "PENDING_PAYMENT":
        raise HTTPException(status_code=409, detail="Bukti hanya dapat dikirim untuk pesanan yang menunggu pembayaran")

    content = await file.read(MAX_PROOF_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="File bukti transaksi kosong")
    if len(content) > MAX_PROOF_BYTES:
        raise HTTPException(status_code=413, detail="Ukuran bukti transaksi maksimal 5 MB")
    detected_type = _proof_kind(content)
    if detected_type is None or file.content_type != detected_type:
        raise HTTPException(status_code=415, detail="Gunakan gambar bukti transaksi JPG, PNG, atau WebP")

    # Re-check under a write lock so a concurrent cancel or duplicate upload cannot win.
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))
    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.owner_id == owner_id)
    ).scalar_one_or_none()
    if order is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order.status != "PENDING_PAYMENT":
        db.rollback()
        raise HTTPException(status_code=409, detail="Bukti hanya dapat dikirim untuk pesanan yang menunggu pembayaran")

    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[detected_type]
    filename = f"{order.id}-{secrets.token_urlsafe(18)}.{extension}"
    destination = payment_proof_path(filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    order.proof_filename = filename
    order.status = "PAYMENT_SUBMITTED"
    order.updated_at = utc_now()
    try:
        db.commit()
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    db.refresh(order)
    notification_sent = await payment_review_bot.notify_order(order.id)
    payload = _order_payload(order)
    payload["notification_sent"] = notification_sent
    return payload


@router.post("/orders/{order_id}/notify")
async def retry_admin_notification(
    order_id: int,
    owner_id: int = Depends(require_client_id),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    order = db.execute(
        select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.owner_id == owner_id)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Pesanan tidak ditemukan")
    if order.status != "PAYMENT_SUBMITTED":
        raise HTTPException(status_code=409, detail="Pesanan tidak sedang menunggu pemeriksaan pembayaran")
    if order.admin_notified_at is not None:
        return {"notification_sent": True}
    return {"notification_sent": await payment_review_bot.notify_order(order_id)}


@router.get("/qris.jpeg", include_in_schema=False)
def qris_image() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "backend" / "app" / "static" / "qris.jpeg",
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )
