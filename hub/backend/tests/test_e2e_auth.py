"""E2E — ข้อ 1 ระบบยืนยันตัวตนแบบรวมศูนย์ (Passkey / Authenticator / Recovery).

E2E จริง: รัน ceremony WebAuthn เต็ม (software authenticator สร้าง attestation/assertion
จริง verify ด้วย py_webauthn) + TOTP enroll→verify ด้วย pyotp จริง + recovery flow.
ไม่ mock crypto — จับ bug signature/origin/UV ได้.

Positive + Negative ครบทุก flow.
รัน: docker compose exec hub-backend pytest tests/test_e2e_auth.py -v
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User, UserTotpCredential
from app.services import webauthn_service as ws
from app.services import totp_service
from tests.passkey_ceremony import (
    UVSoftWebauthnDevice,
    do_login,
    do_register,
    do_stepup,
)


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def e2e_user(db: Session) -> User:
    u = User(
        email=f"e2e-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="E2E Auth Tester",
        user_type="staff",
        identifier=f"T{uuid.uuid4().hex[:4]}",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.query(PasskeyBackupCode).filter(PasskeyBackupCode.user_id == u.id).delete()
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == u.id).delete()
    db.query(UserTotpCredential).filter(UserTotpCredential.user_id == u.id).delete()
    db.query(User).filter(User.id == u.id).delete()
    db.commit()


# ═══════════════ 1(2) Passkey — register → login (E2E ceremony) ═══════════════


def test_e2e_passkey_register_then_login_positive(db, e2e_user):
    """register passkey → login ด้วยอุปกรณ์เดิม → สำเร็จ (คืน user ถูกคน)."""
    row, device = do_register(e2e_user, db)
    assert row.id is not None
    result = do_login(e2e_user.email, db, device)
    assert result.user.id == e2e_user.id


def test_e2e_passkey_login_wrong_device_negative(db, e2e_user):
    """login ด้วยอุปกรณ์ที่ไม่เคยลงทะเบียน → ต้องล้มเหลว."""
    do_register(e2e_user, db)
    attacker_device = UVSoftWebauthnDevice()  # อุปกรณ์อื่น ไม่มี credential ในระบบ
    with pytest.raises(Exception):
        do_login(e2e_user.email, db, attacker_device)


def test_e2e_passkey_stepup_positive(db, e2e_user):
    """register → step-up (re-auth) ด้วยอุปกรณ์เดิม → สำเร็จ."""
    _, device = do_register(e2e_user, db)
    result = do_stepup(e2e_user, db, device)
    assert result.user.id == e2e_user.id


def test_e2e_passkey_duplicate_register_excluded_negative(db, e2e_user):
    """ลงทะเบียน credential เดิมซ้ำ → ถูกกันด้วย excludeCredentials."""
    _, device = do_register(e2e_user, db)
    opts = ws.register_begin(e2e_user, db)
    excluded = {c["id"] for c in (opts.get("excludeCredentials") or [])}
    assert len(excluded) >= 1  # credential เดิมถูกใส่ใน exclude list


# ═══════════════ 1(3) Authenticator (TOTP) — enroll → verify ═══════════════


def test_e2e_totp_enroll_confirm_verify_positive(db, e2e_user):
    """enroll TOTP → confirm ด้วย code จริง → verify_active ผ่าน."""
    import pyotp

    secret, uri = totp_service.start_enroll(e2e_user.id, db)
    db.flush()
    code = pyotp.TOTP(secret).now()
    assert totp_service.confirm_enroll(e2e_user.id, code, db) is True
    assert totp_service.is_enabled(e2e_user.id, db) is True
    # verify_active ด้วย code ใหม่
    code2 = pyotp.TOTP(secret).now()
    assert totp_service.verify_active(e2e_user.id, code2, db) is True


def test_e2e_totp_wrong_code_negative(db, e2e_user):
    """confirm ด้วย code ผิด → ล้มเหลว, ยังไม่ ACTIVE."""
    totp_service.start_enroll(e2e_user.id, db)
    db.flush()
    assert totp_service.confirm_enroll(e2e_user.id, "000000", db) is False
    assert totp_service.is_enabled(e2e_user.id, db) is False


def test_e2e_totp_verify_before_enroll_negative(db, e2e_user):
    """verify_active ทั้งที่ยังไม่ enroll → False (ไม่ error)."""
    assert totp_service.verify_active(e2e_user.id, "123456", db) is False


def test_e2e_totp_revoke_then_disabled(db, e2e_user):
    """enroll → revoke → is_enabled = False."""
    import pyotp

    secret, _ = totp_service.start_enroll(e2e_user.id, db)
    db.flush()
    totp_service.confirm_enroll(e2e_user.id, pyotp.TOTP(secret).now(), db)
    totp_service.revoke(e2e_user.id, db)
    db.flush()
    assert totp_service.is_enabled(e2e_user.id, db) is False


# ═══════════════ 1(3) Recovery — Backup Code ═══════════════


def test_e2e_backup_code_generate_and_recover_positive(db, e2e_user):
    """ออก backup code → กู้คืนด้วย code ที่ถูก → สำเร็จ (revoke passkey เดิม)."""
    from app.services import passkey_recovery

    do_register(e2e_user, db)
    codes = passkey_recovery.ensure_backup_codes(e2e_user.id, db)
    db.flush()
    assert codes and len(codes) >= 1  # ออก backup code (ช่องทางกู้คืน)
    # กู้คืนด้วย code แรก → verify ผ่าน
    assert passkey_recovery.verify_backup_code(e2e_user.id, codes[0], db) is True


def test_e2e_backup_code_wrong_negative(db, e2e_user):
    """กู้คืนด้วย backup code ผิด → ล้มเหลว."""
    from app.services import passkey_recovery

    do_register(e2e_user, db)
    passkey_recovery.ensure_backup_codes(e2e_user.id, db)
    db.flush()
    assert (
        passkey_recovery.verify_backup_code(e2e_user.id, "WRONG-CODE-9999", db) is False
    )


def test_e2e_backup_code_reuse_negative(db, e2e_user):
    """ใช้ backup code เดิมซ้ำ (หลังใช้ไปแล้ว) → ล้มเหลว."""
    from app.services import passkey_recovery

    do_register(e2e_user, db)
    codes = passkey_recovery.ensure_backup_codes(e2e_user.id, db)
    db.flush()
    assert passkey_recovery.verify_backup_code(e2e_user.id, codes[0], db) is True
    db.flush()
    # ใช้ code เดิมซ้ำ → ต้อง False (single-use)
    assert passkey_recovery.verify_backup_code(e2e_user.id, codes[0], db) is False


# ═══════════════ 1 — has_second_factor สะท้อน factor จริงหลัง enroll ═══════════════


def test_e2e_has_second_factor_after_passkey(db, e2e_user):
    from app.services import mfa_policy

    assert mfa_policy.has_second_factor(e2e_user, db) is False  # ก่อน
    do_register(e2e_user, db)
    assert mfa_policy.has_second_factor(e2e_user, db) is True  # หลัง register


def test_e2e_has_second_factor_after_totp(db, e2e_user):
    import pyotp
    from app.services import mfa_policy

    secret, _ = totp_service.start_enroll(e2e_user.id, db)
    db.flush()
    totp_service.confirm_enroll(e2e_user.id, pyotp.TOTP(secret).now(), db)
    assert mfa_policy.has_second_factor(e2e_user, db) is True  # TOTP ก็นับ
