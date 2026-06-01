"""Tests for slowapi rate limiting."""

import pytest


@pytest.mark.slow
def test_login_rate_limit_429_after_threshold(client):
    """ส่ง > rate_limit_login (default 10/min) → ครั้งที่เกินได้ 429."""
    # ใช้ /auth/google/login ที่ rate-limited
    # ยิงเร็ว ๆ 15 ครั้ง — บางครั้งต้องเด้ง 429
    statuses = []
    for _ in range(15):
        r = client.get("/auth/google/login", follow_redirects=False)
        statuses.append(r.status_code)

    # ต้องมีอย่างน้อย 1 ครั้งที่ได้ 429
    assert 429 in statuses, (
        f"Rate limit ไม่ทำงาน — เห็น statuses: {set(statuses)} "
        "(คาดว่าจะมี 429 หลังเกิน 10 ครั้ง/นาที)"
    )


@pytest.mark.smoke
def test_rate_limit_only_blocks_specific_endpoints(client):
    """Endpoints ที่ไม่ rate-limited (เช่น /health) ยิงรัวได้ไม่ block."""
    for _ in range(30):
        r = client.get("/health")
        assert r.status_code == 200, "/health ไม่ควรมี rate limit"
