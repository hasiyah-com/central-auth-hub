"""Admin router — overview KPIs + subsystem approval.

Endpoints:
  GET  /admin/overview                          -> KPI สรุป
  GET  /admin/subsystems                        -> list ทุก subsystem
  GET  /admin/subsystems/pending                -> เฉพาะที่รออนุมัติ
  GET  /admin/subsystems/{id}/active-sessions   -> users กำลังใช้งานอยู่ตอนนี้
  POST /admin/subsystems/{id}/approve            -> อนุมัติ subsystem
  POST /admin/subsystems/{id}/reject             -> ปฏิเสธ subsystem
  POST /admin/subsystems/{id}/suspend            -> ระงับใช้งาน subsystem (active → suspended)
  POST /admin/subsystems/{id}/resume             -> เปิดใช้งานใหม่ (suspended → active)
  GET  /admin/audit                              -> audit log viewer (filtered, paginated)
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, case, func, not_, or_
from sqlalchemy.orm import Session, aliased

from app.config import settings
from app.database import get_db
from app.deps import get_client_ip, require_hub_admin
from app.models import (
    AccessList,
    ApiAlert,
    AuditLog,
    LoginSession,
    Subsystem,
    SubsystemChangeRequest,
    User,
)
from app.services.audit_service import log_action
from app.services.critical_action_policy import gate as _stepup_gate
from app.services import passkey_recovery
from app.services.change_request_service import apply_approved
from app.services.email_service import (
    send_identity_challenge,
    send_revoke_notification,
    send_secret_retrieval_email,
)
from app.services.change_request_service import close_subsystem_login_sessions
from app.services.auth_policy import get_auth_policy, set_auth_policy
from app.services.identity_challenge import create_challenge
from app.services.jwt_service import revoke_jti
from app.services.webhook_dispatcher import send_access_revoked, send_access_updated
from app.services.subsystem_health import (
    get_status as get_health_status,
    clear_status as clear_health_status,
)
from app.redis_client import redis_client

log = logging.getLogger(__name__)


# ============ Notification read state (Redis-backed per admin) ============

_NOTIF_READ_PREFIX = "notif:read:"
_NOTIF_READ_TTL_SEC = 60 * 60 * 24 * 30  # 30 วัน


def _notif_read_key(admin_id) -> str:
    return f"{_NOTIF_READ_PREFIX}{admin_id}"


def _notif_marker(category: str, item_id: str) -> str:
    return f"{category}:{item_id}"


def _get_read_set(admin_id) -> set[str]:
    """Set ของ category:item_id ที่ admin คนนี้ mark อ่านแล้ว."""
    try:
        members = redis_client.smembers(_notif_read_key(admin_id))
        return set(members or [])
    except Exception:
        return set()


def _is_read(admin_id, read_set: set[str], category: str, item_id: str) -> bool:
    return _notif_marker(category, item_id) in read_set


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
            "redirect_uris": list(s.redirect_uris or []),
            "allowed_roles": list(s.allowed_roles or []),
            "access_revoke_webhook_url": s.access_revoke_webhook_url,
            "previous_secret_expires_at": s.previous_secret_expires_at,
            "whitelist_count": cnt or 0,
            "owner_email": owner_email,
            "created_at": s.created_at,
            "approved_at": s.approved_at,
            "health": get_health_status(str(s.id)),  # None ถ้ายังไม่เคยเช็ค
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


@router.post(
    "/subsystems/{subsystem_id}/approve",
    dependencies=[Depends(_stepup_gate("subsystem_approve"))],
)
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


@router.get("/users/{user_id}/passkeys")
def list_user_passkeys(
    user_id: str,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Admin ดู passkey ของ user (read-only overview) — Phase: admin passkey overview.

    ไม่ส่ง credential_id/public_key. ใช้ในหน้า Users (admin เห็นว่าใครมี passkey อะไร).
    """
    from app.services import webauthn_service
    from app.services.geoip import lookup_country
    from app.services import passkey_recovery

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้")

    rows = webauthn_service.list_for_user(target.id, db)
    passkeys = [
        {
            "id": str(r.id),
            "device_name": r.device_name,
            "device_type": r.device_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            "last_used_country": lookup_country(str(r.last_used_ip))
            if r.last_used_ip
            else None,
            "counter_regression_count": r.counter_regression_count or 0,
        }
        for r in rows
    ]
    bc = passkey_recovery.get_status(target.id, db)
    return {
        "user_id": str(target.id),
        "email": target.email,
        "passkeys": passkeys,
        "count": len(passkeys),
        "backup_codes": {
            "remaining": bc["remaining"],
            "total": bc["total"],
            "low": bc["low"],
        },
    }


@router.post(
    "/users/{user_id}/reset-passkeys",
    dependencies=[Depends(_stepup_gate("admin_reset"))],  # Improvement #8 — Phase 5
)
def reset_user_passkeys(
    user_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Admin reset passkey ของ user (กรณี user แจ้ง device หาย) — Phase 4 recovery.

    Revoke passkey ทั้งหมด (soft delete, reason=admin_reset). user ต้อง login
    ด้วย Google แล้ว enroll passkey ใหม่.
    """
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้")

    count = passkey_recovery.admin_reset_passkeys(target.id, db)
    log_action(
        db,
        actor_id=admin.id,
        action="passkey_admin_reset",
        target_type="user",
        target_id=target.id,
        ip=get_client_ip(request),
        metadata={"email": target.email, "revoked_count": count},
    )
    db.commit()
    return {
        "user_id": str(target.id),
        "email": target.email,
        "revoked_count": count,
        "message": f"revoke passkey {count} ตัวของ {target.email} แล้ว",
    }


@router.post(
    "/subsystems/{subsystem_id}/reject",
    dependencies=[Depends(_stepup_gate("subsystem_reject"))],
)
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


# ============ Suspend / Resume ============


@router.post(
    "/subsystems/{subsystem_id}/suspend",
    dependencies=[Depends(_stepup_gate("subsystem_suspend"))],
)
def suspend_subsystem(
    subsystem_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ระงับการใช้งาน subsystem ที่ active แล้ว → status='suspended'.

    หลังจากนี้ /oauth/authorize จะ reject + ทุก session ที่ active อยู่ถูกตัดทันที
    (logout_at=NOW, jti revoked, webhook → subsystem ลบ local session)
    """
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")
    if subsystem.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"suspend ใช้กับ subsystem ที่ active เท่านั้น (ตอนนี้: {subsystem.status})",
        )

    subsystem.status = "suspended"

    # ล้าง health cache — กัน entry เก่าค้างใน Redis ระหว่างถูกระงับ
    # (health loop ข้าม subsystem ที่ไม่ active อยู่แล้ว)
    clear_health_status(str(subsystem.id))

    # Force-revoke ทุก session ที่ active (logout_at + jti) ก่อน commit
    closed = close_subsystem_login_sessions(db, subsystem.id)

    log_action(
        db,
        actor_id=admin.id,
        action="subsystem_suspended",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "name": subsystem.name,
            "sessions_closed": closed["closed"],
            "jti_revoked": closed["jti_revoked"],
        },
    )
    db.commit()

    # Webhook → subsystem ตัด local session ทุก user (fail-safe)
    # ใช้ access_updated (รองรับ hub_user_id=None = kick all) ไม่ใช่ access_revoked
    # (access_revoked ที่ฝั่ง subsystem-dorm/library require hub_user_id เป็นรายคน)
    try:
        send_access_updated(
            subsystem,
            {
                "hub_user_id": None,
                "reason": "subsystem_suspended",
            },
        )
    except Exception:
        pass

    return {
        "id": str(subsystem.id),
        "name": subsystem.name,
        "status": "suspended",
        "sessions_closed": closed["closed"],
        "jti_revoked": closed["jti_revoked"],
        "message": (
            f"ระงับ '{subsystem.name}' แล้ว — "
            f"ตัด {closed['closed']} session, revoke {closed['jti_revoked']} JWT"
        ),
    }


