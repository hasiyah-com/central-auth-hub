"""Phase 6 — Full WebAuthn ceremony integration tests (software authenticator).

ต่างจาก unit tests เดิม (test_passkey_register/login) ที่ทดสอบ guard layers —
ชุดนี้รัน ceremony เต็ม: สร้าง attestation/assertion จริงด้วย soft-webauthn
แล้ว verify ผ่าน py_webauthn (signature, challenge, origin, RP ID, UV, sign_count).

ครอบ: register → login → stepup → counter regression → revoke isolation.
นี่คือชุดที่จับ bug origin/UV/signature ได้ (unit tests จับไม่ได้).
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.services import webauthn_service as ws
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
def test_user(db: Session) -> User:
    u = User(
        email=f"cer-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Ceremony Tester",
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


# ─── Register ceremony ──────────────────────────────────────────────────────


@pytest.mark.smoke
def test_register_full_ceremony_saves_credential(test_user, db):
    """register_begin → soft create attestation → register_complete verifies + saves."""
    row, _ = do_register(test_user, db, device_name="My Laptop")
    db.commit()
    assert row.device_name == "My Laptop"
    assert row.sign_count == 0
    assert len(bytes(row.credential_id)) > 0
    assert len(bytes(row.public_key)) > 0  # COSE public key stored
    assert ws.count_active(test_user.id, db) == 1


@pytest.mark.smoke
def test_register_then_duplicate_excluded(test_user, db):
    """register แล้ว — register_begin ส่ง credential นั้นใน excludeCredentials."""
    row, _ = do_register(test_user, db)
    db.commit()
    opts = ws.register_begin(test_user, db)
    excluded_ids = {c["id"] for c in opts.get("excludeCredentials", [])}
    from tests.passkey_ceremony import b64u

    assert b64u(bytes(row.credential_id)) in excluded_ids


# ─── Login ceremony ─────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_login_full_ceremony_verifies_signature(test_user, db):
    """register → login: signature verified, sign_count advances, no regression."""
    row, dev = do_register(test_user, db)
    db.commit()
    result = do_login(test_user.email, db, dev)
    db.commit()
    assert result.user.id == test_user.id
    assert result.credential.id == row.id
    assert result.credential.sign_count == 1  # advanced 0 → 1
    assert result.counter_regression is False


@pytest.mark.smoke
def test_login_sign_count_advances_each_time(test_user, db):
    """หลาย login ติดกัน — sign_count เพิ่มขึ้นเรื่อยๆ."""
    _, dev = do_register(test_user, db)
    db.commit()
    counts = []
    for _ in range(3):
        r = do_login(test_user.email, db, dev)
        db.commit()
        counts.append(r.credential.sign_count)
    assert counts == [1, 2, 3]


@pytest.mark.smoke
def test_login_foreign_device_rejected(test_user, db):
    """อุปกรณ์อื่น (credential_id ไม่ตรง) → 401 invalid_credential."""
    from fastapi import HTTPException

    do_register(test_user, db)
    db.commit()
    # foreign device — init ให้มี credential แต่ไม่อยู่ใน whitelist ของ test_user
    foreign = UVSoftWebauthnDevice()
    foreign.cred_init("localhost", uuid.uuid4().bytes)
    with pytest.raises(HTTPException) as exc:
        do_login(test_user.email, db, foreign)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_credential"


@pytest.mark.smoke
def test_login_after_revoke_rejected(test_user, db):
    """revoke passkey แล้ว — login ด้วย device เดิม → 401."""
    from datetime import datetime

    from fastapi import HTTPException

    row, dev = do_register(test_user, db)
    db.commit()
    row.revoked_at = datetime.utcnow()
    row.revoked_reason = "user_deleted"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        do_login(test_user.email, db, dev)
    assert exc.value.status_code == 401


# ─── Counter regression (clone detection — Improvement #10) ─────────────────


@pytest.mark.smoke
def test_counter_regression_detected(test_user, db):
    """sign_count ไม่เดินหน้า (จำลอง clone) → regression flagged แต่ allow (lenient)."""
    _, dev = do_register(test_user, db)
    db.commit()
    r1 = do_login(test_user.email, db, dev)  # count → 1
    db.commit()
    assert r1.counter_regression is False

    # จำลอง cloned authenticator — reset device counter
    dev.sign_count = 0
    r2 = do_login(test_user.email, db, dev)  # assertion count=1 <= stored=1
    db.commit()
    assert r2.counter_regression is True  # ตรวจจับได้
    # lenient — login ยังสำเร็จ + bump counter_regression_count
    assert r2.credential.counter_regression_count >= 1


# ─── Step-up ceremony ───────────────────────────────────────────────────────


@pytest.mark.smoke
def test_stepup_full_ceremony(test_user, db):
    """register → stepup ceremony เต็ม → AuthResult (ไม่ออก JWT)."""
    _, dev = do_register(test_user, db)
    db.commit()
    result = do_stepup(test_user, db, dev)
    db.commit()
    assert result.user.id == test_user.id
    assert result.credential.sign_count == 1


@pytest.mark.smoke
def test_stepup_no_passkey_raises(test_user, db):
    """user ไม่มี passkey → stepup_begin 400 no_passkey (fallback OTP)."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ws.stepup_begin(test_user, db)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "no_passkey"


# ─── Phase 7: Discoverable login + adoption ─────────────────────────────────


def _do_discoverable(db, device, origin="http://localhost:3000"):
    from tests.passkey_ceremony import _assertion_to_cred, _opts_to_soft

    opts = ws.discoverable_begin(db)
    assertion = device.get(_opts_to_soft(opts, is_auth=True), origin)
    return ws.discoverable_complete(_assertion_to_cred(assertion), db)


@pytest.mark.smoke
def test_discoverable_login_identifies_by_userhandle(test_user, db):
    """discoverable login (ไม่กรอก email) → identify จาก userHandle."""
    _, dev = do_register(test_user, db)
    db.commit()
    result = _do_discoverable(db, dev)
    db.commit()
    assert result.user.id == test_user.id  # identified โดยไม่ใช้ email


@pytest.mark.smoke
def test_discoverable_foreign_device_rejected(test_user, db):
    """device ที่ไม่เคย register → discoverable 401 (challenge ไม่มีใน Redis หลัง getdel)."""
    from fastapi import HTTPException

    _, dev = do_register(test_user, db)
    db.commit()
    foreign = UVSoftWebauthnDevice()
    foreign.cred_init("localhost", uuid.uuid4().bytes)
    with pytest.raises(HTTPException):
        _do_discoverable(db, foreign)


@pytest.mark.smoke
def test_adoption_status_optin_default(test_user, db):
    """default (after=0) → nudge=false เสมอ (opt-in)."""
    st = ws.adoption_status(test_user, db)
    assert st["nudge"] is False
    assert st["has_passkey"] is False


@pytest.mark.smoke
def test_adoption_status_nudge_when_overdue(test_user, db, monkeypatch):
    """after>0 + account เก่า + ไม่มี passkey → nudge=true."""
    from datetime import datetime, timedelta

    from app.config import settings as s

    monkeypatch.setattr(s, "passkey_required_after_days", 7)
    test_user.created_at = datetime.utcnow() - timedelta(days=30)
    db.commit()
    st = ws.adoption_status(test_user, db)
    assert st["nudge"] is True

    # มี passkey → nudge=false
    do_register(test_user, db)
    db.commit()
    assert ws.adoption_status(test_user, db)["nudge"] is False
