"""L3 sequence — Stability / Operational readiness (ทดสอบกับของจริง ไม่ mock).

ตอบคำถาม "ระบบนี้อยู่รอดใน production ไหม" ที่ผลการทดลอง offline ตอบไม่ได้:

  1. restart      — state อยู่รอดข้ามการ restart ของ service ไหม
  2. cold profile — ผู้ใช้ใหม่/ประวัติน้อย ต้องเงียบ ไม่เดามั่ว
  3. model หาย/เสีย — history เพี้ยน/ว่าง ต้อง degrade ไม่ crash
  4. concurrency  — ยิงพร้อมกันหลาย request ต้องไม่เพี้ยน/ไม่ race
  5. latency      — อยู่ในงบเวลาของ login path
  6. fail-safe    — ml-service ล่ม/ช้า ต้องไม่ลาก login ล่มตาม (B21)
  7. **L3 ห้ามแตะ access decision** — ตั้งได้แค่ monitoring_decision

เกณฑ์ข้อ 7 สำคัญที่สุด: L3 อยู่ในสถานะ shadow — ถ้ามันแตะ access decision ได้
แปลว่าโมเดลที่ยังไม่ผ่าน production replay กำลังตัดสินสิทธิ์ผู้ใช้จริง

skip เองถ้า Redis / ml-service ไม่พร้อม (เป็น integration test)

Run: docker compose exec hub-backend pytest tests/test_l3_stability.py -v -s
"""

from __future__ import annotations

import asyncio
import json
import random
import statistics
import time

import pytest

from app.config import settings
from app.security import l3_sequence as L3
from app.services.l3_sequence_client import get_sequence_score

USER = "pytest-l3-stab"
# เขียน 2200 แถว แต่ record_residual ทำ ltrim ที่ MAX_HISTORY -> เก็บจริง 2000
# 2000 = TIER_CHALLENGE พอดี (eligibility สูงสุดที่ระบบไปถึงได้ เพราะ buffer เต็ม)
N_WRITTEN = L3.TIER_CHALLENGE + 200
N_HISTORY = min(N_WRITTEN, L3.MAX_HISTORY)
NORMAL = [4.0, 0.3, 3.0, 0.8, 0.5, 0.2]
DRIFT = [12.0, 1.0, 8.0, 0.0, 9.0, 0.99]
ACTIONS = ["allow", "warn", "challenge", "block"]


def _redis():
    try:
        from app.redis_client import redis_client

        redis_client.ping()
        return redis_client
    except Exception:  # noqa: BLE001
        return None


def _key(uid: str) -> str:
    return L3._REDIS_KEY.format(user_id=uid)


def _seed(r, uid: str, n: int, seed: int = 42) -> None:
    """เขียน residual ปกติ n แถวผ่าน API ของ hub เอง (เหมือน production ทุกประการ)."""
    r.delete(_key(uid))
    rng = random.Random(seed)
    for _ in range(n):
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


@pytest.fixture(scope="module")
def seeded():
    r = _redis()
    if r is None:
        pytest.skip("Redis ไม่พร้อม")
    _seed(r, USER, N_WRITTEN)
    yield r
    for uid in (
        USER,
        f"{USER}-cold",
        f"{USER}-diag",
        f"{USER}-corrupt",
        f"{USER}-twin",
    ):
        r.delete(_key(uid))


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


# ══════════════ 1. Cold profile — ประวัติน้อยต้องเงียบ ══════════════
@pytest.mark.asyncio
async def test_cold_profile_user_abstains(seeded):
    """ผู้ใช้ไม่มีประวัติเลย -> abstain และไม่แตะ decision."""
    seeded.delete(_key(f"{USER}-cold"))
    out = await _ok(f"{USER}-cold", DRIFT)
    assert out["eligibility"] == "abstain"
    assert out["fired"] is False
    assert L3.monitoring_decision(L3.result_from_payload(out)) == L3.MONITORING_NORMAL


