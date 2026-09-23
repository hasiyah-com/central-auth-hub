"""SHAP explainer ของ point view ต้องสร้างครั้งเดียวต่อ process — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate 2026-09-21 §4): request แรกของ process ใช้ 1,115 ms เทียบกับ
20 ms ของครั้งถัดไป · `predict_with_explanation` ครั้งแรก 875 ms (import `shap` +
สร้าง TreeExplainer) · `_load_explainer()` เช็ค status แล้วค่อยสร้างโดยไม่มีล็อก →
request ที่มาพร้อมกันตอนเย็นผ่านการเช็คทุกตัวแล้วสร้างซ้ำ · 20 request พร้อมกัน
ใช้ 15.2 วินาที (worker 1 ตัว)

อาการเดียวกับ B63 (fit ซ้ำ) แต่คนละจุด — B63 ใส่ล็อกให้ fit รายคนแล้ว ส่วน explainer
ของ point view ยังไม่มี

ทางแก้: ล็อกแบบ double-check + สร้างตั้งแต่ startup (ค่าที่ได้เหมือนเดิมทุกประการ)

รันบน host: `cd ml-service && python -m pytest tests/test_explainer_init.py -q`
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

from app import model as M


@pytest.fixture
def fresh(monkeypatch):
    """สถานะเริ่มต้นของ process + shap ปลอมที่สร้างช้าและนับจำนวนครั้ง."""
    monkeypatch.setattr(M, "_explainer", None)
    monkeypatch.setattr(M, "_explainer_status", "uninitialized")
    monkeypatch.setattr(M, "load_model", lambda: object())
    calls = {"n": 0}

    def install(*, fail: bool = False, delay: float = 0.05):
        def tree_explainer(model, **kw):
            calls["n"] += 1
            time.sleep(delay)  # ขยายช่วงเวลาที่ race เกิดได้
            if fail:
                raise RuntimeError("shap ใช้กับโมเดลนี้ไม่ได้")
            return {"explainer_for": model}

        fake = types.ModuleType("shap")
        fake.TreeExplainer = tree_explainer
        monkeypatch.setitem(sys.modules, "shap", fake)
        return calls

    return install


def _hammer(n: int = 20) -> list:
    barrier = threading.Barrier(n)
    out = [None] * n

    def go(i):
        barrier.wait()
        out[i] = M._load_explainer()

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_concurrent_first_calls_build_the_explainer_once(fresh):
    calls = fresh()
    out = _hammer(20)
    assert calls["n"] == 1
    assert all(o is out[0] for o in out)
    assert M.explainer_status() == "ready"


def test_concurrent_failures_do_not_retry(fresh):
    """พังแล้วต้องจำว่า unavailable — ไม่ใช่ทุก request ลองสร้างใหม่แล้วพังซ้ำ."""
    calls = fresh(fail=True)
    out = _hammer(20)
    assert calls["n"] == 1
    assert all(o is None for o in out)
    assert M.explainer_status() == "unavailable"


def test_later_calls_do_not_take_the_lock(fresh, monkeypatch):
    """ทางเดินปกติหลังสร้างเสร็จต้องไม่ติดล็อก (ไม่เพิ่ม latency ของ steady state)."""
    fresh()
    M._load_explainer()

    class Boom:
        def __enter__(self):
            raise AssertionError("ไม่ควรแตะล็อกเมื่อ explainer พร้อมแล้ว")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(M, "_EXPLAINER_LOCK", Boom())
    assert M._load_explainer() is not None


def test_startup_builds_the_explainer(monkeypatch):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from app import main

    seen = []
    monkeypatch.setattr(main, "load_model", lambda: seen.append("model"))
    monkeypatch.setattr(main, "warm_explainer", lambda: seen.append("explainer"))
    main.startup()
    assert seen == ["model", "explainer"]


def test_startup_survives_a_broken_explainer(monkeypatch):
    """explainer เป็นคำอธิบาย ไม่ใช่ตัวตัดสิน — พังแล้ว service ต้องขึ้นได้ (B21)."""
    pytest.importorskip("fastapi")
    from app import main

    def boom():
        raise RuntimeError("shap พัง")

    monkeypatch.setattr(main, "load_model", lambda: None)
    monkeypatch.setattr(main, "warm_explainer", boom)
    main.startup()  # ต้องไม่ raise
