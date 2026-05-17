"""Developer Portal router — ระบบย่อยลงทะเบียนกับ Hub.

Endpoints:
  POST /developer/subsystems              -> ลงทะเบียน subsystem ใหม่
  GET  /developer/subsystems              -> ดู subsystem ของฉัน
  POST /developer/subsystems/{id}/whitelist -> upload whitelist CSV
  GET  /developer/subsystems/{id}/whitelist -> ดู whitelist ปัจจุบัน
"""
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_developer
from app.models import AccessList, SecretRetrievalToken, Subsystem, User
from app.services.audit_service import log_action
from app.services.secret_service import (
    encrypt_secret,
    generate_client_credentials,
    generate_retrieval_token,
    hash_retrieval_token,
    hash_secret,
)

router = APIRouter()

# scope ที่อนุญาตให้ subsystem ขอได้
ALLOWED_SCOPES = {
    "email", "name", "student_id", "employee_id",
    "faculty", "major", "year", "position", "phone", "address",
}


# ============ Schemas ============

class SubsystemCreate(BaseModel):
    name: str
    description: str | None = None
    redirect_uris: list[str]
    scope: list[str]


class SubsystemResponse(BaseModel):
    id: str
    name: str
    description: str | None
    client_id: str
    status: str
    scope: list[str]
    created_at: datetime


class WhitelistAddUser(BaseModel):
    email: EmailStr
    role: str = "member"


# ============ 1. ลงทะเบียน subsystem ============

@router.post("/subsystems")
def register_subsystem(
    payload: SubsystemCreate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ลงทะเบียนระบบย่อยใหม่ — สร้าง client_id/secret + one-time retrieval link.

    หลังเรียก endpoint นี้:
      - subsystem ถูกสร้างด้วย status='pending' (รอ admin อนุมัติ)
      - client_secret ถูก hash เก็บใน DB (ไม่เก็บ plaintext)
      - คืน secret_retrieval_url สำหรับดู client_secret ครั้งเดียว
    """
    # ตรวจ scope ที่ขอ
    invalid = set(payload.scope) - ALLOWED_SCOPES
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"scope ไม่ถูกต้อง: {invalid}. ใช้ได้: {ALLOWED_SCOPES}",
        )

    # สร้าง credentials
    client_id, client_secret = generate_client_credentials()

    # สร้าง subsystem record (status = pending)
    subsystem = Subsystem(
        name=payload.name,
        description=payload.description,
        client_id=client_id,
        client_secret_hash=hash_secret(client_secret),   # เก็บ hash เท่านั้น
        redirect_uris=payload.redirect_uris,
        scope=payload.scope,
        status="pending",
        owner_user_id=user.id,
    )
    db.add(subsystem)
    db.flush()   # ทำให้ได้ subsystem.id ก่อน commit

    # สร้าง one-time retrieval token (อายุ 15 นาที)
    # plaintext token ส่งให้ผู้ใช้ทาง URL — DB เก็บเฉพาะ HMAC ของ token
    plaintext_token = generate_retrieval_token()
    retrieval = SecretRetrievalToken(
        token=hash_retrieval_token(plaintext_token),
        subsystem_id=subsystem.id,
        secret_encrypted=encrypt_secret(client_secret),   # encrypt ชั่วคราว
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )
    db.add(retrieval)

    # audit log
    log_action(
        db,
        actor_id=user.id,
        action="subsystem_registered",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"name": payload.name, "scope": payload.scope},
    )

    db.commit()

    retrieval_url = f"{settings.hub_base_url}/secret/retrieve?token={plaintext_token}"
    return {
        "subsystem_id": str(subsystem.id),
        "client_id": client_id,
        "status": "pending",
        "message": "ลงทะเบียนสำเร็จ — รอ admin อนุมัติ",
        "secret_retrieval_url": retrieval_url,
        "note": (
            "ในระบบจริง URL นี้จะถูกส่งทาง email — "
            "ลิงก์หมดอายุใน 15 นาที และดู client_secret ได้เพียงครั้งเดียว"
        ),
    }


# ============ 2. ดู subsystem ของฉัน ============

@router.get("/subsystems", response_model=list[SubsystemResponse])
def my_subsystems(
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดูรายการ subsystem ทั้งหมดที่ฉันเป็นเจ้าของ."""
    subs = db.query(Subsystem).filter(Subsystem.owner_user_id == user.id).all()
    return [
        SubsystemResponse(
            id=str(s.id),
            name=s.name,
            description=s.description,
            client_id=s.client_id,
            status=s.status,
            scope=s.scope,
            created_at=s.created_at,
        )
        for s in subs
    ]


# ============ 3. upload whitelist CSV ============

@router.post("/subsystems/{subsystem_id}/whitelist")
def upload_whitelist(
    subsystem_id: str,
    request: Request,
    file: UploadFile = File(..., description="CSV: email,role,note"),
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """อัปโหลด whitelist CSV — ระบุว่า user คนไหนเข้า subsystem นี้ได้.

    รูปแบบ CSV (มี header):
        email,role,note
        student001@student.uni.ac.th,resident,
        teacher001@uni.ac.th,staff,
    """
    # ตรวจว่าเป็นเจ้าของ subsystem นี้จริง
    subsystem = (
        db.query(Subsystem)
        .filter(Subsystem.id == subsystem_id, Subsystem.owner_user_id == user.id)
        .first()
    )
    if not subsystem:
        raise HTTPException(
            status_code=404,
            detail="ไม่พบ subsystem หรือคุณไม่ใช่เจ้าของ",
        )

    # อ่าน + parse CSV
    content = file.file.read().decode("utf-8-sig")   # utf-8-sig รองรับ BOM จาก Excel
    reader = csv.DictReader(io.StringIO(content))
    if "email" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV ต้องมี column 'email'")

    added: list[str] = []
    skipped: list[dict] = []

    for row in reader:
        email = (row.get("email") or "").strip()
        role = (row.get("role") or "member").strip()
        if not email:
            continue

        # หา user ใน Hub
        target = db.query(User).filter(User.email == email).first()
        if not target:
            skipped.append({"email": email, "reason": "ไม่พบ user ใน Hub"})
            continue

        # เช็คว่ามีใน access_list อยู่แล้วหรือยัง
        existing = (
            db.query(AccessList)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == target.id,
            )
            .first()
        )
        if existing:
            skipped.append({"email": email, "reason": "อยู่ใน whitelist อยู่แล้ว"})
            continue

        # เพิ่มเข้า access_list
        db.add(AccessList(
            subsystem_id=subsystem.id,
            user_id=target.id,
            role_in_sub=role,
            granted_by=user.id,
        ))
        added.append(email)

    log_action(
        db,
        actor_id=user.id,
        action="whitelist_uploaded",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"added": len(added), "skipped": len(skipped)},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "added": len(added),
        "skipped": len(skipped),
        "added_emails": added,
        "skipped_details": skipped,
    }