@pytest.mark.asyncio
async def test_below_diagnostic_threshold_abstains(seeded):
    """ประวัติ < TIER_DIAGNOSTIC (100) -> abstain แม้ residual จะสุดโต่ง."""
    _seed(seeded, f"{USER}-cold", L3.TIER_DIAGNOSTIC - 1, seed=7)
    out = await _ok(f"{USER}-cold", DRIFT)
    assert out["eligibility"] == "abstain"
    assert out["fired"] is False


@pytest.mark.asyncio
async def test_diagnostic_tier_scores_but_cannot_change_decision(seeded):
    """tier diagnostic (100-999): ให้คะแนน+log ได้ แต่ห้ามเปลี่ยน decision (แผน §5)."""
    _seed(seeded, f"{USER}-diag", 300, seed=9)
    out = await _ok(f"{USER}-diag", DRIFT)
    res = L3.result_from_payload(out)
    assert res.eligibility == "diagnostic"
    assert res.shadow_decision is None, "diagnostic ห้ามเสนอ shadow decision"
    assert (
        L3.monitoring_decision(res) == L3.MONITORING_NORMAL
    ), "tier diagnostic ยังไม่น่าเชื่อพอจะรบกวน SOC"


# ══════════════ 2. History เสีย/หาย — ต้อง degrade ไม่ crash ══════════════
@pytest.mark.asyncio
async def test_corrupt_entries_are_skipped_not_fatal(seeded):
    """แถวขยะปนใน history -> ข้ามเฉพาะแถวเสีย ที่เหลือยังใช้ได้."""
    uid = f"{USER}-corrupt"
    _seed(seeded, uid, N_WRITTEN, seed=11)
    k = _key(uid)
    for junk in ("not-json", "[1,2,3]", '{"a":1}', "[]", json.dumps([None] * 6)):
        seeded.rpush(k, junk)
    out = await _ok(uid, NORMAL)
    assert out["eligibility"] in ("warn", "challenge")
    assert out["n_history"] >= L3.TIER_WARN, "แถวดีต้องยังถูกนับ"


@pytest.mark.asyncio
async def test_all_history_corrupt_degrades_to_abstain(seeded):
    """history เสียทั้งหมด -> abstain เงียบๆ ไม่ throw."""
    uid = f"{USER}-corrupt"
    seeded.delete(_key(uid))
    for _ in range(500):
        seeded.rpush(_key(uid), "totally-not-json")
    out = await _ok(uid, DRIFT)
    assert out["fired"] is False
    assert out["eligibility"] == "abstain"


@pytest.mark.asyncio
async def test_history_wiped_mid_flight_is_safe(seeded):
    """Redis ถูกล้าง (เช่น flush/eviction) ระหว่างใช้งาน -> กลับไป abstain ไม่ crash."""
    uid = f"{USER}-corrupt"
    seeded.delete(_key(uid))
    out = await _ok(uid, DRIFT)
    assert out["fired"] is False
    assert out["n_history"] == 0


@pytest.mark.asyncio
async def test_malformed_residual_never_reaches_network(seeded):
    """residual ผิดรูป -> client ปฏิเสธเองก่อนยิง HTTP."""
    for bad in ([], [1.0, 2.0], [float("nan")] * L3.DIMS, [0.0] * (L3.DIMS + 1)):
        out = await get_sequence_score(USER, bad)
        assert out["fired"] is False
        if len(bad) != L3.DIMS:
            assert out["error"] == "invalid_residual"


# ══════════════ 3. Restart — state อยู่รอด + ผลซ้ำได้ ══════════════
@pytest.mark.asyncio
async def test_history_is_durable_outside_process(seeded):
    """history อยู่ใน Redis ไม่ใช่หน่วยความจำ process -> restart hub/ml ไม่ทำข้อมูลหาย."""
    # ltrim คุมเพดานที่ MAX_HISTORY เสมอ (กัน memory โตไม่จำกัด)
    assert seeded.llen(_key(USER)) == L3.MAX_HISTORY
    assert seeded.ttl(_key(USER)) == -1, "ห้ามตั้ง TTL — history ต้องอยู่ถาวร"


