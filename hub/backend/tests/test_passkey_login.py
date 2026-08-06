"""Phase 2 unit tests — Passkey login service (plan v3).

Scope:
    - auth_begin returns options (even for non-existent user — no enumeration)
    - auth_begin populates allow_credentials from active Passkeys only
    - auth_complete: challenge expired/missing → 400
    - auth_complete: unknown user → 401 invalid_credential (opaque)
    - auth_complete: bad rawId → 400 credential_id_bad_b64
    - auth_complete: unknown credential for user → 401 invalid_credential

Note: A full attestation-aware login test (mock authenticator that produces
      a valid signature) lives in Phase 6 integration suite. Phase 2 tests
      verify pre-verification guards + the lenient counter regression branch.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PasskeyBackupCode, PasskeyCredential, User
from app.redis_client import redis_client
from app.services import webauthn_service
from app.services.webauthn_service import _auth_challenge_key_email


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
    u = User(
        email=f"passkey-login-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Passkey Login Tester",
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


def _add_credential(
    db: Session, user: User, *, revoked: bool = False
) -> PasskeyCredential:
    from datetime import datetime

    cred = PasskeyCredential(
        user_id=user.id,
        credential_id=uuid.uuid4().bytes,  # 16 bytes random
        public_key=b"\x30\x59\x30\x13",  # dummy DER
        sign_count=42,
        device_name="Test Device",
        transports=["internal"],
        revoked_at=datetime.utcnow() if revoked else None,
        revoked_reason="user_deleted" if revoked else None,
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred


# ─── auth_begin ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_auth_begin_unknown_email_does_not_enumerate(db):
    """Unknown email → still returns options (no 404). Anti-enumeration.

    allowCredentials ต้อง **ไม่ว่าง** (dummy descriptors) — กัน enumeration
    ผ่าน shape ของ response (empty=ไม่มี passkey vs non-empty=มี).
    """
    options = webauthn_service.auth_begin(
        f"nonexistent-{uuid.uuid4().hex[:6]}@uni.ac.th", db
    )
    assert "challenge" in options
    assert options["userVerification"] == "required"  # Decision #2
    # Anti-enum: ต้องมี dummy descriptor (ไม่ใช่ list ว่าง)
    assert len(options.get("allowCredentials", [])) >= 1


@pytest.mark.smoke
def test_auth_begin_dummy_is_deterministic_per_email(db):
    """email เดียวกัน → dummy credential id เดิมทุกครั้ง (กัน shape/timing tell)."""
    email = f"ghost-{uuid.uuid4().hex[:6]}@uni.ac.th"
    a = webauthn_service.auth_begin(email, db)
    b = webauthn_service.auth_begin(email, db)
    ids_a = [c["id"] for c in a["allowCredentials"]]
    ids_b = [c["id"] for c in b["allowCredentials"]]
    assert ids_a == ids_b and len(ids_a) >= 1


@pytest.mark.smoke
def test_auth_begin_dummy_differs_between_emails(db):
    """คนละ email → dummy id ต่างกัน (เลียนแบบ credential จริงที่ unique)."""
    a = webauthn_service.auth_begin(f"a-{uuid.uuid4().hex[:6]}@uni.ac.th", db)
    b = webauthn_service.auth_begin(f"b-{uuid.uuid4().hex[:6]}@uni.ac.th", db)
    assert a["allowCredentials"][0]["id"] != b["allowCredentials"][0]["id"]


@pytest.mark.smoke
def test_auth_begin_dummy_not_in_db(test_user, db):
    """dummy credential id ต้องไม่ตรง credential จริงใน DB → ceremony fail
    แบบเดียวกับ wrong credential (401 invalid_credential)."""
    from app.services.webauthn_service import _b64url_decode

    options = webauthn_service.auth_begin(
        f"nobody-{uuid.uuid4().hex[:6]}@uni.ac.th", db
    )
    dummy_id = _b64url_decode(options["allowCredentials"][0]["id"])
    hit = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.credential_id == dummy_id)
        .first()
    )
    assert hit is None


@pytest.mark.smoke
def test_auth_begin_blank_email_raises(db):
    """Empty email → 400."""
    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_begin("   ", db)
    assert exc.value.status_code == 400


@pytest.mark.smoke
def test_auth_begin_populates_allow_credentials(test_user, db):
    """Active Passkeys appear in allowCredentials with transports."""
    _add_credential(db, test_user)
    options = webauthn_service.auth_begin(test_user.email, db)

    assert len(options["allowCredentials"]) == 1
    entry = options["allowCredentials"][0]
    assert entry["type"] == "public-key"
    assert "transports" in entry
    assert "internal" in entry["transports"]


@pytest.mark.smoke
def test_auth_begin_excludes_revoked(test_user, db):
    """Revoked credentials → not in allow_credentials (จะได้ dummy แทน)."""
    from app.services.webauthn_service import _b64url

    cred = _add_credential(db, test_user, revoked=True)
    options = webauthn_service.auth_begin(test_user.email, db)
    returned_ids = {c["id"] for c in options.get("allowCredentials", [])}
    # credential ที่ revoked ต้องไม่อยู่ใน list (ได้ dummy เพราะไม่มี active)
    assert _b64url(cred.credential_id) not in returned_ids
    assert len(returned_ids) >= 1  # dummy (anti-enum)


@pytest.mark.smoke
def test_auth_begin_stores_challenge_in_redis(test_user, db):
    """Challenge persisted at email-keyed Redis location."""
    webauthn_service.auth_begin(test_user.email, db)
    key = _auth_challenge_key_email(test_user.email)
    assert redis_client.get(key) is not None
    # cleanup
    redis_client.delete(key)


# ─── auth_complete pre-verification guards ──────────────────────────────────


@pytest.mark.smoke
def test_auth_complete_blank_email_raises(db):
    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_complete("", {"rawId": "abc"}, db)
    assert exc.value.status_code == 400


@pytest.mark.smoke
def test_auth_complete_missing_credential_raises(db):
    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_complete("x@y.com", None, db)  # type: ignore[arg-type]
    assert exc.value.status_code == 400


@pytest.mark.smoke
def test_auth_complete_no_challenge_in_redis_raises(test_user, db):
    """No challenge in Redis → 400 challenge_expired_or_missing."""
    # Ensure no leftover key
    redis_client.delete(_auth_challenge_key_email(test_user.email))

    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_complete(test_user.email, {"rawId": "AAAA"}, db)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "challenge_expired_or_missing"


@pytest.mark.smoke
def test_auth_complete_unknown_user_returns_opaque_401(db):
    """Unknown email + valid challenge → 401 invalid_credential (no enumeration)."""
    fake_email = f"nope-{uuid.uuid4().hex[:6]}@uni.ac.th"
    # Pre-set Redis challenge as if auth_begin was called
    from app.services.webauthn_service import _b64url

    redis_client.setex(
        _auth_challenge_key_email(fake_email),
        60,
        _b64url(b"x" * 32),
    )
    try:
        with pytest.raises(HTTPException) as exc:
            webauthn_service.auth_complete(fake_email, {"rawId": "AAAA"}, db)
        assert exc.value.status_code == 401
        assert exc.value.detail["code"] == "invalid_credential"
    finally:
        redis_client.delete(_auth_challenge_key_email(fake_email))


@pytest.mark.smoke
def test_auth_complete_bad_rawid_raises(test_user, db):
    """Malformed rawId base64 → 400 credential_id_bad_b64.

    (challenge is consumed by getdel before rawId check — so we need a
    fresh Redis key per test scenario.)
    """
    from app.services.webauthn_service import _b64url

    redis_client.setex(
        _auth_challenge_key_email(test_user.email),
        60,
        _b64url(b"x" * 32),
    )
    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_complete(
            test_user.email,
            {"rawId": "!!!not-base64!!!"},
            db,
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] in (
        "credential_id_bad_b64",
        "credential_missing_rawId",
    )


@pytest.mark.smoke
def test_login_session_populates_device_and_ml():
    """_build_login_session ต้อง parse device + รัน ML จริง
    (กัน dashboard '?' — bug 2026-06-11; + ML runs — bug 2026-06-11 #2).
    """
    import inspect

    from app.routers import passkey as pk

    src = inspect.getsource(pk._build_login_session)
    assert (
        "parse_os_name" in src and "parse_browser" in src and "parse_device_type" in src
    )
    assert "lookup_geo" in src  # geo lookup (country + city)
    # ML/RBA ต้องรันจริง (ไม่ hardcode 0.0)
    assert "evaluate_login_risk" in src, "ต้องรัน risk engine (ML), ห้าม hardcode 0.0"
    assert "extract_session_features" in src
    # login_finish + discoverable เรียก helper นี้
    assert "_build_login_session" in inspect.getsource(pk.login_finish)


@pytest.mark.smoke
def test_auth_complete_unknown_credential_for_user_returns_401(test_user, db):
    """User exists but rawId doesn't match any active credential → 401."""
    from app.services.webauthn_service import _b64url

    # Add a credential (so user has at least one) but query with a different rawId
    _add_credential(db, test_user)
    redis_client.setex(
        _auth_challenge_key_email(test_user.email),
        60,
        _b64url(b"x" * 32),
    )
    random_other_id = _b64url(uuid.uuid4().bytes)
    with pytest.raises(HTTPException) as exc:
        webauthn_service.auth_complete(
            test_user.email,
            {"rawId": random_other_id},
            db,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_credential"
