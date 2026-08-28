"""Health history — เก็บจุดข้อมูล latency ย้อนหลังไว้วาดกราฟ.

health loop ping ทุก 5 นาที → push ลง Redis list (trim 288 จุด ≈ 24 ชม.)
endpoint /admin/subsystems/{id}/health-history คืนจุดเหล่านั้น + สรุป

รัน:
    docker compose exec hub-backend pytest tests/test_health_history.py -v
"""

from __future__ import annotations

import json

from app.services import subsystem_health as sh


class _FakePipe:
    """จำลอง redis pipeline — เก็บคำสั่งไว้ใน store ตอน execute()."""

    def __init__(self, store: dict):
        self.store = store
        self.ops: list = []

    def rpush(self, key, val):
        self.ops.append(("rpush", key, val))
        return self

    def ltrim(self, key, start, end):
        self.ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op in self.ops:
            if op[0] == "rpush":
                self.store.setdefault(op[1], []).append(op[2])
            elif op[0] == "ltrim":
                _, key, start, end = op
                lst = self.store.get(key, [])
                self.store[key] = lst[start:] if end == -1 else lst[start : end + 1]
        self.ops = []


def _fake_redis(monkeypatch) -> dict:
    store: dict[str, list] = {}
    monkeypatch.setattr(
        sh.redis_client, "pipeline", lambda: _FakePipe(store), raising=False
    )

    def lrange(key, start, end):
        lst = store.get(key, [])
        return lst[start:] if end == -1 else lst[start : end + 1]

    monkeypatch.setattr(sh.redis_client, "lrange", lrange, raising=False)
    return store


def test_append_and_read_history(monkeypatch):
    _fake_redis(monkeypatch)
    sh._append_history(
        "sub-1",
        {"status": "healthy", "latency_ms": 42, "checked_at": "2026-08-21T10:00:00"},
    )
    sh._append_history(
        "sub-1",
        {"status": "degraded", "latency_ms": 900, "checked_at": "2026-08-21T10:05:00"},
    )
    hist = sh.get_history("sub-1")
    assert [p["latency_ms"] for p in hist] == [42, 900]
    assert hist[-1]["status"] == "degraded"


def test_history_trimmed_to_max(monkeypatch):
    _fake_redis(monkeypatch)
    for i in range(sh.HEALTH_HISTORY_MAX + 20):
        sh._append_history(
            "sub-2", {"status": "healthy", "latency_ms": i, "checked_at": f"t{i}"}
        )
    hist = sh.get_history("sub-2")
    assert len(hist) == sh.HEALTH_HISTORY_MAX
    # เก็บจุดล่าสุดไว้ (เก่าสุดถูก trim ทิ้ง)
    assert hist[-1]["latency_ms"] == sh.HEALTH_HISTORY_MAX + 19


def test_history_stores_only_graph_fields(monkeypatch):
    store = _fake_redis(monkeypatch)
    sh._append_history(
        "sub-3",
        {
            "status": "healthy",
            "latency_ms": 12,
            "checked_at": "2026-08-21T11:00:00",
            "url": "https://x/health",
            "error": None,
            "components": {"db": "ok"},
        },
    )
    point = json.loads(store[sh._history_key("sub-3")][0])
    assert set(point.keys()) == {"at", "status", "latency_ms"}


def test_append_history_is_fail_safe(monkeypatch):
    """Redis ล่ม → ต้องไม่ raise (B21) ไม่งั้น health loop พังทั้งรอบ."""

    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(sh.redis_client, "pipeline", boom, raising=False)
    sh._append_history("sub-4", {"status": "healthy", "latency_ms": 1})  # ต้องไม่ระเบิด


def test_get_history_returns_empty_on_redis_error(monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(sh.redis_client, "lrange", boom, raising=False)
    assert sh.get_history("sub-5") == []


def test_get_history_skips_corrupt_entries(monkeypatch):
    store = _fake_redis(monkeypatch)
    store[sh._history_key("sub-6")] = [
        json.dumps({"at": "t1", "status": "healthy", "latency_ms": 10}),
        "{not-json",
        json.dumps({"at": "t2", "status": "down", "latency_ms": None}),
    ]
    hist = sh.get_history("sub-6")
    assert len(hist) == 2
    assert hist[0]["latency_ms"] == 10


def test_history_endpoint_requires_admin(client, teacher_token, auth_headers):
    import uuid

    r = client.get(
        f"/admin/subsystems/{uuid.uuid4()}/health-history",
        headers=auth_headers(teacher_token),
    )
    assert r.status_code == 403
