"""Hub OAuth client — PKCE + token exchange + JWT verify ผ่าน JWKS.

Subsystem A คุยกับ Hub 3 จุด:
  1. /oauth/authorize  — redirect ผู้ใช้ไป (ผ่าน browser ใช้ HUB_PUBLIC_URL)
  2. /oauth/token      — แลก code เป็น JWT (server-to-server ใช้ HUB_INTERNAL_URL)
  3. /.well-known/jwks.json — ดึง public key มา verify JWT (cache)
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import json

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidTokenError as JWTError

from app.config import settings

# cache JWKS ในหน่วยความจำ (Hub rotate key ไม่บ่อย — 10 นาทีพอ)
_JWKS_CACHE_TTL = 600
_jwks_cache: dict = {"data": None, "fetched_at": 0}


# ============ PKCE ============


def generate_pkce_pair() -> tuple[str, str]:
    """สร้าง (code_verifier, code_challenge) ตาม RFC 7636.

    code_verifier: 43-128 chars URL-safe random
    code_challenge: base64url(SHA256(verifier)) แบบไม่มี padding
    """
    code_verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


# ============ Authorization URL (browser redirect) ============


def build_authorize_url(state: str, code_challenge: str) -> str:
    """สร้าง URL ที่ browser จะ redirect ไป Hub /oauth/authorize.

    ใช้ HUB_PUBLIC_URL เพราะ browser ต้องเห็น localhost
    """
    params = {
        "client_id": settings.dorm_client_id,
        "redirect_uri": settings.dorm_callback_url,
        "state": state,
        "code_challenge": code_challenge,
    }
    return f"{settings.hub_public_url}/oauth/authorize?{urlencode(params)}"


# ============ Token Exchange (server-to-server) ============


async def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """POST /oauth/token แลก authorization code → JWT.

    ใช้ HUB_INTERNAL_URL เพราะเป็น call ระหว่าง container ภายใน Docker network
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{settings.hub_internal_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.dorm_client_id,
                "client_secret": settings.dorm_client_secret,
                "code_verifier": code_verifier,
            },
        )
        r.raise_for_status()
        return r.json()


# ============ JWKS + JWT verify ============


async def _fetch_jwks() -> dict:
    """ดึง JWKS จาก Hub (cache 10 นาที)."""
    now = time.time()
    if _jwks_cache["data"] and (now - _jwks_cache["fetched_at"]) < _JWKS_CACHE_TTL:
        return _jwks_cache["data"]

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{settings.hub_internal_url}/.well-known/jwks.json")
        r.raise_for_status()
        jwks = r.json()

    _jwks_cache["data"] = jwks
    _jwks_cache["fetched_at"] = now
    return jwks


async def verify_hub_jwt(token: str) -> dict:
    """ตรวจ JWT ที่ Hub ออกให้ subsystem นี้ — คืน claims dict.

    Verify ครบ:
      - signature ด้วย public key ที่ matched kid
      - iss = https://hub.local (Hub's issuer)
      - aud = client_id ของเรา (กัน token ของ subsystem อื่นใช้กับเรา)
    """
    jwks = await _fetch_jwks()

    # หา key ที่ kid ตรงกับ header ของ token (PyJWT API)
    header = pyjwt.get_unverified_header(token)
    kid = header.get("kid")
    matched = next((k for k in jwks["keys"] if k.get("kid") == kid), None)
    if not matched:
        raise JWTError(f"ไม่พบ public key สำหรับ kid={kid}")

    # PyJWT รับ key object — convert JWK dict → RSA public key ก่อน
    public_key = RSAAlgorithm.from_jwk(json.dumps(matched))

    return pyjwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=settings.jwt_issuer,
        audience=settings.dorm_client_id,
        options={"verify_aud": True, "verify_iss": True, "verify_exp": True},
    )