@router.post(
    "/subsystems/{subsystem_id}/resume",
    dependencies=[Depends(_stepup_gate("subsystem_resume"))],
)
def resume_subsystem(
    subsystem_id: str,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """เปิดใช้งาน subsystem ที่ถูก suspended → status='active'."""
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")
    if subsystem.status != "suspended":
        raise HTTPException(
            status_code=400,
            detail=f"resume ใช้กับ subsystem ที่ suspended เท่านั้น (ตอนนี้: {subsystem.status})",
        )

    subsystem.status = "active"
    if not subsystem.approved_at:
        subsystem.approved_at = datetime.utcnow()

    # ล้าง health cache เก่า (อาจเป็น 'down' จากก่อน suspend) → preflight ไม่ block
    # ผิด ๆ จนกว่า health loop รอบถัดไป (≤5 นาที) จะ refresh ค่าจริง
    clear_health_status(str(subsystem.id))

    log_action(
        db,
        actor_id=admin.id,
        action="subsystem_resumed",
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
        "message": f"เปิดใช้งาน '{subsystem.name}' อีกครั้ง",
    }


# ============ Active sessions (users กำลังใช้งานอยู่) ============


@router.get("/subsystems/{subsystem_id}/active-sessions")
def list_active_sessions(
    subsystem_id: str,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """แสดง user ที่กำลัง active ใน subsystem นี้ (login แล้วยังไม่ logout + ไม่หมดอายุ JWT).

    เกณฑ์ active:
      - logout_at IS NULL
      - created_at อยู่ใน JWT expire window (จริงๆ user อาจปิด browser แต่ token ยังใช้ได้)
    """
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")

    cutoff = datetime.utcnow() - timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )

    rows = (
        db.query(LoginSession, User.email, User.full_name, User.user_type)
        .outerjoin(User, User.id == LoginSession.user_id)
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.logout_at.is_(None),
            LoginSession.created_at >= cutoff,
            # ตัด session ที่ถูก block ออก — ไม่ถือว่า active
            LoginSession.decision.notin_(["block", "would_block"]),
        )
        .order_by(LoginSession.created_at.desc())
        .all()
    )

    now = datetime.utcnow()
    return {
        "subsystem": {"id": str(subsystem.id), "name": subsystem.name},
        "count": len(rows),
        "sessions": [
            {
                "session_id": str(sess.id),
                "user_id": str(sess.user_id) if sess.user_id else None,
                "user_email": email,
                "full_name": full_name,
                "user_type": user_type,
                "ip": str(sess.ip) if sess.ip else None,
                "geo_country": sess.geo_country,
                "geo_city": sess.geo_city,
                "browser": sess.browser,
                "os_name": sess.os_name,
                "device_type": sess.device_type,
                "decision": sess.decision,
                "login_at": sess.created_at.isoformat() if sess.created_at else None,
                "duration_sec": int((now - sess.created_at).total_seconds())
                if sess.created_at
                else 0,
            }
            for sess, email, full_name, user_type in rows
        ],
    }


# ============ Subsystem activity stats ============


@router.get("/subsystems/{subsystem_id}/stats")
def subsystem_stats(
    subsystem_id: str,
    days: int = Query(7, ge=1, le=90, description="กี่วันย้อนหลัง"),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """KPI ของ subsystem — login counts, decision breakdown, unique users, active session count.

    ใช้ที่:
      - หน้า admin /subsystems/{id} แสดง section "ภาพรวม"
    """
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")

    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    base = db.query(LoginSession).filter(
        LoginSession.subsystem_id == subsystem.id,
        LoginSession.created_at >= cutoff,
    )
    total_logins = base.count()

    # decision breakdown
    decision_rows = (
        db.query(LoginSession.decision, func.count(LoginSession.id))
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.created_at >= cutoff,
        )
        .group_by(LoginSession.decision)
        .all()
    )
    decision_breakdown = {(d or "unknown"): c for d, c in decision_rows}

    # unique users
    unique_users = (
        db.query(func.count(func.distinct(LoginSession.user_id)))
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

    # active sessions ตอนนี้ (logout_at NULL + within JWT window)
    jwt_cutoff = now - timedelta(minutes=settings.jwt_access_token_expire_minutes)
    active_now = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.logout_at.is_(None),
            LoginSession.created_at >= jwt_cutoff,
            LoginSession.decision.notin_(["block", "would_block"]),
        )
        .scalar()
        or 0
    )

    # daily login counts (last N days)
    daily_rows = (
        db.query(
            func.date(LoginSession.created_at).label("d"),
            func.count(LoginSession.id).label("cnt"),
        )
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.created_at >= cutoff,
        )
        .group_by("d")
        .order_by("d")
        .all()
    )
    daily = [
        {
            "date": (d.isoformat() if hasattr(d, "isoformat") else str(d)),
            "count": int(c),
        }
        for d, c in daily_rows
    ]

    return {
        "subsystem": {"id": str(subsystem.id), "name": subsystem.name},
        "range": {
            "days": days,
            "from": cutoff.isoformat(),
            "to": now.isoformat(),
        },
        "total_logins": total_logins,
        "unique_users": unique_users,
        "active_now": active_now,
        "decision_breakdown": decision_breakdown,
        "daily": daily,
    }


# ============ Per-subsystem audit log ============


