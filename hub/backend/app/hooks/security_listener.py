"""นับ failed_login per-IP (proto rate limit — log เตือนเท่านั้น ยังไม่ block).

Threshold: 5 failures / 5 minutes per IP → log warning + เก็บ flag
ใน production จริงควรย้ายไป Redis (กระจาย instance) — รอบนี้ใช้ memory
"""
import logging
import time
from collections import defaultdict, deque

from app.services.hooks import (
    EVT_LOGIN_FAILURE,
    EVT_OAUTH_FAILURE,
    register,
)

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 5
WINDOW_SECONDS = 5 * 60

# ip -> deque[timestamp]
_failures: dict[str, deque] = defaultdict(deque)
flagged_ips: set[str] = set()


def _track_failure(payload: dict) -> None:
    ip = payload.get("ip")
    if not ip:
        return

    now = time.time()
    bucket = _failures[ip]
    bucket.append(now)

    # ตัด entries เก่ากว่า WINDOW_SECONDS ออก
    cutoff = now - WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= FAILURE_THRESHOLD and ip not in flagged_ips:
        flagged_ips.add(ip)
        logger.warning(
            "[security] IP %s reached %d failed logins in %ds — flagged",
            ip, len(bucket), WINDOW_SECONDS,
        )


def register_listeners() -> None:
    register(EVT_LOGIN_FAILURE, _track_failure)
    register(EVT_OAUTH_FAILURE, _track_failure)


def is_flagged(ip: str) -> bool:
    """สำหรับ middleware/router ใช้เช็ค IP ที่ flag ไว้ (Week 9+ rate limit จริง)."""
    return ip in flagged_ips
