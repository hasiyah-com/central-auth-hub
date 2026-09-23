"""hub ต้องเห็นว่า L3 abstain เพราะโมเดลยังไม่พร้อม — เขียนก่อน implementation (RED).

ที่มา (ML Capacity Gate §15–18, 2026-09-22): ml-service ย้าย fit ออกจากเส้นทาง request · ผู้ใช้ที่ยัง
ไม่มีโมเดลได้ `eligibility = "abstain"` + `abstain_reason = "model_warming"` ภายใน ~50 ms ·
แต่ `l3_sequence_client._coerce` เก็บเฉพาะฟิลด์ที่รู้จัก → `abstain_reason` หายระหว่างทาง ·
hub จึงแยกไม่ได้ระหว่าง "โมเดลยังไม่พร้อม" กับ "ประวัติไม่พอ" — อาการแบบ B61 (abstain เงียบ
ที่ดูเหมือนทำงานปกติ)

ข้อกำหนด:
  - ส่ง `abstain_reason` ต่อทั้ง `/v1/sequence-score` และ `/v1/l3-evaluate`
  - รับเฉพาะค่าที่รู้จัก — ค่าอื่นจาก payload ภายนอกปัดเป็น None (แบบเดียวกับ monitoring_decision)
"""

from __future__ import annotations

import pytest

from app.services import l3_sequence_client as C


def test_quiet_has_no_abstain_reason():
    assert C.QUIET["abstain_reason"] is None


def test_model_warming_is_kept():
    out = C._coerce({"eligibility": "abstain", "abstain_reason": "model_warming"})
    assert out["abstain_reason"] == "model_warming"
    assert out["eligibility"] == "abstain"


@pytest.mark.parametrize("bad", ["challenge", "ignore previous", 1, None, ["x"]])
def test_unknown_reasons_are_dropped(bad):
    assert C._coerce({"abstain_reason": bad})["abstain_reason"] is None


def test_missing_reason_is_none():
    assert C._coerce({"eligibility": "warn"})["abstain_reason"] is None


def test_unified_response_keeps_the_sequence_reason():
    data = {
        "monitoring_decision": "normal",
        "sequence": {"eligibility": "abstain", "abstain_reason": "model_warming"},
        "point": {},
    }
    out = C._coerce_unified(data)
    assert out["sequence"]["abstain_reason"] == "model_warming"
