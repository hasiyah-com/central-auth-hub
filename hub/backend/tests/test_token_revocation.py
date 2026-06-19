"""Token Revocation tests — jti blacklist (Redis) + verify + logout endpoints.

ครอบ:
  - revoke_jti / is_revoked round-trip
  - verify_token ปฏิเสธ token ที่ถูก revoke (แม้ signature/exp ถูก)
  - POST /auth/logout → revoke token ตัวเอง → /auth/me ใช้ token เดิมไม่ได้ (401)
  - /auth/logout idempotent (token เสีย → ไม่ error)
"""

import time

import pytest
from jwt.exceptions import InvalidTokenError as JWTError

from app.services.jwt_service import (
    create_access_token,
    is_revoked,
    revoke_jti,
    verify_token,
)


@pytest.mark.smoke
def test_revoke_jti_roundtrip():
    jti = f"test-{time.time_ns()}"
    assert is_revoked(jti) is False
    revoke_jti(jti, int(time.time()) + 300)
    assert is_revoked(jti) is True


@pytest.mark.smoke
def test_revoke_jti_expired_no_store():
    """exp ผ่านไปแล้ว → ttl <= 0 → ไม่ต้องเก็บ (token หมดอายุเองอยู่แล้ว)."""
    jti = f"test-exp-{time.time_ns()}"
    revoke_jti(jti, int(time.time()) - 10)
    assert is_revoked(jti) is False


@pytest.mark.smoke
def test_verify_token_rejects_revoked(admin_user):
    """token ที่ถูก revoke → verify_token raise (แม้ signature ถูก)."""
    token, jti = create_access_token(admin_user)
    # ก่อน revoke ใช้ได้
    payload = verify_token(token)
    assert payload["jti"] == jti
    # revoke แล้วใช้ไม่ได้
    revoke_jti(jti, int(payload["exp"]))
    with pytest.raises(JWTError):
        verify_token(token)


@pytest.mark.smoke
def test_logout_revokes_own_token(client, admin_user, auth_headers):
    """POST /auth/logout → /auth/me ด้วย token เดิม → 401."""
    token, _jti = create_access_token(admin_user)
    headers = auth_headers(token)

    # /auth/me ใช้ได้ก่อน logout
    assert client.get("/auth/me", headers=headers).status_code == 200

    # logout → revoke
    r = client.post("/auth/logout", headers=headers)
    assert r.status_code == 200
    assert r.json()["token_revoked"] is True

    # token เดิมใช้ไม่ได้แล้ว
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.smoke
def test_logout_idempotent_bad_token(client, auth_headers):
    """token เสีย → /auth/logout ไม่ error (idempotent)."""
    r = client.post("/auth/logout", headers=auth_headers("garbage.token.xxx"))
    assert r.status_code == 200
    assert r.json()["token_revoked"] is False
