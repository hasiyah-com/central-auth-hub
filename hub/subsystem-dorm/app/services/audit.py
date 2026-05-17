"""Audit logger ของ Subsystem A — บันทึก state-changing action.

ตาม pattern เดียวกับ Hub's log_action (services/audit_service.py)
"""
from sqlalchemy.orm import Session

from app.models import DormAuditLog


def log_action(
    db: Session,
    *,
    actor_hub_user_id=None,
    action: str,
    target_type: str | None = None,
    target_id=None,
    ip: str | None = None,
    metadata: dict | None = None,
) -> None:
    """เพิ่ม audit log entry.

    หมายเหตุ: caller commit เอง (ให้ business logic + audit อยู่ใน transaction เดียว)
    """
    entry = DormAuditLog(
        actor_hub_user_id=actor_hub_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        metadata_json=metadata or {},
    )
    db.add(entry)
