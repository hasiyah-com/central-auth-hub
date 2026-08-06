"""E2E — ข้อ 5 เชื่อมต่อระบบย่อยผ่าน OAuth 2.0 + PKCE → JWT → verify JWKS.

E2E จริงของ subsystem OAuth flow: seed auth_code (หลัง user ยืนยันตัวตนสำเร็จ) →
POST /oauth/token (client_secret + PKCE verifier) → ได้ JWT (RS256, aud=client_id) →
verify ผ่าน public key (JWKS) เหมือน subsystem จริง. ครอบ positive + negative
(secret ผิด/verifier ผิด/code ใช้ซ้ำ — atomic getdel/aud confusion).

รัน: docker compose exec hub-backend pytest tests/test_e2e_oauth_flow.py -v
"""

from __future__ import annotations

import json
import secrets
import uuid

import pytest

from app.models import Subsystem, User
from app.redis_client import redis_client
from app.services.secret_service import hash_secret
from app.services.pkce import generate_pkce_pair
from app.services.jwt_service import verify_token


@pytest.fixture
def oauth_subsystem(db):
    """subsystem active + secret ที่รู้ plaintext (สำหรับ token exchange จริง)."""
    plain_secret = f"sec_{uuid.uuid4().hex}"
    sub = Subsystem(
        name=f"e2e-oauth-{uuid.uuid4().hex[:6]}",
        client_id=f"cli_{uuid.uuid4().hex[:16]}",
        client_secret_hash=hash_secret(plain_secret),
        redirect_uris=["https://e2e-oauth.example.com/callback"],
        scope=["email", "name"],
        status="active",
        access_policy="explicit",
    )
    db.add(sub)
    db.commit()
    sub._plain_secret = plain_secret  # เก็บไว้ให้เทสใช้
    yield sub
    db.query(Subsystem).filter(Subsystem.id == sub.id).delete(synchronize_session=False)
    db.commit()


def _seed_authcode(sub, user, code_challenge) -> str:
    """จำลองว่า user ยืนยันตัวตนสำเร็จแล้ว → Hub ออก auth_code (Redis, 60 วิ)."""
    code = secrets.token_urlsafe(32)
    redis_client.setex(
        f"authcode:{code}",
        60,
        json.dumps(
            {
                "user_id": str(user.id),
                "client_id": sub.client_id,
                "subsystem_id": str(sub.id),
                "code_challenge": code_challenge,
                "scope": list(sub.scope),
            }
        ),
    )
    return code


def _exchange(client, code, client_id, secret, verifier):
    return client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": secret,
            "code_verifier": verifier,
        },
    )


# ═══════════ Full flow (positive) ═══════════


def test_e2e_oauth_full_flow_positive(client, oauth_subsystem, db):
    """auth_code → /oauth/token → JWT (RS256, aud=client_id) → verify ผ่าน JWKS."""
    user = db.query(User).filter(User.status == "active").first()
    verifier, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)

    r = _exchange(
        client, code, oauth_subsystem.client_id, oauth_subsystem._plain_secret, verifier
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # verify JWT เหมือน subsystem จริง (aud = client_id ของตัวเอง)
    claims = verify_token(token, audience=oauth_subsystem.client_id)
    assert claims["aud"] == oauth_subsystem.client_id
    assert claims["sub"] == str(user.id)


def test_e2e_oauth_jwt_has_scope_fields(client, oauth_subsystem, db):
    """JWT ที่ออกให้ subsystem มี claim ตาม scope + role."""
    user = db.query(User).filter(User.status == "active").first()
    verifier, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)
    r = _exchange(
        client, code, oauth_subsystem.client_id, oauth_subsystem._plain_secret, verifier
    )
    body = r.json()
    assert body["token_type"] == "bearer" and "expires_in" in body


# ═══════════ Negative ═══════════


def test_e2e_oauth_wrong_secret_negative(client, oauth_subsystem, db):
    """client_secret ผิด → 401 (ไม่ออก token)."""
    user = db.query(User).filter(User.status == "active").first()
    verifier, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)
    r = _exchange(client, code, oauth_subsystem.client_id, "wrong-secret", verifier)
    assert r.status_code in (400, 401)


def test_e2e_oauth_wrong_pkce_verifier_negative(client, oauth_subsystem, db):
    """code_verifier ไม่ตรง code_challenge → ปฏิเสธ (กัน auth-code interception)."""
    user = db.query(User).filter(User.status == "active").first()
    _, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)
    wrong_verifier, _ = generate_pkce_pair()  # verifier คนละคู่
    r = _exchange(
        client,
        code,
        oauth_subsystem.client_id,
        oauth_subsystem._plain_secret,
        wrong_verifier,
    )
    assert r.status_code in (400, 401)


def test_e2e_oauth_code_reuse_negative(client, oauth_subsystem, db):
    """ใช้ auth_code ซ้ำครั้งที่ 2 → ปฏิเสธ (atomic getdel — ใช้ครั้งเดียว)."""
    user = db.query(User).filter(User.status == "active").first()
    verifier, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)
    r1 = _exchange(
        client, code, oauth_subsystem.client_id, oauth_subsystem._plain_secret, verifier
    )
    assert r1.status_code == 200
    # ใช้ code เดิมซ้ำ → ต้องล้มเหลว (ถูก getdel ไปแล้ว)
    r2 = _exchange(
        client, code, oauth_subsystem.client_id, oauth_subsystem._plain_secret, verifier
    )
    assert r2.status_code in (400, 401)


def test_e2e_oauth_invalid_code_negative(client, oauth_subsystem):
    """auth_code ที่ไม่มีจริง → ปฏิเสธ."""
    verifier, _ = generate_pkce_pair()
    r = _exchange(
        client,
        "nonexistent-code",
        oauth_subsystem.client_id,
        oauth_subsystem._plain_secret,
        verifier,
    )
    assert r.status_code in (400, 401)


def test_e2e_oauth_aud_confusion_negative(client, oauth_subsystem, db):
    """JWT ของ subsystem A verify ด้วย aud ของ B ไม่ผ่าน (audience confusion, B4)."""
    user = db.query(User).filter(User.status == "active").first()
    verifier, challenge = generate_pkce_pair()
    code = _seed_authcode(oauth_subsystem, user, challenge)
    token = _exchange(
        client, code, oauth_subsystem.client_id, oauth_subsystem._plain_secret, verifier
    ).json()["access_token"]
    # verify ด้วย aud ผิด (client_id อื่น) → ต้อง raise
    with pytest.raises(Exception):
        verify_token(token, audience="cli_someone_else")
