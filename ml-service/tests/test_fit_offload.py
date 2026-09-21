"""ย้าย fit ของ L3 sequence ออกจากเส้นทาง request — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate §14–15): fit หนึ่งคน ~165 ms · cold burst 20 request พร้อมกัน p50
1.2–1.7 วินาที (เกินเพดาน L3 500 ms ทุกตัว) · จำกัด fit พร้อมกันอย่างเดียวไม่พอ (11 คน × 165 ms
≈ 1.8 วินาทีแม้ไม่แย่ง GIL) · ที่ภาระจริงหลัง restart แทบทุก login เป็นคนที่ยังไม่มีโมเดล และ
cache หมดอายุทุก 1 ชม. ต่อ worker → งาน fit เกินกำลังเครื่องได้ · hub หยุดรอที่ 500 ms แต่
ml-service ยัง fit ต่อจนกิน CPU ของ request ที่อุ่นแล้ว

ทางแก้ที่ตัดสินแล้ว (2026-09-22):
  - cache miss → ส่ง fit ให้ thread เบื้องหลัง**ตัวเดียวต่อ process** แล้วรอได้ไม่เกินงบ
    (`L3_FIT_WAIT_MS`, ค่าเริ่มต้น 150) · ทันก็ให้คะแนนตามปกติ · ไม่ทันตอบทันทีว่า abstain
    พร้อม `abstain_reason = "model_warming"` (ไม่บอกว่า "ดูแล้วไม่เจอ" — บทเรียน B61)
  - คนเดียวกันส่ง fit ซ้ำไม่ได้ขณะรออยู่ · fit พังต้องไม่ค้างสถานะ (ลองใหม่ได้)
  - คะแนนหลังโมเดลพร้อมต้องเท่ากับการ fit แบบเดิมทุกประการ
"""

from __future__ import annotations

import json
import random
import threading
import time

import pytest

from app import sequence as SEQ


class FakeRedis:
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


def _seed(r, user, n=300, seed=42):
    rng = random.Random(seed)
    r.lists[SEQ.REDIS_KEY.format(user_id=user)] = [
        json.dumps([rng.gauss(0, 1) for _ in range(SEQ.DIMS)]) for _ in range(n)
    ]


RESID = [0.1] * SEQ.DIMS


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("L3_FIT_WAIT_MS", raising=False)
    SEQ.reset_capacity_stats()
    SEQ._MODEL_CACHE.clear()
    SEQ._LOCKS.clear()
    SEQ.wait_for_background_fits(timeout=10)
    yield
    SEQ.wait_for_background_fits(timeout=10)
    SEQ._MODEL_CACHE.clear()
    SEQ._LOCKS.clear()
    SEQ.reset_capacity_stats()


def _slow_fit(monkeypatch, seconds):
    real = SEQ.fit_user_model
    active = {"now": 0, "max": 0}
    guard = threading.Lock()

    def slow(history, n_history=None):
        with guard:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        try:
            time.sleep(seconds)
            return real(history, n_history=n_history)
        finally:
            with guard:
                active["now"] -= 1

    monkeypatch.setattr(SEQ, "fit_user_model", slow)
    return active


def test_fast_fit_within_budget_is_scored_on_the_first_request(monkeypatch):
    """fit ที่เสร็จทันงบต้องได้คะแนนตั้งแต่ครั้งแรก — ใช้โมเดลที่ fit ไว้ก่อน เพื่อไม่ให้เทส
    ขึ้นกับความเร็วเครื่อง (host fit 300 แถว 196–311 ms เกินงบ 150 ms · บทเรียน B76)."""
    r = FakeRedis()
    _seed(r, "u1")
    history = SEQ.load_history(r, "u1")
    ready = SEQ.fit_user_model(history, n_history=len(history))
    monkeypatch.setattr(SEQ, "fit_user_model", lambda h, n_history=None: ready)
    out = SEQ.score(r, "u1", RESID)
    assert out.get("abstain_reason") is None
    assert out["eligibility"] != "abstain"


def test_slow_fit_answers_quickly_with_model_warming(monkeypatch):
    monkeypatch.setenv("L3_FIT_WAIT_MS", "50")
    _slow_fit(monkeypatch, 0.4)
    r = FakeRedis()
    _seed(r, "u1")
    t0 = time.perf_counter()
    out = SEQ.score(r, "u1", RESID)
    took = time.perf_counter() - t0
    assert took < 0.25  # ไม่รอ fit จนเสร็จ
    assert out["eligibility"] == "abstain"
    assert out["abstain_reason"] == "model_warming"
    assert out["fired"] is False


