"""SQLAlchemy models ของ Subsystem A (ระบบหอพัก).

หมายเหตุสำคัญ — ไม่มี FK ไปยัง Hub:
  hub_user_id เก็บเป็น UUID อิสระ (จาก JWT.sub) ไม่ใช่ FK
  เพราะ Subsystem A เป็น microservice แยก — ไม่ควรผูก DB กับ Hub
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.dialects.postgresql import INET, UUID

from app.database import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _utcnow():
    """Naive UTC now — DB column เป็น DateTime ไม่มี tz."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Room(Base):
    """ห้องในหอพัก (seed 24 ห้องตอน setup)."""
    __tablename__ = "rooms"

    id = uuid_pk()
    building = Column(String(10), nullable=False, index=True)    # "A" / "B"
    floor = Column(Integer, nullable=False)
    room_number = Column(String(10), unique=True, nullable=False, index=True)  # "A101"
    capacity = Column(Integer, nullable=False, default=2)
    status = Column(String(20), default="available", index=True)  # available/full/maintenance
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Resident(Base):
    """ผู้ที่ login เข้า subsystem (สร้างอัตโนมัติตอน login ครั้งแรก).

    role_in_sub มาจาก JWT claim role_in_subsystem ที่ Hub ออกให้
    (resident หรือ staff — กำหนดใน access_list ของ Hub)
    """
    __tablename__ = "residents"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    student_id = Column(String(50), nullable=True)
    faculty = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)

    role_in_sub = Column(String(50), nullable=False)   # resident / staff
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True, index=True)

    # check-in lifecycle
    checked_in_at = Column(DateTime, nullable=True)
    checked_out_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="active", index=True)  # active/checked_in/checked_out

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Reservation(Base):
    """ขอจองห้อง — flow: pending → approved/rejected → checked_in.

    ลบใช้ cancelled_at (soft delete) ตาม convention ของ Hub
    """
    __tablename__ = "reservations"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=False, index=True)
    status = Column(String(20), default="pending", index=True)
    # pending / approved / rejected / checked_in / cancelled

    reason = Column(Text, nullable=True)   # เหตุผลที่ขอห้องนี้

    created_at = Column(DateTime, default=_utcnow, index=True)

    approved_by_hub_user_id = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)
    checked_in_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)   # soft delete


class DormAuditLog(Base):
    """audit log ของ Subsystem A — ทุก state-changing action.

    ตามแบบ Hub's AuditLog แต่อยู่ใน DB ของ subsystem
    """
    __tablename__ = "dorm_audit_logs"

    id = uuid_pk()
    actor_hub_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(INET, nullable=True)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime, default=_utcnow, index=True)
