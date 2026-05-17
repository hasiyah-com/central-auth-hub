"""SQLAlchemy models ของ Subsystem B (ระบบห้องสมุด).

ไม่มี FK ไป Hub: hub_user_id เก็บเป็น UUID อิสระ (จาก JWT.sub)
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
    """Naive UTC now — เข้ากับ DateTime column (ไม่มี tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Book(Base):
    """หนังสือในห้องสมุด (seed 30 เล่ม ตอน setup)."""
    __tablename__ = "books"

    id = uuid_pk()
    isbn = Column(String(20), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    author = Column(String(255), nullable=False)
    category = Column(String(100), index=True)  # คอมพิวเตอร์/วิศวกรรม/...
    description = Column(Text, nullable=True)

    copies_total = Column(Integer, nullable=False, default=1)
    copies_available = Column(Integer, nullable=False, default=1)

    status = Column(String(20), default="active", index=True)  # active/withdrawn
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Member(Base):
    """สมาชิกห้องสมุด — สร้างจาก JWT.sub ตอน login ครั้งแรก."""
    __tablename__ = "members"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    student_id = Column(String(50), nullable=True)
    faculty = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)

    role_in_sub = Column(String(50), nullable=False)   # member / librarian
    status = Column(String(20), default="active", index=True)   # active/suspended

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Borrowing(Base):
    """การยืมหนังสือ.

    Lifecycle:
      requested → active → returned
      (cancel ได้ตอน requested เท่านั้น — ผ่าน cancelled_at, soft delete)

    Overdue คำนวณตอน query: status='active' AND due_at < NOW()
    """
    __tablename__ = "borrowings"

    id = uuid_pk()
    hub_user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id"), nullable=False, index=True)

    status = Column(String(20), default="requested", index=True)
    # requested / active / returned / cancelled

    # Lifecycle timestamps
    requested_at = Column(DateTime, default=_utcnow, nullable=False, index=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by_hub_user_id = Column(UUID(as_uuid=True), nullable=True)

    borrowed_at = Column(DateTime, nullable=True)   # = approved_at, แต่เก็บแยกไว้สำหรับชัดเจน
    due_at = Column(DateTime, nullable=True, index=True)

    returned_at = Column(DateTime, nullable=True)
    received_by_hub_user_id = Column(UUID(as_uuid=True), nullable=True)  # librarian ที่รับคืน

    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, nullable=True)


class LibraryAuditLog(Base):
    """audit log ของ Subsystem B — ทุก state-changing action."""
    __tablename__ = "library_audit_logs"

    id = uuid_pk()
    actor_hub_user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(INET, nullable=True)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime, default=_utcnow, index=True)
