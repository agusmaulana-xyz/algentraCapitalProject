import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..gemini_parser import GeminiParser
from ..models import AppSetting
from ..signal_service import validate_classification


router = APIRouter(prefix="/api/parser", tags=["parser"])
parser = GeminiParser()


class ParserTestRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context: str | None = Field(default=None, max_length=16000)


def _setting(db: Session, key: str, default):
    row = db.get(AppSetting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return default


@router.post("/test")
async def test_parser(payload: ParserTestRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        classification = await parser.parse(payload.message, payload.context)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    mapping = _setting(db, "symbol_mapping", {})
    result = validate_classification(
        classification,
        default_symbol=str(_setting(db, "default_symbol", "XAUUSD")),
        confidence_threshold=float(_setting(db, "confidence_threshold", 0.75)),
        symbol_mapping=mapping if isinstance(mapping, dict) else {},
        allow_updates=bool(_setting(db, "allow_updates", False)),
    )
    return {
        "classification": classification.model_dump(mode="json"),
        "status": result.status,
        "symbol": result.symbol,
        "normalized_text": result.normalized_text,
        "validation_reason": result.reason,
    }
