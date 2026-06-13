"""Phase 3 — Passkey lifecycle (list / rename / delete) tests.

Scope:
  - get_owned_passkey: scoped to user (cross-user isolation)
  - rename: nickname_history append
  - revoke: soft-delete + last-Passkey guard (Decision #15)
  - count_active_excluding

Service-level (สร้าง row ตรงใน DB — ไม่ต้อง WebAuthn ceremony).
API-level RBAC (admin-only) ทดสอบใน test_passkey_security.py.
"""

import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.services import webauthn_service as ws


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
        email=f"pk-life-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Lifecycle Tester",
        user_type="admin",
        identifier=f"A{uuid.uuid4().hex[:3]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.query(PasskeyBackupCode).filter(PasskeyBackupCode.user_id == u.id).delete()
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == u.id).delete()
    db.delete(u)
    db.commit()


def _add(db, user, name="Device", revoked=False) -> PasskeyCredential:
    c = PasskeyCredential(
        user_id=user.id,
        credential_id=uuid.uuid4().bytes,
        public_key=b"k",
        sign_count=0,
        device_name=name,
        transports=["internal"],
        revoked_at=datetime.utcnow() if revoked else None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ─── get_owned_passkey (isolation) ──────────────────────────────────────────


@pytest.mark.smoke
def test_get_owned_passkey_found(test_user, db):
    c = _add(db, test_user)
    row = ws.get_owned_passkey(test_user.id, str(c.id), db)
    assert row.id == c.id


@pytest.mark.smoke
def test_get_owned_passkey_wrong_user_404(test_user, db):
    """passkey ของ user อื่น → 404 (แม้รู้ id) — cross-user isolation."""
    c = _add(db, test_user)
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Other",
        user_type="admin",
        identifier=f"A{uuid.uuid4().hex[:3]}",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    try:
        with pytest.raises(HTTPException) as exc:
            ws.get_owned_passkey(other.id, str(c.id), db)
        assert exc.value.status_code == 404
    finally:
        db.delete(other)
        db.commit()


@pytest.mark.smoke
def test_get_owned_passkey_bad_uuid_404(test_user, db):
    with pytest.raises(HTTPException) as exc:
        ws.get_owned_passkey(test_user.id, "not-a-uuid", db)
    assert exc.value.status_code == 404


@pytest.mark.smoke
def test_get_owned_passkey_revoked_404(test_user, db):
    c = _add(db, test_user, revoked=True)
    with pytest.raises(HTTPException) as exc:
        ws.get_owned_passkey(test_user.id, str(c.id), db)
    assert exc.value.status_code == 404


# ─── rename ─────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_rename_appends_history(test_user, db):
    c = _add(db, test_user, name="Old Name")
    row = ws.rename_passkey(test_user.id, str(c.id), "New Name", db)
    db.commit()
    assert row.device_name == "New Name"
    assert len(row.nickname_history) == 1
    assert row.nickname_history[0]["from"] == "Old Name"
    assert row.nickname_history[0]["to"] == "New Name"
    assert "at" in row.nickname_history[0]


@pytest.mark.smoke
def test_rename_same_name_noop(test_user, db):
    c = _add(db, test_user, name="Same")
    row = ws.rename_passkey(test_user.id, str(c.id), "Same", db)
    assert row.nickname_history in (None, [])


@pytest.mark.smoke
def test_rename_blank_raises(test_user, db):
    c = _add(db, test_user)
    with pytest.raises(HTTPException) as exc:
        ws.rename_passkey(test_user.id, str(c.id), "   ", db)
    assert exc.value.status_code == 400


# ─── revoke + last-Passkey guard (Decision #15) ─────────────────────────────


@pytest.mark.smoke
def test_revoke_last_passkey_blocked(test_user, db):
    """ลบตัวสุดท้าย → 400 last_passkey."""
    c = _add(db, test_user)
    with pytest.raises(HTTPException) as exc:
        ws.revoke_passkey(test_user.id, str(c.id), db)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "last_passkey"
    # ยังไม่ถูก revoke
    db.refresh(c)
    assert c.revoked_at is None


@pytest.mark.smoke
def test_revoke_non_last_succeeds(test_user, db):
    """มี 2 ตัว → ลบ 1 ได้."""
    c1 = _add(db, test_user, name="First")
    _add(db, test_user, name="Second")
    row = ws.revoke_passkey(test_user.id, str(c1.id), db)
    db.commit()
    assert row.revoked_at is not None
    assert row.revoked_reason == "user_deleted"
    assert ws.count_active(test_user.id, db) == 1


@pytest.mark.smoke
def test_revoke_allow_last_override(test_user, db):
    """allow_last=True (เช่น admin reset/recovery) → ลบตัวสุดท้ายได้."""
    c = _add(db, test_user)
    row = ws.revoke_passkey(
        test_user.id, str(c.id), db, reason="admin_reset", allow_last=True
    )
    db.commit()
    assert row.revoked_at is not None
    assert row.revoked_reason == "admin_reset"


@pytest.mark.smoke
def test_count_active_excluding(test_user, db):
    c1 = _add(db, test_user)
    _add(db, test_user)
    assert ws.count_active_excluding(test_user.id, c1.id, db) == 1
