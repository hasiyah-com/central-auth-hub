"""Health check endpoints."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip
from app.rate_limiter import limiter

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/health/whoami")
@limiter.limit("10/minute")
def whoami(request: Request):
    """🔧 DEBUG ชั่วคราว — วัดว่า client IP จริงเดินทางมาถึง backend ไหม.

    ใช้ตรวจ single-domain mode (Traefik → Next.js rewrite → backend) ว่า hop ที่
    เพิ่มมากลืน X-Forwarded-For หรือเปล่า — เทียบกับ IP จริงของเครื่องที่เปิด.

    **ไม่คืนข้อมูลใด ๆ สู่ public** (ตอบแค่ ok) — ค่าที่วัดได้เขียนลง container log
    อย่างเดียว อ่านที่ Dokploy → Logs. ลบ endpoint นี้ทิ้งได้เมื่อวัดเสร็จ.
    """
    log.warning(
        "[whoami] peer=%s | xff=%r | x-real-ip=%r | resolved=%s | ua=%r",
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-real-ip"),
        get_client_ip(request),
        request.headers.get("user-agent"),
    )
    return {"ok": True}


@router.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    """Readiness probe — checks DB connectivity."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
