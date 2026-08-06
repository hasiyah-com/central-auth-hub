"""Centralized slowapi limiter — แยก module กัน circular import.

Routers import `limiter` ตัวนี้ + ใช้ `@limiter.limit(...)` decorate endpoint
main.py register `limiter` เข้า app.state + add middleware

Storage: Redis (shared) — rate limit นับรวมข้าม worker/replica (in-memory จะนับแยก
ต่อ process → attacker หมุน worker เลี่ยง limit ได้). Redis เป็น hard dependency
อยู่แล้ว (session/authcode/jti/risk-challenge) — ใช้ตัวเดียวกัน. ถ้าสร้าง storage
ด้วย Redis ไม่ได้ (เช่น dev ที่ไม่ได้เปิด Redis) → fallback in-memory (limiter ยังทำงาน).
"""

import logging

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.deps import get_client_ip

log = logging.getLogger(__name__)


def _client_ip_for_limiter(request: Request) -> str:
    """อ่าน X-Forwarded-For ผ่าน get_client_ip — กัน Docker IP 172.x
    ทำให้ทุก request ดูเหมือนมาจาก IP เดียว (กลายเป็น DoS-ของตัวเอง).
    """
    try:
        return get_client_ip(request) or get_remote_address(request)
    except Exception:
        return get_remote_address(request)


def _build_limiter() -> Limiter:
    """สร้าง Limiter ที่ใช้ Redis storage — fallback in-memory ถ้าเชื่อมต่อไม่ได้."""
    try:
        lim = Limiter(
            key_func=_client_ip_for_limiter,
            default_limits=["300/minute"],
            storage_uri=settings.redis_url,
        )
        # ตรวจว่า storage เชื่อมต่อได้จริง (ไม่งั้น error จะโผล่ตอน request แรก)
        lim.limiter.storage.check()
        return lim
    except Exception as e:  # noqa: BLE001 — fallback ให้ limiter ยังทำงาน
        log.warning(
            "rate-limiter: Redis storage ใช้ไม่ได้ (%s) → fallback in-memory "
            "(rate limit นับแยกต่อ worker — ตั้ง REDIS_URL ให้ถูกใน prod)",
            e,
        )
        return Limiter(key_func=_client_ip_for_limiter, default_limits=["300/minute"])


limiter = _build_limiter()
