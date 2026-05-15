"""Audit service — บันทึกทุกการกระทำสำคัญลง audit_logs.

ใช้เรียกจาก router ต่างๆ เมื่อมี action ที่ต้องบันทึกหลักฐาน
เช่น ลงทะเบียน subsystem, อนุมัติ, เพิ่ม access, ดู secret
"""
from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(
    db: Session,
    *,
    actor_id=None,
    action: str,
    target_type: str | None = None,
    target_id=None,
    ip: str | None = None,
    metadata: dict | None = None,
) -> None:
    """เพิ่ม audit log entry.

    หมายเหตุ: ฟังก์ชันนี้ไม่ commit — ให้ caller commit เอง
             (เพื่อให้ audit + business logic อยู่ใน transaction เดียวกัน)

    Args:
        actor_id: ใครทำ action นี้ (None = system)
        action: ชื่อ action เช่น 'subsystem_registered', 'subsystem_approved'
        target_type: ประเภทของเป้าหมาย เช่น 'subsystem', 'user', 'access_list'
        target_id: ID ของเป้าหมาย
        ip: IP address ของ actor
        metadata: ข้อมูลเพิ่มเติม (เก็บเป็น JSON)
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        metadata_json=metadata or {},
    )
    db.add(entry)
