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
from app.rate_limiter import limiter
from app.services.audit_service import log_action
from app.services.change_request_service import create_request as create_change_request
from app.services.email_service import send_secret_retrieval_email
from app.services.webhook_dispatcher import send_access_revoked
from app.services.secret_service import (
    encrypt_secret,
    generate_client_credentials,
    generate_retrieval_token,
    hash_retrieval_token,
    hash_secret,
)

router = APIRouter()

# scope ที่อนุญาตให้ subsystem ขอได้
# - Hub-specific: email, name, student_id, employee_id, faculty, major, year, position, phone, address
# - OIDC standard alias (OIDC Core 1.0 §5.4):
#     openid  = marker (ไม่ map field — แสดงว่าใช้ OIDC flow)
#     profile = expand → name, student_id, employee_id, faculty, major, year, position
#     email   = email (อยู่แล้วใน list)
ALLOWED_SCOPES = {
    # OIDC standard
    "openid",
    "profile",
    # Hub-specific (compatible กับ OIDC `email`)
    "email",
    "name",
    "student_id",
    "employee_id",
    "faculty",
    "major",
    "year",
    "position",
    "phone",
    "address",
}


# ============ Schemas ============


class SubsystemCreate(BaseModel):
    name: str
    description: str | None = None
    redirect_uris: list[str]
    scope: list[str]
    # role ที่ allowed สำหรับ access_list.role_in_sub
    # เช่น หอพัก ["resident","teacher","staff"] / ห้องสมุด ["member","librarian"]
    # ปล่อยว่าง = ["user"] (subsystem ทั่วไป)
    allowed_roles: list[str] | None = None
    access_revoke_webhook_url: str | None = None


class SubsystemResponse(BaseModel):
    id: str
    name: str
    description: str | None
    client_id: str
    status: str
    scope: list[str]
    allowed_roles: list[str] = []
    created_at: datetime


class WhitelistAddUser(BaseModel):
    email: EmailStr
    role: str = "member"


class TransferOwner(BaseModel):
    new_owner_email: EmailStr


class WhitelistBulkRoleUpdate(BaseModel):
    """อัปเดต role ของหลาย user พร้อมกัน — atomic transaction."""

    updates: list[dict]  # [{"user_id": "uuid", "role_in_sub": "staff"}]


class WhitelistRoleUpdate(BaseModel):
    role_in_sub: str


class SubsystemUpdate(BaseModel):
    """Patch — ส่งเฉพาะ field ที่ต้องการแก้.

    ถ้าแก้ scope ให้กว้างขึ้น (เพิ่ม scope ใหม่) → status reset เป็น pending รอ admin re-approve
    """

    description: str | None = None
    redirect_uris: list[str] | None = None
    scope: list[str] | None = None
    allowed_roles: list[str] | None = None
    access_revoke_webhook_url: str | None = None


def _validate_role_in_sub(role: str, subsystem: Subsystem) -> str:
    """Validate role_in_sub กับ subsystem.allowed_roles + ทำความสะอาด whitespace.

    raise HTTPException(400) ถ้า role ไม่อยู่ใน list.
    """
    cleaned = role.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="role_in_sub ห้ามว่าง")
    allowed = list(subsystem.allowed_roles or ["user"])
    if cleaned not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"role '{cleaned}' ไม่อยู่ใน allowed_roles ของระบบนี้ " f"(ใช้ได้: {allowed})"
            ),
        )
    return cleaned


# ============ 1. ลงทะเบียน subsystem ============


