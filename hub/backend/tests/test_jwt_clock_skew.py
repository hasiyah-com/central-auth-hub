"""ความคลาดของนาฬิกากับการตรวจ JWT — เขียนก่อน implementation (RED).

**ที่มา (B77):** ชุดเทสเต็มล้มแบบสุ่มด้วย 401 ในเทสคนละตัวทุกรอบ · บันทึกของ
`TEST_DIAG=1` ชี้ว่า `ImmatureSignatureError: The token is not yet valid (iat)`
โดย `age_s = -0.848` คือ token ที่เพิ่งออกมีเวลา `iat` ล้ำหน้าเวลาปัจจุบัน เพราะนาฬิกา
ในคอนเทนเนอร์ถอยหลังประมาณ 0.97 วินาที (นับได้ 16 ครั้งในรอบเดียว) ระหว่างที่ออก
token กับที่ตรวจ token

ไม่ใช่เรื่องของเทสอย่างเดียว — NTP ปรับเวลา หรือ hub หลายเครื่องที่นาฬิกาไม่ตรงกัน
ให้ผลแบบเดียวกันใน production · ทางแก้คือเผื่อความคลาดไว้ไม่กี่วินาที (RFC 7519 §4.1.4
อนุญาต "some small leeway" ไว้สำหรับกรณีนี้)

**ขอบเขตของการเผื่อ:** เผื่อเฉพาะการตรวจเวลา (`iat`, `nbf`, `exp`) เท่านั้น
ลายเซ็น · issuer · audience · revocation ต้องเข้มเท่าเดิมทุกกรณี

PyJWT 2.12 ตัดสินด้วย `iat > now + leeway` และ `exp <= now - leeway` โดยแปลง claim
เป็น int ก่อน · เทสขอบเขตจึงใช้ +5 (ต้องผ่าน) กับ +7 (ต้องไม่ผ่าน) ไม่ใช้ +6 เพราะ
ตอนที่ `now` ตรงวินาทีพอดี +6 จะกลายเป็นเท่ากับเพดานแล้วผ่านได้
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt as pyjwt
import pytest
from jwt.exceptions import InvalidTokenError as JWTError

from app.config import Settings, settings
from app.services import jwt_service
from app.services.jwt_service import revoke_jti, verify_token

SKEW_DEFAULT = 5


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _mint(
    *,
    iat_delta: int = 0,
    exp_delta: int = 900,
    nbf_delta: int | None = None,
    issuer: str | None = None,
    audience: str | None = None,
    key: str | None = None,
) -> tuple[str, str]:
    """สร้าง token ที่คุมเวลาได้เอง — คืน (token, jti)."""
    now = _now()
    jti = uuid.uuid4().hex
    payload = {
        "iss": issuer if issuer is not None else settings.hub_issuer,
        "sub": str(uuid.uuid4()),
        "aud": audience if audience is not None else settings.jwt_hub_audience,
        "iat": now + iat_delta,
        "exp": now + exp_delta,
        "jti": jti,
    }
    if nbf_delta is not None:
        payload["nbf"] = now + nbf_delta
    token = pyjwt.encode(
        payload,
        key if key is not None else jwt_service._active_private_key(),
        algorithm="RS256",
        headers={"kid": settings.jwt_active_kid},
    )
    return token, jti


# ── คอนฟิก ───────────────────────────────────────────────────────────────


def test_default_skew_is_five_seconds():
    assert settings.jwt_clock_skew_seconds == SKEW_DEFAULT


@pytest.mark.parametrize("value", [0, 1, 5, 60])
def test_values_inside_the_allowed_range_are_accepted(value):
    assert Settings(jwt_clock_skew_seconds=value).jwt_clock_skew_seconds == value


@pytest.mark.parametrize("value", [-1, -5, 61, 600])
def test_values_outside_the_allowed_range_are_refused_at_startup(value):
    """ค่าผิดต้องหยุดตั้งแต่สร้าง Settings — ไม่ใช่ปล่อยให้ token ตรวจหลวมเงียบๆ."""
    with pytest.raises(Exception) as e:
        Settings(jwt_clock_skew_seconds=value)
    assert "jwt_clock_skew_seconds" in str(e.value)


def test_non_numeric_value_is_refused():
    with pytest.raises(Exception):
        Settings(jwt_clock_skew_seconds="ไม่ใช่ตัวเลข")


# ── iat ล้ำหน้า (อาการที่ทำให้ชุดเทสล้ม) ──────────────────────────────────


def test_token_issued_one_second_in_the_future_is_accepted():
    """อาการจริงของ B77 — นาฬิกาถอยไม่ถึงวินาที แล้ว token ที่เพิ่งออกถูกปฏิเสธ."""
    token, _ = _mint(iat_delta=1)
    assert verify_token(token)["jti"]


def test_iat_at_the_skew_boundary_is_accepted():
    token, _ = _mint(iat_delta=SKEW_DEFAULT)
    assert verify_token(token)["jti"]


def test_iat_just_past_the_boundary_is_refused():
    token, _ = _mint(iat_delta=SKEW_DEFAULT + 2)
    with pytest.raises(JWTError):
        verify_token(token)


def test_iat_far_in_the_future_is_refused():
    token, _ = _mint(iat_delta=30)
    with pytest.raises(JWTError):
        verify_token(token)


# ── nbf ──────────────────────────────────────────────────────────────────


def test_nbf_within_the_skew_is_accepted():
    token, _ = _mint(nbf_delta=1)
    assert verify_token(token)["jti"]


def test_nbf_at_the_skew_boundary_is_accepted():
    token, _ = _mint(nbf_delta=SKEW_DEFAULT)
    assert verify_token(token)["jti"]


def test_nbf_beyond_the_skew_is_refused():
    token, _ = _mint(nbf_delta=30)
    with pytest.raises(JWTError):
        verify_token(token)


# ── exp ──────────────────────────────────────────────────────────────────


def test_token_expired_within_the_skew_is_accepted():
    token, _ = _mint(exp_delta=-2)
    assert verify_token(token)["jti"]


def test_token_expired_just_past_the_skew_is_refused():
    token, _ = _mint(exp_delta=-(SKEW_DEFAULT + 2))
    with pytest.raises(JWTError):
        verify_token(token)


def test_token_expired_long_ago_is_refused():
    token, _ = _mint(exp_delta=-3600)
    with pytest.raises(JWTError):
        verify_token(token)


# ── การตรวจอย่างอื่นต้องไม่หลวมตาม ───────────────────────────────────────


def test_skew_does_not_loosen_the_signature_check(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    token, _ = _mint(iat_delta=1, key=pem)
    with pytest.raises(JWTError):
        verify_token(token)


def test_skew_does_not_loosen_the_issuer_check():
    token, _ = _mint(iat_delta=1, issuer="https://ปลอม.example")
    with pytest.raises(JWTError):
        verify_token(token)


def test_skew_does_not_loosen_the_audience_check():
    token, _ = _mint(iat_delta=1, audience="cli_other")
    with pytest.raises(JWTError):
        verify_token(token)


def test_skew_does_not_loosen_revocation():
    token, jti = _mint(iat_delta=1)
    revoke_jti(jti, _now() + 900)
    with pytest.raises(JWTError):
        verify_token(token)


# ── ค่าที่ใช้จริงมาจากคอนฟิก ────────────────────────────────────────────


def test_verify_reads_the_skew_from_settings(monkeypatch):
    """ตั้งเป็น 0 แล้ว token ที่ iat ล้ำหน้า 1 วินาทีต้องถูกปฏิเสธอีกครั้ง."""
    monkeypatch.setattr(settings, "jwt_clock_skew_seconds", 0)
    token, _ = _mint(iat_delta=2)
    with pytest.raises(JWTError):
        verify_token(token)
