"""Centralized slowapi limiter — แยก module กัน circular import.

Routers import `limiter` ตัวนี้ + ใช้ `@limiter.limit(...)` decorate endpoint
main.py register `limiter` เข้า app.state + add middleware
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.deps import get_client_ip


def _client_ip_for_limiter(request: Request) -> str:
    """อ่าน X-Forwarded-For ผ่าน get_client_ip — กัน Docker IP 172.x
    ทำให้ทุก request ดูเหมือนมาจาก IP เดียว (กลายเป็น DoS-ของตัวเอง).
    """
    try:
        return get_client_ip(request) or get_remote_address(request)
    except Exception:
        return get_remote_address(request)


limiter = Limiter(key_func=_client_ip_for_limiter, default_limits=["300/minute"])