@router.get("/subsystems/{subsystem_id}/audit")
def subsystem_audit(
    subsystem_id: str,
    action: str | None = Query(None, description="filter by action"),
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Audit log เฉพาะ subsystem นี้ (target_id = subsystem_id) — paginated.

    ตรงกับ /admin/audit แต่ filter ฝั่ง server (เลิกพึ่ง client filter)
    """
    subsystem = db.query(Subsystem).filter(Subsystem.id == subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="ไม่พบ subsystem")

    q = (
        db.query(
            AuditLog,
            User.email,
            User.user_type,
            User.is_hub_admin,
        )
        .outerjoin(User, AuditLog.actor_id == User.id)
        .filter(
            AuditLog.target_type == "subsystem",
            AuditLog.target_id == subsystem.id,
        )
        .order_by(AuditLog.created_at.desc())
    )
    if action:
        q = q.filter(AuditLog.action == action)

    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    return {
        "subsystem": {"id": str(subsystem.id), "name": subsystem.name},
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": str(log.id),
                "actor_id": str(log.actor_id) if log.actor_id else None,
                "actor_email": email,
                "actor_user_type": user_type,
                "actor_is_hub_admin": bool(is_admin),
                "action": log.action,
                "ip": str(log.ip) if log.ip else None,
                "metadata": log.metadata_json,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log, email, user_type, is_admin in rows
        ],
    }


# ============ Force-revoke session ============


_VALID_REVOKE_LEVELS = {"notify", "challenge", "ban"}


@router.post(
    "/subsystems/{subsystem_id}/sessions/{session_id}/revoke",
    dependencies=[Depends(_stepup_gate("session_revoke"))],
)
def revoke_session(
    subsystem_id: str,
    session_id: str,
    request: Request,
    level: str = Query(
        "challenge",
        pattern="^(notify|challenge|ban)$",
        description=(
            "Revoke level: "
            "notify = ปิด session + email แจ้ง (login ใหม่ได้ทันที), "
            "challenge = ปิด session + ต้องคลิก confirm link ใน email ก่อน login ใหม่, "
            "ban = ปิด session + ลบ user ออกจาก whitelist (login ใหม่ไม่ได้จนกว่า admin จะเพิ่มกลับ)"
        ),
    ),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """บังคับให้ session ของ user หลุดทันที — มี 3 ระดับให้เลือก.

    การทำงานหลักทุก level:
      1. mark login_sessions.logout_at = NOW()
      2. ใส่ jti ลง Redis revocation list (JWT ใช้ Hub API ต่อไม่ได้)
      3. ยิง webhook ให้ subsystem ลบ local session

    เพิ่มเติมตาม level:
      - notify   → email แจ้ง user (can_relogin=True)
      - challenge → สร้าง identity challenge + email confirm link
      - ban      → ลบจาก access_list (revoked_at=NOW) + email แจ้ง (can_relogin=False)
    """
    if level not in _VALID_REVOKE_LEVELS:
        raise HTTPException(
            status_code=400, detail=f"level ต้องเป็น {sorted(_VALID_REVOKE_LEVELS)}"
        )

    sess = (
        db.query(LoginSession)
        .filter(
            LoginSession.id == session_id,
            LoginSession.subsystem_id == subsystem_id,
        )
        .first()
    )
    if not sess:
        raise HTTPException(status_code=404, detail="ไม่พบ session")
    if sess.logout_at is not None:
        raise HTTPException(status_code=400, detail="session นี้ปิดไปแล้ว")

    # 1. mark logout
    sess.logout_at = datetime.utcnow()

    # 2. revoke jti ถ้ามี — TTL = jwt expire (60min default)
    revoked_jwt = False
    if sess.jti:
        exp_unix = int(
            (
                sess.created_at
                + timedelta(minutes=settings.jwt_access_token_expire_minutes)
            ).timestamp()
        )
        revoked_jwt = revoke_jti(sess.jti, exp_unix)

    # ดึง user + subsystem ครั้งเดียว
    target_user = (
        db.query(User).filter(User.id == sess.user_id).first() if sess.user_id else None
    )
    subsystem = (
        db.query(Subsystem).filter(Subsystem.id == sess.subsystem_id).first()
        if sess.subsystem_id
        else None
    )
    subsystem_name = subsystem.name if subsystem else None

    # 3. Level-specific action
    extra_actions: dict = {}
    if level == "ban" and target_user and subsystem:
        # ลบจาก access_list (soft delete)
        from app.models import AccessList  # local import

        entry = (
            db.query(AccessList)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == target_user.id,
                AccessList.revoked_at.is_(None),
            )
            .first()
        )
        if entry:
            entry.revoked_at = datetime.utcnow()
            extra_actions["whitelist_removed"] = True

    challenge_url: str | None = None
    if level == "challenge" and target_user:
        try:
            plaintext_token, _expires = create_challenge(
                str(target_user.id), reason="admin_revoked"
            )
            challenge_url = (
                f"{settings.hub_base_url}/auth/confirm-identity?token={plaintext_token}"
            )
            extra_actions["challenge_created"] = True
        except Exception as e:
            extra_actions["challenge_error"] = str(e)

    # 4. Webhook ยิงก่อน log — เพื่อจับ delivery result ใส่ใน audit metadata
    #    ("เตะออกจริงๆ" = subsystem confirm 200 OK)
    webhook_delivered: bool | None = None
    if subsystem and sess.user_id:
        try:
            webhook_delivered = send_access_revoked(
                subsystem,
                {
                    "hub_user_id": str(sess.user_id),
                    "revoked_by": str(admin.id),
                    "reason": f"session_force_revoked_{level}",
                },
            )
        except Exception as e:
            log.warning("webhook send_access_revoked failed: %r", e)
            webhook_delivered = False

    # log #1 — target=login_session (สำหรับหน้า audit ของ session/user)
    log_action(
        db,
        actor_id=admin.id,
        action=f"session_force_revoked_{level}",
        target_type="login_session",
        target_id=sess.id,
        ip=get_client_ip(request),
        metadata={
            "level": level,
            "user_id": str(sess.user_id) if sess.user_id else None,
            "user_email": target_user.email if target_user else None,
            "subsystem_id": str(sess.subsystem_id) if sess.subsystem_id else None,
            "subsystem_name": subsystem_name,
            "jti_revoked": revoked_jwt,
            "had_jti": sess.jti is not None,
            "webhook_delivered": webhook_delivered,
            **extra_actions,
        },
    )

    # log #2 — target=subsystem (เพื่อโผล่ในหน้า audit ของ subsystem นี้
    # ให้เห็นว่ามี user คนไหนถูกเตะออก ใครเตะ เตะระดับไหน เตะสำเร็จไหม)
    if subsystem:
        log_action(
            db,
            actor_id=admin.id,
            action=f"user_force_revoked_{level}",
            target_type="subsystem",
            target_id=subsystem.id,
            ip=get_client_ip(request),
            metadata={
                "level": level,
                "session_id": str(sess.id),
                "user_id": str(sess.user_id) if sess.user_id else None,
                "user_email": target_user.email if target_user else None,
                "user_full_name": target_user.full_name if target_user else None,
                "jti_revoked": revoked_jwt,
                "webhook_delivered": webhook_delivered,
                **extra_actions,
            },
        )
    db.commit()

    # 5. Email user
    email_sent = False
    if target_user and target_user.email:
        try:
            if level == "challenge" and challenge_url:
                from app.services.identity_challenge import CHALLENGE_TTL_MIN

                email_sent = send_identity_challenge(
                    to_email=target_user.email,
                    full_name=target_user.full_name,
                    confirm_url=challenge_url,
                    expires_at=datetime.utcnow() + timedelta(minutes=CHALLENGE_TTL_MIN),
                    reason="admin_revoked",
                )
            else:
                email_sent = send_revoke_notification(
                    to_email=target_user.email,
                    full_name=target_user.full_name,
                    subsystem_name=subsystem_name,
                    when=sess.logout_at,
                    reason=f"admin {admin.email} กด revoke ({level})",
                    can_relogin=(level == "notify"),
                )
        except Exception:
            email_sent = False

    return {
        "session_id": str(sess.id),
        "level": level,
        "logout_at": sess.logout_at.isoformat(),
        "jti_revoked": revoked_jwt,
        "email_sent": email_sent,
        "whitelist_removed": extra_actions.get("whitelist_removed", False),
        "challenge_created": extra_actions.get("challenge_created", False),
        "message": {
            "notify": "ปิด session + แจ้งทาง email แล้ว (user login ใหม่ได้ปกติ)",
            "challenge": "ปิด session + ส่ง link confirm ทาง email (user ต้องคลิกก่อน login ใหม่ได้)",
            "ban": "ปิด session + ลบจาก whitelist (user login ใหม่ไม่ได้)",
        }[level],
    }


# ============ Change Request Approval Workflow ============


@router.get("/notifications")
def list_notifications(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """รวมการแจ้งเตือนทุกประเภท — สำหรับหน้า /notifications.

    Categories:
      - approval_requests : SubsystemChangeRequest status=pending
      - ml_anomaly        : LoginSession ที่ risk_score ≥ 0.7 ใน 24h
      - api_alerts        : ApiAlert ที่ยังไม่ resolved
      - subsystem_health  : Subsystem ที่ Redis health = down/degraded
    """
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    read_set = _get_read_set(admin.id)

    # 1) Approval requests (pending)
    pending_reqs_q = (
        db.query(
            SubsystemChangeRequest,
            Subsystem.name.label("sub_name"),
            User.email.label("req_email"),
        )
        .join(Subsystem, Subsystem.id == SubsystemChangeRequest.subsystem_id)
        .outerjoin(User, User.id == SubsystemChangeRequest.requested_by)
        .filter(SubsystemChangeRequest.status == "pending")
        .order_by(SubsystemChangeRequest.created_at.desc())
    )
    pending_total = pending_reqs_q.count()
    pending_items = [
        {
            "id": str(req.id),
            "title": f"{req.request_type.replace('_', ' ').title()} · {sub_name}",
            "subtitle": f"by {req_email or 'unknown'}",
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "severity": "warning",
            "meta": {"request_type": req.request_type},
            "is_read": _is_read(admin.id, read_set, "approval_requests", str(req.id)),
        }
        for req, sub_name, req_email in pending_reqs_q.limit(20).all()
    ]

    # 1b) Recent admin overrides (approved + auto-applied within 24h)
    override_q = (
        db.query(
            SubsystemChangeRequest,
            Subsystem.name.label("sub_name"),
            User.email.label("req_email"),
        )
        .join(Subsystem, Subsystem.id == SubsystemChangeRequest.subsystem_id)
        .outerjoin(User, User.id == SubsystemChangeRequest.requested_by)
        .filter(
            SubsystemChangeRequest.status == "approved",
            SubsystemChangeRequest.reviewed_at >= cutoff_24h,
            # auto-approved by admin = reviewer_id == requested_by
            SubsystemChangeRequest.reviewer_id == SubsystemChangeRequest.requested_by,
        )
        .order_by(SubsystemChangeRequest.reviewed_at.desc())
    )
    override_total = override_q.count()
    override_items = [
        {
            "id": str(req.id),
            "title": f"🛡️ Admin Override · {req.request_type.replace('_', ' ').title()} · {sub_name}",
            "subtitle": f"by {req_email or 'unknown'}",
            "created_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
            "severity": "info",
            "meta": {"request_type": req.request_type, "override": True},
            "is_read": _is_read(admin.id, read_set, "admin_overrides", str(req.id)),
        }
        for req, sub_name, req_email in override_q.limit(20).all()
    ]

    # 1c) Recent decisions (admin approve/reject dev's request, 24h)
    #     ต่างจาก admin_overrides ตรงที่ผู้ขอ ≠ ผู้ review (มีคู่ dev+admin จริง)
    # join reviewer แยกออกมาเพื่อแสดงว่า admin คนไหนเป็นคน decide
    reviewer_alias = aliased(User)
    decided_q = (
        db.query(
            SubsystemChangeRequest,
            Subsystem.name.label("sub_name"),
            User.email.label("req_email"),
            reviewer_alias.email.label("reviewer_email"),
        )
        .join(Subsystem, Subsystem.id == SubsystemChangeRequest.subsystem_id)
        .outerjoin(User, User.id == SubsystemChangeRequest.requested_by)
        .outerjoin(
            reviewer_alias, reviewer_alias.id == SubsystemChangeRequest.reviewer_id
        )
        .filter(
            SubsystemChangeRequest.status.in_(("approved", "rejected")),
            SubsystemChangeRequest.reviewed_at >= cutoff_24h,
            # ตัดออกที่ admin auto-approve ตัวเอง (อันนั้นอยู่ใน admin_overrides แล้ว)
            SubsystemChangeRequest.reviewer_id != SubsystemChangeRequest.requested_by,
        )
        .order_by(SubsystemChangeRequest.reviewed_at.desc())
    )
    decided_total = decided_q.count()
    decided_items = [
        {
            "id": str(req.id),
            "title": (
                f"{'✅' if req.status == 'approved' else '❌'} "
                f"{req.status.title()} · "
                f"{req.request_type.replace('_', ' ').title()} · {sub_name}"
            ),
            "subtitle": (
                f"requested by {req_email or 'unknown'} · "
                f"decided by {reviewer_email or 'unknown'}"
                + (f" · note: {req.reviewer_note}" if req.reviewer_note else "")
            ),
            "created_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
            "severity": "info" if req.status == "approved" else "warning",
            "meta": {
                "request_type": req.request_type,
                "status": req.status,
                "reviewer_note": req.reviewer_note,
            },
            "is_read": _is_read(admin.id, read_set, "decided_requests", str(req.id)),
        }
        for req, sub_name, req_email, reviewer_email in decided_q.limit(20).all()
    ]

    # 2) ML anomaly — ใช้ threshold เดียวกับ Telegram alert
    #    (alert_ml_warning_threshold = 0.5 default · ตัวที่เห็นใน Telegram)
    ml_threshold = float(settings.alert_ml_warning_threshold)
    ml_critical = float(settings.alert_ml_critical_threshold)
    ml_q = (
        db.query(
            LoginSession,
            User.email.label("user_email"),
            Subsystem.name.label("sub_name"),
        )
        .outerjoin(User, User.id == LoginSession.user_id)
        .outerjoin(Subsystem, Subsystem.id == LoginSession.subsystem_id)
        .filter(
            LoginSession.created_at >= cutoff_24h,
            LoginSession.risk_score.is_not(None),
            LoginSession.risk_score >= ml_threshold,
        )
        .order_by(LoginSession.created_at.desc())
    )
    ml_total = ml_q.count()
    ml_items = [
        {
            "id": str(sess.id),
            "title": f"High risk login · score {float(sess.risk_score):.2f}",
            "subtitle": f"{user_email or '?'} → {sub_name or 'Hub-direct'}",
            "created_at": sess.created_at.isoformat() if sess.created_at else None,
            "severity": (
                "critical" if float(sess.risk_score or 0) >= ml_critical else "warning"
            ),
            "meta": {
                "session_id": str(sess.id),
                "decision": sess.decision,
                "ip": str(sess.ip) if sess.ip else None,
            },
            "is_read": _is_read(admin.id, read_set, "ml_anomaly", str(sess.id)),
        }
        for sess, user_email, sub_name in ml_q.limit(20).all()
    ]

    # 3) API alerts (ยังไม่ resolved)
    api_q = (
        db.query(ApiAlert)
        .filter(ApiAlert.resolved.is_(False))
        .order_by(ApiAlert.created_at.desc())
    )
    api_total = api_q.count()
    api_items = [
        {
            "id": str(a.id),
            "title": f"{a.rule.replace('_', ' ').title()} · {a.ip}",
            "subtitle": (
                f"count {(a.detail or {}).get('count', '?')} · "
                f"window {(a.detail or {}).get('window_sec', '?')}s"
            ),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "severity": a.severity,
            "meta": {"rule": a.rule, "ip": str(a.ip)},
            "is_read": _is_read(admin.id, read_set, "api_alerts", str(a.id)),
        }
        for a in api_q.limit(20).all()
    ]

    # 3b) API alerts summary (เช้า/บ่าย/เย็น) — 3 ล่าสุดใน 24h
    #     แสดงสถานะภาพรวมไม่ใช่ alert ด่วน
    api_summary_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "api_alerts_summary",
            AuditLog.created_at >= cutoff_24h,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(3)
        .all()
    )
    for row in api_summary_rows:
        meta = row.metadata_json or {}
        label = meta.get("label") or "📋 รายงาน API"
        total_alerts = meta.get("total", 0)
        unresolved = meta.get("unresolved", 0)
        by_sev = meta.get("by_severity") or {}
        if total_alerts == 0:
            subtitle = "✓ ไม่มี API alert ใน 24h"
            sev = "info"
        else:
            sev_parts = []
            if by_sev.get("critical"):
                sev_parts.append(f"{by_sev['critical']} critical")
            if by_sev.get("warning"):
                sev_parts.append(f"{by_sev['warning']} warning")
            if by_sev.get("info"):
                sev_parts.append(f"{by_sev['info']} info")
            subtitle = (
                f"{total_alerts} alerts ใน 24h"
                + (f" · {unresolved} unresolved" if unresolved else "")
                + (" · " + " · ".join(sev_parts) if sev_parts else "")
            )
            sev = (
                "critical"
                if by_sev.get("critical", 0) > 0
                else "warning"
                if unresolved > 0
                else "info"
            )
        api_total += 1
        api_items.append(
            {
                "id": str(row.id),
                "title": f"{label} · {meta.get('date', '')}",
                "subtitle": subtitle,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "severity": sev,
                "meta": {
                    "kind": "api_summary",
                    "slot": meta.get("slot"),
                    "date": meta.get("date"),
                    "total": total_alerts,
                    "unresolved": unresolved,
                    "resolved": meta.get("resolved"),
                    "by_severity": by_sev,
                    "top_rules": meta.get("top_rules"),
                    "top_ips": meta.get("top_ips"),
                    "window_hours": meta.get("window_hours"),
                },
                "is_read": _is_read(admin.id, read_set, "api_alerts", str(row.id)),
            }
        )

    # 4) Subsystem health (Redis cache: status != online)
    health_items: list[dict] = []
    health_total = 0
    subsystems_active = db.query(Subsystem).filter(Subsystem.status == "active").all()
    for sub in subsystems_active:
        h = get_health_status(str(sub.id))
        if h and h.get("status") in ("down", "degraded"):
            health_total += 1
            if len(health_items) < 20:
                health_items.append(
                    {
                        "id": str(sub.id),
                        "title": f"{sub.name} · {h.get('status').upper()}",
                        "subtitle": (
                            h.get("error") or f"latency {h.get('latency_ms', '?')}ms"
                        ),
                        "created_at": h.get("checked_at"),
                        "severity": (
                            "critical" if h.get("status") == "down" else "warning"
                        ),
                        "meta": {
                            "subsystem_id": str(sub.id),
                            "url": h.get("url"),
                        },
                        "is_read": _is_read(
                            admin.id, read_set, "subsystem_health", str(sub.id)
                        ),
                    }
                )

    # 4b) Health summaries (เช้า/บ่าย/เย็น) — สรุปการเช็คสุขภาพ 3 ช่วงต่อวัน
    #     ดึงล่าสุด 3 entries จาก audit_logs (action=subsystem_health_summary)
    #     เพื่อให้ admin รู้ว่าระบบเช็คสุขภาพทำงานปกติแม้ไม่มี subsystem ที่ down
    summary_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "subsystem_health_summary",
            AuditLog.created_at >= cutoff_24h,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(3)
        .all()
    )
    for row in summary_rows:
        meta = row.metadata_json or {}
        counts = meta.get("counts") or {}
        label = meta.get("label") or "รายงานสุขภาพ"
        total_subs = meta.get("total", 0)
        online = counts.get("online", 0)
        degraded = counts.get("degraded", 0)
        down = counts.get("down", 0)
        unknown = counts.get("unknown", 0)
        unhealthy = degraded + down
        # severity ตามสภาพ
        if down > 0:
            sev = "critical"
        elif degraded > 0:
            sev = "warning"
        else:
            sev = "info"
        # text สรุป — รวม Hub + subsystems
        if unhealthy == 0 and unknown == 0:
            subtitle = f"✓ ทุกระบบปกติ ({online}/{total_subs} online · รวม Hub)"
        else:
            parts = []
            if online:
                parts.append(f"{online} online")
            if degraded:
                parts.append(f"{degraded} degraded")
            if down:
                parts.append(f"{down} down")
            if unknown:
                parts.append(f"{unknown} unknown")
            subtitle = (" · ".join(parts) if parts else "ไม่มีรายการ") + " (รวม Hub)"
        health_total += 1
        health_items.append(
            {
                "id": str(row.id),
                "title": f"{label} · {meta.get('date', '')}",
                "subtitle": subtitle,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "severity": sev,
                "meta": {
                    "kind": "health_summary",
                    "slot": meta.get("slot"),
                    "date": meta.get("date"),
                    "counts": counts,
                    "total": total_subs,
                    "details": meta.get("details"),
                },
                "is_read": _is_read(
                    admin.id, read_set, "subsystem_health", str(row.id)
                ),
            }
        )

    total = (
        pending_total
        + ml_total
        + api_total
        + health_total
        + override_total
        + decided_total
    )

    # นับ unread per category — Sidebar badge ใช้ตัวนี้ (ลดลงเมื่อ admin กดอ่าน)
    def _unread(items: list[dict]) -> int:
        return sum(1 for x in items if not x.get("is_read"))

    unread_by_category = {
        "approval_requests": _unread(pending_items),
        "admin_overrides": _unread(override_items),
        "decided_requests": _unread(decided_items),
        "ml_anomaly": _unread(ml_items),
        "api_alerts": _unread(api_items),
        "subsystem_health": _unread(health_items),
    }
    unread_in_view = sum(unread_by_category.values())

    return {
        "total": total,
        "unread_in_view": unread_in_view,
        "unread_by_category": unread_by_category,
        "categories": {
            "approval_requests": {
                "label": "คำขอจาก Developer (รอ review)",
                "icon": "📋",
                "count": pending_total,
                "items": pending_items,
                "link": "/pending-requests",
            },
            "admin_overrides": {
                "label": "Admin Override (24h ล่าสุด)",
                "icon": "🛡️",
                "count": override_total,
                "items": override_items,
                "link": "/pending-requests",
            },
            "decided_requests": {
                "label": "ประวัติ approve/reject คำขอ (24h ล่าสุด)",
                "icon": "📜",
                "count": decided_total,
                "items": decided_items,
                "link": "/pending-requests",
            },
            "ml_anomaly": {
                "label": "ML Anomaly Login",
                "icon": "🧠",
                "count": ml_total,
                "items": ml_items,
                "link": "/ml",
            },
            "api_alerts": {
                "label": "API Security Alerts",
                "icon": "🛡️",
                "count": api_total,
                "items": api_items,
                "link": "/api-alerts",
            },
            "subsystem_health": {
                "label": "Subsystem health / รายงาน",
                "icon": "🟢",
                "count": health_total,
                "items": health_items,
                "link": "/subsystems",
            },
        },
    }


@router.post("/subsystems/health/emit-summary-now")
async def emit_health_summary_now(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """[Admin] บังคับสร้าง health summary ทันที (ไม่รอ slot 8/13/18).

    Slot จะเซ็ตเป็น "manual-HHMMSS" + วันที่ปัจจุบัน — ไม่ชน mutex ของ slot ปกติ
    Summary จะรวม Hub self-check + subsystems ทั้งหมด
    """
    import asyncio as _asyncio

    from app.services.subsystem_health import (
        BKK_TZ,
        _emit_api_alerts_summary,
        _emit_summary,
        _ping,
    )

    subsystems = db.query(Subsystem).filter(Subsystem.status == "active").all()
    # ping subsystems พร้อมกัน (Hub self-check จะถูกเรียกใน _emit_summary)
    results = (
        await _asyncio.gather(*[_ping(s) for s in subsystems]) if subsystems else []
    )

    now_bkk = datetime.now(BKK_TZ)
    slot = f"manual-{now_bkk.strftime('%H%M%S')}"
    label = "🧪 รายงาน (manual)"
    date_str = now_bkk.strftime("%Y-%m-%d")

    await _emit_summary(db, subsystems, list(results), slot, label, date_str)
    _emit_api_alerts_summary(db, slot, label, date_str)

    return {
        "ok": True,
        "emitted": True,
        "slot": slot,
        "date": date_str,
        "subsystems": len(subsystems),
        "includes_hub_self_check": True,
        "includes_api_alerts_summary": True,
    }


class NotifMarkBody(BaseModel):
    items: list[dict]  # [{"category": "...", "id": "..."}]


@router.post("/notifications/mark-read")
def notifications_mark_read(
    body: NotifMarkBody,
    admin: User = Depends(require_hub_admin),
):
    """เพิ่มรายการเข้า read set (per-admin Redis)."""
    if not body.items:
        return {"marked": 0}
    markers = [
        _notif_marker(i.get("category", ""), str(i.get("id", "")))
        for i in body.items
        if i.get("category") and i.get("id")
    ]
    if not markers:
        return {"marked": 0}
    try:
        redis_client.sadd(_notif_read_key(admin.id), *markers)
        # refresh TTL กัน Redis เก็บค้างถาวร
        redis_client.expire(_notif_read_key(admin.id), _NOTIF_READ_TTL_SEC)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"redis error: {e}")
    return {"marked": len(markers)}


@router.post("/notifications/mark-unread")
def notifications_mark_unread(
    body: NotifMarkBody,
    admin: User = Depends(require_hub_admin),
):
    """ลบ marker ออกจาก read set."""
    if not body.items:
        return {"unmarked": 0}
    markers = [
        _notif_marker(i.get("category", ""), str(i.get("id", "")))
        for i in body.items
        if i.get("category") and i.get("id")
    ]
    if not markers:
        return {"unmarked": 0}
    try:
        removed = redis_client.srem(_notif_read_key(admin.id), *markers) or 0
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"redis error: {e}")
    return {"unmarked": int(removed)}


@router.post("/notifications/clear-all")
def notifications_clear_all(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Mark **ทุกอันที่กำลังเห็นใน notification feed** ว่า read.

    ดึง items จาก /notifications logic แบบเดียว — ไม่ลบ Redis set เก่า
    """
    # Re-use logic ง่ายๆ ด้วยการเรียก inline:
    payload = (
        list_notifications.__wrapped__(admin=admin, db=db)
        if hasattr(list_notifications, "__wrapped__")
        else list_notifications(admin=admin, db=db)
    )
    markers: list[str] = []
    for cat_key, cat in (payload.get("categories") or {}).items():
        for item in cat.get("items", []):
            markers.append(_notif_marker(cat_key, str(item["id"])))
    if not markers:
        return {"marked": 0}
    try:
        redis_client.sadd(_notif_read_key(admin.id), *markers)
        redis_client.expire(_notif_read_key(admin.id), _NOTIF_READ_TTL_SEC)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"redis error: {e}")
    return {"marked": len(markers)}


