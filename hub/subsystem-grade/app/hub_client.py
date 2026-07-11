"""Hub OAuth client — PKCE + token exchange + JWT verify ผ่าน JWKS.

(pattern เดียวกับ subsystem-dorm — ปรับ client_id เป็น grade)
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidTokenError as JWTError

from app.config import settings

_JWKS_CACHE_TTL = 600
_jwks_cache: dict = {"data": None, "fetched_at": 0}


def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def build_authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.grade_client_id,
        "redirect_uri": settings.grade_callback_url,
        "state": state,
        "code_challenge": code_challenge,
    }
    return f"{settings.hub_public_url}/oauth/authorize?{urlencode(params)}"


async def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{settings.hub_internal_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.grade_client_id,
                "client_secret": settings.grade_client_secret,
                "code_verifier": code_verifier,
            },
        )
        r.raise_for_status()
        return r.json()


async def notify_hub_logout(hub_user_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(
                f"{settings.hub_internal_url}/oauth/logout",
                data={
                    "client_id": settings.grade_client_id,
                    "client_secret": settings.grade_client_secret,
                    "hub_user_id": hub_user_id,
                },
            )
            return r.status_code == 200
    except Exception:
        return False


async def _fetch_jwks() -> dict:
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
    """ตรวจ JWT ที่ Hub ออก — signature (kid) + iss + aud=client_id ของเรา."""
    jwks = await _fetch_jwks()
    header = pyjwt.get_unverified_header(token)
    kid = header.get("kid")
    matched = next((k for k in jwks["keys"] if k.get("kid") == kid), None)
    if not matched:
        raise JWTError(f"ไม่พบ public key สำหรับ kid={kid}")
    public_key = RSAAlgorithm.from_jwk(json.dumps(matched))
    return pyjwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=settings.jwt_issuer,
        audience=settings.grade_client_id,
        leeway=60,
        options={"verify_aud": True, "verify_iss": True, "verify_exp": True},
    )
