"""Admin router — overview KPIs + subsystem approval.

Endpoints:
  GET  /admin/overview                     -> KPI สรุป
  GET  /admin/subsystems                   -> list ทุก subsystem
  GET  /admin/subsystems/pending           -> เฉพาะที่รออนุมัติ
  POST /admin/subsystems/{id}/approve       -> อนุมัติ subsystem
  POST /admin/subsystems/{id}/reject        -> ปฏิเสธ subsystem
  GET  /admin/audit                         -> audit log viewer (filtered, paginated)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import AccessList, AuditLog, LoginSession, Subsystem, User
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
    active_users = (
        db.query(func.count(User.id)).filter(User.status == "active").scalar()
    )
    subsystems_count = db.query(func.count(Subsystem.id)).scalar()
    active_subsystems = (
        db.query(func.count(Subsystem.id)).filter(Subsystem.status == "active").scalar()
    )
    pending_subsystems = (
        db.query(func.count(Subsystem.id))
        .filter(Subsystem.status == "pending")
        .scalar()
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
    """list subsystem ทั้งหมด (กรองตาม status ได้: pending/active/suspended).

    ใช้ subquery + outer join นับสมาชิก whitelist + ดึง owner email
    ครั้งเดียว (ก่อนหน้านี้เป็น N+1)
    """
    wl_count = (
        db.query(
            AccessList.subsystem_id.label("sid"),
            func.count(AccessList.id).label("cnt"),
        )
        .filter(AccessList.revoked_at.is_(None))
        .group_by(AccessList.subsystem_id)
        .subquery()
    )

    owner = aliased(User)
    q = (
        db.query(Subsystem, wl_count.c.cnt, owner.email)
        .outerjoin(wl_count, wl_count.c.sid == Subsystem.id)
        .outerjoin(owner, owner.id == Subsystem.owner_user_id)
    )
    if status:
        q = q.filter(Subsystem.status == status)

    return [
        {
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "client_id": s.client_id,
            "status": s.status,
            "scope": s.scope,
            "whitelist_count": cnt or 0,
            "owner_email": owner_email,
            "created_at": s.created_at,
            "approved_at": s.approved_at,
        }
        for s, cnt, owner_email in q.all()
    ]


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
        ip=get_client_ip(request),
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
    """ปฏิเสธ subsystem — เปลี่ยน status pending -> suspended.

    ใช้กับ subsystem ที่ pending เท่านั้น — จะไม่ suspend ระบบที่ active แล้ว
    (สำหรับ suspend ระบบ active ควรมี endpoint แยก /suspend ในอนาคต)
    """
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")
    if subsystem.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"reject ใช้กับ subsystem ที่ pending เท่านั้น (ตอนนี้: {subsystem.status})",
        )

    subsystem.status = "suspended"

    log_action(
        db,
        actor_id=admin.id,
        action="subsystem_rejected",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={"name": subsystem.name},
    )
    db.commit()

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": "suspended",
        "message": f"ปฏิเสธ '{subsystem.name}' แล้ว",
    }


# ============ Audit log viewer ============


@router.get("/audit")
def list_audit_logs(
    action: str | None = Query(
        None, description="filter by action (e.g. subsystem_approved)"
    ),
    actor_id: str | None = Query(None, description="filter by actor user_id"),
    target_type: str | None = Query(
        None, description="filter by target_type (user/subsystem/etc.)"
    ),
    skip: int = 0,
    limit: int = Query(50, ge=1, le=500),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """List audit logs (admin only) — paginated, newest first, with optional filters.

    Joins users on actor_id to surface the actor's email — UI-friendly without
    a second roundtrip. Actor may be NULL (system action) → email returns None.
    """
    q = (
        db.query(AuditLog, User.email)
        .outerjoin(User, AuditLog.actor_id == User.id)
        .order_by(AuditLog.created_at.desc())
    )
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if target_type:
        q = q.filter(AuditLog.target_type == target_type)

    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    items = [
        {
            "id": str(log.id),
            "actor_id": str(log.actor_id) if log.actor_id else None,
            "actor_email": email,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": str(log.target_id) if log.target_id else None,
            "ip": str(log.ip) if log.ip else None,
            "metadata": log.metadata_json,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log, email in rows
    ]

    return {
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
    }
