"""failed_logins_24h ต้องนับการยืนยันตัวตนที่ล้มเหลวจริง ไม่ใช่ผลตัดสินของระบบเอง.

เดิมนับ LoginSession.decision in (block, would_block) → ผลตัดสินกลายเป็นฟีเจอร์ของ
การตัดสินครั้งถัดไป (วงป้อนกลับ) และนับ shadow would_block ที่ผู้ใช้เข้าได้จริงเป็น "ล้มเหลว".

นิยามใหม่ (audit_logs · ช่วง [now-24h, now)):
  - ยืนยันตัวตนไม่ผ่านขณะรู้ตัวผู้ใช้แล้ว (actor_id = ผู้ใช้):
      passkey_stepup_failed · risk_mfa_verify_failed · stepup_totp_failed ·
      risk_force_enroll_otp_failed
  - passkey login ไม่ผ่านก่อนรู้ตัวผู้ใช้ (actor_id NULL) ผูกด้วย email ที่ถูกพยายามเข้า:
      passkey_login_failed · oauth_passkey_login_failed
  - ไม่นับ: block/would_block · IdP subject ไม่ตรง · กู้บัญชีไม่ผ่าน · ถูกปฏิเสธสิทธิ์ ·
    บัญชีถูกปิด · discoverable passkey ที่ไม่มี email (ผูกบัญชีไม่ได้)
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AuditLog, LoginSession, User
from app.security.rule_engine import FEAT
from app.services.feature_extraction import extract_session_features

IDX = FEAT["failed_logins_24h"]
NOW = datetime(2026, 9, 20, 12, 0, 0)


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _make_user(db, prefix="fail"):
    u = User(
        email=f"{prefix}-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Failed Login Tester",
        user_type="staff",
        identifier=f"S{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _cleanup(db, u):
    db.query(AuditLog).filter(AuditLog.actor_id == u.id).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.target_id == u.id).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.user_id == u.id).delete()
    db.delete(u)
    db.commit()


@pytest.fixture
def user(db):
    u = _make_user(db)
    yield u
    _cleanup(db, u)


@pytest.fixture
def other(db):
    u = _make_user(db, "other")
    yield u
    _cleanup(db, u)


def _audit(db, action, *, actor=None, email=None, at=None, marker=None):
    """marker = user ที่ใช้ target_id เพื่อให้ cleanup ลบแถว actor_id NULL ได้."""
    meta = {"code": "test"}
    if email is not None:
        meta["email"] = email
    row = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        target_type="test",
        target_id=(marker or actor).id if (marker or actor) else None,
        ip="1.2.3.4",
        metadata_json=meta,
        created_at=at or NOW - timedelta(hours=1),
    )
    db.add(row)
    db.commit()
    return row


def _failed(db, u, now=NOW):
    return extract_session_features(db, u.id, "1.2.3.4", "Mozilla/5.0", "TH", now=now)[
        IDX
    ]


def test_would_block_and_block_sessions_are_not_failures(user, db):
    for i in range(6):
        for dec in ("would_block", "block"):
            db.add(
                LoginSession(
                    user_id=user.id,
                    ip="1.2.3.4",
                    user_agent="Mozilla/5.0",
                    decision=dec,
                    created_at=NOW - timedelta(minutes=10 + i),
                )
            )
    db.commit()
    assert _failed(db, user) == 0.0


def test_actor_attributed_verification_failures_count(user, db):
    for action in (
        "passkey_stepup_failed",
        "risk_mfa_verify_failed",
        "stepup_totp_failed",
        "risk_force_enroll_otp_failed",
    ):
        _audit(db, action, actor=user)
    assert _failed(db, user) == 4.0


def test_passkey_login_failure_attributed_by_email_case_insensitive(user, db):
    _audit(db, "passkey_login_failed", email=user.email.upper(), marker=user)
    _audit(db, "oauth_passkey_login_failed", email=user.email, marker=user)
    assert _failed(db, user) == 2.0


def test_failures_on_another_account_are_not_counted(user, other, db):
    _audit(db, "passkey_login_failed", email=other.email, marker=other)
    _audit(db, "stepup_totp_failed", actor=other)
    assert _failed(db, user) == 0.0
    assert _failed(db, other) == 2.0


def test_discoverable_failure_without_email_is_not_attributed(user, db):
    _audit(db, "passkey_login_failed", marker=user)
    assert _failed(db, user) == 0.0


def test_non_verification_failures_are_excluded(user, db):
    for action in (
        "hub_login_failed_google_sub_mismatch",
        "oauth_login_failed_google_sub_mismatch",
        "hub_login_failed_line_sub_mismatch",
        "passkey_recovery_failed",
        "oauth_login_failed_access_policy",
        "hub_login_failed_inactive",
        "oauth_login_failed_inactive",
        "passkey_register_failed",
    ):
        _audit(db, action, actor=user, email=user.email)
    assert _failed(db, user) == 0.0


def test_window_is_point_in_time_24h(user, db):
    _audit(
        db, "stepup_totp_failed", actor=user, at=NOW - timedelta(hours=24, seconds=1)
    )
    _audit(db, "stepup_totp_failed", actor=user, at=NOW - timedelta(hours=24))
    _audit(db, "stepup_totp_failed", actor=user, at=NOW - timedelta(hours=23))
    _audit(db, "stepup_totp_failed", actor=user, at=NOW)
    _audit(db, "stepup_totp_failed", actor=user, at=NOW + timedelta(minutes=1))
    assert _failed(db, user) == 2.0
