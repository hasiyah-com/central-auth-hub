"""JWT service — sign และ verify token ด้วย RS256 (asymmetric key).

- Hub ใช้ private key sign token
- Subsystem ใช้ public key (จาก JWKS endpoint) verify token
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from jose import jwt, jwk, JWTError

from app.config import settings

ISSUER = "https://hub.local"
KEY_ID = "hub-key-1"


# ============ โหลด key (cache ไว้ ไม่อ่านไฟล์ซ้ำ) ============

@lru_cache
def _private_key() -> str:
    with open(settings.jwt_private_key_path, "r") as f:
        return f.read()


@lru_cache
def _public_key() -> str:
    with open(settings.jwt_public_key_path, "r") as f:
        return f.read()


# ============ สร้าง / ตรวจสอบ token ============

def create_access_token(user, audience: str | None = None) -> str:
    """สร้าง JWT access token สำหรับ user.

    audience = client_id ของ subsystem (ถ้าเป็น token สำหรับ subsystem)
               หรือ None ถ้าเป็น token ทั่วไปของ Hub
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        # Standard claims
        "iss": ISSUER,
        "sub": str(user.id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        # User data
        "email": user.email,
        "name": user.full_name,
        "user_type": user.user_type,
        "faculty": user.faculty,
    }
    if audience:
        payload["aud"] = audience

    headers = {"kid": KEY_ID}
    return jwt.encode(payload, _private_key(), algorithm="RS256", headers=headers)


def verify_token(token: str, audience: str | None = None) -> dict:
    """ตรวจสอบ JWT — คืน payload ถ้า valid, raise JWTError ถ้าไม่ valid."""
    options = {"verify_aud": audience is not None}
    return jwt.decode(
        token,
        _public_key(),
        algorithms=["RS256"],
        issuer=ISSUER,
        audience=audience,
        options=options,
    )


# ============ JWKS — public key สำหรับให้ subsystem verify ============

def get_jwks() -> dict:
    """คืน JWKS (JSON Web Key Set) — subsystem ดึงไปใช้ verify token."""
    key = jwk.construct(_public_key(), algorithm="RS256")
    jwk_dict = key.to_dict()
    jwk_dict.update({"use": "sig", "kid": KEY_ID, "alg": "RS256"})
    return {"keys": [jwk_dict]}
