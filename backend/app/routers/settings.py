import json
import math
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
ALLOWED_SETTINGS = {
    "confidence_threshold", "default_symbol", "symbol_mapping", "demo_mode", "allow_updates",
    "kill_switch", "max_daily_loss_money", "max_lot", "max_open_trades",
    "max_signal_age_seconds", "max_market_deviation_pct", "allowed_symbols",
}
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,32}$")


def _validate_setting(key: str, value: object) -> object:
    if key in {"demo_mode", "allow_updates", "kill_switch"}:
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"Setting '{key}' harus boolean")
        return value
    if key in {"confidence_threshold", "max_daily_loss_money", "max_lot", "max_market_deviation_pct"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HTTPException(status_code=422, detail=f"Setting '{key}' harus angka valid")
        ranges = {
            "confidence_threshold": (0.0, 1.0),
            "max_daily_loss_money": (0.0, 10_000_000.0),
            "max_lot": (0.01, 1000.0),
            "max_market_deviation_pct": (0.1, 100.0),
        }
        lower, upper = ranges[key]
        if not lower <= value <= upper:
            raise HTTPException(status_code=422, detail=f"Setting '{key}' di luar rentang {lower} sampai {upper}")
        return float(value)
    if key in {"max_open_trades", "max_signal_age_seconds"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=422, detail=f"Setting '{key}' harus bilangan bulat")
        lower, upper = (1, 100) if key == "max_open_trades" else (0, 86400)
        if not lower <= value <= upper:
            raise HTTPException(status_code=422, detail=f"Setting '{key}' di luar rentang {lower} sampai {upper}")
        return value
    if key == "default_symbol":
        if not isinstance(value, str) or not SYMBOL_PATTERN.fullmatch(value):
            raise HTTPException(status_code=422, detail="default_symbol tidak valid")
        return value.upper()
    if key == "symbol_mapping":
        if not isinstance(value, dict) or len(value) > 100:
            raise HTTPException(status_code=422, detail="symbol_mapping harus objek maksimal 100 pasangan")
        normalized = {}
        for source, target in value.items():
            if not isinstance(source, str) or not isinstance(target, str) or not SYMBOL_PATTERN.fullmatch(source) or not SYMBOL_PATTERN.fullmatch(target):
                raise HTTPException(status_code=422, detail="Semua symbol mapping harus berupa symbol valid")
            normalized[source.upper()] = target.upper()
        return normalized
    if key == "allowed_symbols":
        if not isinstance(value, list) or len(value) > 100 or any(not isinstance(symbol, str) or not SYMBOL_PATTERN.fullmatch(symbol) for symbol in value):
            raise HTTPException(status_code=422, detail="allowed_symbols harus berupa daftar maksimal 100 symbol")
        return sorted({symbol.upper() for symbol in value})
    raise HTTPException(status_code=422, detail=f"Setting '{key}' tidak dikenal")


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
    values = {}
    for item in db.query(AppSetting).all():
        try:
            values[item.key] = json.loads(item.value)
        except (TypeError, json.JSONDecodeError):
            continue
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
        if not payload.api_key.strip() or "\r" in payload.api_key or "\n" in payload.api_key:
            raise HTTPException(status_code=422, detail="API key Gemini tidak valid")
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
        if key not in ALLOWED_SETTINGS:
            raise HTTPException(status_code=422, detail=f"Setting '{key}' tidak dapat diubah dari dashboard")
        normalized = _validate_setting(key, value)
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 10_000:
            raise HTTPException(status_code=422, detail=f"Nilai setting '{key}' terlalu besar")
        item = db.get(AppSetting, key)
        if item is None:
            db.add(AppSetting(key=key, value=encoded))
        else:
            item.value = encoded
    db.commit()
    return {key: _validate_setting(key, value) for key, value in payload.values.items()}
