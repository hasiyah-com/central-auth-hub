"""Phase 4 — Passkey recovery tests (backup code / email OTP / admin reset).

Service-level: verify_backup_code, email_otp_*, admin_reset_passkeys,
_normalize_code, _revoke_all_passkeys.
API-level RBAC for admin reset + anti-enum guards.
"""

import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.redis_client import redis_client
from app.services import passkey_recovery as pr


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def test_user(db: Session) -> User:
    u = User(
        email=f"recover-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Recover Tester",
        user_type="staff",
        identifier=f"T{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.query(PasskeyBackupCode).filter(PasskeyBackupCode.user_id == u.id).delete()
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == u.id).delete()
    db.delete(u)
    db.commit()


def _add_passkey(db, user):
    c = PasskeyCredential(
        user_id=user.id,
        credential_id=uuid.uuid4().bytes,
        public_key=b"k",
        device_name="Device",
        transports=["internal"],
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ─── normalize ──────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_normalize_code_variants():
    assert pr._normalize_code("ab3d7k9p") == "AB3D-7K9P"
    assert pr._normalize_code("AB3D-7K9P") == "AB3D-7K9P"
    assert pr._normalize_code("ab3d 7k9p") == "AB3D-7K9P"
    assert pr._normalize_code("xyz") == "XYZ"  # bad → จะ verify fail


# ─── backup code recovery ───────────────────────────────────────────────────


@pytest.mark.smoke
def test_verify_backup_code_success_revokes_all(test_user, db):
    """code ถูก → mark used + revoke passkey ทั้งหมด."""
    codes = pr.generate_backup_codes(test_user.id, db)
    db.commit()
    _add_passkey(db, test_user)
    _add_passkey(db, test_user)

    ok = pr.verify_backup_code(test_user.id, codes[0], db, ip="1.2.3.4")
    db.commit()
    assert ok is True

    # code ถูก mark used
    used = (
        db.query(PasskeyBackupCode)
        .filter(
            PasskeyBackupCode.user_id == test_user.id,
            PasskeyBackupCode.used_at.isnot(None),
        )
        .count()
    )
    assert used == 1

    # passkey ทั้งหมด revoked
    from app.services import webauthn_service as ws

    assert ws.count_active(test_user.id, db) == 0


@pytest.mark.smoke
def test_verify_backup_code_normalized_input(test_user, db):
    """code lowercase ไม่มี dash → ยัง verify ผ่าน (normalize)."""
    codes = pr.generate_backup_codes(test_user.id, db)
    db.commit()
    raw = codes[0].replace("-", "").lower()
    assert pr.verify_backup_code(test_user.id, raw, db) is True


@pytest.mark.smoke
def test_verify_backup_code_reuse_fails(test_user, db):
    """code ใช้แล้ว → ครั้งที่สอง fail."""
    codes = pr.generate_backup_codes(test_user.id, db)
    db.commit()
    assert pr.verify_backup_code(test_user.id, codes[0], db) is True
    db.commit()
    assert pr.verify_backup_code(test_user.id, codes[0], db) is False


@pytest.mark.smoke
def test_verify_backup_code_wrong_fails(test_user, db):
    pr.generate_backup_codes(test_user.id, db)
    db.commit()
    assert pr.verify_backup_code(test_user.id, "ZZZZ-ZZZZ", db) is False


@pytest.mark.smoke
def test_verify_backup_code_no_codes_fails(test_user, db):
    """user ไม่มี backup code → False."""
    assert pr.verify_backup_code(test_user.id, "AB3D-7K9P", db) is False


@pytest.mark.smoke
def test_verify_backup_code_only_current_generation(test_user, db):
    """code generation เก่า (หลัง rotate) → ใช้ไม่ได้."""
    old = pr.generate_backup_codes(test_user.id, db)
    db.commit()
    pr.generate_backup_codes(test_user.id, db, rotate=True)  # gen 2
    db.commit()
    # code gen 1 ใช้ไม่ได้แล้ว
    assert pr.verify_backup_code(test_user.id, old[0], db) is False


# ─── email OTP recovery ─────────────────────────────────────────────────────


@pytest.mark.smoke
def test_email_otp_begin_opaque(test_user, db):
    """begin คืน True เสมอ (anti-enum) + เก็บ Redis ถ้ามี user."""
    assert pr.email_otp_begin(test_user.email, db) is True
    assert redis_client.get(pr._otp_key(test_user.email)) is not None
    # unknown email → True เหมือนกัน แต่ไม่เก็บ Redis
    ghost = f"ghost-{uuid.uuid4().hex[:6]}@uni.ac.th"
    assert pr.email_otp_begin(ghost, db) is True
    assert redis_client.get(pr._otp_key(ghost)) is None
    redis_client.delete(pr._otp_key(test_user.email))


@pytest.mark.smoke
def test_email_otp_verify_success_revokes(test_user, db):
    """OTP ถูก → revoke passkey."""
    from app.services import mfa_service

    _add_passkey(db, test_user)
    otp = "123456"
    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": 0}),
    )
    codes = pr.email_otp_verify(test_user.email, otp, db)
    db.commit()
    assert codes is not None and len(codes) == 10  # คืน codes ใหม่
    from app.services import webauthn_service as ws

    assert ws.count_active(test_user.id, db) == 0


