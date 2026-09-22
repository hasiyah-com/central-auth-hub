"""L3 ช่วงโมเดลยังไม่พร้อม — integration จริง hub -> Redis -> ml-service (ไม่ mock).

ที่มา (ML Capacity Gate §15–18, 2026-09-22): ml-service ย้าย fit ออกจากเส้นทาง request ·
ผู้ใช้ที่ยังไม่มีโมเดลได้ `abstain` + `abstain_reason = "model_warming"` ภายในงบรอ (50 ms) แทนการ
รอ fit จน hub timeout · สัญญาใหม่ที่ต้องพิสูจน์บนเส้นทางจริง (บทเรียน B61):

  1. request แรกของผู้ใช้ใหม่ **ไม่ใช่ error** และบอกเหตุผลว่า model_warming (ไม่ใช่ l3_timeout)
  2. ตอบเร็ว — ไม่รอ fit จนเสร็จ
  3. หลัง fit เสร็จ request ถัดไปได้คะแนนจริง (eligibility ตาม tier ของประวัติ)

ใช้ ml-service ของชุดเทส (worker เดียว) · ผู้ใช้ไม่ซ้ำกันทุกรอบ จึงไม่มี cache ค้างจากรอบก่อน
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid

import pytest

from app.security import l3_sequence as L3
from app.services.l3_sequence_client import get_sequence_score

N_HISTORY = L3.TIER_CHALLENGE  # 2000 แถว — fit ใช้ ~165 ms เกินงบ 50 ms แน่นอน
RESID = [4.0, 0.3, 3.0, 0.8, 0.5, 0.2]


def _redis():
    try:
        from app.redis_client import redis_client

        redis_client.ping()
        return redis_client
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture
def fresh_user():
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    uid = f"pytest-l3-warming-{uuid.uuid4().hex[:10]}"
    rng = random.Random(7)
    for _ in range(N_HISTORY):
        L3.record_residual(
            r,
            uid,
            [
                rng.gauss(4.0, 0.6),
                rng.gauss(0.3, 0.05),
                rng.gauss(3.0, 0.3),
                rng.gauss(0.8, 0.1),
                rng.gauss(0.5, 0.4),
                rng.gauss(0.2, 0.05),
            ],
        )
    yield uid
    r.delete(f"l3resid:{uid}")


@pytest.mark.asyncio
async def test_first_request_of_a_new_user_is_model_warming(fresh_user):
    t0 = time.perf_counter()
    out = await get_sequence_score(fresh_user, RESID)
    took_ms = (time.perf_counter() - t0) * 1000
    assert out["error"] is None, out["error"]  # ไม่ใช่ l3_timeout แบบเดิม
    assert out["eligibility"] == "abstain"
    assert out["abstain_reason"] == "model_warming"
    assert out["fired"] is False
    # งบรอ 50 ms + HTTP — เผื่อเครื่องช้าไว้มาก แต่ต้องต่ำกว่าเพดาน L3 ของ login (500 ms)
    assert took_ms < 400, f"ตอบช้าเกินไปสำหรับ model_warming: {took_ms:.0f} ms"


@pytest.mark.asyncio
async def test_after_warming_the_user_gets_a_real_score(fresh_user):
    first = await get_sequence_score(fresh_user, RESID)
    assert first["abstain_reason"] == "model_warming"
    for i in range(10):
        await asyncio.sleep(0.3 * (i + 1))
        out = await get_sequence_score(fresh_user, RESID)
        if out.get("abstain_reason") != "model_warming":
            break
    assert out["error"] is None
    assert out["abstain_reason"] is None
    assert out["eligibility"] == L3.eligibility(N_HISTORY)
    assert out["n_history"] == N_HISTORY
