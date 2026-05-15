"""Secret retrieval router — one-time link สำหรับดู client_secret.

Flow:
  1. ตอน register subsystem ระบบสร้าง token + encrypt secret เก็บไว้
  2. ส่ง URL ?token=xxx ให้ developer (จริง: ทาง email)
  3. Developer เปิด URL -> เห็น client_secret ครั้งเดียว
  4. ระบบ mark used + ลบ encrypted secret ทันที
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SecretRetrievalToken, Subsystem
from app.services.audit_service import log_action
from app.services.secret_service import decrypt_secret

router = APIRouter()


@router.get("/retrieve")
def retrieve_secret(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """ดู client_secret ผ่าน one-time link.

    เงื่อนไขความปลอดภัย:
      - ลิงก์ใช้ได้ครั้งเดียว (used_at ต้องเป็น NULL)
      - ลิงก์หมดอายุใน 15 นาที (expires_at)
      - หลังดูแล้ว encrypted secret ถูกลบทันที
    """
    rt = (
        db.query(SecretRetrievalToken)
        .filter(SecretRetrievalToken.token == token)
        .first()
    )
    if not rt:
        raise HTTPException(status_code=404, detail="ลิงก์ไม่ถูกต้อง")

    # เช็คว่าใช้ไปแล้วหรือยัง
    if rt.used_at is not None:
        raise HTTPException(
            status_code=410,
            detail="ลิงก์นี้ถูกใช้ไปแล้ว — หากต้องการ secret ใหม่ ให้ rotate key",
        )

    # เช็คหมดอายุ
    if rt.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=410,
            detail="ลิงก์หมดอายุแล้ว (เกิน 15 นาที) — ลงทะเบียนใหม่หรือ rotate key",
        )

    # ถอดรหัส secret
    client_secret = decrypt_secret(rt.secret_encrypted)

    # หา subsystem เพื่อแสดง client_id คู่กัน
    subsystem = db.query(Subsystem).filter(Subsystem.id == rt.subsystem_id).first()

    # mark used + ลบ encrypted secret (one-time!)
    rt.used_at = datetime.utcnow()
    rt.secret_encrypted = ""   # discard — ดูซ้ำไม่ได้อีก

    log_action(
        db,
        actor_id=subsystem.owner_user_id if subsystem else None,
        action="secret_retrieved",
        target_type="subsystem",
        target_id=rt.subsystem_id,
        ip=request.client.host if request.client else None,
    )
    db.commit()

    return {
        "client_id": subsystem.client_id if subsystem else None,
        "client_secret": client_secret,
        "warning": (
            "⚠️ client_secret นี้แสดงเพียงครั้งเดียว — "
            "เก็บไว้ในที่ปลอดภัย (.env ของ subsystem) "
            "หากทำหาย ต้อง rotate key เพื่อสร้างใหม่"
        ),
    }
