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

from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import User
from app.services.audit_service import log_action
from app.services.critical_action_policy import gate as _stepup_gate

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
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
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


# ============ Mutations (critical action — step-up required) ============


@router.post(
    "/",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(_stepup_gate("create_user"))],
)
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
        raise HTTPException(status_code=409, detail="email นี้มีอยู่แล้ว")
    if (
        payload.identifier
        and db.query(User).filter(User.identifier == payload.identifier).first()
    ):
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
    for k, v in data.items():
        setattr(user, k, v)
    # sync is_hub_admin ตาม user_type
    if "user_type" in data:
        user.is_hub_admin = data["user_type"] == "admin"

    log_action(
        db,
        actor_id=admin.id,
        action="update_user",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"changed": list(data.keys()), "before": _jsonable(before)},
    )
    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.delete("/{user_id}", dependencies=[Depends(_stepup_gate("delete_user"))])
def delete_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ลบ user (soft delete — status=deleted). ไม่ hard delete เพื่อรักษา FK + history."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="ห้ามลบบัญชีของตัวเอง")
    if user.status == "deleted":
        raise HTTPException(status_code=409, detail="user นี้ถูกลบไปแล้ว")

    user.status = "deleted"
    log_action(
        db,
        actor_id=admin.id,
        action="delete_user",
        target_type="user",
        target_id=user.id,
        ip=get_client_ip(request),
        metadata={"email": user.email, "soft_delete": True},
    )
    db.commit()
    return {"deleted": True, "id": str(user.id), "status": user.status}


def _jsonable(d: dict) -> dict:
    """แปลงค่าใน dict ให้ JSON-serializable (audit metadata)."""
    return {
        k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
        for k, v in d.items()
    }