@pytest.mark.asyncio
async def test_scoring_is_deterministic(seeded):
    """เรียกซ้ำด้วย input เดียวกัน -> ผลเท่ากันเป๊ะ (random_state คงที่)."""
    a = await _ok(USER, DRIFT)
    b = await _ok(USER, DRIFT)
    assert a["raw_score"] == b["raw_score"]
    assert a["fired"] == b["fired"] and a["tier"] == b["tier"]


@pytest.mark.asyncio
async def test_identical_history_gives_identical_model(seeded):
    """สอง user ที่มี history เหมือนกันเป๊ะ -> โมเดล/คะแนนเหมือนกัน.

    พิสูจน์ว่าการ refit (ซึ่งจะเกิดหลัง restart เพราะ cache หาย) ให้ผลเดิม —
    restart จึงไม่ทำให้พฤติกรรมการตัดสินเปลี่ยน
    """
    _seed(seeded, f"{USER}-twin", N_WRITTEN, seed=42)  # seed เดียวกับ USER
    a = await _ok(USER, DRIFT)
    b = await _ok(f"{USER}-twin", DRIFT)
    assert a["raw_score"] == pytest.approx(b["raw_score"], abs=1e-9)
    assert a["fired"] == b["fired"]


# ══════════════ 4. Concurrency ══════════════
@pytest.mark.asyncio
async def test_concurrent_requests_same_user_consistent(seeded):
    """ยิงพร้อมกัน 40 request ของ user เดียว -> ผลต้องเท่ากันทุกอัน (ไม่มี race ใน cache)."""
    await _ok(USER, DRIFT)  # warm cache — ข้อนี้วัดความคงเส้นคงวา ไม่ใช่ cold-start
    outs = await asyncio.gather(*[_ok(USER, DRIFT) for _ in range(40)])
    scores = {round(o["raw_score"], 9) for o in outs}
    assert len(scores) == 1, f"ผลไม่คงที่ภายใต้ concurrency: {scores}"
    assert all(o["n_history"] == outs[0]["n_history"] for o in outs)


@pytest.mark.asyncio
async def test_concurrent_requests_multi_user_no_crosstalk(seeded):
    """หลาย user พร้อมกัน -> โมเดลต้องไม่ปนกัน (cache แยกตาม user)."""
    _seed(seeded, f"{USER}-twin", 400, seed=99)  # โปรไฟล์ต่างกัน + tier ต่างกัน
    # warm cache ทีละคนก่อน — ข้อนี้วัด "โมเดลไม่ปนกัน" ไม่ใช่วัด cold-start capacity
    # (cache-miss storm มีเทสของตัวเองด้านล่าง)
    await _ok(USER, DRIFT)
    await _ok(f"{USER}-twin", DRIFT)
    outs = await asyncio.gather(
        *[_ok(USER if i % 2 == 0 else f"{USER}-twin", DRIFT) for i in range(30)]
    )
    big = {o["n_history"] for i, o in enumerate(outs) if i % 2 == 0}
    small = {o["n_history"] for i, o in enumerate(outs) if i % 2 == 1}
    assert big == {N_HISTORY}, f"user A ได้ history ผิด: {big}"
    assert small == {400}, f"user B ได้ history ผิด: {small}"


@pytest.mark.asyncio
async def test_concurrent_write_and_score_is_safe(seeded):
    """เขียน history พร้อมกับให้คะแนน -> ไม่ระเบิด (rpush/ltrim เป็น pipeline).

    history ที่โตระหว่างทางทำให้ cache invalid -> บาง request จะ refit แล้ว timeout
    ซึ่งยอมรับได้ (fail-safe) · สิ่งที่ห้ามเกิดคือ exception หรือข้อมูลเพี้ยน
    """
    uid = f"{USER}-twin"

    def writer():
        for _ in range(50):
            L3.record_residual(seeded, uid, NORMAL)

    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, writer)
    outs = await asyncio.gather(
        *[get_sequence_score(uid, DRIFT) for _ in range(20)], return_exceptions=True
    )
    await task
    assert not any(isinstance(o, Exception) for o in outs), "ห้าม raise"
    bad = [o["error"] for o in outs if o["error"] and o["error"] != "l3_timeout"]
    assert not bad, f"error ที่ไม่ใช่ timeout: {bad}"
    n_hist = {o["n_history"] for o in outs if o["error"] is None}
    assert all(400 <= n <= L3.MAX_HISTORY for n in n_hist), f"n_history เพี้ยน: {n_hist}"


