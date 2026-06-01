"""Unit tests for JWT service — encode/decode round-trip + claims."""

import pytest
from jwt.exceptions import InvalidTokenError as JWTError

from app.config import settings
from app.services.jwt_service import (
    create_access_token,
    create_subsystem_token,
    verify_token,
)


@pytest.mark.smoke
def test_create_access_token_has_required_claims(admin_user):
    """Hub-direct JWT ต้องมี aud=hub.internal + email + user_type + is_hub_admin."""
    token = create_access_token(admin_user)
    assert isinstance(token, str)
    assert token.count(".") == 2  # header.payload.signature

    payload = verify_token(token)
    assert payload["aud"] == settings.jwt_hub_audience
    assert payload["email"] == admin_user.email
    assert payload["user_type"] == admin_user.user_type
    # is_hub_admin ไม่ได้อยู่ใน JWT claim — frontend infer จาก user_type === "admin"
    assert payload["sub"] == str(admin_user.id)
    assert "iat" in payload
    assert "exp" in payload


@pytest.mark.smoke
def test_subsystem_token_has_audience_filter(teacher_user):
    """Subsystem JWT ต้องมี aud = client_id + เฉพาะ field ใน scope."""
    token = create_subsystem_token(
        user=teacher_user,
        client_id="cli_test123",
        scope=["email", "name"],
        role_in_sub="member",
    )
    # Verify ด้วย audience ผิด → fail
    with pytest.raises(JWTError):
        verify_token(token, audience="hub.internal")

    # Verify ด้วย audience ถูก → ผ่าน
    payload = verify_token(token, audience="cli_test123")
    assert payload["aud"] == "cli_test123"
    assert payload["email"] == teacher_user.email
    assert payload["name"] == teacher_user.full_name
    assert payload["role_in_subsystem"] == "member"
    # field ที่ไม่ได้อยู่ใน scope → ต้องไม่มีใน token (data minimization)
    assert "student_id" not in payload
    assert "phone" not in payload


@pytest.mark.smoke
def test_verify_token_rejects_wrong_audience(admin_user):
    """JWT ของ Hub ใช้ที่ subsystem ไม่ได้ (audience mismatch)."""
    token = create_access_token(admin_user)
    # aud=hub.internal — verify ด้วย client_id อื่น → fail
    with pytest.raises(JWTError):
        verify_token(token, audience="cli_anything")


@pytest.mark.smoke
def test_verify_token_rejects_tampered(admin_user):
    """แก้ payload แล้ว verify ไม่ผ่าน."""
    token = create_access_token(admin_user)
    # tamper signature (เปลี่ยน char สุดท้าย)
    bad = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(JWTError):
        verify_token(bad)