@router.post("/subsystems")
@limiter.limit(settings.rate_limit_register)
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

    # validate allowed_roles (ถ้าระบุมา) — กัน role ว่าง / space-only
    allowed_roles = [r.strip() for r in (payload.allowed_roles or []) if r.strip()] or [
        "user"
    ]

    # สร้าง subsystem record (status = pending)
    subsystem = Subsystem(
        name=payload.name,
        description=payload.description,
        client_id=client_id,
        client_secret_hash=hash_secret(client_secret),  # เก็บ hash เท่านั้น
        redirect_uris=payload.redirect_uris,
        scope=payload.scope,
        allowed_roles=allowed_roles,
        access_revoke_webhook_url=(payload.access_revoke_webhook_url or "").strip()
        or None,
        status="pending",
        owner_user_id=user.id,
    )
    db.add(subsystem)
    db.flush()  # ทำให้ได้ subsystem.id ก่อน commit

    # สร้าง one-time retrieval token (อายุ 15 นาที)
    # plaintext token ส่งให้ผู้ใช้ทาง URL — DB เก็บเฉพาะ HMAC ของ token
    plaintext_token = generate_retrieval_token()
    retrieval = SecretRetrievalToken(
        token=hash_retrieval_token(plaintext_token),
        subsystem_id=subsystem.id,
        secret_encrypted=encrypt_secret(client_secret),  # encrypt ชั่วคราว
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

    # ส่ง secret retrieval link ทาง email ของผู้ลงทะเบียน
    # ปลอดภัยกว่าการแสดงบนหน้าจอ (กันคนข้างหลังเห็น)
    # ถ้า SMTP ไม่ตั้งค่า / ส่งล้มเหลว → fallback คืน URL ตรงในกรณี dev mode
    email_ok = send_secret_retrieval_email(
        to_email=user.email,
        subsystem_name=subsystem.name,
        retrieval_url=retrieval_url,
        expires_at=retrieval.expires_at,
        client_id=client_id,
    )

    response: dict = {
        "subsystem_id": str(subsystem.id),
        "client_id": client_id,
        "status": "pending",
        "message": "ลงทะเบียนสำเร็จ — รอ admin อนุมัติ",
    }

    if email_ok:
        response["secret_delivery"] = "email"  # pragma: allowlist secret
        response["secret_sent_to"] = user.email  # pragma: allowlist secret
        response["note"] = (
            f"ลิงก์ดู client_secret ถูกส่งไปที่ {user.email} แล้ว — "
            "ตรวจสอบ inbox + จดเก็บภายใน 15 นาที (ดูได้ครั้งเดียว)"
        )
    else:
        # Fallback dev mode — ส่งคืน URL ใน response (ไม่ปลอดภัยใน production)
        response["secret_delivery"] = "url"  # pragma: allowlist secret
        response["secret_retrieval_url"] = retrieval_url  # pragma: allowlist secret
        response["warning"] = (
            "Email ส่งไม่สำเร็จ (SMTP ไม่ตั้งค่า หรือ error) — "
            "ใช้ลิงก์นี้ดู secret ทันที (ครั้งเดียว, 15 นาที)"
        )

    return response


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
            allowed_roles=list(s.allowed_roles or []),
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
    # owner หรือ hub admin
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    # อ่าน + parse CSV
    content = file.file.read().decode("utf-8-sig")  # utf-8-sig รองรับ BOM จาก Excel
    reader = csv.DictReader(io.StringIO(content))
    if "email" not in (reader.fieldnames or []):
        raise HTTPException(status_code=400, detail="CSV ต้องมี column 'email'")

    added: list[str] = []
    skipped: list[dict] = []

    allowed = list(subsystem.allowed_roles or ["user"])
    # CSV ใช้ allowed_roles[0] เป็น default ถ้าไม่ระบุ row.role
    default_role = allowed[0]

    for row in reader:
        email = (row.get("email") or "").strip()
        role = (row.get("role") or default_role).strip()
        if not email:
            continue
        # validate role
        if role not in allowed:
            skipped.append(
                {
                    "email": email,
                    "reason": f"role '{role}' ไม่อยู่ใน allowed_roles ({allowed})",
                }
            )
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
        db.add(
            AccessList(
                subsystem_id=subsystem.id,
                user_id=target.id,
                role_in_sub=role,
                granted_by=user.id,
            )
        )
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
    """ดูรายชื่อ user ใน whitelist ของ subsystem (owner หรือ hub admin)."""
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

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
        "allowed_roles": list(subsystem.allowed_roles or []),
        "total": len(rows),
        "users": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "user_type": u.user_type,
                "role_in_sub": al.role_in_sub,
                "granted_at": al.granted_at,
            }
            for al, u in rows
        ],
    }


# ============ 5. เพิ่ม user ทีละคน (หลังลงทะเบียนแล้ว) ============