@router.get("/notifications/count")
def notifications_count(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Count summary — ใช้ใน sidebar badge + dashboard banner (poll ทุก 30s).

    Returns:
      - total: จำนวนรวมในระบบ (ไม่เกี่ยวกับ read state)
      - unread: จำนวนที่ admin คนนี้ยังไม่อ่าน (รวมทุก category)
      - by_category: total ต่อ category
    """
    # ใช้ logic เดียวกับ /notifications เพื่อให้ unread ตรงกัน
    full = list_notifications(admin=admin, db=db)
    return {
        "total": full["total"],
        "unread": full.get("unread_in_view", full["total"]),
        # total ต่อ category (สำหรับ tab counter)
        "by_category": {k: cat["count"] for k, cat in full["categories"].items()},
        # unread ต่อ category (สำหรับ sidebar badge)
        "unread_by_category": full.get("unread_by_category", {}),
    }


@router.get("/notifications/_count_legacy")
def notifications_count_legacy(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Legacy fast counter — ไม่ใช้แล้ว (เก็บไว้กัน external call)."""
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)

    pending = (
        db.query(func.count(SubsystemChangeRequest.id))
        .filter(SubsystemChangeRequest.status == "pending")
        .scalar()
        or 0
    )
    overrides = (
        db.query(func.count(SubsystemChangeRequest.id))
        .filter(
            SubsystemChangeRequest.status == "approved",
            SubsystemChangeRequest.reviewed_at >= cutoff_24h,
            SubsystemChangeRequest.reviewer_id == SubsystemChangeRequest.requested_by,
        )
        .scalar()
        or 0
    )
    ml = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.created_at >= cutoff_24h,
            LoginSession.risk_score.is_not(None),
            LoginSession.risk_score >= float(settings.alert_ml_warning_threshold),
        )
        .scalar()
        or 0
    )
    api = (
        db.query(func.count(ApiAlert.id)).filter(ApiAlert.resolved.is_(False)).scalar()
        or 0
    )
    # health = scan Redis
    health = 0
    for sub in db.query(Subsystem).filter(Subsystem.status == "active").all():
        h = get_health_status(str(sub.id))
        if h and h.get("status") in ("down", "degraded"):
            health += 1

    return {
        "total": pending + overrides + ml + api + health,
        "by_category": {
            "approval_requests": pending,
            "admin_overrides": overrides,
            "ml_anomaly": ml,
            "api_alerts": api,
            "subsystem_health": health,
        },
    }