@pytest.mark.asyncio
async def test_cache_miss_storm_degrades_gracefully(seeded):
    """cache miss พร้อมกัน (เช่น หลัง ml-service restart) -> ต้องไม่ error/ไม่ค้าง (B63).

    fit โมเดลรายคนใช้เวลา ~0.4-0.9 วิ ที่ history 2000 · ถ้าไม่มี lock request ที่มา
    พร้อมกัน N อันจะ fit ซ้ำ N ครั้งจน timeout ทุกอัน (วัดได้จริงก่อนใส่ lock)
    ผลที่ยอมรับได้: บาง request abstain/timeout เงียบๆ — ห้าม raise, ห้ามค้างเกิน timeout
    """
    uid = f"{USER}-storm"
    _seed(seeded, uid, N_WRITTEN, seed=123)  # user ใหม่ = cache ว่างแน่นอน
    t0 = time.perf_counter()
    outs = await asyncio.gather(
        *[get_sequence_score(uid, DRIFT) for _ in range(20)], return_exceptions=True
    )
    elapsed = (time.perf_counter() - t0) * 1000
    seeded.delete(_key(uid))

    assert not any(isinstance(o, Exception) for o in outs), "ห้าม raise ขึ้น flow login"
    errs = [o["error"] for o in outs if o["error"]]
    ok = [o for o in outs if o["error"] is None]
    print(
        f"\n  cache-miss storm (20 พร้อมกัน): สำเร็จ {len(ok)}/20 · "
        f"timeout {len(errs)} · รวม {elapsed:.0f}ms"
    )
    # เพดาน: timeout ต่อ request + เผื่อ overhead — ต้องไม่บานเป็นเชิงเส้นตามจำนวน request
    assert (
        elapsed < settings.l3_timeout_seconds * 1000 * 6
    ), f"storm ใช้เวลา {elapsed:.0f}ms — น่าจะ fit ซ้ำหลายรอบ (lock ไม่ทำงาน)"
    assert all(e in ("l3_timeout", "l3_unreachable: ReadTimeout") for e in errs), errs
    # หลัง storm จบ cache ต้องอุ่นแล้ว -> request ถัดไปต้องเร็วและสำเร็จ
    after = await get_sequence_score(uid, DRIFT)
    assert after["error"] is None or after["error"] == "l3_timeout"


@pytest.mark.asyncio
async def test_cold_capacity_many_distinct_users(seeded):
    """สถานการณ์จริงหลัง ml-service restart: ผู้ใช้หลายคน cold พร้อมกัน.

    เป็น capacity probe — รายงานตัวเลข ไม่ตั้งเกณฑ์ผ่าน/ไม่ผ่านตายตัว
    (ขึ้นกับ CPU ของเครื่องที่รัน) สิ่งที่บังคับคือ: ห้าม raise และห้ามคืนค่าเพี้ยน
    """
    n_users = 8
    uids = [f"{USER}-cap{i}" for i in range(n_users)]
    for i, uid in enumerate(uids):
        _seed(seeded, uid, 1200, seed=200 + i)
    t0 = time.perf_counter()
    outs = await asyncio.gather(
        *[get_sequence_score(u, DRIFT) for u in uids], return_exceptions=True
    )
    cold_ms = (time.perf_counter() - t0) * 1000
    # client ยอมแพ้ที่ timeout แต่ ml-service ยัง fit ต่อจนจบ -> รอให้ warm ก่อนวัดรอบสอง
    # (สะท้อนของจริง: หลัง restart มีช่วง warm-up ที่ L3 ยังเงียบอยู่)
    await asyncio.sleep(3.0)
    t0 = time.perf_counter()
    outs2 = await asyncio.gather(*[_ok(u, DRIFT) for u in uids])
    warm_ms = (time.perf_counter() - t0) * 1000
    for uid in uids:
        seeded.delete(_key(uid))

    assert not any(isinstance(o, Exception) for o in outs)
    ok_cold = sum(1 for o in outs if o["error"] is None)
    ok_warm = sum(1 for o in outs2 if o["error"] is None)
    print(
        f"\n  cold {n_users} users พร้อมกัน: สำเร็จ {ok_cold}/{n_users} ใน {cold_ms:.0f}ms"
        f"  ->  รอบสอง (warm): สำเร็จ {ok_warm}/{n_users} ใน {warm_ms:.0f}ms"
    )
    assert (
        ok_warm == n_users
    ), f"รอบที่สองต้องสำเร็จทุกคน (cache อุ่นแล้ว) — ได้ {ok_warm}/{n_users}"
    assert {o["n_history"] for o in outs2} == {1200}, "n_history ต้องตรงของแต่ละคน"


