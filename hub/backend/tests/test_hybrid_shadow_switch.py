"""สวิตช์ฉุกเฉิน HYBRID_SHADOW_ENABLED และเพดานเวลารวมของ L3 — เขียนก่อน implementation (RED).

แผน Hybrid Shadow ขั้นที่ 3/13 กำหนดคำสั่งปิดฉุกเฉิน

    HYBRID_SHADOW_ENABLED=false
    L3_MODE=monitor_only

ปิดแล้วต้อง: ไม่คำนวณ Hybrid Candidate · การตัดสินจริงทำงานแบบเดิม · ไม่ต้อง deploy ใหม่

**เพดานเวลา:** `httpx.AsyncClient(timeout=0.5)` เป็นเพดานต่อช่วง (connect/read/...)
วัดได้ request ที่ใช้ 626 ms แล้วยังสำเร็จ (step12 §4) · L3 ต้องมีเพดานรวมจริง
หมดเวลาแล้ว login เดินต่อ L3 abstain พร้อม `l3_timeout` และห้ามใช้คะแนนเก่าหรือผลบางส่วน
"""

from __future__ import annotations

import asyncio
import copy
import time

import pytest

pytestmark = pytest.mark.asyncio

TIMEOUT = 0.2  # วินาที — สั้นพอให้เทสเร็ว
MARGIN_MS = 150  # เผื่อ scheduling ของ event loop


def _quiet_l3(point_raw=0.99, seq_raw=0.99):
    from app.services import l3_sequence_client as CLI

    out = copy.deepcopy(CLI.UNIFIED_QUIET)
    out["point"] = {
        "available": True,
        "anomaly_score": point_raw,
        "is_anomaly": True,
        "explanation": [],
        "error": None,
        "explainer": "ready",
    }
    out["sequence"] = {
        **out["sequence"],
        "raw_score": seq_raw,
        "score": seq_raw,
        "eligibility": "challenge",
        "n_history": 1200,
    }
    out["monitoring_decision"] = "l3_investigate"
    return out


@pytest.fixture
def engine(monkeypatch):
    """เรียก risk_engine ตัวจริง · คุม L3 ด้วย fake ที่กำหนดความหน่วงได้."""
    from app.config import settings
    from app.security import l3_sequence as L3
    from app.security import risk_engine, rule_engine
    from app.services import l3_sequence_client as CLI

    state = {
        "delay": 0.0,
        "pre_delay": 0.0,
        "recorded": 0,
        "fuse_calls": 0,
        "l3": _quiet_l3(),
    }

    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)
    monkeypatch.setattr(settings, "l3_timeout_seconds", TIMEOUT, raising=False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(
        rule_engine, "_check_cross_subsystem_risk", lambda *a, **kw: None
    )

    def residual(*a, **kw):
        if state["pre_delay"]:
            time.sleep(state["pre_delay"])
        return [0.0] * L3.DIMS

    def record(*a, **kw):
        state["recorded"] += 1

    monkeypatch.setattr(L3, "residual_raw", residual)
    monkeypatch.setattr(L3, "record_residual", record)

    async def fake_l3(user_id, features, resid, access_decision="allow", explain=False):
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        return copy.deepcopy(state["l3"])

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)

    real_fuse = risk_engine.fuse

    def counting_fuse(*a, **kw):
        state["fuse_calls"] += 1
        return real_fuse(*a, **kw)

    monkeypatch.setattr(risk_engine, "fuse", counting_fuse)

    async def run(mode="shadow_hybrid", enabled=True):
        from app.security.rule_engine import FEAT

        monkeypatch.setattr(settings, "l3_mode", mode, raising=False)
        monkeypatch.setattr(settings, "hybrid_shadow_enabled", enabled, raising=False)
        state["fuse_calls"] = 0
        v = [0.0] * 23
        v[FEAT["permission_change_age"]] = 365.0
        t0 = time.perf_counter()
        out = await risk_engine.evaluate_login_risk(
            v, "u-switch", None, None, db=None, shadow_mode=True
        )
        out["_elapsed_ms"] = (time.perf_counter() - t0) * 1000
        return out

    state["run"] = run
    return state


# ══════════════════════════════════════════════════════════════════════════════
# 1. สวิตช์ฉุกเฉิน
# ══════════════════════════════════════════════════════════════════════════════


async def test_switch_is_declared_and_defaults_on():
    """ค่าเริ่มต้นเปิด — การเปิด Hybrid ยังต้องตั้ง L3_MODE=shadow_hybrid เองอยู่แล้ว
    สวิตช์นี้มีไว้ปิดฉุกเฉิน ไม่ใช่ตัวเปิด."""
    from app.config import Settings

    field = Settings.model_fields["hybrid_shadow_enabled"]
    assert field.default is True


async def test_invalid_switch_value_is_rejected_at_startup():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(hybrid_shadow_enabled="maybe")


async def test_disabled_does_not_compute_hybrid(engine):
    out = await engine["run"](enabled=False)
    assert out["hybrid_shadow"] is None, "ปิดแล้วต้องไม่มีผล hybrid (ไม่ใช่สำเนา baseline)"
    assert out["l3"]["changed_shadow_decision"] is None
    assert out["hybrid_shadow_enabled"] is False
    # การตัดสินจริง + baseline = 2 ครั้ง · ไม่มีรอบของ hybrid
    assert engine["fuse_calls"] == 2