# ============ 4. ดู whitelist ปัจจุบัน ============

@router.get("/subsystems/{subsystem_id}/whitelist")
def get_whitelist(
    subsystem_id: str,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดูรายชื่อ user ใน whitelist ของ subsystem."""
    subsystem = (
        db.query(Subsystem)
        .filter(Subsystem.id == subsystem_id, Subsystem.owner_user_id == user.id)
        .first()
    )
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem หรือคุณไม่ใช่เจ้าของ")

    rows = (
        db.query(AccessList, User)
        .join(User, User.id == AccessList.user_id)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.revoked_at.is_(None),
        )
        .all()
    )
    return {
        "subsystem": subsystem.name,
        "total": len(rows),
        "users": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "role_in_sub": al.role_in_sub,
                "granted_at": al.granted_at,
            }
            for al, u in rows
        ],
    }


# ============ 5. เพิ่ม user ทีละคน (หลังลงทะเบียนแล้ว) ============

def _get_owned_subsystem(subsystem_id: str, user: User, db: Session) -> Subsystem:
    """helper — หา subsystem ที่ user เป็นเจ้าของ (ใช้ซ้ำหลาย endpoint)."""
    subsystem = (
        db.query(Subsystem)
        .filter(Subsystem.id == subsystem_id, Subsystem.owner_user_id == user.id)
        .first()
    )
    if not subsystem:
        raise HTTPException(
            status_code=404, detail="ไม่พบ subsystem หรือคุณไม่ใช่เจ้าของ"
        )
    return subsystem


@router.post("/subsystems/{subsystem_id}/whitelist/user")
def add_user_to_whitelist(
    subsystem_id: str,
    payload: WhitelistAddUser,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """เพิ่ม user เข้า whitelist ทีละคน (สำหรับเพิ่มภายหลังจากลงทะเบียนแล้ว).

    ใช้ได้ตลอดเวลา ไม่ว่า subsystem จะ status ไหน — เจ้าของจัดการ whitelist
    ของตัวเองได้
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    # หา target user
    target = db.query(User).filter(User.email == payload.email).first()
    if not target:
        raise HTTPException(
            status_code=404, detail=f"ไม่พบ user อีเมล {payload.email} ใน Hub"
        )

    # เช็คว่ามีใน access_list อยู่แล้วไหม
    existing = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == target.id,
        )
        .first()
    )
    if existing:
        if existing.revoked_at is None:
            raise HTTPException(
                status_code=400, detail=f"{payload.email} อยู่ใน whitelist อยู่แล้ว"
            )
        # เคยถูก revoke -> คืนสิทธิ์ (un-revoke) แทนการสร้างใหม่
        existing.revoked_at = None
        existing.role_in_sub = payload.role
        existing.granted_by = user.id
        action = "whitelist_user_restored"
    else:
        db.add(AccessList(
            subsystem_id=subsystem.id,
            user_id=target.id,
            role_in_sub=payload.role,
            granted_by=user.id,
        ))
        action = "whitelist_user_added"

    log_action(
        db,
        actor_id=user.id,
        action=action,
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"email": payload.email, "role": payload.role},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "email": payload.email,
        "role": payload.role,
        "result": "เพิ่มเข้า whitelist แล้ว",
    }


# ============ 6. ลบ user ออกจาก whitelist ============

@router.delete("/subsystems/{subsystem_id}/whitelist/{user_id}")
def remove_user_from_whitelist(
    subsystem_id: str,
    user_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ลบ user ออกจาก whitelist (soft delete — set revoked_at).

    user คนนั้นจะ login เข้า subsystem นี้ไม่ได้อีก แต่ประวัติยังเก็บไว้
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    entry = (
        db.query(AccessList)
        .filter(
            AccessList.subsystem_id == subsystem.id,
            AccessList.user_id == user_id,
            AccessList.revoked_at.is_(None),
        )
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=404, detail="ไม่พบ user นี้ใน whitelist (หรือถูกลบไปแล้ว)"
        )

    # soft delete — ไม่ลบ record จริง เก็บประวัติไว้
    entry.revoked_at = datetime.utcnow()

    log_action(
        db,
        actor_id=user.id,
        action="whitelist_user_removed",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"removed_user_id": user_id},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "removed_user_id": user_id,
        "result": "ลบออกจาก whitelist แล้ว (soft delete — ประวัติยังเก็บไว้)",
    }
