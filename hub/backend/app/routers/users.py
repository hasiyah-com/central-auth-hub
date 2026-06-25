"""Admin endpoints for managing users.

CRUD (create/update/delete) เป็น critical action — ต้องผ่าน step-up gate
(``critical_action_policy.gate``) นอกเหนือจาก require_hub_admin. Flow:
    admin เรียก → gate ตรวจ stepup cache → ไม่เจอ = 403 stepup_required
    → frontend พาไป /auth/passkey/stepup → verify → retry ผ่าน.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from datetime import datetime

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import AccessList, AuditLog, Subsystem, User
from app.rate_limiter import limiter
from app.services.audit_service import log_action
from app.services.change_request_service import close_subsystem_login_sessions
from app.services.critical_action_policy import gate as _stepup_gate
from app.services.webhook_dispatcher import send_access_restored, send_access_revoked

router = APIRouter()

_VALID_USER_TYPES = {"student", "teacher", "staff", "admin"}
_VALID_STATUS = {"active", "suspended", "deleted"}


# ============ Schemas ============


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    user_type: str
    identifier: Optional[str] = None
    faculty: Optional[str] = None
    major: Optional[str] = None
    year_or_position: Optional[str] = None
    phone: Optional[str] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    user_type: str  # student/teacher/staff/admin
    identifier: Optional[str] = Field(None, max_length=50)
    faculty: Optional[str] = Field(None, max_length=100)
    major: Optional[str] = Field(None, max_length=100)
    year_or_position: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)


class UserUpdate(BaseModel):
    """Partial update — ทุก field optional. email/user_type เปลี่ยนได้แต่ตรวจซ้ำ."""

    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    user_type: Optional[str] = None
    identifier: Optional[str] = Field(None, max_length=50)
    faculty: Optional[str] = Field(None, max_length=100)
    major: Optional[str] = Field(None, max_length=100)
    year_or_position: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, max_length=20)
    status: Optional[str] = None


# ============ Endpoints ============


@router.get("/", response_model=list[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    user_type: Optional[str] = Query(None, description="filter by user_type"),
    faculty: Optional[str] = Query(None, description="filter by faculty"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """List all users with optional filters. (admin only)"""
    q = db.query(User)
    if user_type:
        q = q.filter(User.user_type == user_type)
    if faculty:
        q = q.filter(User.faculty == faculty)
    users = q.offset(skip).limit(limit).all()
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            user_type=u.user_type,
            identifier=u.identifier,
            faculty=u.faculty,
            major=u.major,
            year_or_position=u.year_or_position,
            phone=u.phone,
            status=u.status,
        )
        for u in users
    ]


@router.get("/count")
def count_users(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Count users by type. (admin only)"""
    from sqlalchemy import func

    rows = db.query(User.user_type, func.count(User.id)).group_by(User.user_type).all()
    return {ut: c for ut, c in rows}


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="user_access_denied",
            reason="not_found",
            requested_user_id=str(user_id),
        )
        raise HTTPException(status_code=404, detail="User not found")
    return _serialize(user)


# ============ Helpers ============


def _serialize(u: User) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        email=u.email,
        full_name=u.full_name,
        user_type=u.user_type,
        identifier=u.identifier,
        faculty=u.faculty,
        major=u.major,
        year_or_position=u.year_or_position,
        phone=u.phone,
        status=u.status,
    )


def _audit_fail(
    db: Session,
    *,
    request: Request,
    actor_id,
    action: str,
    target_id=None,
    reason: str | None = None,
    **extra,
) -> None:
    """log failure attempt (B7) — ip + user_agent + reason แล้ว commit.

    ใช้ก่อน raise — ตามรอย "ใครพยายามแก้/ลบ/สร้าง user ที่ fail" (เดา ID / enum).
    """
    meta = {"reason": reason, "user_agent": request.headers.get("user-agent"), **extra}
    log_action(
        db,
        actor_id=actor_id,
        action=action,
        target_type="user",
        target_id=target_id,
        ip=get_client_ip(request),
        metadata={k: v for k, v in meta.items() if v is not None},
    )
    db.commit()


