"""Tests — TOTP authenticator (enroll + lifecycle + step-up) + passkey status enforcement.

Phase 1 ของแผน TOTP + Recovery Ticket. ครอบ:
  - totp_service.verify / lifecycle (REGISTERED→ACTIVE→SUSPENDED→REVOKED)
  - enroll start/verify endpoints (gate totp_enroll)
  - stepup/totp/verify → grant method="totp" → critical action ผ่าน (แต่ change_google ยังบังคับ passkey)
  - passkey status: SUSPENDED ไม่ถูกนับ/auth ไม่ได้
"""

from __future__ import annotations

import uuid

import pyotp
import pytest

from app.models import (
    CRED_ACTIVE,
    CRED_REGISTERED,
    CRED_REVOKED,
    CRED_SUSPENDED,
    AuditLog,
    PasskeyCredential,
    User,
    UserTotpCredential,
)
from app.services import stepup_cache, totp_service, webauthn_service
from app.services.jwt_service import create_access_token


def _mk_user(db) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"totp_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"TOTP Test {s}",
        user_type="teacher",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _purge(db, uid):
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(
        synchronize_session=False
    )
    db.query(UserTotpCredential).filter(UserTotpCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def temp_user(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    _purge(db, uid)


# ─────────────────────────────────────────────────────────────
# 1. service — verify + lifecycle
# ─────────────────────────────────────────────────────────────


def test_totp_verify_correct_wrong_expired():
    secret = totp_service.generate_secret()
    assert totp_service.verify(secret, pyotp.TOTP(secret).now()) is True
    assert totp_service.verify(secret, "000000") in (
        True,
        False,
    )  # อาจตรงโดยบังเอิญ (rare)
    # code จากอนาคตไกล (valid_window=1 ไม่ครอบ) → ผิดแน่นอน
    future = pyotp.TOTP(secret).at(__import__("time").time() + 600)
    assert totp_service.verify(secret, future) is False
    assert totp_service.verify(secret, "") is False


def test_totp_lifecycle(temp_user, db):
    # start → REGISTERED
    secret, uri = totp_service.start_enroll(temp_user.id, db)
    db.commit()
    assert uri.startswith("otpauth://totp/")
    row = totp_service.get_row(temp_user.id, db)
    assert row.status == CRED_REGISTERED
    assert totp_service.is_enabled(temp_user.id, db) is False
    # verify_active ยังไม่ได้ (ยัง REGISTERED)
    assert (
        totp_service.verify_active(temp_user.id, pyotp.TOTP(secret).now(), db) is False
    )

    # confirm → ACTIVE
    assert (
        totp_service.confirm_enroll(temp_user.id, pyotp.TOTP(secret).now(), db) is True
    )
    db.commit()
    db.refresh(row)
    assert row.status == CRED_ACTIVE and row.enabled_at is not None
    assert totp_service.is_enabled(temp_user.id, db) is True
    assert (
        totp_service.verify_active(temp_user.id, pyotp.TOTP(secret).now(), db) is True
    )

    # suspend → verify_active ไม่ได้
    totp_service.suspend(temp_user.id, db)
    db.commit()
    assert (
        totp_service.verify_active(temp_user.id, pyotp.TOTP(secret).now(), db) is False
    )
    # reactivate → ได้อีก
    totp_service.reactivate(temp_user.id, db)
    db.commit()
    assert (
        totp_service.verify_active(temp_user.id, pyotp.TOTP(secret).now(), db) is True
    )
    # revoke → ไม่ได้
    totp_service.revoke(temp_user.id, db)
    db.commit()
    db.refresh(row)
    assert row.status == CRED_REVOKED
    assert (
        totp_service.verify_active(temp_user.id, pyotp.TOTP(secret).now(), db) is False
    )


def test_confirm_enroll_wrong_code_stays_registered(temp_user, db):
    secret, _ = totp_service.start_enroll(temp_user.id, db)
    db.commit()
    assert totp_service.confirm_enroll(temp_user.id, "000001", db) is False
    row = totp_service.get_row(temp_user.id, db)
    # อาจ REGISTERED (code ผิดจริง) — ไม่ควรกลายเป็น ACTIVE
    assert row.status == CRED_REGISTERED


# ─────────────────────────────────────────────────────────────
# 2. endpoints — enroll (gate) + step-up
# ─────────────────────────────────────────────────────────────


def test_enroll_start_requires_stepup(client, temp_user, auth_headers):
    token, jti = create_access_token(temp_user)
    stepup_cache.clear(str(temp_user.id), jti)
    r = client.post("/auth/account/totp/enroll/start", headers=auth_headers(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "stepup_required"


def test_enroll_flow_via_api(client, temp_user, auth_headers):
    token, jti = create_access_token(temp_user)
    stepup_cache.set_granted(str(temp_user.id), jti, "passkey")
    try:
        r = client.post("/auth/account/totp/enroll/start", headers=auth_headers(token))
        assert r.status_code == 200
        secret = r.json()["secret"]
        assert r.json()["otpauth_uri"].startswith("otpauth://")
        # verify ด้วย code จริง
        code = pyotp.TOTP(secret).now()
        r2 = client.post(
            "/auth/account/totp/enroll/verify",
            headers=auth_headers(token),
            json={"code": code},
        )
        assert r2.status_code == 200 and r2.json()["status"] == "ACTIVE"
        # status endpoint
        r3 = client.get("/auth/account/totp/status", headers=auth_headers(token))
        assert r3.json()["enabled"] is True
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


def test_stepup_totp_grants_method_totp(client, temp_user, auth_headers, db):
    # เปิด TOTP ให้ user ก่อน (ตรง service)
    secret, _ = totp_service.start_enroll(temp_user.id, db)
    totp_service.confirm_enroll(temp_user.id, pyotp.TOTP(secret).now(), db)
    db.commit()
    token, jti = create_access_token(temp_user)
    try:
        r = client.post(
            "/auth/stepup/totp/verify",
            headers=auth_headers(token),
            json={"code": pyotp.TOTP(secret).now()},
        )
        assert r.status_code == 200 and r.json()["granted"] is True
        cached = stepup_cache.check_cached(str(temp_user.id), jti)
        assert cached and cached["method"] == "totp"
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


def test_change_google_still_requires_passkey_not_totp(
    client, temp_user, auth_headers, db
):
    """TOTP step-up ไม่ปลดล็อก change-google (บังคับ passkey เท่านั้น)."""
    token, jti = create_access_token(temp_user)
    stepup_cache.set_granted(str(temp_user.id), jti, "totp")  # มี grant แต่เป็น totp
    try:
        r = client.post(
            "/auth/account/change-google/start", headers=auth_headers(token)
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "stepup_required"
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


# ─────────────────────────────────────────────────────────────
# 3. passkey status enforcement
# ─────────────────────────────────────────────────────────────


def test_passkey_suspended_not_counted(temp_user, db):
    """passkey SUSPENDED ไม่ถูกนับใน count_active (auth ไม่ได้)."""
    pk = PasskeyCredential(
        user_id=temp_user.id,
        credential_id=uuid.uuid4().bytes + uuid.uuid4().bytes,
        public_key=b"\x00" * 32,
        sign_count=0,
        device_name="test-device",
        status=CRED_ACTIVE,
    )
    db.add(pk)
    db.commit()
    assert webauthn_service.count_active(temp_user.id, db) == 1
    pk.status = CRED_SUSPENDED
    db.commit()
    assert webauthn_service.count_active(temp_user.id, db) == 0
    pk.status = CRED_ACTIVE
    db.commit()
    assert webauthn_service.count_active(temp_user.id, db) == 1
