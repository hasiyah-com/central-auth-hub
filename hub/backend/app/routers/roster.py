"""Roster Sync API — subsystem ดึงรายชื่อผู้ใช้ที่เข้าได้ (S2S, read-only).

Use case: ระบบที่ข้อมูลถูกสร้างก่อน user login (เช่นระบบเกรด) ดึง roster มา
pre-create record ผูกด้วย user_id ล่วงหน้า. ตอน user login → JWT.sub match.

Auth: header ``X-Api-Key`` (ออกตอนลงทะเบียน subsystem). เก็บ Argon2 hash ใน DB,
lookup ด้วย prefix (12 ตัวแรก) แล้ว verify hash เต็ม.

ส่งเฉพาะ 3 field: user_id, email, user_type (ข้อมูลเต็มไหลตอน login ตาม scope).
กรองด้วย Access Policy ของ subsystem (เกณฑ์เดียวกับ login-time).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_client_ip
from app.models import Subsystem
from app.rate_limiter import limiter
from app.services.access_policy import list_allowed_users
from app.services.audit_service import log_action
from app.services.secret_service import verify_secret

router = APIRouter(prefix="/api/v1", tags=["Roster Sync"])


def _authenticate(db: Session, api_key: str | None) -> Subsystem:
    """หา subsystem จาก X-Api-Key — opaque 401 ทุก failure (anti-enumeration)."""
    if not api_key or len(api_key) < 12:
        raise HTTPException(status_code=401, detail="invalid API key")
    prefix = api_key[:12]
    # lookup ด้วย prefix (index) แล้ว verify hash เต็ม (Argon2)
    candidates = (
        db.query(Subsystem)
        .filter(Subsystem.api_key_prefix == prefix, Subsystem.api_key_hash.isnot(None))
        .all()
    )
    for sub in candidates:
        if verify_secret(sub.api_key_hash, api_key):
            return sub
    raise HTTPException(status_code=401, detail="invalid API key")


@router.get("/roster")
@limiter.limit("30/minute")
def get_roster(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    db: Session = Depends(get_db),
):
    """คืนรายชื่อผู้ใช้ที่เข้า subsystem นี้ได้ (ตาม Access Policy).

    Response:
      { "subsystem": "...", "access_policy": "...", "count": N,
        "users": [{"user_id": "<uuid>", "email": "...", "user_type": "..."}] }
    """
    subsystem = _authenticate(db, x_api_key)

    # subsystem ที่ยังไม่ active → ไม่ให้ดึง roster (สอดคล้องกับ login ที่ reject)
    if subsystem.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"subsystem ยังไม่ active (status={subsystem.status})",
        )

    users = list_allowed_users(db, subsystem)

    log_action(
        db,
        actor_id=None,
        action="roster_pulled",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "access_policy": subsystem.access_policy,
            "count": len(users),
            "api_key_prefix": subsystem.api_key_prefix,
        },
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "access_policy": subsystem.access_policy,
        "count": len(users),
        "users": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "user_type": u.user_type,
            }
            for u in users
        ],
    }