async def test_enabled_computes_hybrid(engine):
    out = await engine["run"](enabled=True)
    assert out["hybrid_shadow"] is not None
    assert out["hybrid_shadow"]["final_risk"] > out["baseline_shadow"]["final_risk"]
    assert out["hybrid_shadow_enabled"] is True
    assert engine["fuse_calls"] == 3


async def test_disabled_keeps_actual_decision_unchanged(engine):
    off = await engine["run"](mode="off", enabled=True)
    disabled = await engine["run"](mode="shadow_hybrid", enabled=False)
    assert disabled["decision"] == off["decision"]
    assert disabled["score"] == off["score"]


async def test_disabled_also_removes_l3_from_hybrid_stepup(engine):
    """kill switch ต้องเอา L3 ออกจากทุกการรวมคะแนน รวมโหมดที่ L3 มีผลจริง."""
    off = await engine["run"](mode="off", enabled=True)
    stepup_on = await engine["run"](mode="hybrid_stepup", enabled=True)
    stepup_off = await engine["run"](mode="hybrid_stepup", enabled=False)
    assert stepup_on["score"] > off["score"], "เงื่อนไขของเทส: เปิดอยู่ L3 ต้องมีผล"
    assert stepup_off["score"] == off["score"]
    assert stepup_off["decision"] == off["decision"]


async def test_disabled_still_lets_l3_monitor(engine):
    """ปิด Hybrid แล้ว L3 ยังเฝ้าระวังได้ตาม L3_MODE."""
    out = await engine["run"](mode="monitor_only", enabled=False)
    assert out["monitoring_decision"] == "l3_investigate"


async def test_switch_takes_effect_without_reload(engine):
    """เปลี่ยนค่าแล้วมีผลกับ login ถัดไปทันที — ไม่ต้อง deploy ใหม่."""
    first = await engine["run"](enabled=True)
    second = await engine["run"](enabled=False)
    third = await engine["run"](enabled=True)
    assert first["hybrid_shadow"] is not None
    assert second["hybrid_shadow"] is None
    assert third["hybrid_shadow"] is not None


async def test_disabled_writes_null_shadow_columns(engine):
    from app.services.shadow_record import SOURCE_GOOGLE, shadow_columns

    out = await engine["run"](enabled=False)
    cols = shadow_columns(out, source=SOURCE_GOOGLE)
    assert cols["hybrid_shadow_score"] is None
    assert cols["hybrid_shadow_decision"] is None
    assert cols["l3_changed_shadow_decision"] is None
    assert cols["baseline_shadow_decision"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. เพดานเวลารวมของ L3
# ══════════════════════════════════════════════════════════════════════════════


async def test_slow_l3_is_cut_at_the_total_deadline(engine):
    engine["delay"] = TIMEOUT * 5
    out = await engine["run"]()
    assert out["latency_l3_ms"] <= TIMEOUT * 1000 + MARGIN_MS, out["latency_l3_ms"]
    assert out["_elapsed_ms"] <= TIMEOUT * 1000 + MARGIN_MS * 2
    assert out["l3"] is not None


async def test_timeout_is_recorded_and_l3_abstains(engine):
    engine["delay"] = TIMEOUT * 5
    out = await engine["run"]()
    assert out["evidence"]["anomaly"]["abstained"] is True
    assert out["evidence"]["anomaly"]["abstain_reason"] == "l3_timeout"
    assert out["l3"]["combined_evidence"] is None, "หมดเวลาแล้วห้ามมีคะแนน L3 บางส่วน"


async def test_timeout_makes_hybrid_equal_baseline(engine):
    engine["delay"] = TIMEOUT * 5
    out = await engine["run"]()
    assert out["hybrid_shadow"]["final_risk"] == out["baseline_shadow"]["final_risk"]
    assert out["hybrid_shadow"]["decision"] == out["baseline_shadow"]["decision"]
    assert out["l3"]["changed_shadow_decision"] is False


async def test_timeout_keeps_actual_decision_unchanged(engine):
    off = await engine["run"](mode="off")
    engine["delay"] = TIMEOUT * 5
    slow = await engine["run"](mode="hybrid_stepup")
    assert slow["decision"] == off["decision"]
    assert slow["score"] == off["score"]


async def test_timeout_does_not_reuse_previous_score(engine):
    fast = await engine["run"]()
    assert fast["l3"]["combined_evidence"] is not None
    engine["delay"] = TIMEOUT * 5
    slow = await engine["run"]()
    assert slow["l3"]["combined_evidence"] is None
    assert slow["l3"]["point_evidence"] is None


async def test_residual_is_still_recorded_after_timeout(engine):
    """ประวัติของ L3 ต้องต่อเนื่องแม้รอบนี้ ML ตอบไม่ทัน."""
    engine["delay"] = TIMEOUT * 5
    await engine["run"]()
    assert engine["recorded"] == 1


async def test_deadline_covers_work_before_the_http_call(engine):
    """เพดานเป็นเวลารวม — งานก่อนเรียก ML กินงบไปแล้ว เวลาที่เหลือต้องลดตาม."""
    engine["pre_delay"] = TIMEOUT * 0.75
    engine["delay"] = TIMEOUT * 0.5
    out = await engine["run"]()
    assert out["latency_l3_ms"] <= TIMEOUT * 1000 + MARGIN_MS, out["latency_l3_ms"]
    assert out["evidence"]["anomaly"]["abstain_reason"] == "l3_timeout"


async def test_fast_l3_is_not_affected_by_the_deadline(engine):
    engine["delay"] = TIMEOUT * 0.1
    out = await engine["run"]()
    assert out["evidence"]["anomaly"]["abstained"] is False
    assert out["l3"]["combined_evidence"] is not None
