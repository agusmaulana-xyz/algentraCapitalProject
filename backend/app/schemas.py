from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class ClientLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=72)
    remember_me: bool = False


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=72)


class VerifyEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^\d{6}$")


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetConfirmRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^\d{6}$")
    password: str = Field(min_length=12, max_length=72)


class MT5AccountCreate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    server: str = Field(min_length=1, max_length=128)
    login: str = Field(min_length=1, max_length=32)
    role: Literal["follower"] = "follower"


class MT5AccountUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    server: str = Field(min_length=1, max_length=128)
    login: str = Field(min_length=1, max_length=32)


class MT5AccountActive(BaseModel):
    active: bool


class CopyPositionInput(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=64)
    action: Literal["BUY", "SELL"]
    lots: float = Field(gt=0, le=1000, allow_inf_nan=False)
    entry_price: float = Field(gt=0, allow_inf_nan=False)
    sl: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    tp: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class CopySnapshotInput(BaseModel):
    terminal_login: str = Field(min_length=1, max_length=32)
    terminal_server: str = Field(min_length=1, max_length=128)
    positions: list[CopyPositionInput] = Field(max_length=500)


class SignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: str | None
    group_name: str | None
    message_id: str | None
    sender_id: str | None
    sender_name: str | None
    raw_text: str
    parsed_json: str | None
    normalized_text: str | None
    confidence: float | None
    status: str
    created_at: datetime
    ticket: str | None = None
    profit: float | None = None


class LogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    source: str
    message: str
    created_at: datetime


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