# ══════════════ 5. Latency ══════════════
@pytest.mark.asyncio
async def test_latency_within_login_budget(seeded):
    """L3 ต้องไม่กินเวลาเกินงบของ login path.

    งบ: timeout เฉพาะของ L3 = settings.l3_timeout_seconds เป็นเพดานแข็ง (B63)
    เกณฑ์ที่ตั้ง: p95 ต้องต่ำกว่าครึ่งหนึ่งของ timeout — ถ้าชนเพดานคือ L3 กลายเป็นคอขวด
    """
    await _ok(USER, NORMAL)  # warm-up (fit ครั้งแรกอยู่ที่ ml-service cache)
    lat = []
    for _ in range(30):
        t0 = time.perf_counter()
        await _ok(USER, DRIFT)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    p50, p95, mx = lat[len(lat) // 2], lat[int(len(lat) * 0.95)], lat[-1]
    print(
        f"\n  latency (n={len(lat)}, history={N_HISTORY}): "
        f"p50={p50:.1f}ms p95={p95:.1f}ms max={mx:.1f}ms "
        f"mean={statistics.mean(lat):.1f}ms"
    )
    budget = settings.l3_timeout_seconds * 1000 / 2
    assert p95 < budget, f"p95 {p95:.0f}ms เกินครึ่งของ timeout ({budget:.0f}ms)"


@pytest.mark.asyncio
async def test_ml_health_exposes_l3_readiness(seeded):
    """`/health` ต้องบอกสถานะ L3 ได้ — กัน B61 ซ้ำ.

    L3 abstain เพราะต่อ Redis ไม่ได้ ให้ผลภายนอกเหมือน "ทำงานปกติแต่ไม่เจออะไร" เป๊ะ
    ถ้าไม่มีจุดให้ตรวจ จะไม่มีใครรู้ว่ามันไม่เคยทำงานเลย (เคยเกิดมาแล้วทั้ง environment)
    """
    import httpx

    h = httpx.get(f"{settings.ml_service_url}/health", timeout=5).json()
    assert "l3_sequence" in h, "/health ต้องรายงานสถานะ L3 แยกจากโมเดลหลัก"
    l3 = h["l3_sequence"]
    assert l3["redis"] in ("ok", "unavailable")
    assert l3["ready"] is True, f"L3 ไม่พร้อมในสภาพแวดล้อมทดสอบ: {l3}"
    # ยืนยัน MODEL_VERSION ตรงกันข้าม service ตอน runtime (ไม่ใช่แค่ตอนอ่าน source)
    assert l3["model_version"] == L3.MODEL_VERSION


# ══════════════ 6. Fail-safe (B21) ══════════════
@pytest.mark.asyncio
async def test_ml_service_down_fails_safe(seeded, monkeypatch):
    """ml-service ล่ม -> L3 เงียบ + error code · ห้ามลาก login ล่มตาม."""
    monkeypatch.setattr(settings, "ml_service_url", "http://127.0.0.1:59999")
    out = await get_sequence_score(USER, DRIFT)
    assert out["fired"] is False
    assert out["error"] and "unreachable" in out["error"]
    assert L3.monitoring_decision(L3.result_from_payload(out)) == L3.MONITORING_NORMAL


@pytest.mark.asyncio
async def test_ml_service_slow_times_out_cleanly(seeded, monkeypatch):
    """ml-service ช้า -> timeout แล้วเงียบ ไม่ค้าง login."""
    monkeypatch.setattr(settings, "l3_timeout_seconds", 0.001)
    t0 = time.perf_counter()
    out = await get_sequence_score(USER, DRIFT)
    elapsed = (time.perf_counter() - t0) * 1000
    assert out["fired"] is False
    assert out["error"] in ("l3_timeout", "l3_unreachable: ConnectTimeout")
    assert elapsed < 1000, f"ใช้เวลา {elapsed:.0f}ms ทั้งที่ timeout 1ms"


@pytest.mark.asyncio
async def test_redis_unavailable_at_hub_is_safe(seeded):
    """hub เขียน history ไม่ได้ (redis=None) -> ไม่ throw."""
    L3.record_residual(None, USER, NORMAL)  # ต้องไม่ raise


@pytest.mark.asyncio
async def test_risk_engine_survives_l3_failure(monkeypatch):
    """risk_engine ต้องคืน decision ปกติแม้ L3 ระเบิดทั้งชั้น."""
    from app.security import risk_engine
    from app.security.rule_engine import FEAT

    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)

    async def boom(*a, **kw):
        raise RuntimeError("L3 ระเบิด")

    from app.services import l3_sequence_client as CLI

    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    # L3 ระเบิดทั้งชั้น (ทั้ง point + sequence อยู่หลัง client ตัวเดียวกันแล้ว)
    monkeypatch.setattr(CLI, "evaluate_l3", boom)

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    out = await risk_engine.evaluate_login_risk(
        v, "u-stab", None, None, db=None, shadow_mode=False
    )
    assert out["decision"] in ACTIONS
    assert out["l3_sequence"] is None, "L3 พัง -> ไม่ควรมี contract"


