import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.telegram_client as telegram_module
from app.config import Settings
from app.database import Base
from app.models import ChatGroup
from app.telegram_client import TelegramManager


def telegram_settings():
    return Settings(
        _env_file=None,
        APP_SECRET_KEY="m3-telegram-test-secret-key-longer-than-32-chars",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="M3-testing-password-123",
        TELEGRAM_API_ID=12345,
        TELEGRAM_API_HASH="fake-telegram-api-hash",
    )


class FakeClient:
    def __init__(self, *, require_2fa=False):
        self.connected = False
        self.authorized = False
        self.require_2fa = require_2fa
        self.handlers = []
        self.dialogs = []
        self.phone = None
        self.code = None
        self.password = None

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def send_code_request(self, phone):
        self.phone = phone
        return SimpleNamespace(phone_code_hash="mock-code-hash")

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if password is not None:
            self.password = password
            self.authorized = True
        elif self.require_2fa:
            raise telegram_module.SessionPasswordNeededError()
        else:
            self.code = code
            self.authorized = True

    async def get_me(self):
        return SimpleNamespace(first_name="Ayu", last_name="Tester", username="ayu_test")

    def add_event_handler(self, handler, event):
        self.handlers.append((handler, event))

    async def is_user_authorized(self):
        return self.authorized

    async def get_dialogs(self):
        return self.dialogs

    async def log_out(self):
        self.authorized = False
        self.connected = False


class NoMonitorTelegramManager(TelegramManager):
    def _start_monitor(self):
        pass


def test_login_supports_code_and_2fa(monkeypatch, tmp_path):
    class Need2FA(Exception):
        pass

    monkeypatch.setattr(telegram_module, "SessionPasswordNeededError", Need2FA)
    fake = FakeClient(require_2fa=True)
    manager = NoMonitorTelegramManager(
        telegram_settings(),
        client_factory=lambda *args, **kwargs: fake,
        session_path=tmp_path / "telegram_test",
        processor=object(),
    )

    async def exercise():
        sent = await manager.send_code("+628123456789")
        assert sent["status"] == "code_sent"
        assert fake.phone == "+628123456789"
        needed = await manager.verify_code("12345")
        assert needed["requires_2fa"] is True
        connected = await manager.verify_2fa("mock-2fa-password")
        assert connected["account_name"] == "Ayu Tester"
        assert len(fake.handlers) == 1
        state = await manager.status()
        assert state["connected"] is True
        assert await manager.logout() == {"status": "logged_out"}
        assert fake.authorized is False

    asyncio.run(exercise())


def test_group_listing_filters_user_dialogs_and_returns_channel_ids(tmp_path):
    fake = FakeClient()
    fake.authorized = True
    fake.dialogs = [
        SimpleNamespace(id=-10042, name="Signal Room", is_group=True, is_channel=False, entity=SimpleNamespace(title="Signal Room", username="signalroom")),
        SimpleNamespace(id=12, name="Personal chat", is_group=False, is_channel=False, entity=SimpleNamespace(title="Personal chat", username=None)),
        SimpleNamespace(id=-10077, name="Market News", is_group=False, is_channel=True, entity=SimpleNamespace(title="Market News", username="marketnews")),
    ]
    manager = TelegramManager(telegram_settings(), client_factory=lambda *args, **kwargs: fake, session_path=tmp_path / "telegram_test")
    manager.client = fake
    fake.connected = True

    groups = asyncio.run(manager.get_groups())

    assert [group["chat_id"] for group in groups] == ["-10042", "-10077"]
    assert groups[0]["username"] == "signalroom"


def test_listener_processes_only_enabled_whitelisted_groups(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    class RecordingProcessor:
        def __init__(self):
            self.calls = []

        async def process_message(self, db, **kwargs):
            self.calls.append(kwargs)

    class Event:
        chat_id = -10042
        sender_id = 77
        message = SimpleNamespace(
            id=19,
            raw_text="BUY NOW",
            date=datetime(2026, 9, 30, tzinfo=timezone.utc),
            reply_to_msg_id=None,
        )

        async def get_sender(self):
            return SimpleNamespace(first_name="Signal", last_name="Admin", username="signal_admin")

    processor = RecordingProcessor()
    manager = TelegramManager(
        telegram_settings(),
        client_factory=lambda *args, **kwargs: FakeClient(),
        session_factory=session_factory,
        session_path=tmp_path / "telegram_test",
        processor=processor,
    )
    with Session(engine) as db:
        db.add(ChatGroup(chat_id="-10042", name="Room", alias="Gold Room", enabled=False))
        db.commit()

    async def exercise():
        await manager._on_new_message(Event())
        assert processor.calls == []
        with Session(engine) as db:
            group = db.get(ChatGroup, "-10042")
            group.enabled = True
            db.commit()
        await manager._on_new_message(Event())

    asyncio.run(exercise())

    assert len(processor.calls) == 1
    assert processor.calls[0]["group_name"] == "Gold Room"
    assert processor.calls[0]["sender_name"] == "Signal Admin"
    assert processor.calls[0]["message_id"] == "19"
    engine.dispose()
