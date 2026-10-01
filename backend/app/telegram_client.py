import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError

from .config import PROJECT_ROOT, Settings, get_settings
from .database import SessionLocal
from .models import ChatGroup, Signal, SystemLog
from .signal_service import SignalService


logger = logging.getLogger("copytrade.telegram")


class TelegramManager:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
        session_path: Path | None = None,
        processor: SignalService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory or TelegramClient
        self.session_factory = session_factory
        self.session_path = session_path or PROJECT_ROOT / "backend" / "data" / "telegram_user"
        self.processor = processor
        self.client = None
        self.pending_phone: str | None = None
        self.phone_code_hash: str | None = None
        self.awaiting_2fa = False
        self.account_name: str | None = None
        self._handler_bound = False
        self._monitor_task: asyncio.Task | None = None
        self._auth_lock = asyncio.Lock()

    def _secure_session_files(self) -> None:
        if os.name != "nt":
            try:
                self.session_path.parent.chmod(0o700)
            except OSError:
                logger.warning("Could not restrict Telegram session directory permissions")
            for suffix in (".session", ".session-journal", ".session-wal", ".session-shm"):
                path = self.session_path.with_suffix(suffix)
                if path.exists():
                    try:
                        path.chmod(0o600)
                    except OSError:
                        logger.warning("Could not restrict Telegram session file permissions")

    @property
    def configured(self) -> bool:
        return self.settings.telegram_api_id is not None and self.settings.telegram_api_hash is not None

    def set_processor(self, processor: SignalService) -> None:
        self.processor = processor

    def _ensure_configured(self) -> None:
        if not self.configured:
            raise RuntimeError("TELEGRAM_API_ID dan TELEGRAM_API_HASH belum dikonfigurasi di .env")

    def _get_client(self):
        self._ensure_configured()
        if self.client is None:
            self.session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                self.session_path.parent.chmod(0o700)
            api_hash = self.settings.telegram_api_hash.get_secret_value()
            self.client = self.client_factory(
                str(self.session_path),
                self.settings.telegram_api_id,
                api_hash,
                auto_reconnect=True,
                request_retries=3,
                connection_retries=3,
                retry_delay=1,
                flood_sleep_threshold=60,
            )
        return self.client

    async def _connect(self):
        client = self._get_client()
        if not client.is_connected():
            await client.connect()
        return client

    async def send_code(self, phone: str) -> dict[str, object]:
        self._ensure_configured()
        normalized_phone = phone.strip()
        if len(normalized_phone) < 7 or len(normalized_phone) > 24 or not normalized_phone.startswith("+"):
            raise ValueError("Nomor telepon harus dalam format internasional, contoh +628123456789")
        async with self._auth_lock:
            client = await self._connect()
            sent = await client.send_code_request(normalized_phone)
            self.pending_phone = normalized_phone
            self.phone_code_hash = sent.phone_code_hash
            self.awaiting_2fa = False
        masked = normalized_phone[:3] + "••••" + normalized_phone[-3:]
        return {"status": "code_sent", "phone": masked, "requires_2fa": False}

    async def verify_code(self, code: str) -> dict[str, object]:
        if not self.pending_phone or not self.phone_code_hash:
            raise ValueError("Minta kode Telegram terlebih dahulu")
        async with self._auth_lock:
            try:
                await self.client.sign_in(
                    phone=self.pending_phone,
                    code=code.strip(),
                    phone_code_hash=self.phone_code_hash,
                )
            except SessionPasswordNeededError:
                self.awaiting_2fa = True
                return {"status": "two_factor_required", "requires_2fa": True}
            return await self._finish_login()

    async def verify_2fa(self, password: str) -> dict[str, object]:
        if not self.pending_phone or not self.awaiting_2fa:
            raise ValueError("Login belum meminta password 2FA")
        async with self._auth_lock:
            await self.client.sign_in(password=password)
            return await self._finish_login()

    async def _finish_login(self) -> dict[str, object]:
        me = await self.client.get_me()
        if me is None:
            raise RuntimeError("Telegram tidak mengembalikan profil akun")
        first = getattr(me, "first_name", "") or ""
        last = getattr(me, "last_name", "") or ""
        self.account_name = " ".join(value for value in (first, last) if value).strip() or getattr(me, "username", None)
        self.pending_phone = None
        self.phone_code_hash = None
        self.awaiting_2fa = False
        self._secure_session_files()
        self._attach_message_handler()
        self._start_monitor()
        return {"status": "connected", "requires_2fa": False, "account_name": self.account_name}

    def _attach_message_handler(self) -> None:
        if self.client is not None and not self._handler_bound and self.processor is not None:
            self.client.add_event_handler(self._on_new_message, events.NewMessage(incoming=True))
            self._handler_bound = True

    def _start_monitor(self) -> None:
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._reconnect_loop(), name="telegram-reconnect")

    async def _reconnect_loop(self) -> None:
        delay = 2
        while True:
            try:
                if not self.client.is_connected():
                    await self.client.connect()
                if self.client.is_connected() and await self.client.is_user_authorized():
                    self._attach_message_handler()
                delay = 2
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                raise
            except FloodWaitError as exc:
                await asyncio.sleep(min(max(exc.seconds, 1), 3600))
            except Exception as exc:
                logger.warning("Telegram reconnect failed (%s); retrying in %s seconds", type(exc).__name__, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def startup(self) -> None:
        if not self.configured or not self.session_path.with_suffix(".session").exists():
            return
        try:
            client = await self._connect()
            if await client.is_user_authorized():
                self._secure_session_files()
                me = await client.get_me()
                self.account_name = " ".join(
                    part for part in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if part
                ) or getattr(me, "username", None)
                self._attach_message_handler()
                self._start_monitor()
        except FloodWaitError as exc:
            logger.warning("Telegram startup delayed by FloodWait (%s seconds)", exc.seconds)
        except Exception as exc:
            logger.warning("Telegram startup reconnect failed (%s)", type(exc).__name__)

    async def shutdown(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if self.client is not None and self.client.is_connected():
            await self.client.disconnect()
        self._secure_session_files()
        self._handler_bound = False

    async def reconnect(self) -> dict[str, object]:
        client = await self._connect()
        if not await client.is_user_authorized():
            return {"status": "disconnected", "connected": False, "account_name": None}
        await self._finish_login()
        return {"status": "connected", "connected": True, "account_name": self.account_name}

    async def logout(self) -> dict[str, str]:
        client = self.client
        self.pending_phone = None
        self.phone_code_hash = None
        self.awaiting_2fa = False
        self.account_name = None
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if client is not None:
            if client.is_connected() and await client.is_user_authorized():
                await client.log_out()
            if client.is_connected():
                await client.disconnect()
        self.client = None
        self._handler_bound = False
        return {"status": "logged_out"}

    async def status(self) -> dict[str, object]:
        connected = bool(self.client and self.client.is_connected())
        if connected:
            try:
                connected = await self.client.is_user_authorized()
            except Exception:
                connected = False
        state = "connected" if connected else "awaiting_2fa" if self.awaiting_2fa else "awaiting_code" if self.pending_phone else "disconnected"
        return {
            "configured": self.configured,
            "connected": connected,
            "state": state,
            "account_name": self.account_name if connected else None,
        }

    async def get_groups(self) -> list[dict[str, object]]:
        if self.client is None or not self.client.is_connected() or not await self.client.is_user_authorized():
            raise RuntimeError("Telegram belum terhubung")
        dialogs = await self.client.get_dialogs()
        groups = []
        for dialog in dialogs:
            if not (getattr(dialog, "is_group", False) or getattr(dialog, "is_channel", False)):
                continue
            entity = getattr(dialog, "entity", None)
            groups.append({
                "chat_id": str(dialog.id),
                "name": getattr(dialog, "name", None) or getattr(entity, "title", "Telegram group"),
                "username": getattr(entity, "username", None),
            })
        return groups

    async def _on_new_message(self, event) -> None:
        if self.processor is None or event.chat_id is None:
            return
        chat_id = str(event.chat_id)
        with self.session_factory() as db:
            group = db.get(ChatGroup, chat_id)
            if group is None or not group.enabled:
                return
            display_name = group.alias or group.name
            recent = db.execute(
                select(Signal.raw_text)
                .where(Signal.group_id == chat_id)
                .order_by(Signal.created_at.desc(), Signal.id.desc())
                .limit(5)
            ).scalars().all()

        message = event.message
        raw_text = (getattr(message, "raw_text", None) or getattr(message, "message", None) or "").strip()
        if not raw_text:
            return
        context_parts = list(reversed([text for text in recent if text]))
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            try:
                reply = await message.get_reply_message()
                reply_text = (getattr(reply, "raw_text", None) or "").strip() if reply else ""
                if reply_text and reply_text not in context_parts:
                    context_parts.append(reply_text)
            except Exception as exc:
                logger.info("Could not fetch Telegram reply context (%s)", type(exc).__name__)
        sender_id = getattr(event, "sender_id", None)
        sender_name = None
        try:
            sender = await event.get_sender()
            sender_name = " ".join(
                part for part in (getattr(sender, "first_name", ""), getattr(sender, "last_name", "")) if part
            ) or getattr(sender, "username", None)
        except Exception:
            sender_name = str(sender_id) if sender_id is not None else None
        context = "\n".join(context_parts[-5:]) or None
        try:
            with self.session_factory() as db:
                await self.processor.process_message(
                    db,
                    group_id=chat_id,
                    group_name=display_name,
                    message_id=str(getattr(message, "id", "")),
                    sender_id=str(sender_id) if sender_id is not None else None,
                    sender_name=sender_name,
                    raw_text=raw_text,
                    created_at=getattr(message, "date", None),
                    context=context,
                )
        except Exception as exc:
            logger.exception("Telegram message processing failed (%s)", type(exc).__name__)
            with self.session_factory() as db:
                db.add(SystemLog(level="ERROR", source="Telegram", message=f"Message processing failed: {type(exc).__name__}"))
                db.commit()