def test_after_warming_the_score_equals_a_direct_fit(monkeypatch):
    real_fit = SEQ.fit_user_model  # เก็บตัวจริงไว้ก่อนทำให้ช้า
    monkeypatch.setenv("L3_FIT_WAIT_MS", "50")
    _slow_fit(monkeypatch, 0.3)
    r = FakeRedis()
    _seed(r, "u1")
    assert SEQ.score(r, "u1", RESID)["abstain_reason"] == "model_warming"
    assert SEQ.wait_for_background_fits(timeout=10)
    warmed = SEQ.score(r, "u1", RESID)

    history = SEQ.load_history(r, "u1")
    model = real_fit(history, n_history=len(history))
    direct = SEQ.evaluate_window(model, history[-(SEQ.WINDOW - 1) :] + [list(RESID)])
    assert warmed["score"] == direct["score"]
    assert warmed["raw_score"] == direct["raw_score"]
    assert warmed["percentile"] == direct["percentile"]


def test_one_fit_per_user_while_many_requests_wait(monkeypatch):
    monkeypatch.setenv("L3_FIT_WAIT_MS", "20")
    _slow_fit(monkeypatch, 0.3)
    r = FakeRedis()
    _seed(r, "u1")
    barrier = threading.Barrier(20)

    def go():
        barrier.wait()
        SEQ.score(r, "u1", RESID)

    ts = [threading.Thread(target=go) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert SEQ.wait_for_background_fits(timeout=10)
    assert SEQ.capacity_stats()["fits_total"] == 1


def test_background_fits_run_one_at_a_time(monkeypatch):
    """CPU ที่ใช้ fit มีเพดาน — ไม่แย่ง GIL กับ request ที่อุ่นแล้ว."""
    monkeypatch.setenv("L3_FIT_WAIT_MS", "0")
    active = _slow_fit(monkeypatch, 0.05)
    r = FakeRedis()
    for i in range(6):
        _seed(r, f"u{i}", seed=i)
    for i in range(6):
        SEQ.score(r, f"u{i}", RESID)
    assert SEQ.wait_for_background_fits(timeout=10)
    assert active["max"] == 1
    assert SEQ.capacity_stats()["fits_total"] == 6


def test_a_failed_fit_does_not_stick(monkeypatch):
    monkeypatch.setenv("L3_FIT_WAIT_MS", "200")
    calls = {"n": 0}

    def boom(history, n_history=None):
        calls["n"] += 1
        raise RuntimeError("fit พัง")

    monkeypatch.setattr(SEQ, "fit_user_model", boom)
    r = FakeRedis()
    _seed(r, "u1")
    out = SEQ.score(r, "u1", RESID)
    assert out["fired"] is False  # fail-safe
    assert SEQ.wait_for_background_fits(timeout=10)
    SEQ.score(r, "u1", RESID)
    assert calls["n"] == 2  # ไม่ค้าง future ที่พังไว้


def test_warm_path_does_not_touch_the_background_queue(monkeypatch):
    r = FakeRedis()
    _seed(r, "u1")
    SEQ.score(r, "u1", RESID)
    assert SEQ.wait_for_background_fits(timeout=30)  # ให้ cache อุ่นจริงก่อน

    touched = {"n": 0}

    def spy(*a, **k):
        touched["n"] += 1
        raise AssertionError("cache อุ่นแล้วต้องไม่ส่งงาน fit")

    monkeypatch.setattr(SEQ, "_submit_fit", spy)
    out = SEQ.score(r, "u1", RESID)
    # score() กลืน exception เป็น QUIET — จึงต้องนับการเรียกและตรวจว่าได้คะแนนจริง
    assert touched["n"] == 0
    assert out["eligibility"] != "abstain"


@pytest.mark.parametrize("bad", ["abc", "-1", "401", "nan"])
def test_invalid_budget_is_refused(monkeypatch, bad):
    monkeypatch.setenv("L3_FIT_WAIT_MS", bad)
    with pytest.raises(ValueError, match="L3_FIT_WAIT_MS"):
        SEQ.fit_wait_seconds()


def test_default_budget_is_150_ms():
    assert SEQ.fit_wait_seconds() == pytest.approx(0.150)


def test_stats_report_warming_and_queue(monkeypatch):
    monkeypatch.setenv("L3_FIT_WAIT_MS", "0")
    _slow_fit(monkeypatch, 0.2)
    r = FakeRedis()
    _seed(r, "u1")
    SEQ.score(r, "u1", RESID)
    s = SEQ.capacity_stats()
    assert s["warming_responses"] == 1
    assert s["fits_pending"] in (0, 1)
