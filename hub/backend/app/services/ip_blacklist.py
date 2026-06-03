"""IP Blacklist service — ตรวจสอบ + จัดการ IP blacklist.

เรียกจาก oauth.py ตอน login เพื่อตั้ง is_attack_ip อัตโนมัติ.
เรียกจาก ml_admin.py ตอน toggle attack IP เพื่อ sync blacklist.
"""

import logging

from sqlalchemy.orm import Session

from app.models import IpBlacklist
from app.services.alert_service import send_alert

log = logging.getLogger(__name__)


def is_blacklisted(db: Session, ip: str) -> bool:
    """เช็คว่า IP อยู่ใน blacklist ไหม (exact match)."""
    if not ip:
        return False
    return (
        db.query(IpBlacklist).filter(IpBlacklist.ip_address == ip).first()
    ) is not None


def add_to_blacklist(
    db: Session,
    ip: str,
    reason: str | None = None,
    added_by_id: str | None = None,
) -> IpBlacklist | None:
    """เพิ่ม IP เข้า blacklist (skip ถ้ามีอยู่แล้ว). คืน record ใหม่ หรือ None ถ้าซ้ำ."""
    existing = db.query(IpBlacklist).filter(IpBlacklist.ip_address == ip).first()
    if existing:
        return None
    entry = IpBlacklist(
        ip_address=ip,
        reason=reason,
        added_by=added_by_id,
    )
    db.add(entry)
    # Fire alert (fail-safe)
    try:
        send_alert(
            severity="warning",
            kind="ip_blacklist.added",
            key=ip,
            title=f"IP เพิ่มเข้า blacklist: {ip}",
            detail={
                "ip": ip,
                "reason": reason,
                "added_by": str(added_by_id) if added_by_id else "auto",
            },
        )
    except Exception as e:
        log.exception("alert dispatch failed for blacklist add %s: %r", ip, e)
    return entry


def remove_from_blacklist(db: Session, ip: str) -> bool:
    """ลบ IP ออกจาก blacklist. คืน True ถ้าลบสำเร็จ."""
    entry = db.query(IpBlacklist).filter(IpBlacklist.ip_address == ip).first()
    if not entry:
        return False
    db.delete(entry)
    return True