def _get_owned_subsystem(subsystem_id: str, user: User, db: Session) -> Subsystem:
    """helper — หา subsystem ที่ user เป็นเจ้าของ หรือเป็น Hub admin.

    Hub admin = supervisor → emergency override ได้ทุก subsystem
    ปกติ dev จัดการของตัวเองเป็นหลัก (self-service)
    """
    q = db.query(Subsystem).filter(Subsystem.id == subsystem_id)
    if not user.is_hub_admin:
        q = q.filter(Subsystem.owner_user_id == user.id)
    subsystem = q.first()
    if not subsystem:
        raise HTTPException(
            status_code=404,
            detail=(
                "ไม่พบ subsystem"
                if user.is_hub_admin
                else "ไม่พบ subsystem หรือคุณไม่ใช่เจ้าของ"
            ),
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

    # validate role ตาม allowed_roles ของ subsystem
    role_clean = _validate_role_in_sub(payload.role, subsystem)

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
        existing.role_in_sub = role_clean
        existing.granted_by = user.id
        action = "whitelist_user_restored"
    else:
        db.add(
            AccessList(
                subsystem_id=subsystem.id,
                user_id=target.id,
                role_in_sub=role_clean,
                granted_by=user.id,
            )
        )
        action = "whitelist_user_added"

    log_action(
        db,
        actor_id=user.id,
        action=action,
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"email": payload.email, "role": role_clean},
    )
    db.commit()

    return {
        "subsystem": subsystem.name,
        "email": payload.email,
        "role": role_clean,
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

    # Fire webhook → subsystem (fail-safe — webhook fail ไม่กระทบ revoke)
    try:
        send_access_revoked(
            subsystem,
            {
                "hub_user_id": user_id,
                "revoked_by": str(user.id),
                "reason": "whitelist_user_removed",
            },
        )
    except Exception:
        # logged inside dispatcher — ห้าม raise
        pass

    return {
        "subsystem": subsystem.name,
        "removed_user_id": user_id,
        "result": "ลบออกจาก whitelist แล้ว (soft delete — ประวัติยังเก็บไว้)",
    }


# ============ 7. แก้ไข role ใน whitelist ============


@router.patch("/subsystems/{subsystem_id}/whitelist/{user_id}")
def update_whitelist_role(
    subsystem_id: str,
    user_id: str,
    payload: WhitelistRoleUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอเปลี่ยน role ของ user ใน whitelist — สร้าง pending request รอ admin approve."""
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
            status_code=404, detail="ไม่พบ user ใน whitelist หรือถูก revoke แล้ว"
        )

    new_role = _validate_role_in_sub(payload.role_in_sub, subsystem)
    if new_role == entry.role_in_sub:
        return {
            "subsystem": subsystem.name,
            "user_id": user_id,
            "role": entry.role_in_sub,
            "result": "role เดิม — ไม่มีการเปลี่ยนแปลง",
        }

    # หา user email สำหรับ display ใน admin pending-requests
    target_user = db.query(User).filter(User.id == user_id).first()
    target_email = target_user.email if target_user else None

    old_role_snapshot = entry.role_in_sub
    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="change_whitelist_role",
            payload={
                "user_id": user_id,
                "new_role": new_role,
                "old_role": old_role_snapshot,
                "target_email": target_email,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "whitelist_role_changed"
            if is_admin_override
            else "whitelist_role_change_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "user_id": user_id,
            "old_role": old_role_snapshot,
            "new_role": new_role,
            "admin_override": is_admin_override,
        },
    )
    db.commit()

    # Telegram alert
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",  # admin override + dev request ส่งเหมือนกัน — แค่ title prefix ต่าง
            kind=(
                "change_request.admin_override_whitelist_role"
                if is_admin_override
                else "change_request.whitelist_role"
            ),
            key=f"{subsystem.id}:{user_id}",
            title=(
                f"🛡️ Admin Override · เปลี่ยน role · {subsystem.name}"
                if is_admin_override
                else f"🧰 ขอเปลี่ยน role · {subsystem.name}"
            ),
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "actor": user.email,
                "target": target_email or user_id,
                "old_role": old_role_snapshot,
                "new_role": new_role,
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem": subsystem.name,
        "user_id": user_id,
        "old_role": old_role_snapshot,
        "new_role": new_role,
        "status": req.status,
        "admin_override": is_admin_override,
        "result": (
            f"แก้ role '{old_role_snapshot}' → '{new_role}' แล้ว (admin override)"
            if is_admin_override
            else f"ส่ง request เปลี่ยน role '{old_role_snapshot}' → '{new_role}' ให้ admin approve"
        ),
    }


# ============ 8. แก้ไข subsystem ============


@router.patch("/subsystems/{subsystem_id}")
def update_subsystem(
    subsystem_id: str,
    payload: SubsystemUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """แก้ไข subsystem — split เป็น 2 group:

    Apply immediately (cosmetic / non-sensitive):
      - description
      - access_revoke_webhook_url

    Create pending request (admin approval required):
      - redirect_uris   (open redirect risk)
      - scope           (privilege escalation risk)
      - allowed_roles   (permissioning impact)
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    if (
        payload.description is None
        and payload.redirect_uris is None
        and payload.scope is None
        and payload.allowed_roles is None
        and payload.access_revoke_webhook_url is None
    ):
        raise HTTPException(status_code=400, detail="ต้องส่งอย่างน้อย 1 field ที่ต้องการแก้")

    immediate_changes: dict = {}
    pending_requests: list[dict] = []

    # ── Immediate group ──
    if payload.description is not None:
        old = subsystem.description
        new = payload.description.strip() or None
        if old != new:
            subsystem.description = new
            immediate_changes["description"] = {"old": old, "new": new}

    if payload.access_revoke_webhook_url is not None:
        new_webhook = payload.access_revoke_webhook_url.strip() or None
        if subsystem.access_revoke_webhook_url != new_webhook:
            immediate_changes["access_revoke_webhook_url"] = {
                "old": subsystem.access_revoke_webhook_url,
                "new": new_webhook,
            }
            subsystem.access_revoke_webhook_url = new_webhook

    # ── Pending-approval group (dev) / instant apply (admin override) ──
    auto_applied: list[dict] = []

    def _enqueue(req_type: str, payload_dict: dict, label: str):
        try:
            req, applied = create_change_request(
                db,
                subsystem=subsystem,
                requested_by=user,
                request_type=req_type,
                payload=payload_dict,
            )
            entry = {
                "request_id": str(req.id),
                "request_type": req_type,
                "label": label,
            }
            if req.status == "approved":
                # admin override → applied แล้ว
                entry["applied"] = applied
                auto_applied.append(entry)
            else:
                pending_requests.append(entry)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if payload.redirect_uris is not None:
        cleaned = [u.strip() for u in payload.redirect_uris if u.strip()]
        if not cleaned:
            raise HTTPException(
                status_code=400, detail="redirect_uris ต้องมีอย่างน้อย 1 ตัว"
            )
        if list(subsystem.redirect_uris or []) != cleaned:
            _enqueue(
                "edit_redirect_uris",
                {"redirect_uris": cleaned},
                "Redirect URIs",
            )

    if payload.scope is not None:
        cleaned_scope = [s.strip() for s in payload.scope if s.strip()]
        if not cleaned_scope:
            raise HTTPException(status_code=400, detail="scope ต้องมีอย่างน้อย 1 ตัว")
        invalid = set(cleaned_scope) - ALLOWED_SCOPES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"scope ไม่ถูกต้อง: {sorted(invalid)} — ใช้ได้: {sorted(ALLOWED_SCOPES)}",
            )
        if set(subsystem.scope or []) != set(cleaned_scope):
            _enqueue("edit_scope", {"scope": cleaned_scope}, "Scope")

    if payload.allowed_roles is not None:
        cleaned_roles = [r.strip() for r in payload.allowed_roles if r.strip()]
        if not cleaned_roles:
            raise HTTPException(
                status_code=400, detail="allowed_roles ต้องมีอย่างน้อย 1 ตัว"
            )
        # ⚠ orphan check แม้ใน request — กัน admin approve แล้วเจอ user หล่น
        current_used = {
            r[0]
            for r in db.query(AccessList.role_in_sub)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.revoked_at.is_(None),
            )
            .distinct()
            .all()
        }
        orphaned = current_used - set(cleaned_roles)
        if orphaned:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"ตัด role {sorted(orphaned)} ออกไม่ได้ — "
                    f"ยังมี user ใน whitelist ใช้ role เหล่านี้อยู่ "
                    f"(แก้ role ของพวกเขาก่อน)"
                ),
            )
        if list(subsystem.allowed_roles or []) != cleaned_roles:
            _enqueue(
                "edit_allowed_roles",
                {"allowed_roles": cleaned_roles},
                "Allowed Roles",
            )

    if not immediate_changes and not pending_requests and not auto_applied:
        return {
            "id": str(subsystem.id),
            "result": "ไม่มีการเปลี่ยนแปลง",
            "status": subsystem.status,
        }

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_updated",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "immediate": immediate_changes,
            "pending_requests": pending_requests,
            "auto_applied": auto_applied,
        },
    )
    db.commit()

    # Telegram alert
    if pending_requests or auto_applied:
        try:
            from app.services.alert_service import send_alert

            if auto_applied:
                send_alert(
                    severity="warning",
                    kind="change_request.admin_override_subsystem_edit",
                    # unique per batch — รวม request_id ของทุก auto_applied
                    key=f"{subsystem.id}:override:{','.join(r['request_id'] for r in auto_applied)}",
                    title=f"🛡️ Admin Override · แก้ไข {subsystem.name}",
                    detail={
                        "subsystem": subsystem.name,
                        "subsystem_id": str(subsystem.id),
                        "actor": user.email,
                        "applied": [
                            {"type": r["request_type"], "label": r["label"]}
                            for r in auto_applied
                        ],
                    },
                )
            if pending_requests:
                send_alert(
                    severity="warning",
                    kind="change_request.subsystem_edit",
                    # unique per batch — รวม request_id ของทุก pending
                    key=f"{subsystem.id}:pending:{','.join(r['request_id'] for r in pending_requests)}",
                    title=f"📝 ขอแก้ไข {subsystem.name}",
                    detail={
                        "subsystem": subsystem.name,
                        "subsystem_id": str(subsystem.id),
                        "requested_by": user.email,
                        "requests": pending_requests,
                        "review_url": f"{settings.admin_frontend_url}/pending-requests",
                    },
                )
        except Exception:
            pass

    msg_parts = []
    if immediate_changes:
        msg_parts.append(f"บันทึกแล้ว ({len(immediate_changes)} field)")
    if auto_applied:
        kinds = ", ".join(r["label"] for r in auto_applied)
        msg_parts.append(f"admin override applied: {kinds}")
    if pending_requests:
        kinds = ", ".join(r["label"] for r in pending_requests)
        msg_parts.append(f"ส่ง request ให้ admin review: {kinds}")

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": subsystem.status,
        "immediate_changes": immediate_changes,
        "pending_requests": pending_requests,
        "auto_applied": auto_applied,
        "result": " · ".join(msg_parts),
    }


