"""L3 contract ต้องถูกบันทึกลง risk_breakdown (JSON column) — ไม่ต้อง migration.

ที่มา: tests/reports/exp_final_gate_2026-08-26.md
  การทดลองพบว่า raw (L3 ยิง) กับ effective (decision เปลี่ยน) ต่างกันมาก (16.3% vs 0.2%)
  ถ้า production เก็บแค่ decision จะสรุปผิดว่า "L3 ไม่ทำอะไรเลย"
  -> ต้องเก็บ contract ทุก login เพื่อวัด raw vs effective ตอน production replay

เก็บใน LoginSession.risk_breakdown (JSON) ซึ่งมีอยู่แล้ว — ใส่ที่ risk_engine จุดเดียว
ครอบคลุมทุก call site (auth ×3, oauth, passkey) โดยไม่ต้องแก้ router

Run: py -m pytest hub/backend/tests/test_l3_contract_persisted.py -v
"""

from __future__ import annotations

import pytest

from app.security import l3_sequence as L3

CONTRACT_FIELDS = {
    "eligible",
    "eligibility",
    "raw_score",
    "percentile",
    "decision",
    "tier",
    "score",
    "model_version",
    "n_history",
}


def test_contract_has_all_fields_for_replay():
    """ทุกฟิลด์ที่ production replay ต้องใช้."""
    c = L3.to_contract(L3.L3Result(fired=False, score=0.0), None)
    assert CONTRACT_FIELDS <= set(c), f"ขาด {CONTRACT_FIELDS - set(c)}"


def test_contract_json_serializable():
    """ต้องลง JSON column ได้ (ห้ามมี numpy type หรือ object)."""
    import json

    c = L3.to_contract(
        L3.L3Result(
            fired=True,
            score=0.5,
            tier="anomaly",
            raw_score=1.2,
            percentile=0.995,
            eligibility="warn",
            shadow_decision="would_warn",
        ),
        None,
    )
    json.dumps(c)  # ต้องไม่ raise


@pytest.mark.asyncio
async def test_risk_engine_puts_contract_in_breakdown(monkeypatch):
    """เมื่อเปิด L3 -> risk_breakdown ต้องมี l3_sequence (ไม่ต้องแก้ router)."""
    from app.config import settings
    from app.security import risk_engine

    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)

    async def fake_ml(features):
        return {"anomaly_score": 0.0, "explanation": []}

    monkeypatch.setattr(risk_engine, "get_anomaly_score", fake_ml)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)

    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    out = await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )
    assert (
        "l3_sequence" in out["breakdown"]
    ), "risk_breakdown ต้องมี l3_sequence — ไม่งั้น production replay วัด raw ไม่ได้"


@pytest.mark.asyncio
async def test_no_contract_when_disabled(monkeypatch):
    """ปิด L3 -> ไม่ควรมี key ค้างใน breakdown (ไม่เพิ่ม noise ให้ข้อมูลเดิม)."""
    from app.config import settings
    from app.security import risk_engine

    monkeypatch.setattr(settings, "l3_sequence_enabled", False, raising=False)

    async def fake_ml(features):
        return {"anomaly_score": 0.0, "explanation": []}

    monkeypatch.setattr(risk_engine, "get_anomaly_score", fake_ml)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)

    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    out = await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )
    assert "l3_sequence" not in out["breakdown"]
