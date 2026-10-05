from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from telethon.errors import FloodWaitError, PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError

from ..database import get_db
from ..models import ChatGroup
from ..telegram_client import TelegramManager


router = APIRouter(prefix="/api/tg", tags=["telegram"])
telegram_manager = TelegramManager()


class SendCodeRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=24)


class VerifyCodeRequest(BaseModel):
    code: str = Field(min_length=3, max_length=12)


class Verify2FARequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class GroupSelection(BaseModel):
    chat_id: str = Field(min_length=1, max_length=128)
    enabled: bool
    alias: str | None = Field(default=None, max_length=255)


class GroupSelectionRequest(BaseModel):
    groups: list[GroupSelection] = Field(max_length=1000)


@router.get("/status")
async def status() -> dict[str, object]:
    return await telegram_manager.status()


@router.post("/send-code")
async def send_code(payload: SendCodeRequest) -> dict[str, object]:
    try:
        return await telegram_manager.send_code(payload.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FloodWaitError as exc:
        raise HTTPException(status_code=429, detail=f"Telegram meminta tunggu {exc.seconds} detik") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gagal meminta kode Telegram ({type(exc).__name__})") from exc


@router.post("/verify-code")
async def verify_code(payload: VerifyCodeRequest) -> dict[str, object]:
    try:
        return await telegram_manager.verify_code(payload.code)
    except SessionPasswordNeededError:
        return {"status": "two_factor_required", "requires_2fa": True}
    except (PhoneCodeExpiredError, PhoneCodeInvalidError) as exc:
        raise HTTPException(status_code=422, detail="Kode Telegram tidak valid atau sudah kedaluwarsa") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FloodWaitError as exc:
        raise HTTPException(status_code=429, detail=f"Telegram meminta tunggu {exc.seconds} detik") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Verifikasi Telegram gagal ({type(exc).__name__})") from exc


@router.post("/verify-2fa")
async def verify_2fa(payload: Verify2FARequest) -> dict[str, object]:
    try:
        return await telegram_manager.verify_2fa(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FloodWaitError as exc:
        raise HTTPException(status_code=429, detail=f"Telegram meminta tunggu {exc.seconds} detik") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Password 2FA Telegram gagal ({type(exc).__name__})") from exc


@router.post("/logout")
async def logout() -> dict[str, str]:
    try:
        return await telegram_manager.logout()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Logout Telegram gagal ({type(exc).__name__})") from exc


@router.post("/reconnect")
async def reconnect() -> dict[str, object]:
    try:
        return await telegram_manager.reconnect()
    except FloodWaitError as exc:
        raise HTTPException(status_code=429, detail=f"Telegram meminta tunggu {exc.seconds} detik") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Reconnect Telegram gagal ({type(exc).__name__})") from exc


@router.get("/groups")
async def groups(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    try:
        available = await telegram_manager.get_groups()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    saved = {row.chat_id: row for row in db.query(ChatGroup).all()}
    return [
        {
            **item,
            "enabled": saved[item["chat_id"]].enabled if item["chat_id"] in saved else False,
            "alias": saved[item["chat_id"]].alias if item["chat_id"] in saved else None,
        }
        for item in available
    ]


@router.post("/groups/select")
async def select_groups(payload: GroupSelectionRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        available = await telegram_manager.get_groups()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    allowed = {item["chat_id"]: item for item in available}
    if len({item.chat_id for item in payload.groups}) != len(payload.groups):
        raise HTTPException(status_code=422, detail="chat_id tidak boleh duplikat")
    submitted_ids = {item.chat_id for item in payload.groups}
    disabled = 0
    for saved in db.query(ChatGroup).all():
        if saved.enabled and saved.chat_id not in submitted_ids:
            saved.enabled = False
            disabled += 1
    for selection in payload.groups:
        if selection.chat_id not in allowed:
            raise HTTPException(status_code=422, detail="Grup harus dipilih dari daftar akun Telegram")
        item = db.get(ChatGroup, selection.chat_id)
        if item is None:
            item = ChatGroup(chat_id=selection.chat_id, name=str(allowed[selection.chat_id]["name"]))
            db.add(item)
        item.enabled = selection.enabled
        item.alias = selection.alias.strip()[:255] if selection.alias and selection.alias.strip() else None
    db.commit()
    return {"saved": len(payload.groups), "disabled": disabled}
