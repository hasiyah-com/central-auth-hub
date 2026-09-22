"""ข้อมูล shadow ต้องบอกได้ว่า L3 abstain เพราะโมเดลยังไม่พร้อม — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate §19.4, 2026-09-22): หลัง restart L3 abstain ~71% ในนาทีแรก และก่อนแบ่ง
worker ตามผู้ใช้ ผู้ใช้คนเดียวได้ model_warming สลับกับคะแนนจริง · ถ้า `risk_breakdown["l3"]`
ไม่บอกเหตุผล การวิเคราะห์ shadow จะนับ "L3 ยังไม่พร้อม" ปนกับ "L3 ดูแล้วไม่ยิง" — ตัวเลขที่หลอก
ตัวเอง (บทเรียน B61) · ผู้ใช้อนุมัติแก้ `risk_engine.py` (อยู่ใน scoring freeze) พร้อม re-freeze

ทดสอบผ่านเส้นทางที่ production เรียกจริง (`evaluate_login_risk`) — บทเรียน B66/B70
"""

from __future__ import annotations

import copy

import pytest


def _unified(**seq_over):
    from app.services.l3_sequence_client import UNIFIED_QUIET

    out = copy.deepcopy(UNIFIED_QUIET)
    out["sequence"] = {**out["sequence"], **seq_over}
    return out


async def _risk(monkeypatch, payload):
    from app.security import risk_engine
    from app.security.rule_engine import FEAT
    from app.services import l3_sequence_client as CLI

    async def fake_l3(user_id, features, residual, access_decision="allow"):
        return payload

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )


@pytest.mark.asyncio
async def test_warming_is_recorded_in_the_l3_summary(monkeypatch):
    out = await _risk(
        monkeypatch, _unified(eligibility="abstain", abstain_reason="model_warming")
    )
    assert out["breakdown"]["l3"]["abstain_reason"] == "model_warming"


@pytest.mark.asyncio
async def test_a_scored_login_records_no_reason(monkeypatch):
    out = await _risk(monkeypatch, _unified(eligibility="warn", abstain_reason=None))
    assert out["breakdown"]["l3"]["abstain_reason"] is None


@pytest.mark.asyncio
async def test_recording_the_reason_does_not_change_the_decision(monkeypatch):
    """เหตุผลเป็นข้อมูลเท่านั้น — การตัดสินจริงและผลจำลองต้องเท่ากับกรณีไม่มีเหตุผล."""
    warm = await _risk(
        monkeypatch, _unified(eligibility="abstain", abstain_reason="model_warming")
    )
    plain = await _risk(monkeypatch, _unified(eligibility="abstain"))
    assert warm["decision"] == plain["decision"]
    assert warm["score"] == plain["score"]
    assert warm["baseline_shadow"] == plain["baseline_shadow"]
    assert warm["hybrid_shadow"] == plain["hybrid_shadow"]