@pytest.mark.smoke
def test_email_otp_verify_wrong_increments(test_user, db):
    from app.services import mfa_service

    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps({"hash": mfa_service.hash_otp("123456"), "attempts": 0}),
    )
    assert pr.email_otp_verify(test_user.email, "000000", db) is None
    data = json.loads(redis_client.get(pr._otp_key(test_user.email)))
    assert data["attempts"] == 1
    redis_client.delete(pr._otp_key(test_user.email))


@pytest.mark.smoke
def test_email_otp_verify_lockout(test_user, db):
    """attempts >= 5 → lockout (ลบ key, return None)."""
    from app.services import mfa_service

    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps({"hash": mfa_service.hash_otp("123456"), "attempts": 5}),
    )
    assert pr.email_otp_verify(test_user.email, "123456", db) is None
    assert redis_client.get(pr._otp_key(test_user.email)) is None  # ถูกลบ


@pytest.mark.smoke
def test_email_otp_verify_no_challenge_fails(test_user, db):
    redis_client.delete(pr._otp_key(test_user.email))
    assert pr.email_otp_verify(test_user.email, "123456", db) is None


# ─── admin reset ────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_has_backup_codes_guard(test_user, db):
    """has_backup_codes — กัน re-enroll หลัง recovery crash.

    Bug 2026-06-11: ลบ passkey → re-enroll → passkey count=0 แต่ codes มีอยู่
    → generate_backup_codes RuntimeError → 'ตั้งค่าไม่สำเร็จ'.
    """
    assert pr.has_backup_codes(test_user.id, db) is False
    pr.generate_backup_codes(test_user.id, db)
    db.commit()
    assert pr.has_backup_codes(test_user.id, db) is True

    # จำลอง re-enroll guard: existing==0 + has_codes → skip (ไม่ raise)
    existing = 0
    should_generate = existing == 0 and not pr.has_backup_codes(test_user.id, db)
    assert should_generate is False  # skip — ไม่ crash


@pytest.mark.smoke
def test_regen_otp_no_passkey_revoke(test_user, db):
    """regen OTP → ออก codes ใหม่ แต่ passkey ไม่ถูก revoke (ต่างจาก recovery)."""
    from app.services import mfa_service
    from app.services import webauthn_service as ws

    pr.generate_backup_codes(test_user.id, db)
    db.commit()
    _add_passkey(db, test_user)
    otp = "246810"
    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps(
            {"hash": mfa_service.hash_otp(otp), "attempts": 0, "purpose": "regenerate"}
        ),
    )
    codes = pr.email_otp_verify(test_user.email, otp, db, purpose="regenerate")
    db.commit()
    assert codes is not None and len(codes) == 10
    # passkey ยังอยู่ (ไม่ถูก revoke)
    assert ws.count_active(test_user.id, db) == 1


@pytest.mark.smoke
def test_otp_purpose_binding(test_user, db):
    """OTP ของ regenerate ใช้กับ recovery verify ไม่ได้ (purpose mismatch)."""
    from app.services import mfa_service

    otp = "135790"
    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps(
            {"hash": mfa_service.hash_otp(otp), "attempts": 0, "purpose": "regenerate"}
        ),
    )
    # verify ด้วย purpose=recovery → None (mismatch — กัน revoke passkey โดยไม่ตั้งใจ)
    assert pr.email_otp_verify(test_user.email, otp, db, purpose="recovery") is None
    redis_client.delete(pr._otp_key(test_user.email))


@pytest.mark.smoke
def test_regen_otp_endpoints_registered(client):
    """regen-otp start → opaque sent (anti-enum)."""
    r = client.post(
        "/auth/passkey/backup-codes/regen-otp/start",
        json={"email": f"x-{uuid.uuid4().hex[:6]}@uni.ac.th"},
    )
    assert r.status_code == 200
    assert r.json()["sent"] is True


@pytest.mark.smoke
def test_ensure_backup_codes_auto_heal(test_user, db):
    """ensure_backup_codes: ไม่มี→gen1, มี usable→None, ใช้หมด→rotate ใหม่."""

    # ไม่มี → ออก gen 1
    c1 = pr.ensure_backup_codes(test_user.id, db)
    db.commit()
    assert c1 is not None and len(c1) == 10

    # มี usable → None (ไม่รบกวน)
    assert pr.ensure_backup_codes(test_user.id, db) is None

    # ใช้หมด → rotate ออกใหม่
    db.query(PasskeyBackupCode).filter(
        PasskeyBackupCode.user_id == test_user.id,
        PasskeyBackupCode.used_at.is_(None),
    ).update({PasskeyBackupCode.used_at: datetime.utcnow()})
    db.commit()
    c2 = pr.ensure_backup_codes(test_user.id, db)
    db.commit()
    assert c2 is not None and len(c2) == 10
    assert pr._current_generation(test_user.id, db) == 2


