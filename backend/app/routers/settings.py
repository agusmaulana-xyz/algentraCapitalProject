import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from dotenv import set_key

from ..config import PROJECT_ROOT, get_settings
from ..database import get_db
from ..gemini_parser import GeminiParser
from ..models import AppSetting
from ..schemas import SettingsUpdate


router = APIRouter(prefix="/api/settings", tags=["settings"])


class GeminiConfigUpdate(BaseModel):
    api_key: str | None = Field(default=None, min_length=20, max_length=1024)
    model: str | None = Field(default=None, min_length=2, max_length=100)

    @model_validator(mode="after")
    def validate_model_name(self):
        if self.model is not None and not re.fullmatch(r"[A-Za-z0-9._-]+", self.model):
            raise ValueError("Nama model hanya boleh berisi huruf, angka, titik, garis bawah, dan tanda hubung")
        if self.api_key is None and self.model is None:
            raise ValueError("Isi api_key atau model")
        return self


@router.get("")
def read_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    values = {item.key: json.loads(item.value) for item in db.query(AppSetting).all()}
    config = get_settings()
    values["gemini_configured"] = bool(config.gemini_api_key and config.gemini_api_key.get_secret_value())
    values["gemini_model"] = config.gemini_model
    return values


@router.put("/gemini-config")
def update_gemini_config(payload: GeminiConfigUpdate) -> dict[str, object]:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        raise HTTPException(status_code=409, detail="Buat file .env dari .env.example terlebih dahulu")
    if payload.api_key is not None:
        set_key(str(env_path), "GEMINI_API_KEY", payload.api_key, quote_mode="always")
    if payload.model is not None:
        set_key(str(env_path), "GEMINI_MODEL", payload.model, quote_mode="always")
    get_settings.cache_clear()
    GeminiParser.reload_instances()
    config = get_settings()
    return {"gemini_configured": bool(config.gemini_api_key and config.gemini_api_key.get_secret_value()), "gemini_model": config.gemini_model}


@router.put("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    if len(payload.values) > 100:
        raise HTTPException(status_code=422, detail="Maksimal 100 setting per permintaan")
    for key, value in payload.values.items():
        if not key.strip() or len(key) > 128:
            raise HTTPException(status_code=422, detail="Nama setting harus berisi 1-128 karakter")
        if any(part in key.casefold() for part in ("key", "secret", "password", "token")):
            raise HTTPException(status_code=422, detail="Rahasia harus disimpan di environment, bukan settings database")
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded) > 10_000:
            raise HTTPException(status_code=422, detail=f"Nilai setting '{key}' terlalu besar")
        item = db.get(AppSetting, key)
        if item is None:
            db.add(AppSetting(key=key, value=encoded))
        else:
            item.value = encoded
    db.commit()
    return payload.values
