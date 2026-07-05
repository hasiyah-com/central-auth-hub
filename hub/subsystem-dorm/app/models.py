"""SQLAlchemy models ของ Subsystem A (ระบบหอพัก).

หมายเหตุสำคัญ — ไม่มี FK ไปยัง Hub:
  hub_user_id เก็บเป็น UUID อิสระ (จาก JWT.sub) ไม่ใช่ FK
  เพราะ Subsystem A เป็น microservice แยก — ไม่ควรผูก DB กับ Hub
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
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
    building = Column(String(10), nullable=False, index=True)  # "A" / "B"
    floor = Column(Integer, nullable=False)
    room_number = Column(String(10), unique=True, nullable=False, index=True)  # "A101"
    capacity = Column(Integer, nullable=False, default=2)
    status = Column(
        String(20), default="available", index=True
    )  # available/full/maintenance
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Resident(Base):
    """ผู้ที่ login เข้า subsystem (สร้างอัตโนมัติตอน login ครั้งแรก).

    user_type มาจาก JWT claim user_type ที่ Hub ออกให้
    (student=ผู้พัก, staff/teacher/admin=เจ้าหน้าที่)
    """

    __tablename__ = "residents"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    # ── Fields ที่ Hub ออกได้ตาม scope (10 ฟิลด์) ──
    # Subsystem เก็บทุกฟิลด์ แม้ scope ปัจจุบันไม่ขอ — กันเสีย data ตอนขยาย scope
    # field ไหน scope ไม่ขอ จะคงค่าเดิม (= NULL ถ้าไม่เคยมี) ไม่ลบทิ้ง
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    student_id = Column(String(50), nullable=True)  # scope: student_id
    employee_id = Column(String(50), nullable=True)  # scope: employee_id
    faculty = Column(String(100), nullable=True)  # scope: faculty
    major = Column(String(100), nullable=True)  # scope: major
    year = Column(String(50), nullable=True)  # scope: year
    position = Column(String(50), nullable=True)  # scope: position
    phone = Column(String(50), nullable=True)  # scope: phone
    address = Column(Text, nullable=True)  # scope: address

    user_type = Column(String(50), nullable=False)  # student / teacher / staff / admin
    room_id = Column(
        UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=True, index=True
    )

    # check-in lifecycle
    checked_in_at = Column(DateTime, nullable=True)
    checked_out_at = Column(DateTime, nullable=True)
    status = Column(
        String(20), default="active", index=True
    )  # active/checked_in/checked_out

    # Hub revocation tracking — sync'd ผ่าน webhook จาก Hub
    # NULL = Hub ยังให้สิทธิ์อยู่ / มีค่า = Hub revoke แล้ว → resident ใช้งานไม่ได้
    # (เก็บแยกจาก status เพราะ status สื่อ check-in lifecycle ของหอพัก)
    hub_access_revoked_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Reservation(Base):
    """ขอจองห้อง — flow: pending → approved/rejected → checked_in.

    ลบใช้ cancelled_at (soft delete) ตาม convention ของ Hub
    """

    __tablename__ = "reservations"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # ── D10 FIX: FK CASCADE policy = RESTRICT (default) ระบุชัดเจน ──
    # ห้ามลบ room ที่มี reservation อ้างถึง (ใช้ status='maintenance' แทน)
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status = Column(String(20), default="pending", index=True)
    # pending / approved / rejected / checked_in / cancelled

    reason = Column(Text, nullable=True)  # เหตุผลที่ขอห้องนี้

    created_at = Column(DateTime, default=_utcnow, index=True)

    approved_by_hub_user_id = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    reject_reason = Column(Text, nullable=True)
    checked_in_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)  # soft delete

    # ── D2 FIX: partial unique index — กัน duplicate active reservation per user ──
    # User คนเดียวมี active reservation ได้สูงสุด 1 รายการเท่านั้น
    # (active = ยังไม่ cancelled และ status ∈ pending/approved/checked_in)
    __table_args__ = (
        Index(
            "uq_reservations_active_per_user",
            "hub_user_id",
            unique=True,
            postgresql_where=text(
                "cancelled_at IS NULL AND status IN ('pending', 'approved', 'checked_in')"
            ),
        ),
    )


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
