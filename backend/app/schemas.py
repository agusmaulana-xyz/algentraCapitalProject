from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class SignalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: str | None
    group_name: str | None
    message_id: str | None
    raw_text: str
    parsed_json: str | None
    normalized_text: str | None
    confidence: float | None
    status: str
    created_at: datetime


class LogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    source: str
    message: str
    created_at: datetime


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