@router.get("/change-requests/count")
def change_requests_count(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """นับ pending requests — ใช้ใน sidebar badge + dashboard widget."""
    pending = (
        db.query(func.count(SubsystemChangeRequest.id))
        .filter(SubsystemChangeRequest.status == "pending")
        .scalar()
        or 0
    )
    by_type_rows = (
        db.query(
            SubsystemChangeRequest.request_type, func.count(SubsystemChangeRequest.id)
        )
        .filter(SubsystemChangeRequest.status == "pending")
        .group_by(SubsystemChangeRequest.request_type)
        .all()
    )
    return {
        "pending": pending,
        "by_type": {t: int(c) for t, c in by_type_rows},
    }


@router.get("/change-requests")
def list_change_requests(
    status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
    subsystem_id: str | None = None,
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """ดูรายการ change request — default = pending."""
    q = (
        db.query(
            SubsystemChangeRequest,
            Subsystem.name.label("subsystem_name"),
            User.email.label("requested_by_email"),
        )
        .join(Subsystem, Subsystem.id == SubsystemChangeRequest.subsystem_id)
        .outerjoin(User, User.id == SubsystemChangeRequest.requested_by)
        .order_by(SubsystemChangeRequest.created_at.desc())
    )
    if status:
        q = q.filter(SubsystemChangeRequest.status == status)
    else:
        q = q.filter(SubsystemChangeRequest.status == "pending")
    if subsystem_id:
        q = q.filter(SubsystemChangeRequest.subsystem_id == subsystem_id)

    total = q.count()
    rows = q.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "items": [
            {
                "id": str(req.id),
                "subsystem_id": str(req.subsystem_id),
                "subsystem_name": sub_name,
                "requested_by": str(req.requested_by),
                "requested_by_email": req_email,
                "request_type": req.request_type,
                "payload": req.payload,
                "status": req.status,
                "reviewer_id": str(req.reviewer_id) if req.reviewer_id else None,
                "reviewer_note": req.reviewer_note,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
            }
            for req, sub_name, req_email in rows
        ],
    }


class ReviewBody(BaseModel):
    note: str | None = None


@router.post("/change-requests/{request_id}/approve")
def approve_change_request(
    request_id: str,
    body: ReviewBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Approve a pending request → apply การเปลี่ยนแปลงจริง.

    ถ้าเป็น rotate_secret → ส่ง email พร้อม one-time link ให้ requester
    """
    req = (
        db.query(SubsystemChangeRequest)
        .filter(SubsystemChangeRequest.id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="ไม่พบ request")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"request นี้ปิดไปแล้ว (status={req.status})",
        )

    subsystem = db.query(Subsystem).filter(Subsystem.id == req.subsystem_id).first()
    if not subsystem:
        raise HTTPException(status_code=404, detail="subsystem หาย")

    # Apply change
    try:
        result = apply_approved(db, req, subsystem)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"apply ล้มเหลว: {e}")

    req.status = "approved"
    req.reviewer_id = admin.id
    req.reviewer_note = (body.note or "").strip() or None
    req.reviewed_at = datetime.utcnow()

    log_action(
        db,
        actor_id=admin.id,
        action="change_request_approved",
        target_type="subsystem",
        target_id=subsystem.id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "request_type": req.request_type,
            "applied_result": result,
        },
    )
    db.commit()

    # หลัง commit → ยิง access_updated webhook ให้ subsystem (fail-safe)
    # role/scope เปลี่ยน → subsystem บังคับ user re-auth → ได้ค่าล่าสุด
    try:
        from app.services.change_request_service import notify_subsystem_after_apply

        notify_subsystem_after_apply(req, subsystem, result)
    except Exception as e:
        log.warning("notify_subsystem_after_apply failed: %r", e)

    # Email requester
    requester = db.query(User).filter(User.id == req.requested_by).first()
    email_sent = False
    if requester and requester.email:
        try:
            if req.request_type == "rotate_secret":
                # ส่ง one-time retrieval link ผ่าน email
                from datetime import datetime as _dt

                expires_at = _dt.fromisoformat(result["retrieval_expires_at"])
                email_sent = send_secret_retrieval_email(
                    to_email=requester.email,
                    subsystem_name=subsystem.name,
                    retrieval_url=result["retrieval_url"],
                    expires_at=expires_at,
                    client_id=subsystem.client_id,
                )
            else:
                # ใช้ email_service.send_change_request_decision (Phase 4)
                from app.services.email_service import (
                    send_change_request_decision,
                )

                email_sent = send_change_request_decision(
                    to_email=requester.email,
                    full_name=requester.full_name,
                    subsystem_name=subsystem.name,
                    request_type=req.request_type,
                    decision="approved",
                    reviewer_email=admin.email,
                    note=req.reviewer_note,
                )
        except Exception:
            email_sent = False

    return {
        "id": str(req.id),
        "status": "approved",
        "applied_result": result,
        "email_sent": email_sent,
        "message": f"Approve เรียบร้อย · type={req.request_type}",
    }


@router.post("/change-requests/{request_id}/reject")
def reject_change_request(
    request_id: str,
    body: ReviewBody,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Reject a pending request — ไม่ apply, email dev พร้อม reason."""
    req = (
        db.query(SubsystemChangeRequest)
        .filter(SubsystemChangeRequest.id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="ไม่พบ request")
    if req.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"request นี้ปิดไปแล้ว (status={req.status})",
        )
    if not body.note or not body.note.strip():
        raise HTTPException(
            status_code=400,
            detail="กรุณาใส่ note อธิบายเหตุผลที่ reject",
        )

    req.status = "rejected"
    req.reviewer_id = admin.id
    req.reviewer_note = body.note.strip()
    req.reviewed_at = datetime.utcnow()

    subsystem = db.query(Subsystem).filter(Subsystem.id == req.subsystem_id).first()

    log_action(
        db,
        actor_id=admin.id,
        action="change_request_rejected",
        target_type="subsystem",
        target_id=req.subsystem_id,
        ip=get_client_ip(request),
        metadata={
            "request_id": str(req.id),
            "request_type": req.request_type,
            "note": req.reviewer_note,
        },
    )
    db.commit()

    # Email requester
    requester = db.query(User).filter(User.id == req.requested_by).first()
    email_sent = False
    if requester and requester.email and subsystem:
        try:
            from app.services.email_service import send_change_request_decision

            email_sent = send_change_request_decision(
                to_email=requester.email,
                full_name=requester.full_name,
                subsystem_name=subsystem.name,
                request_type=req.request_type,
                decision="rejected",
                reviewer_email=admin.email,
                note=req.reviewer_note,
            )
        except Exception:
            email_sent = False

    return {
        "id": str(req.id),
        "status": "rejected",
        "email_sent": email_sent,
        "message": "Reject เรียบร้อย — แจ้ง requester ทาง email แล้ว",
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


# ============ Global Auth Policy (login methods) ============


class AuthPolicyUpdate(BaseModel):
    google: bool
    passkey: bool


def _kick_all_subsystems(db: Session, admin_id, reason: str) -> dict:
    """ตัดทุก session ที่ active ในทุก subsystem + ยิง webhook kick-all.

    ใช้ตอนเปลี่ยน global auth-policy → บังคับ user ทั้งระบบ login ใหม่ตามวิธีที่เลือก.
    คืนสรุป {total_sessions_closed, total_jti_revoked, subsystems: [...]}
    """
    subs = db.query(Subsystem).all()
    total_closed = 0
    total_jti = 0
    per_sub: list[dict] = []
    for sub in subs:
        closed = close_subsystem_login_sessions(db, sub.id)
        total_closed += closed["closed"]
        total_jti += closed["jti_revoked"]
        if closed["closed"]:
            per_sub.append(
                {
                    "subsystem_id": str(sub.id),
                    "subsystem_name": sub.name,
                    "sessions_closed": closed["closed"],
                    "jti_revoked": closed["jti_revoked"],
                }
            )
    return {
        "total_sessions_closed": total_closed,
        "total_jti_revoked": total_jti,
        "subsystems": per_sub,
        "_all_subs": subs,  # ใช้ยิง webhook หลัง commit
    }


@router.get("/auth-policy")
def read_auth_policy(
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """อ่าน global auth-policy ปัจจุบัน (วิธี login ที่เปิดใช้)."""
    return get_auth_policy(db)


@router.put(
    "/auth-policy",
    dependencies=[Depends(_stepup_gate("auth_policy_update"))],
)
def update_auth_policy(
    payload: AuthPolicyUpdate,
    request: Request,
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """เปลี่ยน global auth-policy → kick ทุก session ทุก subsystem ให้ login ใหม่.

    - ต้องเปิดอย่างน้อย 1 วิธี (กัน lockout) — ไม่งั้น 400
    - step-up gate (critical action)
    - หลังเปลี่ยน: ตัด session ทุก subsystem + webhook kick-all → user login ใหม่
      จะเห็นเฉพาะวิธีที่เปิดไว้
    """
    old_policy = get_auth_policy(db)
    try:
        new_policy = set_auth_policy(
            db, google=payload.google, passkey=payload.passkey, actor_id=admin.id
        )
    except ValueError as e:
        # B7 — log failure path
        log_action(
            db,
            actor_id=admin.id,
            action="auth_policy_update_failed",
            target_type="app_setting",
            target_id=None,
            ip=get_client_ip(request),
            metadata={"reason": str(e), "attempted": payload.model_dump()},
        )
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # เปลี่ยนจริงไหม — ถ้าไม่เปลี่ยน ไม่ต้อง kick
    changed = old_policy != new_policy
    kick = {
        "total_sessions_closed": 0,
        "total_jti_revoked": 0,
        "subsystems": [],
        "_all_subs": [],
    }
    if changed:
        kick = _kick_all_subsystems(db, admin.id, reason="auth_policy_changed")

    log_action(
        db,
        actor_id=admin.id,
        action="auth_policy_updated",
        target_type="app_setting",
        target_id=None,
        ip=get_client_ip(request),
        metadata={
            "old": old_policy,
            "new": new_policy,
            "changed": changed,
            "total_sessions_closed": kick["total_sessions_closed"],
            "total_jti_revoked": kick["total_jti_revoked"],
            "subsystems_kicked": kick["subsystems"],
        },
    )
    db.commit()

    # ยิง webhook kick-all ทุก subsystem หลัง commit (fail-safe)
    if changed:
        for sub in kick["_all_subs"]:
            try:
                send_access_updated(
                    sub,
                    {"hub_user_id": None, "reason": "auth_policy_changed"},
                )
            except Exception:
                pass

    methods = [m for m, on in new_policy.items() if on]
    return {
        "policy": new_policy,
        "changed": changed,
        "total_sessions_closed": kick["total_sessions_closed"],
        "total_jti_revoked": kick["total_jti_revoked"],
        "subsystems_kicked": kick["subsystems"],
        "message": (
            f"อัปเดตวิธี login เป็น: {', '.join(methods)} — "
            + (
                f"ตัด {kick['total_sessions_closed']} session ทุก subsystem แล้ว"
                if changed
                else "ไม่มีการเปลี่ยนแปลง"
            )
        ),
    }


# ============ Access Activity (realtime login feed — email-centric) ============

# decision → กลุ่มสำหรับ KPI
_BLOCKED_DECISIONS = ("block", "would_block")
_CHALLENGED_DECISIONS = ("challenge", "mfa", "would_mfa", "would_challenge")


def _activity_item(ls, email, full_name, user_type, sub_name, now=None) -> dict:
    """แปลง (LoginSession + joined fields) → dict สำหรับ feed.

    now != None → ใส่ online_seconds (สำหรับ active section).
    """
    d = {
        "id": str(ls.id),
        "created_at": ls.created_at.isoformat() if ls.created_at else None,
        "user_id": str(ls.user_id) if ls.user_id else None,
        "user_email": email,
        "full_name": full_name,
        "user_type": user_type,
        "subsystem_id": str(ls.subsystem_id) if ls.subsystem_id else None,
        "subsystem_name": sub_name,  # None = Hub-direct
        "login_method": ls.login_method,
        "anomaly_score": float(ls.anomaly_score)
        if ls.anomaly_score is not None
        else None,
        "risk_score": float(ls.risk_score) if ls.risk_score is not None else None,
        "decision": ls.decision,
        "ip": str(ls.ip) if ls.ip else None,
        "geo_country": ls.geo_country,
        "geo_city": ls.geo_city,
        "browser": ls.browser,
        "os_name": ls.os_name,
        "device_type": ls.device_type,
        "is_attack_ip": bool(ls.is_attack_ip),
        "logout_at": ls.logout_at.isoformat() if ls.logout_at else None,
    }
    if now is not None and ls.created_at is not None:
        d["online_seconds"] = int((now - ls.created_at).total_seconds())
    return d


@router.get("/activity")
def access_activity(
    q: str | None = Query(None, description="ค้นหา email / ชื่อ"),
    decision: str | None = Query(None, description="filter decision"),
    subsystem_id: str | None = Query(
        None, description="filter subsystem (uuid) หรือ 'hub' = Hub-direct"
    ),
    channel: str | None = Query(None, description="filter login_method"),
    hours: int = Query(24, ge=1, le=720, description="ช่วงเวลาย้อนหลัง (ชม.)"),
    skip: int = 0,
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_hub_admin),
    db: Session = Depends(get_db),
):
    """Feed การเข้าใช้งานทั้งหมด (login_sessions) — pivot ด้วย email.

    แสดง: ใคร (email/ชื่อ/type) · ระบบย่อยไหน · ช่องทาง (login_method) ·
          ML/risk เท่าไร · decision · ที่ไหน (geo/ip) · device · เมื่อไหร่.

    + KPIs (total/blocked/challenged/unique users/avg risk) ในช่วง `hours`
    + hourly series (24 ช่อง) สำหรับ chart
    ใช้ใน admin /activity (auto-refresh realtime).
    """
    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours)

    base = (
        db.query(
            LoginSession,
            User.email,
            User.full_name,
            User.user_type,
            Subsystem.name.label("subsystem_name"),
        )
        .outerjoin(User, User.id == LoginSession.user_id)
        .outerjoin(Subsystem, Subsystem.id == LoginSession.subsystem_id)
        .filter(LoginSession.created_at >= window_start)
    )

    # ── filters ──
    if q:
        like = f"%{q.strip()}%"
        base = base.filter(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if decision:
        base = base.filter(LoginSession.decision == decision)
    if channel:
        base = base.filter(LoginSession.login_method == channel)
    if subsystem_id == "hub":
        base = base.filter(LoginSession.subsystem_id.is_(None))
    elif subsystem_id:
        base = base.filter(LoginSession.subsystem_id == subsystem_id)

    # ── แยก "กำลังออนไลน์" ออกจาก "ประวัติ" ──
    #   active = logout_at NULL + อยู่ใน JWT window + ไม่ถูก block
    #   history = ที่เหลือ (logout แล้ว / JWT หมดอายุ / ถูก block)
    #   → พอ user logout (logout_at set) row จะหลุดจาก active ไปอยู่ history
    jwt_cutoff = now - timedelta(minutes=settings.jwt_access_token_expire_minutes)
    active_cond = and_(
        LoginSession.logout_at.is_(None),
        LoginSession.created_at >= jwt_cutoff,
        LoginSession.decision.notin_(_BLOCKED_DECISIONS),
    )

    # Active (online now) — ทุก subsystem รวมกัน, ไม่ paginate (cap 200)
    active_rows = (
        base.filter(active_cond)
        .order_by(LoginSession.created_at.desc())
        .limit(200)
        .all()
    )
    active = [
        _activity_item(ls, email, fn, ut, sn, now=now)
        for ls, email, fn, ut, sn in active_rows
    ]

    # History — ที่ไม่ active (paginated)
    hist_q = base.filter(not_(active_cond))
    total = hist_q.count()
    rows = (
        hist_q.order_by(LoginSession.created_at.desc()).offset(skip).limit(limit).all()
    )
    items = [_activity_item(ls, email, fn, ut, sn) for ls, email, fn, ut, sn in rows]

    # ── KPIs (ทั้งช่วง window — ไม่จำกัด page) ──
    kpi_q = db.query(LoginSession).filter(LoginSession.created_at >= window_start)
    # ใช้ filter เดียวกับ base (ยกเว้น pagination) สำหรับ KPI ให้สอดคล้องกับ filter
    if decision:
        kpi_q = kpi_q.filter(LoginSession.decision == decision)
    if channel:
        kpi_q = kpi_q.filter(LoginSession.login_method == channel)
    if subsystem_id == "hub":
        kpi_q = kpi_q.filter(LoginSession.subsystem_id.is_(None))
    elif subsystem_id:
        kpi_q = kpi_q.filter(LoginSession.subsystem_id == subsystem_id)
    if q:
        like = f"%{q.strip()}%"
        kpi_q = kpi_q.outerjoin(User, User.id == LoginSession.user_id).filter(
            or_(User.email.ilike(like), User.full_name.ilike(like))
        )

    kpi_total = kpi_q.count()
    blocked = kpi_q.filter(LoginSession.decision.in_(_BLOCKED_DECISIONS)).count()
    challenged = kpi_q.filter(LoginSession.decision.in_(_CHALLENGED_DECISIONS)).count()
    unique_users = (
        kpi_q.with_entities(func.count(func.distinct(LoginSession.user_id))).scalar()
        or 0
    )
    avg_risk = kpi_q.with_entities(func.avg(LoginSession.risk_score)).scalar()
    avg_risk = round(float(avg_risk), 3) if avg_risk is not None else None

    # ── channel distribution ──
    chan_rows = (
        kpi_q.with_entities(LoginSession.login_method, func.count(LoginSession.id))
        .group_by(LoginSession.login_method)
        .all()
    )
    channels = {(m or "unknown"): c for m, c in chan_rows}

    # ── hourly series (date_trunc) ──
    hour_rows = (
        kpi_q.with_entities(
            func.date_trunc("hour", LoginSession.created_at).label("h"),
            func.count(LoginSession.id),
            func.sum(case((LoginSession.decision.in_(_BLOCKED_DECISIONS), 1), else_=0)),
        )
        .group_by("h")
        .order_by("h")
        .all()
    )
    hourly = [
        {
            "hour": h.isoformat() if h else None,
            "count": int(c or 0),
            "blocked": int(b or 0),
        }
        for h, c, b in hour_rows
    ]

    return {
        "active": active,
        "active_count": len(active),
        "items": items,
        "total": total,
        "skip": skip,
        "limit": limit,
        "window_hours": hours,
        "kpis": {
            "total": kpi_total,
            "blocked": blocked,
            "challenged": challenged,
            "unique_users": unique_users,
            "avg_risk": avg_risk,
            "online": len(active),
        },
        "channels": channels,
        "hourly": hourly,
    }
