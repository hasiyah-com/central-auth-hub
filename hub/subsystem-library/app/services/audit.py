"""Audit logger ของ Subsystem B."""
from sqlalchemy.orm import Session

from app.models import LibraryAuditLog


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
    """เพิ่ม audit log entry (caller commit เอง)."""
    db.add(LibraryAuditLog(
        actor_hub_user_id=actor_hub_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        metadata_json=metadata or {},
    ))
