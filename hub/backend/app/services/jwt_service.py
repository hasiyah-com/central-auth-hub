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
    """สร้าง JWT access token สำหรับ user ที่ login กับ Hub โดยตรง.

    audience = client_id ของ subsystem (ถ้าเป็น token สำหรับ subsystem)
               หรือ None = token ของ Hub เอง (จะตั้ง aud = jwt_hub_audience)

    การแยก audience สำคัญมาก — กัน subsystem token มาใช้กับ Hub endpoint
    เพราะ verify_token() ที่ Hub จะบังคับเช็ค aud = jwt_hub_audience
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        # Standard claims
        "iss": ISSUER,
        "sub": str(user.id),
        "aud": audience or settings.jwt_hub_audience,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        # User data
        "email": user.email,
        "name": user.full_name,
        "user_type": user.user_type,
        "faculty": user.faculty,
    }

    headers = {"kid": KEY_ID}
    return jwt.encode(payload, _private_key(), algorithm="RS256", headers=headers)


def create_subsystem_token(
    user, client_id: str, scope: list[str], role_in_sub: str
) -> str:
    """สร้าง JWT สำหรับ subsystem — ใส่ข้อมูล user เฉพาะ field ที่อยู่ใน scope.

    นี่คือหัวใจของ "Scope-based Data Access":
    subsystem ได้รับเฉพาะข้อมูลที่ลงทะเบียนขอไว้เท่านั้น
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        "iss": ISSUER,
        "sub": str(user.id),
        "aud": client_id,                    # token นี้ใช้ได้เฉพาะ subsystem นี้
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "role_in_subsystem": role_in_sub,
    }

    # map scope -> field ของ user (ใส่เฉพาะที่ subsystem ขอ)
    scope_field_map = {
        "email": ("email", user.email),
        "name": ("name", user.full_name),
        "student_id": ("student_id", user.identifier),
        "employee_id": ("employee_id", user.identifier),
        "faculty": ("faculty", user.faculty),
        "major": ("major", user.major),
        "year": ("year", user.year_or_position),
        "position": ("position", user.year_or_position),
        "phone": ("phone", user.phone),
        "address": ("address", user.address),
    }
    for s in scope:
        if s in scope_field_map:
            key, value = scope_field_map[s]
            payload[key] = value

    headers = {"kid": KEY_ID}
    return jwt.encode(payload, _private_key(), algorithm="RS256", headers=headers)


def verify_token(token: str, audience: str | None = None) -> dict:
    """ตรวจสอบ JWT — คืน payload ถ้า valid, raise JWTError ถ้าไม่ valid.

    audience: ค่าที่คาดหวังใน aud claim. ถ้า None จะใช้ jwt_hub_audience
              (กัน subsystem token หลุดมาใช้ที่ Hub).
    """
    expected_aud = audience or settings.jwt_hub_audience
    return jwt.decode(
        token,
        _public_key(),
        algorithms=["RS256"],
        issuer=ISSUER,
        audience=expected_aud,
        options={"verify_aud": True},
    )


# ============ JWKS — public key สำหรับให้ subsystem verify ============

def get_jwks() -> dict:
    """คืน JWKS (JSON Web Key Set) — subsystem ดึงไปใช้ verify token."""
    key = jwk.construct(_public_key(), algorithm="RS256")
    jwk_dict = key.to_dict()
    jwk_dict.update({"use": "sig", "kid": KEY_ID, "alg": "RS256"})
    return {"keys": [jwk_dict]}
