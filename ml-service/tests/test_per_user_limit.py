"""จำกัดคำขอ L3 ที่ค้างพร้อมกันต่อผู้ใช้ — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate §24.4, 2026-09-22): แบ่ง worker ตามผู้ใช้แล้ว ผู้ใช้คนเดียวที่ยิงถี่ลง worker
เดียวทั้งหมด → ตัวเขาเอง p95 545 ms และ**ผู้ใช้อื่นบน worker เดียวกัน p95 289–312 ms** (เกิน 250 ทุกครั้ง)

ข้อกำหนด (ผู้ใช้กำหนด 2026-09-22):
  - จำกัดเฉพาะคำขอเข้า L3 — ไม่ยุ่งกับ login (ฝั่ง hub ถือเป็น L3 abstain ธรรมดา)
  - เกินเพดาน → ตอบทันทีด้วย `abstain_reason = "per_user_overload"` ไม่เรียกโมเดล
    (ไม่ fit, ไม่แตะ cache, ไม่แตะตัวนับ duplicate)
  - ผู้ใช้รายอื่นต้องไม่ถูกจำกัดตาม
  - นับจำนวนครั้งที่ถูกจำกัด (ดูใน Shadow Pilot)
  - เพดานตั้งได้ด้วย `L3_PER_USER_MAX_INFLIGHT` (ค่าเริ่มต้น 2, ช่วง 1–50) · ค่าผิด = ไม่ start
"""

from __future__ import annotations

import threading
import time

import pytest

from app import limiter as LIM


# ── ตัวจำกัด ───────────────────────────────────────────────────────────────


def test_allows_up_to_the_limit_then_refuses():
    lim = LIM.PerUserLimiter(2)
    assert lim.try_acquire("a") and lim.try_acquire("a")
    assert not lim.try_acquire("a")
    lim.release("a")
    assert lim.try_acquire("a")


def test_users_are_independent():
    lim = LIM.PerUserLimiter(1)
    assert lim.try_acquire("a")
    assert lim.try_acquire("b")  # คนอื่นไม่ถูกจำกัดตาม
    assert not lim.try_acquire("a")


def test_no_state_is_left_behind():
    lim = LIM.PerUserLimiter(2)
    for _ in range(3):
        lim.try_acquire("a")
    lim.release("a")
    lim.release("a")
    assert lim.in_flight("a") == 0
    assert lim.tracked_users() == 0  # ไม่เก็บผู้ใช้ที่ว่างแล้วไว้ (ไม่โตไม่รู้จบ)


