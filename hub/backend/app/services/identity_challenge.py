"""Identity Challenge — บังคับ user ยืนยันตัวตนผ่าน email ก่อน login ใหม่.

ใช้ตอน admin กด Revoke Level 2 (Challenge) — user คนนั้น login ใหม่ไม่ได้
จนกว่าจะคลิกลิงก์ confirm ใน email

Redis schema:
  identity_challenge:user:{user_id}        → "1"  (มี active challenge)
  identity_challenge:token:{token_hash}    → user_id

Verify flow:
  user คลิก link → /auth/confirm-identity?token=xxx
    → look up token_hash → ได้ user_id
    → ลบทั้ง 2 keys
    → user login ได้ปกติ

Security:
  - token = secrets.token_urlsafe(32) — 256-bit random
  - DB ไม่เก็บ plaintext — เก็บ HMAC(token) ผ่าน hash_retrieval_token
  - ทุก key มี TTL = CHALLENGE_TTL_MIN
  - user_id-based key เพื่อ check is_challenged() ใน O(1)
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.redis_client import redis_client
from app.services.secret_service import hash_retrieval_token

log = logging.getLogger(__name__)

CHALLENGE_TTL_MIN = 15  # นาที — เหมือน secret retrieval link

_USER_KEY_PREFIX = "identity_challenge:user:"
_TOKEN_KEY_PREFIX = "identity_challenge:token:"


def _user_key(user_id: str) -> str:
    return f"{_USER_KEY_PREFIX}{user_id}"


def _token_key(token_hash: str) -> str:
    return f"{_TOKEN_KEY_PREFIX}{token_hash}"


def create_challenge(
    user_id: str, reason: str = "admin_revoked"
) -> tuple[str, datetime]:
    """สร้าง challenge token ใหม่ + เก็บใน Redis. คืน (plaintext_token, expires_at).

    Args:
        user_id: Hub user id
        reason: short label เก็บ metadata (ไม่ verify) — ใช้ใน audit
    """
    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_retrieval_token(plaintext)
    ttl = CHALLENGE_TTL_MIN * 60
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_TTL_MIN)

    try:
        # user → marker (สำหรับ check ใน /oauth/authorize)
        redis_client.set(_user_key(user_id), reason, ex=ttl)
        # token_hash → user_id (สำหรับ verify ผ่าน link)
        redis_client.set(_token_key(token_hash), user_id, ex=ttl)
    except Exception as e:
        log.error("identity_challenge redis store failed: %r", e)
        raise

    return plaintext, expires_at


def is_user_challenged(user_id: str) -> bool:
    """user คนนี้มี pending challenge ไหม."""
    try:
        return redis_client.exists(_user_key(user_id)) == 1
    except Exception as e:
        # fail-open: ถ้า Redis ล่ม ปล่อยให้ login ผ่าน (กัน Hub fail ทั้งระบบ)
        log.warning("identity_challenge redis check failed (fail-open): %r", e)
        return False


def verify_and_clear(plaintext_token: str) -> str | None:
    """Verify token → ลบ challenge ถ้า valid.

    Returns user_id ถ้า success, None ถ้า token หมดอายุ/ไม่มี
    """
    if not plaintext_token:
        return None
    token_hash = hash_retrieval_token(plaintext_token)
    try:
        user_id = redis_client.getdel(_token_key(token_hash))
        if not user_id:
            return None
        # ลบ user marker ด้วย
        redis_client.delete(_user_key(user_id))
        return user_id
    except Exception as e:
        log.error("identity_challenge verify failed: %r", e)
        return None


def clear_for_user(user_id: str) -> bool:
    """ลบ challenge ของ user (สำหรับ admin force unblock).

    หา token key ก่อนลบทั้งคู่ — ใช้ pattern scan
    """
    try:
        # ลบ user marker ก่อน
        deleted_user = redis_client.delete(_user_key(user_id))
        # หา token keys ที่ map ไป user_id นี้ → ลบ
        # (เราไม่รู้ token_hash โดยตรง — scan)
        for key in redis_client.scan_iter(f"{_TOKEN_KEY_PREFIX}*"):
            val = redis_client.get(key)
            if val == user_id:
                redis_client.delete(key)
        return bool(deleted_user)
    except Exception as e:
        log.error("identity_challenge clear_for_user failed: %r", e)
        return False