# ============ 8b. ดู pending change requests ของ subsystem ของฉัน ============


@router.get("/subsystems/{subsystem_id}/change-requests")
def list_my_change_requests(
    subsystem_id: str,
    status: str | None = None,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ดู change requests ของ subsystem ของฉัน (หรือ admin = ดูได้ทุกตัว)."""
    from app.models import SubsystemChangeRequest

    subsystem = _get_owned_subsystem(subsystem_id, user, db)
    q = (
        db.query(SubsystemChangeRequest)
        .filter(SubsystemChangeRequest.subsystem_id == subsystem.id)
        .order_by(SubsystemChangeRequest.created_at.desc())
    )
    if status:
        q = q.filter(SubsystemChangeRequest.status == status)
    items = q.limit(50).all()
    return {
        "subsystem_id": str(subsystem.id),
        "items": [
            {
                "id": str(r.id),
                "request_type": r.request_type,
                "payload": r.payload,
                "status": r.status,
                "reviewer_note": r.reviewer_note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            }
            for r in items
        ],
    }


# ============ 9b. Bulk role update ============


@router.post("/subsystems/{subsystem_id}/whitelist/bulk-update")
def bulk_update_roles(
    subsystem_id: str,
    payload: WhitelistBulkRoleUpdate,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอ batch อัปเดต role — สร้าง pending request รอ admin approve.

    Body: { updates: [{user_id, role_in_sub}, ...] }

    Validate ทุกตัวก่อนสร้าง request — fail-fast ถ้า role ผิด
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    if not payload.updates:
        raise HTTPException(status_code=400, detail="updates ว่าง")
    if len(payload.updates) > 500:
        raise HTTPException(status_code=400, detail="updates เกิน 500 รายการต่อ batch")

    # Validate role ทั้ง batch ตาม allowed_roles ปัจจุบัน
    allowed = list(subsystem.allowed_roles or ["user"])
    for i, u in enumerate(payload.updates):
        uid = (u.get("user_id") or "").strip()
        role = (u.get("role_in_sub") or "").strip()
        if not uid or not role:
            raise HTTPException(
                status_code=400,
                detail=f"updates[{i}]: ต้องมี user_id + role_in_sub",
            )
        if role not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"updates[{i}]: role '{role}' ไม่อยู่ใน allowed_roles " f"({allowed})"
                ),
            )

    # Pre-compute preview (สำหรับ admin ดูใน pending UI) — old_role ของแต่ละคน
    preview: list[dict] = []
    for u in payload.updates:
        uid = u.get("user_id")
        entry = (
            db.query(AccessList, User.email)
            .outerjoin(User, User.id == AccessList.user_id)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == uid,
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if entry:
            access, email = entry
            preview.append(
                {
                    "user_id": str(uid),
                    "email": email,
                    "old_role": access.role_in_sub,
                    "new_role": u.get("role_in_sub"),
                }
            )

    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="bulk_change_whitelist_roles",
            payload={
                "updates": payload.updates,
                "preview": preview,  # อ่านอย่างเดียวสำหรับ admin
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "whitelist_bulk_role_update"
            if is_admin_override
            else "whitelist_bulk_role_update_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "updates_count": len(payload.updates),
            "preview_sample": preview[:5],
            "admin_override": is_admin_override,
            "applied": applied if is_admin_override else None,
        },
    )
    db.commit()

    # Telegram alert
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",
            kind=(
                "change_request.admin_override_bulk_role"
                if is_admin_override
                else "change_request.bulk_role"
            ),
            key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
            title=(
                f"🛡️ Admin Override · batch role · {subsystem.name}"
                if is_admin_override
                else f"🧰 ขอเปลี่ยน role · batch · {subsystem.name}"
            ),
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "requested_by": user.email,
                "updates_count": len(payload.updates),
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem_id": str(subsystem.id),
        "updates_count": len(payload.updates),
        "status": req.status,
        "admin_override": is_admin_override,
        "applied": applied if is_admin_override else None,
        "message": (
            (
                f"แก้ batch {(applied or {}).get('changed_count', 0)} รายการ "
                f"(skipped {(applied or {}).get('skipped_count', 0)}) — admin override"
            )
            if is_admin_override
            else f"ส่ง request batch update {len(payload.updates)} รายการ ให้ admin approve"
        ),
    }


# ============ 10. Transfer ownership ============


_TRANSFER_OWNER_ALLOWED = {"teacher", "staff", "admin"}


@router.post("/subsystems/{subsystem_id}/transfer-owner")
def transfer_owner(
    subsystem_id: str,
    payload: TransferOwner,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """โอน ownership ของ subsystem ให้ developer อีกคน.

    - new owner ต้องเป็น teacher / staff / admin (require_developer level)
    - ห้ามโอนให้ตัวเอง
    - ห้ามโอนให้ user ที่ status != active
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    new_owner = db.query(User).filter(User.email == payload.new_owner_email).first()
    if not new_owner:
        raise HTTPException(
            status_code=404, detail=f"ไม่พบ user อีเมล {payload.new_owner_email}"
        )
    if new_owner.id == user.id:
        raise HTTPException(status_code=400, detail="ห้ามโอนให้ตัวเอง")
    if new_owner.user_type not in _TRANSFER_OWNER_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=(
                f"new owner ต้องเป็น {sorted(_TRANSFER_OWNER_ALLOWED)} "
                f"(ตอนนี้: {new_owner.user_type})"
            ),
        )
    if (new_owner.status or "active") != "active":
        raise HTTPException(
            status_code=400,
            detail=f"new owner status = {new_owner.status} — ต้องเป็น active",
        )

    old_owner_id = subsystem.owner_user_id
    subsystem.owner_user_id = new_owner.id

    log_action(
        db,
        actor_id=user.id,
        action="subsystem_owner_transferred",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "old_owner_id": str(old_owner_id) if old_owner_id else None,
            "new_owner_id": str(new_owner.id),
            "new_owner_email": new_owner.email,
        },
    )
    db.commit()

    return {
        "subsystem_id": str(subsystem.id),
        "new_owner": {
            "id": str(new_owner.id),
            "email": new_owner.email,
            "full_name": new_owner.full_name,
        },
        "message": f"โอน '{subsystem.name}' ให้ {new_owner.email} แล้ว",
    }


