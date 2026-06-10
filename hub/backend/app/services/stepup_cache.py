"""Step-up authentication trusted-session cache (Plan v3, Improvement #2).

หลัง user ผ่าน step-up (Passkey verify หรือ OTP verify) → set Redis key
แสดงว่า session นี้ "trusted" ใน window TTL — critical action ในช่วงนั้น
จะ bypass ไม่ต้อง prompt step-up ซ้ำ.

ใช้คู่กับ ``critical_action_policy.gate(...)`` ที่ check key นี้ก่อน raise 403.

Redis key shape:
    stepup:granted:{user_id}:{jti}  →  JSON({granted_at, method, ip})

TTL ใน settings.stepup_cache_ttl_sec (default 900s = 15 นาที).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.config import settings
from app.redis_client import redis_client

log = logging.getLogger(__name__)

_KEY_PREFIX = "stepup:granted"


def _key(user_id: str, jti: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}:{jti}"


def set_granted(
    user_id: str,
    jti: str,
    method: str,
    ip: str | None = None,
    ttl_sec: int | None = None,
) -> None:
    """Mark session jti as trusted after successful step-up.

    Args:
        user_id: User UUID as str
        jti: JWT id (uniquely identifies the current session token)
        method: "passkey" | "otp" — what authenticator was used
        ip: client IP for audit (use ``get_client_ip(request)`` — B20)
        ttl_sec: override default TTL (else uses settings.stepup_cache_ttl_sec)
    """
    if not user_id or not jti:
        log.warning("stepup_cache.set_granted called with empty user_id or jti")
        return
    if method not in ("passkey", "otp"):
        log.warning("stepup_cache.set_granted unknown method=%r", method)
    ttl = ttl_sec if ttl_sec is not None else settings.stepup_cache_ttl_sec
    payload = json.dumps(
        {
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "ip": ip,
        }
    )
    redis_client.setex(_key(user_id, jti), ttl, payload)


def check_cached(user_id: str, jti: str) -> dict | None:
    """Return cached step-up grant payload (dict) or None if expired/missing.

    Caller (critical_action_policy.gate) uses truthy check to bypass step-up.
    """
    if not user_id or not jti:
        return None
    raw = redis_client.get(_key(user_id, jti))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        log.warning("stepup_cache.check_cached malformed payload for %s", user_id)
        return None


def clear(user_id: str, jti: str) -> None:
    """Force-clear the step-up grant (e.g. on logout or password change)."""
    if not user_id or not jti:
        return
    redis_client.delete(_key(user_id, jti))


def clear_all_for_user(user_id: str) -> int:
    """Clear every step-up grant for a user (admin force-revoke).

    Returns count of keys deleted. SCAN-based (safe vs KEYS).
    """
    if not user_id:
        return 0
    pattern = f"{_KEY_PREFIX}:{user_id}:*"
    deleted = 0
    for key in redis_client.scan_iter(match=pattern, count=100):
        redis_client.delete(key)
        deleted += 1
    return deleted