def test_never_exceeds_the_limit_under_threads():
    lim = LIM.PerUserLimiter(3)
    peak = {"now": 0, "max": 0}
    guard = threading.Lock()
    barrier = threading.Barrier(40)

    def go():
        barrier.wait()
        if lim.try_acquire("hot"):
            with guard:
                peak["now"] += 1
                peak["max"] = max(peak["max"], peak["now"])
            time.sleep(0.01)
            with guard:
                peak["now"] -= 1
            lim.release("hot")

    ts = [threading.Thread(target=go) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert 1 <= peak["max"] <= 3
    assert lim.in_flight("hot") == 0


def test_the_slot_context_releases_on_error():
    lim = LIM.PerUserLimiter(1)
    with pytest.raises(RuntimeError):
        with lim.slot("a") as ok:
            assert ok
            raise RuntimeError("evaluate พัง")
    assert lim.in_flight("a") == 0


def test_refused_slot_does_not_release_someone_elses():
    lim = LIM.PerUserLimiter(1)
    assert lim.try_acquire("a")
    with lim.slot("a") as ok:
        assert not ok
    assert lim.in_flight("a") == 1  # ของคนที่ได้ช่องจริงยังอยู่


# ── คอนฟิก ──────────────────────────────────────────────────────────────


def test_default_limit_is_two(monkeypatch):
    monkeypatch.delenv("L3_PER_USER_MAX_INFLIGHT", raising=False)
    assert LIM.limit_from_env() == 2


@pytest.mark.parametrize("bad", ["0", "51", "abc", "-1", "1.5"])
def test_invalid_limit_is_refused(monkeypatch, bad):
    monkeypatch.setenv("L3_PER_USER_MAX_INFLIGHT", bad)
    with pytest.raises(ValueError, match="L3_PER_USER_MAX_INFLIGHT"):
        LIM.limit_from_env()


# ── endpoint จริง ─────────────────────────────────────────────────────────
# เรียก handler ตรงจากหลาย thread (เหมือน threadpool ของ uvicorn) · TestClient ส่งคำขอ
# ทีละตัวจึงจำลองคำขอค้างพร้อมกันไม่ได้


@pytest.fixture
def endpoint(monkeypatch):
    from app import l3_unified as U
    from app import main

    monkeypatch.setenv("L3_CAPACITY_STATS", "1")
    monkeypatch.setattr(main, "L3_LIMITER", LIM.PerUserLimiter(1))
    monkeypatch.setattr(main, "_redis", lambda: None)
    gate = threading.Event()
    entered = threading.Event()
    calls = []

    def slow_eval(redis, user_id, features, residual, access, explain=False):
        calls.append(user_id)
        if user_id == "hot":
            entered.set()
            gate.wait(5)
        return U.overload_result()  # รูปร่างเดียวกับผลจริง พอสำหรับเทสนี้

    monkeypatch.setattr(main.L3U, "evaluate", slow_eval)

    def post(uid):
        req = main.L3EvaluateRequest(user_id=uid, features=[0.0] * main.FEATURE_COUNT)
        return main.l3_evaluate(req)

    def hold_hot():
        th = threading.Thread(target=post, args=("hot",))
        th.start()
        assert entered.wait(5)
        return th

    yield main, post, hold_hot, gate, calls
    gate.set()


def test_second_request_of_the_same_user_is_refused_fast(endpoint):
    main, post, hold_hot, gate, calls = endpoint
    first = hold_hot()
    t0 = time.perf_counter()
    r = post("hot")
    took = time.perf_counter() - t0
    gate.set()
    first.join()
    seq = r["data"]["sequence"]
    assert seq["abstain_reason"] == "per_user_overload"
    assert seq["eligibility"] == "abstain" and seq["fired"] is False
    assert r["data"]["monitoring_decision"] == "normal"
    assert took < 0.5
    assert calls == ["hot"]  # คำขอที่ถูกจำกัดไม่ได้เรียกโมเดลเลย


def test_other_users_pass_while_one_user_is_saturated(endpoint):
    main, post, hold_hot, gate, calls = endpoint
    first = hold_hot()
    t0 = time.perf_counter()
    post("someone-else")
    took = time.perf_counter() - t0
    gate.set()
    first.join()
    assert calls == ["hot", "someone-else"]
    assert took < 0.5


def test_refusals_are_counted(endpoint):
    main, post, hold_hot, gate, calls = endpoint
    first = hold_hot()
    before = main.l3_capacity_stats()["data"]["per_user_overload"]
    post("hot")
    post("hot")
    gate.set()
    first.join()
    data = main.l3_capacity_stats()["data"]
    assert data["per_user_overload"] - before == 2
    assert data["per_user_limit"] == 1
    assert main.L3_LIMITER.tracked_users() == 0


def test_startup_refuses_an_invalid_limit(monkeypatch):
    from app import main

    monkeypatch.setenv("L3_PER_USER_MAX_INFLIGHT", "0")
    with pytest.raises(ValueError, match="L3_PER_USER_MAX_INFLIGHT"):
        main.startup()


def test_overload_result_has_the_same_shape_as_a_real_result():
    """hub แปลงผลด้วยชุด key เดิม — คำตอบที่ถูกจำกัดต้องมี key ครบเท่าผลจริง."""
    from app import l3_unified as U

    real = U.evaluate(None, "u", [0.0] * U.FEATURE_COUNT, None, "allow")
    over = U.overload_result()
    assert set(over) == set(real)
    assert set(over["sequence"]) >= set(real["sequence"]) - {"error"}
    assert over["monitoring_decision"] == U.MONITORING_NORMAL
    assert over["sequence"]["abstain_reason"] == "per_user_overload"
    assert over["point"]["available"] is False
