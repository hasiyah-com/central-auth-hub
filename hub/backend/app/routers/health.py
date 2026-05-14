"""Health check endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter()


@router.get("/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    """Readiness probe — checks DB connectivity."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
