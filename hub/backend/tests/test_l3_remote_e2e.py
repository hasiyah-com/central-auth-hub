"""L3 sequence — integration จริงข้าม container (hub -> Redis -> ml-service).

พิสูจน์ว่าสถาปัตยกรรมที่แยก numeric core ออกไป ทำงานครบวงจรจริง:

    hub          residual_raw() (pure python)  ->  record_residual() เขียน Redis
    ml-service   อ่าน Redis -> fit IForest รายคน -> score window -> คืน contract
    hub          result_from_payload() -> apply_channel() -> to_contract()

ทดสอบด้วยของจริงทั้งหมด (ไม่ mock) — skip เองถ้า Redis/ml-service ไม่พร้อม

Run: docker compose exec hub-backend pytest tests/test_l3_remote_e2e.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from app.security import l3_sequence as L3
from app.services.l3_sequence_client import get_sequence_score

USER = "pytest-l3-e2e"
KEY = L3._REDIS_KEY.format(user_id=USER)


async def _ok(uid: str, resid: list[float], tries: int = 4) -> dict:
    """เรียกจนสำเร็จ — call แรกที่ cache ยังเย็นอาจ timeout ตามที่ออกแบบไว้ (B63).

    ไม่ใช่การกลบปัญหา: พฤติกรรมจริงคือ login แรกหลัง cache miss จะ abstain
    แล้ว login ถัดไปได้ผลจาก cache — ที่นี่จำลองพฤติกรรมนั้นก่อนค่อยตรวจผล
    """
    for i in range(tries):
        out = await get_sequence_score(uid, resid)
        if out["error"] is None:
            return out
        assert out["error"] == "l3_timeout", f"ml-service ไม่พร้อม: {out['error']}"
        await asyncio.sleep(0.5 * (i + 1))
    raise AssertionError(f"ml-service ยัง warm ไม่เสร็จหลัง {tries} ครั้ง")


def _redis():
    try:
        from app.redis_client import redis_client

        redis_client.ping()
        return redis_client
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture
def seeded():
    """เขียน residual ปกติ 1500 แถวผ่าน record_residual() ของ hub เอง (ผ่าน tier warn)."""
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    r.delete(KEY)
    rng = random.Random(42)
    for _ in range(L3.TIER_WARN + 500):
        L3.record_residual(
            r,
            USER,
            [
                rng.gauss(4.0, 0.6),  # gap_log
                rng.gauss(0.3, 0.05),  # scope
                rng.gauss(3.0, 0.3),  # passkey_age_log
                rng.gauss(0.8, 0.1),  # weekday_usage
                rng.gauss(0.5, 0.4),  # hours_from_typical
                rng.gauss(0.2, 0.05),  # sub_rarity
            ],
        )
    yield r
    r.delete(KEY)


def test_record_residual_writes_redis(seeded):
    """hub เขียน history ได้ และ trim ตาม MAX_HISTORY."""
    n = seeded.llen(KEY)
    assert n == L3.TIER_WARN + 500
    assert len(json.loads(seeded.lindex(KEY, 0))) == L3.DIMS


@pytest.mark.asyncio
async def test_normal_residual_does_not_fire(seeded):
    """login ปกติ (ใกล้ค่ากลางของคนนี้) -> ไม่ยิง แต่ต้องได้ eligibility=warn จริง."""
    out = await _ok(USER, [4.0, 0.3, 3.0, 0.8, 0.5, 0.2])
    assert out["eligibility"] == "warn"
    assert out["n_history"] >= L3.TIER_WARN
    assert out["fired"] is False


@pytest.mark.asyncio
async def test_extreme_drift_fires_and_raises_to_warn(seeded):
    """residual เบี่ยงหลายมิติพร้อมกัน -> ยิง + channel ยก allow เป็น warn (ไม่เกิน warn)."""
    out = await _ok(USER, [12.0, 1.0, 8.0, 0.0, 9.0, 0.99])
    res = L3.result_from_payload(out)
    print(f"\n  raw={res.raw_score:.3f} pct={res.percentile:.3f} tier={res.tier}")
    assert res.fired is True
    assert res.reason == L3.REASON
    assert L3.apply_channel("allow", res) == "warn"
    # ห้ามลด friction ที่ L1/L2 ตั้งไว้แล้ว และห้ามยกเกิน warn
    assert L3.apply_channel("challenge", res) == "challenge"
    assert L3.apply_channel("block", res) == "block"


@pytest.mark.asyncio
async def test_contract_complete_for_replay(seeded):
    """contract ที่ลง risk_breakdown ต้องครบ + JSON ได้ + n_history ไม่เป็น 0."""
    out = await _ok(USER, [12.0, 1.0, 8.0, 0.0, 9.0, 0.99])
    c = L3.to_contract(L3.result_from_payload(out), None)
    json.dumps(c)
    assert c["eligible"] is True
    assert c["n_history"] >= L3.TIER_WARN
    assert c["model_version"] == L3.MODEL_VERSION
    assert c["decision"] in ("would_warn", "would_challenge", None)


@pytest.mark.asyncio
async def test_abstain_for_fresh_user():
    """ผู้ใช้ไม่มี history -> abstain (ไม่ยิง ไม่เปลี่ยน decision)."""
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    r.delete(L3._REDIS_KEY.format(user_id="pytest-l3-fresh"))
    out = await _ok("pytest-l3-fresh", [0.0] * L3.DIMS)
    assert out["eligibility"] == "abstain"
    assert out["fired"] is False
    assert L3.apply_channel("allow", L3.result_from_payload(out)) == "allow"
