"""SQLAlchemy models matching the Hub Database schema."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, JSON, Numeric
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY, INET
from sqlalchemy.orm import relationship

from app.database import Base


def uuid_pk():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    """ผู้ใช้ในระบบ (seed 100 คนตอน setup)"""
    __tablename__ = "users"

    id = uuid_pk()
    google_sub = Column(String(255), unique=True, nullable=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    user_type = Column(String(20), nullable=False, index=True)  # student/teacher/staff/admin

    # University info
    identifier = Column(String(50), index=True)   # student_id / employee_id
    faculty = Column(String(100), index=True)
    major = Column(String(100))
    year_or_position = Column(String(50))

    # Contact
    phone = Column(String(20))
    address = Column(Text)

    # Metadata
    status = Column(String(20), default="active", index=True)  # active/suspended/deleted
    is_hub_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Subsystem(Base):
    """ระบบย่อยที่ลงทะเบียนกับ Hub"""
    __tablename__ = "subsystems"

    id = uuid_pk()
    name = Column(String(255), nullable=False)
    description = Column(Text)
    client_id = Column(String(64), unique=True, nullable=False, index=True)
    client_secret_hash = Column(Text, nullable=False)
    redirect_uris = Column(ARRAY(Text), nullable=False)
    scope = Column(ARRAY(String), nullable=False)
    status = Column(String(20), default="pending", index=True)  # pending/active/suspended
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)


class AccessList(Base):
    """Whitelist ของ user ที่เข้าถึงแต่ละ subsystem ได้"""
    __tablename__ = "access_list"
    __table_args__ = (UniqueConstraint("subsystem_id", "user_id"),)

    id = uuid_pk()
    subsystem_id = Column(UUID(as_uuid=True), ForeignKey("subsystems.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role_in_sub = Column(String(50))   # e.g., resident/staff/admin per subsystem
    granted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    granted_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)


class LoginSession(Base):
    """บันทึกทุก login (สำหรับ audit + ML training)"""
    __tablename__ = "login_sessions"

    id = uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    subsystem_id = Column(UUID(as_uuid=True), ForeignKey("subsystems.id"), index=True)
    ip = Column(INET)
    user_agent = Column(Text)
    geo_country = Column(String(50))
    geo_city = Column(String(100))
    anomaly_score = Column(Numeric(3, 2))
    decision = Column(String(20))   # pass/mfa/block
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    """ทุกการกระทำของ admin + ระบบ"""
    __tablename__ = "audit_logs"

    id = uuid_pk()
    actor_id = Column(UUID(as_uuid=True), nullable=True)   # NULL ถ้าเป็น system
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50))
    target_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(INET)
    metadata_json = Column("metadata", JSON)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RequestLog(Base):
    """บันทึก HTTP request ทุกครั้งที่เข้าระบบ — สำหรับ audit + traffic analysis.

    หมายเหตุ: user_id ไม่มี FK constraint — เก็บได้แม้ user ถูกลบไปแล้ว
             (สำหรับ failed login ที่ไม่มี user_id ก็ใส่ NULL)
    """
    __tablename__ = "request_logs"

    id = uuid_pk()
    method = Column(String(10), nullable=False)
    path = Column(Text, nullable=False, index=True)
    status_code = Column(Integer, index=True)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    ip = Column(INET)
    user_agent = Column(Text)
    duration_ms = Column(Integer)
    error_detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SecretRetrievalToken(Base):
    """One-time link สำหรับให้นักพัฒนาดู client_secret ครั้งเดียว"""
    __tablename__ = "secret_retrieval_tokens"

    id = uuid_pk()
    # เก็บเป็น HMAC-SHA256 ของ plaintext token (hex 64 chars) — ไม่เก็บ plaintext
    # ถ้า DB หลุดก็เอา token ที่นี่ไป retrieve ไม่ได้
    token = Column(String(128), unique=True, nullable=False, index=True)
    subsystem_id = Column(UUID(as_uuid=True), ForeignKey("subsystems.id"), nullable=False)
    secret_encrypted = Column(Text, nullable=False)   # AES-encrypted, ลบหลังดู
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