@pytest.mark.smoke
def test_email_otp_verify_returns_new_codes(test_user, db):
    """OTP verify → revoke passkey + ออก codes ใหม่ (B)."""
    from app.services import mfa_service

    pr.generate_backup_codes(test_user.id, db)
    db.commit()
    _add_passkey(db, test_user)
    otp = "999888"
    redis_client.setex(
        pr._otp_key(test_user.email),
        300,
        json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": 0}),
    )
    codes = pr.email_otp_verify(test_user.email, otp, db)
    db.commit()
    assert codes is not None and len(codes) == 10
    # generation เพิ่ม (rotate)
    assert pr._current_generation(test_user.id, db) == 2
    from app.services import webauthn_service as ws

    assert ws.count_active(test_user.id, db) == 0


@pytest.mark.smoke
def test_regenerate_endpoint_admin_only(client, auth_headers, staff_token, admin_token):
    """regenerate — staff 403, admin ไม่มี step-up 403 stepup_required,
    admin + step-up grant → 200 (Phase 5 critical action gate)."""
    import jwt as pyjwt

    from app.services import stepup_cache

    r1 = client.post(
        "/account/passkeys/backup-codes/regenerate",
        headers=auth_headers(staff_token),
    )
    assert r1.status_code == 403

    # admin แต่ยังไม่ step-up → 403 stepup_required (gate ทำงาน)
    r2 = client.post(
        "/account/passkeys/backup-codes/regenerate",
        headers=auth_headers(admin_token),
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["code"] == "stepup_required"

    # grant step-up (จำลอง stepup_finish สำเร็จ) → 200
    payload = pyjwt.decode(
        admin_token, options={"verify_signature": False, "verify_aud": False}
    )
    stepup_cache.set_granted(payload["sub"], payload["jti"], method="passkey")
    try:
        r3 = client.post(
            "/account/passkeys/backup-codes/regenerate",
            headers=auth_headers(admin_token),
        )
        assert r3.status_code == 200
        assert len(r3.json()["backup_codes"]) == 10
    finally:
        stepup_cache.clear(payload["sub"], payload["jti"])


@pytest.mark.smoke
def test_admin_list_passkeys_rbac(client, auth_headers, staff_token, admin_token):
    """GET /admin/users/{id}/passkeys — staff 403, admin 200."""
    import uuid as _uuid

    r1 = client.get(
        f"/admin/users/{_uuid.uuid4()}/passkeys", headers=auth_headers(staff_token)
    )
    assert r1.status_code == 403
    # admin + unknown user → 404 (ผ่าน RBAC แล้ว)
    r2 = client.get(
        f"/admin/users/{_uuid.uuid4()}/passkeys", headers=auth_headers(admin_token)
    )
    assert r2.status_code == 404


@pytest.mark.smoke
def test_admin_reset_revokes_all(test_user, db):
    _add_passkey(db, test_user)
    _add_passkey(db, test_user)
    count = pr.admin_reset_passkeys(test_user.id, db)
    db.commit()
    assert count == 2
    from app.services import webauthn_service as ws

    assert ws.count_active(test_user.id, db) == 0
    # reason = admin_reset
    rows = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.user_id == test_user.id)
        .all()
    )
    assert all(r.revoked_reason == "admin_reset" for r in rows)


# ─── API: admin reset RBAC ──────────────────────────────────────────────────


@pytest.mark.smoke
def test_admin_reset_endpoint_requires_admin(client, auth_headers, staff_token):
    """staff → 403."""
    r = client.post(
        f"/admin/users/{uuid.uuid4()}/reset-passkeys",
        headers=auth_headers(staff_token),
    )
    assert r.status_code == 403


@pytest.mark.smoke
def test_admin_reset_endpoint_no_token(client):
    r = client.post(f"/admin/users/{uuid.uuid4()}/reset-passkeys")
    assert r.status_code in (401, 403)


# ─── API: recovery anti-enumeration ─────────────────────────────────────────


@pytest.mark.smoke
def test_recover_backup_code_opaque_on_unknown(client):
    """unknown email → 400 recovery_failed (เหมือน code ผิด — anti-enum)."""
    r = client.post(
        "/auth/passkey/recover/backup-code",
        json={"email": f"ghost-{uuid.uuid4().hex[:6]}@uni.ac.th", "code": "AB3D-7K9P"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "recovery_failed"


@pytest.mark.smoke
def test_recover_backup_code_rejects_non_email(client):
    r = client.post(
        "/auth/passkey/recover/backup-code",
        json={"email": "notanemail", "code": "AB3D-7K9P"},
    )
    assert r.status_code == 422


@pytest.mark.smoke
def test_recover_email_otp_start_opaque(client):
    """start คืน 200 sent เสมอ (anti-enum)."""
    r = client.post(
        "/auth/passkey/recover/email-otp/start",
        json={"email": f"ghost-{uuid.uuid4().hex[:6]}@uni.ac.th"},
    )
    assert r.status_code == 200
    assert r.json()["sent"] is True
