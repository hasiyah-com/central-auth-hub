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
    """เพิ่ม audit log entry — caller **ต้อง** เรียก db.commit() เองหลังจากนี้.

    ฟังก์ชันนี้แค่ db.add() เท่านั้น ไม่ commit ให้ เพื่อให้ caller ผูกรวม
    audit log + state change เป็น atomic transaction เดียวกันได้.
    """
    db.add(
        LibraryAuditLog(
            actor_hub_user_id=actor_hub_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            metadata_json=metadata or {},
        )
    )
