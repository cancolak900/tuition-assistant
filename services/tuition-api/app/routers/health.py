"""Liveness and readiness probes (used by docker compose healthchecks)."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", summary="Liveness probe")
def liveness() -> dict[str, str]:
    """The process is up. Does not touch the database."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (checks the database)")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise AppError(503, "DATABASE_UNAVAILABLE", "The database is not reachable.") from exc
    return {"status": "ok", "database": "ok"}
