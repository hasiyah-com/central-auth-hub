"""Payload builders สำหรับหน้า subsystem detail — ใช้ร่วมทั้ง admin และ developer portal.

หน้า admin (`/admin/subsystems/{id}/...`) กับ developer portal
(`/developer/subsystems/{id}/...`) ต้องแสดง KPI / health / active-session / audit
ชุดเดียวกัน. ฟังก์ชันในไฟล์นี้รับ `Subsystem` ที่ resolve + ตรวจสิทธิ์มาแล้ว
(admin = ทุกตัว, dev = เฉพาะที่ตัวเองเป็นเจ้าของ) แล้วคืน dict รูปแบบเดียวกัน
เพื่อไม่ให้สองหน้าคำนวณคนละแบบจนข้อมูลไม่ตรงกัน.

หมายเหตุ: logic สะท้อน endpoint เดิมใน `routers/admin.py` (subsystem_stats,
subsystem_health_history, list_active_sessions, subsystem_audit) — เกณฑ์ session
ที่ active ใช้ `_active_session_condition` ตัวเดียวกับ /activity (import แบบ lazy
กัน circular import เพราะ admin.py import service อื่นๆ ตอน load).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, LoginSession, Subsystem, User
from app.services.subsystem_health import get_history as get_health_history


def _session_ttl_min() -> int:
    """อายุ cookie ของ subsystem (นาที) — single source อยู่ที่ admin.py."""
    from app.routers.admin import _SUBSYSTEM_SESSION_TTL_MIN

    return _SUBSYSTEM_SESSION_TTL_MIN


def stats_payload(db: Session, subsystem: Subsystem, days: int = 7) -> dict:
    """KPI — login counts, decision breakdown, unique users, active now, daily series."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)

    total_logins = (
        db.query(func.count(LoginSession.id))
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

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

    unique_users = (
        db.query(func.count(func.distinct(LoginSession.user_id)))
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            LoginSession.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

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

    daily_rows = (
        db.query(
            func.date(LoginSession.created_at).label("d"),
            func.count(LoginSession.id).label("cnt"),
            func.sum(
                case(
                    (
                        and_(
                            LoginSession.risk_score.isnot(None),
                            LoginSession.risk_score < 0.4,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("low"),
            func.sum(
                case(
                    (
                        and_(
                            LoginSession.risk_score >= 0.4,
                            LoginSession.risk_score < 0.5,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("medium"),
            func.sum(case((LoginSession.risk_score >= 0.5, 1), else_=0)).label(
                "high"
            ),
            func.sum(case((LoginSession.risk_score.is_(None), 1), else_=0)).label(
                "unknown"
            ),
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
            "count": int(c or 0),
            "low": int(low or 0),
            "medium": int(medium or 0),
            "high": int(high or 0),
            "unknown": int(unknown or 0),
        }
        for d, c, low, medium, high, unknown in daily_rows
    ]

    return {
        "subsystem": {"id": str(subsystem.id), "name": subsystem.name},
        "range": {"days": days, "from": cutoff.isoformat(), "to": now.isoformat()},
        "total_logins": total_logins,
        "unique_users": unique_users,
        "active_now": active_now,
        "decision_breakdown": decision_breakdown,
        "daily": daily,
    }


def health_history_payload(subsystem: Subsystem, limit: int = 288) -> dict:
    """ประวัติ health (latency ย้อนหลัง) จาก Redis — fail-safe คืน list ว่างถ้าไม่มีข้อมูล."""
    points = get_health_history(str(subsystem.id), limit=limit)
    latencies = [
        p["latency_ms"] for p in points if isinstance(p.get("latency_ms"), (int, float))
    ]
    up = sum(1 for p in points if p.get("status") == "healthy")
    return {
        "points": points,
        "count": len(points),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1)
        if latencies
        else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "healthy_ratio": round(up / len(points), 4) if points else None,
        "interval_sec": 300,
    }


def active_sessions_payload(db: Session, subsystem: Subsystem) -> dict:
    """User ที่ session ยัง valid ใน subsystem นี้ (read-only view)."""
    from app.routers.admin import _active_session_condition

    now = datetime.utcnow()
    rows = (
        db.query(LoginSession, User.email, User.full_name, User.user_type)
        .outerjoin(User, User.id == LoginSession.user_id)
        .filter(
            LoginSession.subsystem_id == subsystem.id,
            _active_session_condition(now),
        )
        .order_by(LoginSession.created_at.desc())
        .all()
    )

    ttl = timedelta(minutes=_session_ttl_min())
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
                "session_expires_at": (sess.created_at + ttl).isoformat()
                if sess.created_at
                else None,
                "duration_sec": int((now - sess.created_at).total_seconds())
                if sess.created_at
                else 0,
            }
            for sess, email, full_name, user_type in rows
        ],
    }


def audit_payload(
    db: Session,
    subsystem: Subsystem,
    action: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> dict:
    """Audit log เฉพาะ subsystem นี้ (target_type=subsystem) — paginated."""
    q = (
        db.query(AuditLog, User.email, User.user_type, User.is_hub_admin)
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
