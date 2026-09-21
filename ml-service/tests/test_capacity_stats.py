"""ตัวนับสำหรับ ML Capacity Gate — เขียนก่อน implementation (RED).

ที่มา: ต้องตอบให้ได้ว่าเมื่อรันหลาย worker แล้ว (1) fit ซ้ำต่อคนกี่ครั้ง (fit storm)
(2) cache โตเท่าไร (3) หน่วยความจำรั่วไหม · cache และ lock ของ L3 อยู่ในหน่วยความจำ
ของแต่ละ process (`_MODEL_CACHE`, `_LOCKS`) — worker 4 ตัวจึงมีสี่ชุดแยกกัน

การนับจากภายนอก (เช่น Redis MONITOR) แยกไม่ได้ว่า request ไหน fit จริงและตัวไหนแค่รอ
ล็อกแล้วเจอ cache · จึงนับที่จุด fit โดยตรง

**ขอบเขตความเป็นส่วนตัว:** สถิติคืนเฉพาะจำนวน ไม่คืน user id · endpoint ปิดไว้เป็นค่า
เริ่มต้น เปิดด้วย `L3_CAPACITY_STATS=1` เท่านั้น (ml-service ไม่มี auth)

รันบน host: `cd ml-service && python -m pytest tests/test_capacity_stats.py -q`
"""

from __future__ import annotations

import json
import random
import threading

import pytest

from app import sequence as SEQ


class FakeRedis:
    """พอสำหรับ sequence.score — llen / lrange บน list ในหน่วยความจำ."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        n = len(items)
        s = start + n if start < 0 else start
        e = end + n if end < 0 else end
        return items[max(s, 0) : e + 1]


def _seed(r: FakeRedis, user: str, n: int, seed: int = 42) -> None:
    rng = random.Random(seed)
    r.lists[SEQ.REDIS_KEY.format(user_id=user)] = [
        json.dumps([rng.gauss(0, 1) for _ in range(SEQ.DIMS)]) for _ in range(n)
    ]


RESID = [0.1] * SEQ.DIMS


@pytest.fixture(autouse=True)
def _clean():
    SEQ.wait_for_background_fits(timeout=30)
    SEQ.reset_capacity_stats()
    SEQ._MODEL_CACHE.clear()
    SEQ._LOCKS.clear()
    yield
    SEQ.reset_capacity_stats()
    SEQ._MODEL_CACHE.clear()
    SEQ._LOCKS.clear()


def test_stats_start_empty():
    s = SEQ.capacity_stats()
    assert s["fits_total"] == 0
    assert s["max_fits_per_user"] == 0
    assert s["cache_entries"] == 0
    assert isinstance(s["pid"], int)


def test_one_fit_is_counted_and_warm_calls_do_not_fit():
    r = FakeRedis()
    _seed(r, "u1", 300)
    SEQ.score(r, "u1", RESID)
    SEQ.score(r, "u1", RESID)
    SEQ.score(r, "u1", RESID)
    assert SEQ.wait_for_background_fits(timeout=30)  # fit อยู่เบื้องหลังแล้ว (§15)
    s = SEQ.capacity_stats()
    assert s["fits_total"] == 1
    assert s["max_fits_per_user"] == 1
    assert s["cache_entries"] == 1


def test_concurrent_cold_requests_fit_once_per_user():
    """ใจกลางของ fit storm — 20 request พร้อมกันบนคนเดียว ต้อง fit ครั้งเดียว (B63)."""
    r = FakeRedis()
    _seed(r, "u1", 500)
    barrier = threading.Barrier(20)

    def go():
        barrier.wait()
        SEQ.score(r, "u1", RESID)

    threads = [threading.Thread(target=go) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert SEQ.wait_for_background_fits(timeout=30)
    s = SEQ.capacity_stats()
    assert s["fits_total"] == 1
    assert s["max_fits_per_user"] == 1


def test_distinct_users_each_fit_once():
    r = FakeRedis()
    for i in range(5):
        _seed(r, f"u{i}", 200, seed=i)
        SEQ.score(r, f"u{i}", RESID)
    assert SEQ.wait_for_background_fits(timeout=30)
    s = SEQ.capacity_stats()
    assert s["fits_total"] == 5
    assert s["max_fits_per_user"] == 1
    assert s["cache_entries"] == 5


def test_abstaining_users_are_not_counted_as_fits():
    r = FakeRedis()
    _seed(r, "new", 10)  # ต่ำกว่า TIER_DIAGNOSTIC — abstain ก่อนถึง fit
    SEQ.score(r, "new", RESID)
    assert SEQ.capacity_stats()["fits_total"] == 0


def test_stats_carry_no_user_identifiers():
    r = FakeRedis()
    _seed(r, "secret-user-id-b7", 200)
    SEQ.score(r, "secret-user-id-b7", RESID)
    assert SEQ.wait_for_background_fits(timeout=30)
    assert "secret-user-id-b7" not in json.dumps(SEQ.capacity_stats())


def test_stats_report_resident_memory():
    rss = SEQ.capacity_stats()["rss_kb"]
    assert rss is None or rss > 0  # None บนระบบที่ไม่มี /proc (Windows host)


# ── endpoint ─────────────────────────────────────────────────────────────


def _client(monkeypatch, enabled: bool):
    fastapi = pytest.importorskip("fastapi.testclient")
    if enabled:
        monkeypatch.setenv("L3_CAPACITY_STATS", "1")
    else:
        monkeypatch.delenv("L3_CAPACITY_STATS", raising=False)
    from app import main

    return fastapi.TestClient(main.app)


def test_endpoint_is_disabled_by_default(monkeypatch):
    assert _client(monkeypatch, False).get("/v1/l3-capacity-stats").status_code == 404


def test_l3_requests_are_counted_per_process(monkeypatch):
    """ใช้พิสูจน์ว่า worker ได้งานเท่ากันไหม (ข้อ 4) — นับที่ endpoint ที่ hub เรียกจริง."""
    client = _client(monkeypatch, True)
    before = client.get("/v1/l3-capacity-stats").json()["data"]["l3_requests"]
    body = {"user_id": "u", "features": [0.0] * 23, "residual": None}
    for _ in range(3):
        client.post("/v1/l3-evaluate", json=body)
    after = client.get("/v1/l3-capacity-stats").json()["data"]["l3_requests"]
    assert after - before == 3


def test_endpoint_returns_stats_when_enabled(monkeypatch):
    r = _client(monkeypatch, True).get("/v1/l3-capacity-stats")
    assert r.status_code == 200
    body = r.json()["data"]
    assert {"pid", "fits_total", "max_fits_per_user", "cache_entries", "rss_kb"} <= set(
        body
    )