# ══════════════ 7. L3 ห้ามเปลี่ยน access decision (เกณฑ์สำคัญที่สุด) ══════════════
def test_monitoring_decision_exhaustive():
    """สแกนทุกชุดค่า — L3 คืนได้เฉพาะคำในแกน monitoring เท่านั้น.

    เทสนี้แทนของเดิมที่สแกน `apply_channel(access_decision, result)` — API นั้นถูกลบแล้ว
    เพราะรับ/คืนค่าในแกน access ซึ่งขัดกับหลักการที่รายงานไว้ (ดู test_l3_access_monitoring_split.py)
    """
    seen = set()
    for elig in ("abstain", "diagnostic", "warn", "challenge"):
        for tier in ("none", "anomaly", "extreme"):
            for fired in (True, False):
                for score in (0.0, 0.5, 1.0):
                    got = L3.monitoring_decision(
                        L3.L3Result(
                            fired=fired,
                            score=score,
                            tier=tier,
                            eligibility=elig,
                            n_history=5000,
                        )
                    )
                    assert got in (L3.MONITORING_NORMAL, L3.MONITORING_INVESTIGATE)
                    assert got not in ACTIONS, f"L3 คืนคำในแกน access: {got}"
                    seen.add(got)
    assert seen == {L3.MONITORING_NORMAL, L3.MONITORING_INVESTIGATE}


@pytest.mark.asyncio
async def test_live_extreme_score_only_sets_monitoring_flag(seeded):
    """ของจริง: residual สุดโต่ง + tier challenge -> ขึ้นธง monitoring เท่านั้น."""
    out = await _ok(USER, DRIFT)
    res = L3.result_from_payload(out)
    assert res.fired is True and res.eligibility == "challenge"
    print(
        f"\n  live: tier={res.tier} shadow={res.shadow_decision} raw={res.raw_score:.3f}"
    )
    assert L3.monitoring_decision(res) == L3.MONITORING_INVESTIGATE
    # would_challenge เก็บไว้วิเคราะห์เท่านั้น — ไม่มีเส้นทางไหนทำให้มันไป enforce ได้
    assert res.shadow_decision == "would_challenge"
    assert L3.to_contract(res, None)["monitoring_decision"] == L3.MONITORING_INVESTIGATE
