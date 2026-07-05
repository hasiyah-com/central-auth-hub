"""Refresh Token service — rotating opaque token คู่กับ short-lived access token.

Design (Hub-direct login เท่านั้น — subsystem ใช้ itsdangerous cookie ของตัวเอง):
  - Token รูปแบบ "{refresh_id}.{secret}" — refresh_id ไม่ใช่ความลับ (ใช้ lookup Redis
    เร็วโดยไม่ต้อง scan), secret คือส่วนที่พิสูจน์ตัวตนจริง
  - Redis เก็บแค่ HMAC-SHA256 ของ secret (ไม่เก็บ plaintext) — เทียบด้วย
    hmac.compare_digest กัน timing attack (B3)
  - rotate() ใช้ redis GETDEL แบบ atomic (B9) → token เดิม "single-use":
    ใช้ซ้ำ (replay) ไม่ได้ ไม่ว่าจะ concurrent request กี่ตัวก็ตาม
  - Caller (routers/auth.py, routers/passkey.py) ผูก refresh_id เข้ากับ
    LoginSession.refresh_id เพื่อให้ logout/force-revoke เรียก revoke() ได้ตรง entry
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from typing import TypedDict

from app.config import settings
from app.redis_client import redis_client

log = logging.getLogger(__name__)

_PREFIX = "refresh:"
_SECRET_BYTES = 32  # secrets.token_urlsafe(32) → 43 chars, 256-bit entropy


class RotateResult(TypedDict):
    user_id: str
    session_id: str
    refresh_id: str
    raw_token: str


def _redis_key(refresh_id: str) -> str:
    return f"{_PREFIX}{refresh_id}"


def _hash_secret(secret: str) -> str:
    """HMAC-SHA256 ของ secret — เก็บค่านี้ใน Redis แทน plaintext (เหมือน secret_service.hash_retrieval_token)."""
    mac = hmac.new(
        settings.secret_key.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256
    )
    return mac.hexdigest()


def _ttl_seconds() -> int:
    return settings.jwt_refresh_token_expire_days * 86400


def issue(*, user_id: str, session_id: str) -> tuple[str, str]:
    """ออก refresh token ใหม่ ผูกกับ user + LoginSession.

    Returns (raw_token, refresh_id) — caller เก็บ refresh_id ไว้ใน
    LoginSession.refresh_id (สำหรับ revoke ทีหลัง), ส่ง raw_token กลับไปให้ client
    """
    refresh_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    raw_token = f"{refresh_id}.{secret}"
    try:
        redis_client.hset(
            _redis_key(refresh_id),
            mapping={
                "user_id": user_id,
                "session_id": session_id,
                "secret_hash": _hash_secret(secret),
            },
        )
        redis_client.expire(_redis_key(refresh_id), _ttl_seconds())
    except Exception as e:
        log.warning("refresh_token issue redis failed: %r", e)
    return raw_token, refresh_id


def rotate(raw_token: str) -> RotateResult | None:
    """ใช้ refresh token ปัจจุบัน → ออกตัวใหม่ (rotation) + invalidate ตัวเดิมทันที.

    ลำดับสำคัญ — เช็ค secret ก่อน consume เสมอ:
      1. อ่าน entry (ไม่ลบ) → เทียบ secret ด้วย hmac.compare_digest (B3)
      2. secret ผิด → return None **โดยไม่ลบ** entry (กัน DoS: attacker เดา secret
         ผิดแต่รู้ refresh_id จริง ไม่ควรทำให้ token ของเจ้าของตัวจริงใช้ไม่ได้)
      3. secret ถูก → ค่อย DELETE (atomic — Redis DEL คืนจำนวนที่ลบได้จริง)
         ถ้า concurrent request อีกตัวชิง DELETE ไปก่อนแล้ว (คืน 0) → แพ้ race,
         ถือว่า invalid (กัน token เดิม rotate ซ้ำสองครั้งพร้อมกัน)
    """
    if not raw_token or "." not in raw_token:
        return None
    refresh_id, _, secret = raw_token.partition(".")
    if not refresh_id or not secret:
        return None

    key = _redis_key(refresh_id)
    try:
        data = redis_client.hgetall(key)
    except Exception as e:
        log.warning("refresh_token rotate redis read failed: %r", e)
        return None
    if not data:
        return None

    stored_hash = data.get("secret_hash", "")
    if not stored_hash or not hmac.compare_digest(stored_hash, _hash_secret(secret)):
        return None

    try:
        deleted = redis_client.delete(key)
    except Exception as e:
        log.warning("refresh_token rotate redis delete failed: %r", e)
        return None
    if not deleted:
        return None  # แพ้ race ให้ request อื่นไปแล้ว

    user_id = data.get("user_id", "")
    session_id = data.get("session_id", "")
    new_raw, new_refresh_id = issue(user_id=user_id, session_id=session_id)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "refresh_id": new_refresh_id,
        "raw_token": new_raw,
    }


def revoke(refresh_id: str) -> None:
    """เพิกถอน refresh token ทันที (logout / force-revoke) — idempotent."""
    if not refresh_id:
        return
    try:
        redis_client.delete(_redis_key(refresh_id))
    except Exception as e:
        log.warning("refresh_token revoke redis failed: %r", e)


def revoke_raw(raw_token: str) -> None:
    """แบบสะดวก — เพิกถอนจาก raw token ตรงๆ (parse refresh_id ให้)."""
    if not raw_token or "." not in raw_token:
        return
    refresh_id, _, _secret = raw_token.partition(".")
    revoke(refresh_id)
