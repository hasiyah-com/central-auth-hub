"""Phase 1 unit tests — Passkey register service + backup codes (plan v3).

Scope:
    - register_begin enforces max Passkeys per user (Improvement #9)
    - register_begin builds proper options
    - backup_codes generation + format + Argon2id verify (Improvement #3)
    - acknowledge_backup_codes marks rows
    - get_status returns correct counts / low threshold

Note: Full WebAuthn attestation verify requires mock authenticator setup
      (planned for Phase 6 integration suite). Phase 1 verifies the
      service-level invariants the router relies on.
"""

import re
import uuid

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.services import passkey_recovery, webauthn_service
from app.services.secret_service import verify_secret


# ─── Fixtures ───────────────────────────────────────────────────────────────


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
    """Create transient user, cleanup after test."""
    u = User(
        email=f"passkey-test-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Passkey Tester",
        user_type="staff",
        identifier=f"T{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    # cascade — delete child rows first
    db.query(PasskeyBackupCode).filter(PasskeyBackupCode.user_id == u.id).delete()
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == u.id).delete()
    db.delete(u)
    db.commit()


# ─── webauthn_service tests ─────────────────────────────────────────────────


@pytest.mark.smoke
def test_register_begin_returns_proper_options(test_user, db):
    """register_begin returns dict with rp, user, challenge, authenticatorSelection."""
    options = webauthn_service.register_begin(test_user, db)

    assert "rp" in options
    assert options["rp"]["id"] == "localhost"  # Q1
    assert options["rp"]["name"] == "Central Auth Hub"

    assert "user" in options
    assert "challenge" in options
    assert len(options["challenge"]) > 0

    sel = options["authenticatorSelection"]
    assert sel["userVerification"] == "required"  # Decision #2
    assert sel["residentKey"] == "preferred"
    # Decision #3 — no attachment restriction
    assert "authenticatorAttachment" not in sel


@pytest.mark.smoke
def test_register_begin_enforces_max(test_user, db, monkeypatch):
    """max_passkeys_per_user → 400 max_passkeys_exceeded (Improvement #9)."""
    from app.services import webauthn_service as ws

    # Insert dummy active credentials = limit
    from app.config import settings as s

    monkeypatch.setattr(s, "webauthn_max_passkeys_per_user", 2)
    for i in range(2):
        db.add(
            PasskeyCredential(
                user_id=test_user.id,
                credential_id=f"dummy-{i}".encode(),
                public_key=b"dummy",
                sign_count=0,
                device_name=f"Test{i}",
                transports=[],
            )
        )
    db.commit()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ws.register_begin(test_user, db)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "max_passkeys_exceeded"
    assert exc.value.detail["current"] == 2
    assert exc.value.detail["max"] == 2


@pytest.mark.smoke
def test_count_active_excludes_revoked(test_user, db):
    """count_active() ignores revoked credentials."""
    from datetime import datetime

    db.add(
        PasskeyCredential(
            user_id=test_user.id,
            credential_id=b"active",
            public_key=b"k",
            device_name="Active",
            transports=[],
        )
    )
    db.add(
        PasskeyCredential(
            user_id=test_user.id,
            credential_id=b"revoked",
            public_key=b"k",
            device_name="Revoked",
            transports=[],
            revoked_at=datetime.utcnow(),
            revoked_reason="user_deleted",
        )
    )
    db.commit()
    assert webauthn_service.count_active(test_user.id, db) == 1


# ─── Backup codes (Improvement #3) ──────────────────────────────────────────


@pytest.mark.smoke
def test_generate_backup_codes_format_and_count(test_user, db):
    """Generates exactly 10 codes in AB3D-7K9P format."""
    codes = passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    assert len(codes) == 10
    for c in codes:
        assert re.match(r"^[A-Z2-9]{4}-[A-Z2-9]{4}$", c), f"format bad: {c}"
        # no ambiguous chars
        assert "0" not in c and "1" not in c and "I" not in c and "O" not in c

    # All hashes saved with generation=1
    rows = (
        db.query(PasskeyBackupCode)
        .filter(PasskeyBackupCode.user_id == test_user.id)
        .all()
    )
    assert len(rows) == 10
    assert all(r.generation == 1 for r in rows)
    assert all(r.used_at is None for r in rows)
    assert all(r.acknowledged_at is None for r in rows)  # not yet acked


@pytest.mark.smoke
def test_backup_code_argon2id_verify_round_trip(test_user, db):
    """Plaintext code verifies against stored Argon2id hash."""
    codes = passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    rows = (
        db.query(PasskeyBackupCode)
        .filter(PasskeyBackupCode.user_id == test_user.id)
        .all()
    )
    # First plaintext code must match one of the hashes
    matched = sum(1 for r in rows if verify_secret(r.code_hash, codes[0]))
    assert matched == 1, "first code should verify against exactly one row"


@pytest.mark.smoke
def test_generate_twice_without_rotate_raises(test_user, db):
    """Second call without rotate=True raises (prevents accidental dup)."""
    passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    with pytest.raises(RuntimeError, match="already exist"):
        passkey_recovery.generate_backup_codes(test_user.id, db)


@pytest.mark.smoke
def test_rotate_increments_generation(test_user, db):
    """rotate=True → new generation, old + new both in DB."""
    passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    new_codes = passkey_recovery.generate_backup_codes(test_user.id, db, rotate=True)
    db.commit()
    assert len(new_codes) == 10
    gens = {
        r.generation
        for r in db.query(PasskeyBackupCode)
        .filter(PasskeyBackupCode.user_id == test_user.id)
        .all()
    }
    assert gens == {1, 2}


@pytest.mark.smoke
def test_acknowledge_marks_unused_codes(test_user, db):
    """acknowledge_backup_codes() sets acknowledged_at on unused rows."""
    passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    updated = passkey_recovery.acknowledge_backup_codes(test_user.id, db)
    db.commit()
    assert updated == 10
    rows = (
        db.query(PasskeyBackupCode)
        .filter(PasskeyBackupCode.user_id == test_user.id)
        .all()
    )
    assert all(r.acknowledged_at is not None for r in rows)


@pytest.mark.smoke
def test_get_status_low_threshold(test_user, db):
    """Improvement #7 — low=true when used >= 7/10."""
    passkey_recovery.generate_backup_codes(test_user.id, db)
    db.commit()
    from datetime import datetime

    rows = (
        db.query(PasskeyBackupCode)
        .filter(PasskeyBackupCode.user_id == test_user.id)
        .limit(6)
        .all()
    )
    for r in rows:
        r.used_at = datetime.utcnow()
    db.commit()

    status = passkey_recovery.get_status(test_user.id, db)
    assert status["used"] == 6
    assert status["remaining"] == 4
    assert status["low"] is False

    # Use one more — crosses threshold
    one_more = (
        db.query(PasskeyBackupCode)
        .filter(
            PasskeyBackupCode.user_id == test_user.id,
            PasskeyBackupCode.used_at.is_(None),
        )
        .first()
    )
    one_more.used_at = datetime.utcnow()
    db.commit()

    status = passkey_recovery.get_status(test_user.id, db)
    assert status["used"] == 7
    assert status["low"] is True


@pytest.mark.smoke
def test_get_status_zero_when_no_codes(test_user, db):
    """No codes generated → generation=0, total=0, low=False."""
    status = passkey_recovery.get_status(test_user.id, db)
    assert status["generation"] == 0
    assert status["total"] == 0
    assert status["used"] == 0
    assert status["low"] is False
    assert status["acknowledged"] is False
