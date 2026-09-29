from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Signal, SystemLog
from ..schemas import LogResponse, SignalResponse
from ..stats_service import get_dashboard_stats


router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict[str, int | float]:
    return get_dashboard_stats(db)


@router.get("/signals", response_model=list[SignalResponse])
def signals(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Signal]:
    query = select(Signal).order_by(Signal.created_at.desc(), Signal.id.desc()).offset(offset).limit(limit)
    return list(db.execute(query).scalars())


@router.get("/logs", response_model=list[LogResponse])
def logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    level: str | None = Query(default=None, min_length=1, max_length=16),
    search: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> list[SystemLog]:
    query = select(SystemLog)
    if level:
        query = query.where(SystemLog.level == level.upper())
    if search:
        query = query.where(SystemLog.message.contains(search))
    query = query.order_by(SystemLog.created_at.desc(), SystemLog.id.desc()).offset(offset).limit(limit)
    return list(db.execute(query).scalars())
