"""JWT service — sign/verify ด้วย RS256 + JWK Set rotation (RFC 7517 §6).

Multi-kid support สำหรับ zero-downtime key rotation:
  - **Active key** (`settings.jwt_active_kid`) ใช้ sign token ใหม่
  - **Extra public keys** (`settings.jwt_extra_public_keys`) — verify-only,
    สำหรับ token ที่ sign ด้วย key เก่ายัง valid อยู่
  - JWKS endpoint คืนทุก kid → subsystem verify ได้ทั้งคู่

Rotation flow:
  T+0:  begin    — เพิ่ม new key เป็น extra (verify only); active = old
  T+5m: activate — สลับ active = new; old อยู่ใน extra (verify only)
  T+65m: finalize — ลบ old ออกจาก extra (ทุก token เก่า expired แล้ว 60min TTL)

Migration note: Migrated from `python-jose` → `PyJWT` (เพื่อตัด ecdsa/pyasn1 CVE)
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from jwt.exceptions import InvalidTokenError as JWTError  # backwards-compat alias

from app.config import settings
from app.redis_client import redis_client
from app.services.hooks import EVT_TOKEN_ISSUED, emit_nowait

log = logging.getLogger(__name__)
ISSUER = "https://hub.local"

# ============ Revocation list (Redis) ============
# Pattern: token's jti → key "jwt:revoked:{jti}" with TTL=remaining exp
# verify_token() ตรวจ key นี้หลัง decode → raise ถ้าเจอ
# Subsystem ตรวจตาม JWKS เท่านั้น → revocation ตรวจที่ Hub endpoints เท่านั้น
# (subsystem ยังคง verify offline ได้เร็ว แต่ revoke จะมีผลตอน user เรียก Hub API ต่อ)

_REVOKE_PREFIX = "jwt:revoked:"


def _redis_key(jti: str) -> str:
    return f"{_REVOKE_PREFIX}{jti}"


def revoke_jti(jti: str, exp_unix: int) -> bool:
    """Revoke JWT โดย jti — TTL = remaining time จนถึง exp.

    ถ้า exp ผ่านไปแล้ว → ไม่ต้อง revoke (verify จะ reject อยู่แล้ว)
    """
    if not jti:
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = exp_unix - now
    if ttl <= 0:
        return False
    try:
        redis_client.set(_redis_key(jti), "1", ex=ttl)
        return True
    except Exception as e:
        log.warning("revoke_jti redis failed: %r", e)
        return False


def is_revoked(jti: str) -> bool:
    """ตรวจว่า jti อยู่ใน revocation list ไหม."""
    if not jti:
        return False
    try:
        return redis_client.exists(_redis_key(jti)) == 1
    except Exception as e:
        # fail-open: ถ้า Redis ล่ม ปล่อยผ่าน (กัน Hub fail ทั้งระบบ)
        # ถ้าต้องการ fail-closed ให้ raise ที่นี่แทน
        log.warning("is_revoked redis failed (fail-open): %r", e)
        return False


# ============ Key loading ============


def _read(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


@lru_cache
def _active_private_key() -> str:
    return _read(settings.jwt_private_key_path)


def _public_pem_for(kid: str) -> str | None:
    """Resolve kid → public key PEM. Restart container เพื่อ pick up change."""
    if kid == settings.jwt_active_kid:
        return _read(settings.jwt_public_key_path)
    # ค้นใน extra (format "kid1:/path/pub1.pem,kid2:/path/pub2.pem")
    for entry in (settings.jwt_extra_public_keys or "").split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        ekid, epath = entry.split(":", 1)
        if ekid.strip() == kid:
            try:
                return _read(epath.strip())
            except OSError as e:
                log.warning(
                    "Failed to read extra public key %s @ %s: %s", kid, epath, e
                )
                return None
    return None


def _all_public_keys() -> dict[str, str]:
    """{kid: pem} — active + all extras. ใช้สำหรับ JWKS endpoint."""
    keys: dict[str, str] = {
        settings.jwt_active_kid: _read(settings.jwt_public_key_path)
    }
    for entry in (settings.jwt_extra_public_keys or "").split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        ekid, epath = entry.split(":", 1)
        ekid = ekid.strip()
        epath = epath.strip()
        if ekid == settings.jwt_active_kid:
            continue  # already added
        try:
            keys[ekid] = _read(epath)
        except OSError as e:
            log.warning("Skip extra public key %s @ %s: %s", ekid, epath, e)
    return keys


# ============ Sign ============


def create_access_token(user, audience: str | None = None) -> tuple[str, str]:
    """สร้าง JWT Hub-direct (aud = hub.internal โดย default).

    Returns (token, jti) — caller เก็บ jti ไว้ใน LoginSession เพื่อ force-revoke ภายหลัง
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "iss": ISSUER,
        "sub": str(user.id),
        "aud": audience or settings.jwt_hub_audience,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti,
        "email": user.email,
        "name": user.full_name,
        "user_type": user.user_type,
        "faculty": user.faculty,
    }
    token = jwt.encode(
        payload,
        _active_private_key(),
        algorithm="RS256",
        headers={"kid": settings.jwt_active_kid},
    )
    emit_nowait(
        EVT_TOKEN_ISSUED,
        {
            "sub": payload["sub"],
            "aud": payload["aud"],
            "exp": payload["exp"],
            "jti": jti,
            "kind": "hub_direct",
            "kid": settings.jwt_active_kid,
        },
    )
    return token, jti


