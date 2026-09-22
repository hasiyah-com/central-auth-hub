"""hub ต้องรับเหตุผล `per_user_overload` จาก ml-service และ login ต้องไม่ถูกจำกัด — RED ก่อนแก้.

ที่มา (ML Capacity Gate §25, 2026-09-22): ml-service จำกัดคำขอ L3 ค้างพร้อมกันต่อผู้ใช้
(`ml-service/app/limiter.py`) · คำขอที่เกินเพดานได้ `eligibility = "abstain"` +
`abstain_reason = "per_user_overload"` · hub ต้องบันทึกเหตุผลนี้ใน `risk_breakdown["l3"]` เพื่อให้
Shadow Pilot แยก "ถูกจำกัด" ออกจาก "ดูแล้วไม่ยิง" ได้ (บทเรียน B61) และการตัดสิน login ต้องเท่าเดิม

ทดสอบผ่านเส้นทางที่ production เรียกจริง (`evaluate_login_risk`) — บทเรียน B66/B70
"""

from __future__ import annotations

import copy

import pytest

from app.services import l3_sequence_client as C

REASON = "per_user_overload"  # ต้องตรงกับ ml-service/app/l3_unified.py:OVERLOAD_REASON


def _unified(**seq_over):
    out = copy.deepcopy(C.UNIFIED_QUIET)
    out["sequence"] = {**out["sequence"], **seq_over}
    return out


async def _risk(monkeypatch, payload):
    from app.security import risk_engine
    from app.security.rule_engine import FEAT

    async def fake_l3(user_id, features, residual, access_decision="allow"):
        return payload

    monkeypatch.setattr(C, "evaluate_l3", fake_l3)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )


def test_client_keeps_the_overload_reason():
    out = C._coerce({"eligibility": "abstain", "abstain_reason": REASON})
    assert out["abstain_reason"] == REASON


def test_unified_response_keeps_the_overload_reason():
    data = {
        "monitoring_decision": "normal",
        "sequence": {"eligibility": "abstain", "abstain_reason": REASON},
        "point": {},
    }
    assert C._coerce_unified(data)["sequence"]["abstain_reason"] == REASON


@pytest.mark.asyncio
async def test_overload_is_recorded_in_the_l3_summary(monkeypatch):
    out = await _risk(
        monkeypatch, _unified(eligibility="abstain", abstain_reason=REASON)
    )
    assert out["breakdown"]["l3"]["abstain_reason"] == REASON


@pytest.mark.asyncio
async def test_overload_does_not_change_the_login_decision(monkeypatch):
    """ถูกจำกัดที่ L3 = login ตัดสินเหมือน L3 abstain ธรรมดาทุกประการ."""
    over = await _risk(
        monkeypatch, _unified(eligibility="abstain", abstain_reason=REASON)
    )
    plain = await _risk(monkeypatch, _unified(eligibility="abstain"))
    assert over["decision"] == plain["decision"]
    assert over["score"] == plain["score"]
    assert over["baseline_shadow"] == plain["baseline_shadow"]
    assert over["hybrid_shadow"] == plain["hybrid_shadow"]