# ============ Mutations (critical action — step-up required) ============


@router.post(
    "/",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(_stepup_gate("create_user"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def create_user(
    payload: UserCreate,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """สร้าง user ใหม่ (admin only + step-up). email/identifier ต้องไม่ซ้ำ."""
    if payload.user_type not in _VALID_USER_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"user_type ต้องเป็น {sorted(_VALID_USER_TYPES)}",
        )
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="create_user_failed",
            reason="email_exists",
            email=email,
        )
        raise HTTPException(status_code=409, detail="email นี้มีอยู่แล้ว")
    if (
        payload.identifier
        and db.query(User).filter(User.identifier == payload.identifier).first()
    ):
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="create_user_failed",
            reason="identifier_exists",
            identifier=payload.identifier,
        )
        raise HTTPException(status_code=409, detail="รหัส (identifier) นี้มีอยู่แล้ว")

    user = User(
        email=email,
        full_name=payload.full_name,
        user_type=payload.user_type,
        identifier=payload.identifier,
        faculty=payload.faculty,
        major=payload.major,
        year_or_position=payload.year_or_position,
        phone=payload.phone,
        status="active",
        is_hub_admin=(payload.user_type == "admin"),
    )
    db.add(user)
    db.flush()  # ได้ user.id ก่อน audit

    log_action(
        db,
        actor_id=admin.id,
        action="create_user",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={
            "email": email,
            "user_type": payload.user_type,
            "identifier": payload.identifier,
        },
    )
    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(_stepup_gate("update_user"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """แก้ไขข้อมูล user (partial). admin แก้ตัวเองได้ ยกเว้นถอด admin/suspend ตัวเอง."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="update_user_failed",
            reason="not_found",
            requested_user_id=str(user_id),
        )
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=422, detail="ไม่มี field ให้แก้")

    # validation
    if "user_type" in data and data["user_type"] not in _VALID_USER_TYPES:
        raise HTTPException(status_code=422, detail="user_type ไม่ถูกต้อง")
    if "status" in data and data["status"] not in _VALID_STATUS:
        raise HTTPException(status_code=422, detail="status ไม่ถูกต้อง")

    # self-lockout guards — admin ห้ามลดสิทธิ์/ปิดบัญชีตัวเอง
    if str(user.id) == str(admin.id):
        if data.get("user_type") and data["user_type"] != "admin":
            raise HTTPException(status_code=400, detail="ห้ามถอดสิทธิ์ admin ของตัวเอง")
        if data.get("status") and data["status"] != "active":
            raise HTTPException(status_code=400, detail="ห้ามปิดบัญชีของตัวเอง")

    # uniqueness checks (เฉพาะเมื่อเปลี่ยนค่า)
    if "email" in data:
        new_email = data["email"].lower()
        if db.query(User).filter(User.email == new_email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="email นี้มีอยู่แล้ว")
        data["email"] = new_email
    if "identifier" in data and data["identifier"]:
        if (
            db.query(User)
            .filter(User.identifier == data["identifier"], User.id != user.id)
            .first()
        ):
            raise HTTPException(status_code=409, detail="รหัสนี้มีอยู่แล้ว")

    before = {k: getattr(user, k) for k in data}

    # Detect transition: deleted → active = "reactivation"
    # ต้อง restore AccessList + ยิง access_restored webhook ทุก subsystem
    is_reactivation = (
        "status" in data and data["status"] == "active" and user.status == "deleted"
    )

    for k, v in data.items():
        setattr(user, k, v)
    # sync is_hub_admin ตาม user_type
    if "user_type" in data:
        user.is_hub_admin = data["user_type"] == "admin"

    subsystems_restored: list[dict] = []
    if is_reactivation:
        # หา subsystems ที่ user เคยถูก kick จากการ delete (ล่าสุด)
        # → restore เฉพาะที่ตรงกัน (กันสับสนกับ manual revoke ของ owner)
        latest_delete = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "delete_user",
                AuditLog.target_id == user.id,
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        kicked_sub_ids: list[str] = []
        if latest_delete and latest_delete.metadata_json:
            meta = latest_delete.metadata_json
            for sk in meta.get("subsystems_kicked") or []:
                if sid := sk.get("subsystem_id"):
                    kicked_sub_ids.append(sid)

        if kicked_sub_ids:
            # restore AccessList rows (revoked_at -> NULL) เฉพาะ subsystems ใน kick list
            entries = (
                db.query(AccessList, Subsystem)
                .join(Subsystem, Subsystem.id == AccessList.subsystem_id)
                .filter(
                    AccessList.user_id == user.id,
                    AccessList.subsystem_id.in_(kicked_sub_ids),
                    AccessList.revoked_at.is_not(None),
                )
                .all()
            )
            for access, sub in entries:
                access.revoked_at = None
                subsystems_restored.append(
                    {
                        "subsystem_id": str(sub.id),
                        "subsystem_name": sub.name,
                        "role_in_sub": access.role_in_sub,
                    }
                )
                # per-subsystem audit log (โผล่ใน subsystem audit panel)
                log_action(
                    db,
                    actor_id=admin.id,
                    action="user_restored_after_reactivation",
                    target_type="subsystem",
                    target_id=sub.id,
                    ip=get_client_ip(request),
                    metadata={
                        "restored_user_id": str(user.id),
                        "restored_user_email": user.email,
                        "restored_user_name": user.full_name,
                        "role_in_sub": access.role_in_sub,
                    },
                )

    log_action(
        db,
        actor_id=admin.id,
        action="update_user",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={
            "changed": list(data.keys()),
            "before": _jsonable(before),
            "reactivation": is_reactivation,
            "subsystems_restored": subsystems_restored,
        },
    )
    db.commit()

    # ยิง webhook ให้ subsystem เคลียร์ hub_access_revoked_at (fail-safe)
    if is_reactivation and subsystems_restored:
        for item in subsystems_restored:
            sub = (
                db.query(Subsystem).filter(Subsystem.id == item["subsystem_id"]).first()
            )
            if not sub:
                continue
            ok = False
            try:
                ok = send_access_restored(
                    sub,
                    {
                        "hub_user_id": str(user.id),
                        "restored_by": str(admin.id),
                        "reason": "user_reactivated_at_hub",
                    },
                )
            except Exception:
                pass
            log_action(
                db,
                actor_id=admin.id,
                action="access_restored_webhook_sent",
                target_type="subsystem",
                target_id=sub.id,
                ip=get_client_ip(request),
                metadata={
                    "restored_user_id": str(user.id),
                    "restored_user_email": user.email,
                    "delivered": ok,
                },
            )
        db.commit()

    db.refresh(user)
    return _serialize(user)


@router.delete(
    "/{user_id}",
    dependencies=[Depends(_stepup_gate("delete_user"))],
)
@limiter.limit(settings.rate_limit_admin_mutation)
def delete_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ลบ user (soft delete — status=deleted). ไม่ hard delete เพื่อรักษา FK + history."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="delete_user_failed",
            reason="not_found",
            requested_user_id=str(user_id),
        )
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(admin.id):
        _audit_fail(
            db,
            request=request,
            actor_id=admin.id,
            action="delete_user_failed",
            target_id=user.id,
            reason="self_delete_blocked",
        )
        raise HTTPException(status_code=400, detail="ห้ามลบบัญชีของตัวเอง")
    if user.status == "deleted":
        raise HTTPException(status_code=409, detail="user นี้ถูกลบไปแล้ว")

    # 1. หาทุก subsystem ที่ user มี access อยู่ — เพื่อ kick + แจ้ง subsystem
    active_access = (
        db.query(AccessList, Subsystem)
        .join(Subsystem, Subsystem.id == AccessList.subsystem_id)
        .filter(
            AccessList.user_id == user.id,
            AccessList.revoked_at.is_(None),
        )
        .all()
    )

    now = datetime.utcnow()
    subsystems_kicked: list[dict] = []
    total_sessions_closed = 0
    total_jti_revoked = 0

    for access, sub in active_access:
        # (a) soft-revoke whitelist entry
        access.revoked_at = now
        # (b) close active LoginSession + revoke jti (เห็นผลใน Active Sessions panel ทันที)
        closed = close_subsystem_login_sessions(db, sub.id, user_ids=[str(user.id)])
        total_sessions_closed += closed["closed"]
        total_jti_revoked += closed["jti_revoked"]
        subsystems_kicked.append(
            {
                "subsystem_id": str(sub.id),
                "subsystem_name": sub.name,
                "sessions_closed": closed["closed"],
                "jti_revoked": closed["jti_revoked"],
            }
        )
        # (c) per-subsystem audit log — เพื่อให้โผล่ในหน้า "AUDIT · กิจกรรมที่เกิดกับ SUBSYSTEM นี้"
        #     (panel filter target_type='subsystem' AND target_id=sub.id)
        log_action(
            db,
            actor_id=admin.id,
            action="user_kicked_by_deletion",
            target_type="subsystem",
            target_id=sub.id,
            ip=get_client_ip(request),
            metadata={
                "kicked_user_id": str(user.id),
                "kicked_user_email": user.email,
                "kicked_user_name": user.full_name,
                "role_in_sub": access.role_in_sub,
                "sessions_closed": closed["closed"],
                "jti_revoked": closed["jti_revoked"],
                "reason": "user_deleted_at_hub",
            },
        )

    # 2. mark user deleted
    user.status = "deleted"

    log_action(
        db,
        actor_id=admin.id,
        action="delete_user",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={
            "email": user.email,
            "soft_delete": True,
            "subsystems_kicked": subsystems_kicked,
            "total_sessions_closed": total_sessions_closed,
            "total_jti_revoked": total_jti_revoked,
        },
    )
    db.commit()

    # 3. ยิง webhook ทุก subsystem (fail-safe — webhook fail ไม่ block flow)
    #    subsystem-dorm/library /internal/access-revoked → mark hub_access_revoked_at
    #    → คุกกี้ session ของ user ใช้ไม่ได้ทันที (ดู deps.read_session)
    webhook_delivered = 0
    for _, sub in active_access:
        ok = False
        try:
            ok = send_access_revoked(
                sub,
                {
                    "hub_user_id": str(user.id),
                    "revoked_by": str(admin.id),
                    "reason": "user_deleted",
                },
            )
            if ok:
                webhook_delivered += 1
        except Exception:
            pass  # webhook dispatcher logs already
        # log webhook outcome per subsystem (โผล่ใน subsystem audit panel ด้วย)
        log_action(
            db,
            actor_id=admin.id,
            action="access_revoked_webhook_sent",
            target_type="subsystem",
            target_id=sub.id,
            ip=get_client_ip(request),
            metadata={
                "kicked_user_id": str(user.id),
                "kicked_user_email": user.email,
                "delivered": ok,
                "reason": "user_deleted",
            },
        )
    db.commit()

    return {
        "deleted": True,
        "id": str(user.id),
        "status": user.status,
        "subsystems_kicked": len(subsystems_kicked),
        "sessions_closed": total_sessions_closed,
        "jti_revoked": total_jti_revoked,
        "webhook_delivered": webhook_delivered,
    }


def _jsonable(d: dict) -> dict:
    """แปลงค่าใน dict ให้ JSON-serializable (audit metadata)."""
    return {
        k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
        for k, v in d.items()
    }
