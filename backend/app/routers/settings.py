import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AppSetting
from ..schemas import SettingsUpdate


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def read_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    return {item.key: json.loads(item.value) for item in db.query(AppSetting).all()}


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
