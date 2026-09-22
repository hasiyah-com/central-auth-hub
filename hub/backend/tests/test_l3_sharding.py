"""ส่ง L3 ของผู้ใช้คนหนึ่งไป worker เดิมเสมอ — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate §19.4, 2026-09-22): ml-service 4 worker มี cache โมเดลแยกต่อ process ·
ผู้ใช้คนเดียวได้ `model_warming` สลับกับคะแนนจริงจนกว่าทุก worker จะ fit ครบ และเกิดซ้ำทุก
ชั่วโมงที่ cache หมดอายุ · ข้อมูล shadow จะปนระหว่าง "L3 ดูแล้ว" กับ "L3 ยังไม่พร้อม"

ทางแก้ที่เลือก: แต่ละ worker มีพอร์ตเฉพาะสำหรับ L3 · hub เลือกพอร์ตจาก hash ของ user_id →
ผู้ใช้คนหนึ่งไป worker เดิมเสมอ (fit ครั้งเดียวต่อคน ไม่ใช่ต่อ worker)

ข้อกำหนด:
  - hash ต้องคงที่ข้าม process และข้ามการ restart — **ห้ามใช้ `hash()` ของ Python**
    (สุ่มค่าใหม่ทุก process ตาม PYTHONHASHSEED) · ใช้ sha256
  - ไม่ตั้ง `L3_SHARD_URLS` = พฤติกรรมเดิม (ใช้ `ml_service_url`)
  - shard ที่ล่มต้องไม่ทำให้ login ล้ม — คืน quiet พร้อม error (fail-safe ตาม B21)
  - URL ผิดรูป = ไม่ start
"""

from __future__ import annotations

import hashlib

import pytest

from app.config import Settings, settings
from app.services import l3_sequence_client as C

URLS = "http://ml-service:9100,http://ml-service:9101,http://ml-service:9102,http://ml-service:9103"


def _expected(uid: str, n: int) -> int:
    return int.from_bytes(hashlib.sha256(uid.encode("utf-8")).digest()[:8], "big") % n


# ── การเลือก shard ───────────────────────────────────────────────────────


@pytest.mark.parametrize("uid", ["u1", "3f2b8c1e-0000-4000-8000-000000000001", "ผู้ใช้"])
def test_shard_index_is_sha256_based(uid):
    """ค่าคงที่ข้าม process — คำนวณซ้ำจาก sha256 โดยตรงต้องได้เท่ากัน."""
    assert C.shard_index(uid, 4) == _expected(uid, 4)


def test_shard_index_is_spread_evenly():
    counts = [0, 0, 0, 0]
    for i in range(10_000):
        counts[C.shard_index(f"user-{i}", 4)] += 1
    assert all(2_200 <= c <= 2_800 for c in counts), counts


def test_single_shard_always_zero():
    assert C.shard_index("anyone", 1) == 0


def test_without_shards_the_base_url_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "l3_shard_urls", "")
    assert C.l3_base_url("u1") == settings.ml_service_url


def test_with_shards_the_same_user_always_gets_the_same_worker(monkeypatch):
    monkeypatch.setattr(settings, "l3_shard_urls", URLS)
    urls = URLS.split(",")
    for uid in ("a", "b", "c", "d", "e"):
        first = C.l3_base_url(uid)
        assert first == urls[_expected(uid, 4)]
        assert all(C.l3_base_url(uid) == first for _ in range(20))


# ── เส้นทางจริงของ client ───────────────────────────────────────────────


class _FakeClient:
    posted: list[str] = []
    fail = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        import httpx

        _FakeClient.posted.append(url)
        if _FakeClient.fail:
            raise httpx.ConnectError("worker ล่ม")
        req = httpx.Request("POST", url)
        return httpx.Response(
            200, json={"data": {"sequence": {}, "point": {}}}, request=req
        )


@pytest.fixture
def fake_http(monkeypatch):
    _FakeClient.posted = []
    _FakeClient.fail = False
    monkeypatch.setattr(C.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "l3_shard_urls", URLS)
    return _FakeClient


@pytest.mark.asyncio
async def test_evaluate_l3_goes_to_the_users_shard(fake_http):
    await C.evaluate_l3("u1", [0.0] * 23, [0.1] * C.DIMS, "allow")
    assert fake_http.posted == [URLS.split(",")[_expected("u1", 4)] + "/v1/l3-evaluate"]


@pytest.mark.asyncio
async def test_sequence_score_goes_to_the_users_shard(fake_http):
    await C.get_sequence_score("u2", [0.1] * C.DIMS)
    assert fake_http.posted == [
        URLS.split(",")[_expected("u2", 4)] + "/v1/sequence-score"
    ]


@pytest.mark.asyncio
async def test_a_dead_shard_is_fail_safe(fake_http):
    fake_http.fail = True
    out = await C.evaluate_l3("u1", [0.0] * 23, [0.1] * C.DIMS, "allow")
    assert out["error"].startswith("l3_unreachable")
    assert out["sequence"]["fired"] is False


# ── คอนฟิก ───────────────────────────────────────────────────────────────


def test_default_has_no_shards():
    """ค่าเริ่มต้นของฟิลด์ (ไม่อ่าน env) ต้องว่าง = พฤติกรรมเดิม."""
    assert Settings.model_fields["l3_shard_urls"].default == ""


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://ml-service:9100",
        "ml-service:9100",
        "http://ml-service:9100,,http://ml-service:9101",
        "http://ml-service:9100,http://ml-service:9100",  # ซ้ำ = worker เดียวได้งานสองส่วน
    ],
)
def test_malformed_shard_urls_are_refused_at_startup(bad):
    with pytest.raises(Exception, match="l3_shard_urls"):
        Settings(l3_shard_urls=bad)


def test_spaces_are_tolerated():
    s = Settings(l3_shard_urls=" http://ml-service:9100 , http://ml-service:9101 ")
    assert C.parse_shard_urls(s.l3_shard_urls) == [
        "http://ml-service:9100",
        "http://ml-service:9101",
    ]