def create_subsystem_token(
    user, client_id: str, scope: list[str], role_in_sub: str
) -> tuple[str, str]:
    """JWT สำหรับ subsystem — เฉพาะ field ใน scope.

    Returns (token, jti)
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "iss": ISSUER,
        "sub": str(user.id),
        "aud": client_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti,
        "role_in_subsystem": role_in_sub,
    }
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
            k, v = scope_field_map[s]
            payload[k] = v

    token = jwt.encode(
        payload,
        _active_private_key(),
        algorithm="RS256",
        headers={"kid": settings.jwt_active_kid},
    )
    emit_nowait(
        EVT_TOKEN_ISSUED,
        {
            "sub": payload["sub"],
            "aud": payload["aud"],
            "exp": payload["exp"],
            "jti": jti,
            "kind": "subsystem",
            "role_in_subsystem": role_in_sub,
            "scope": scope,
            "kid": settings.jwt_active_kid,
        },
    )
    return token, jti


# ============ Verify ============


def verify_token(token: str, audience: str | None = None) -> dict:
    """ตรวจ JWT — lookup public key ตาม `kid` ใน header.

    รองรับ rotation: token ที่ sign ด้วย kid เก่ายัง verify ผ่านถ้า kid อยู่ใน
    extra_public_keys (ระหว่าง grace period)
    """
    expected_aud = audience or settings.jwt_hub_audience
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise JWTError(f"Bad JWT header: {e}") from e

    kid = header.get("kid") or settings.jwt_active_kid
    pub_pem = _public_pem_for(kid)
    if not pub_pem:
        raise JWTError(f"Unknown signing key kid={kid!r}")

    payload = jwt.decode(
        token,
        pub_pem,
        algorithms=["RS256"],
        audience=expected_aud,
        issuer=ISSUER,
        options={"verify_aud": True, "verify_iss": True, "verify_exp": True},
    )
    # Revocation check — หลัง decode ผ่านถึงจะตรวจ
    # (กัน Redis hit ตอน token ผิด signature/aud — ลด attack surface)
    jti = payload.get("jti")
    if jti and is_revoked(jti):
        raise JWTError("token has been revoked")
    return payload


# ============ JWKS ============


def _b64url_uint(n: int) -> str:
    """base64url-encode integer (RFC 7515 Appendix C)."""
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _to_jwk(kid: str, pem: str) -> dict:
    """แปลง RSA public key PEM → JWK dict (RFC 7517)."""
    pub = load_pem_public_key(pem.encode())
    n = pub.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "kid": kid,
        "alg": "RS256",
        "n": _b64url_uint(n.n),
        "e": _b64url_uint(n.e),
    }


def get_jwks() -> dict:
    """คืน JWK Set — ทุก kid ที่ valid (active + extras).

    Subsystem cache JWKS แล้ว match `kid` จาก JWT header — รองรับ rotation
    โดยไม่ต้อง restart subsystem (จะดึง JWKS ใหม่ตอน cache หมดอายุ 10 นาที)
    """
    return {"keys": [_to_jwk(kid, pem) for kid, pem in _all_public_keys().items()]}