# ============ 11. Rotate client_secret (one-time link + 24h grace) ============


_SECRET_GRACE_HOURS = 24


@router.post("/subsystems/{subsystem_id}/rotate-secret")
def rotate_client_secret(
    subsystem_id: str,
    request: Request,
    user: User = Depends(require_developer),
    db: Session = Depends(get_db),
):
    """ขอ rotate client_secret — สร้าง pending request รอ admin approve.

    หลัง admin approve:
      - secret ใหม่ active ทันที (primary)
      - secret เก่ายังใช้ได้ 24 ชม. (grace)
      - dev จะได้รับ email พร้อม one-time link ดู secret ใหม่
    """
    subsystem = _get_owned_subsystem(subsystem_id, user, db)

    try:
        req, applied = create_change_request(
            db,
            subsystem=subsystem,
            requested_by=user,
            request_type="rotate_secret",
            payload={},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_admin_override = req.status == "approved"

    log_action(
        db,
        actor_id=user.id,
        action=(
            "client_secret_rotated" if is_admin_override else "rotate_secret_requested"
        ),
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "admin_override": is_admin_override,
            "previous_expires_at": (applied or {}).get("previous_expires_at"),
        },
    )
    db.commit()

    # ─── Admin override branch: ส่ง email พร้อม one-time link ทันที ───
    if is_admin_override and applied:
        try:
            from datetime import datetime as _dt

            expires_at = _dt.fromisoformat(applied["retrieval_expires_at"])
            send_secret_retrieval_email(
                to_email=user.email,
                subsystem_name=subsystem.name,
                retrieval_url=applied["retrieval_url"],
                expires_at=expires_at,
                client_id=subsystem.client_id,
            )
        except Exception:
            pass

        try:
            from app.services.alert_service import send_alert

            send_alert(
                severity="warning",
                kind="change_request.admin_override_rotate_secret",
                key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
                title=f"🛡️ Admin Override · Rotate Secret · {subsystem.name}",
                detail={
                    "subsystem": subsystem.name,
                    "subsystem_id": str(subsystem.id),
                    "actor": user.email,
                    "grace_hours": applied.get("grace_hours"),
                    "previous_expires_at": applied.get("previous_expires_at"),
                },
            )
        except Exception:
            pass

        return {
            "request_id": str(req.id),
            "subsystem_id": str(subsystem.id),
            "status": "approved",
            "admin_override": True,
            "secret_retrieval_url": applied.get("retrieval_url"),
            "previous_expires_at": applied.get("previous_expires_at"),
            "grace_hours": applied.get("grace_hours"),
            "message": (
                "Admin Override · rotate secret สำเร็จ — secret ใหม่ active "
                f"(เก่ายังใช้ได้ {applied.get('grace_hours', 24)} ชม.) "
                "· ลิงก์ดู secret ใหม่ส่งไปยัง email"
            ),
        }

    # ─── Dev workflow: pending — รอ admin approve ───
    try:
        from app.services.alert_service import send_alert

        send_alert(
            severity="warning",
            kind="change_request.rotate_secret",
            key=f"{subsystem.id}:{req.id}",  # unique per request → ไม่ dedupp
            title=f"🔑 ขอ rotate secret · {subsystem.name}",
            detail={
                "subsystem": subsystem.name,
                "subsystem_id": str(subsystem.id),
                "requested_by": user.email,
                "request_id": str(req.id),
                "review_url": f"{settings.admin_frontend_url}/pending-requests",
            },
        )
    except Exception:
        pass

    return {
        "request_id": str(req.id),
        "subsystem_id": str(subsystem.id),
        "status": "pending",
        "admin_override": False,
        "message": (
            "สร้าง request เรียบร้อย — รอ admin approve "
            "(จะส่ง email พร้อมลิงก์ดู secret ใหม่ให้คุณหลัง approve)"
        ),
    }
