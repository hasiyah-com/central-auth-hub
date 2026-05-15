"""Admin router — overview KPIs + subsystem approval.

Endpoints:
  GET  /admin/overview                     -> KPI สรุป
  GET  /admin/subsystems                   -> list ทุก subsystem
  GET  /admin/subsystems/pending           -> เฉพาะที่รออนุมัติ
  POST /admin/subsystems/{id}/approve       -> อนุมัติ subsystem
  POST /admin/subsystems/{id}/reject        -> ปฏิเสธ subsystem
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_hub_admin
from app.models import User, Subsystem, LoginSession, AccessList
from app.services.audit_service import log_action

router = APIRouter()


# ============ Overview KPIs ============

@router.get("/overview")
def admin_overview(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """KPI สรุปสำหรับหน้า Overview Dashboard. (admin only)"""
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.status == "active").scalar()
    subsystems_count = db.query(func.count(Subsystem.id)).scalar()
    active_subsystems = (
        db.query(func.count(Subsystem.id)).filter(Subsystem.status == "active").scalar()
    )
    pending_subsystems = (
        db.query(func.count(Subsystem.id)).filter(Subsystem.status == "pending").scalar()
    )
    total_logins = db.query(func.count(LoginSession.id)).scalar()
    blocked = (
        db.query(func.count(LoginSession.id))
        .filter(LoginSession.decision == "block")
        .scalar()
    )

    return {
        "users": {"total": total_users, "active": active_users},
        "subsystems": {
            "total": subsystems_count,
            "active": active_subsystems,
            "pending": pending_subsystems,
        },
        "logins": {"total": total_logins, "blocked": blocked},
    }


# ============ Subsystem list ============

@router.get("/subsystems")
def list_subsystems(
    status: str | None = None,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """list subsystem ทั้งหมด (กรองตาม status ได้: pending/active/suspended)."""
    q = db.query(Subsystem)
    if status:
        q = q.filter(Subsystem.status == status)
    subs = q.all()

    result = []
    for s in subs:
        user_count = (
            db.query(func.count(AccessList.id))
            .filter(
                AccessList.subsystem_id == s.id,
                AccessList.revoked_at.is_(None),
            )
            .scalar()
        )
        owner = db.query(User).filter(User.id == s.owner_user_id).first()
        result.append({
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "client_id": s.client_id,
            "status": s.status,
            "scope": s.scope,
            "whitelist_count": user_count,
            "owner_email": owner.email if owner else None,
            "created_at": s.created_at,
            "approved_at": s.approved_at,
        })
    return result


@router.get("/subsystems/pending")
def list_pending_subsystems(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """subsystem ที่รอ admin อนุมัติ."""
    subs = db.query(Subsystem).filter(Subsystem.status == "pending").all()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "scope": s.scope,
            "redirect_uris": s.redirect_uris,
            "created_at": s.created_at,
        }
        for s in subs
    ]


# ============ Approve / Reject ============

@router.post("/subsystems/{subsystem_id}/approve")
def approve_subsystem(
    subsystem_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """อนุมัติ subsystem — เปลี่ยน status เป็น active ระบบย่อยพร้อมใช้งาน."""
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")
    if subsystem.status == "active":
        raise HTTPException(status_code=400, detail="subsystem นี้ active อยู่แล้ว")

    subsystem.status = "active"
    subsystem.approved_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin.id,
        action="subsystem_approved",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=request.client.host if request.client else None,
        metadata={"name": subsystem.name},
    )
    db.commit()

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": "active",
        "approved_at": subsystem.approved_at,
        "message": f"อนุมัติ '{subsystem.name}' แล้ว — ระบบย่อยพร้อมใช้งาน",
    }


@router.post("/subsystems/{subsystem_id}/reject")
def reject_subsystem(
    subsystem_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ปฏิเสธ subsystem — เปลี่ยน status เป็น suspended."""
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")

    subsystem.status = "suspended"

    log_action(
        db,
        actor_id=admin.id,
        action="subsystem_rejected",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=request.client.host if request.client else None,
        metadata={"name": subsystem.name},
    )
    db.commit()

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": "suspended",
        "message": f"ปฏิเสธ '{subsystem.name}' แล้ว",
    }
