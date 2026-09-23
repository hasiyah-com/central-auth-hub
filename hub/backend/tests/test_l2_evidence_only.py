"""L2 Behavior ต้องคืน "หลักฐาน" เท่านั้น — ห้ามมีอำนาจต่อการเข้าถึง (B70).

**บั๊กที่เทสนี้กัน:** `BehaviorResult.min_action` ถูกตั้งเป็น `"challenge"` เมื่อเจอ
subsystem ที่ผู้ใช้ไม่เคยใช้ พร้อมคอมเมนต์ว่า "policy floor" · แต่เส้นทางจริงของ
production (`risk_engine` -> `risk_fusion.fuse`) **ไม่เคยอ่านฟิลด์นี้** — มีเพียง
`PolicyOutcome.min_action` จาก Policy Gate เท่านั้นที่มีผล

วัดยืนยันบนข้อมูลจริง (U01 · seed 46 · size 50): ใน 81 เหตุการณ์ปกติที่ถูก challenge
ได้ `policy min_action distribution: {None: 81}` — floor ไม่เคยถูกใช้เลยสักครั้ง

ผลเสีย: โค้ดกับคอมเมนต์บอกว่ามีการบังคับ step-up ที่ไม่มีอยู่จริง · ผู้อ่านที่เชื่อ
ตามจะประเมินความสามารถของระบบผิด และถ้าใครไป "ต่อสายให้ทำงาน" ภายหลังจะกลายเป็น
การเปลี่ยน dead field ให้เป็น enforcement โดยไม่ผ่าน validation

**ทางแก้ที่เลือก:** ตัดฟิลด์ทิ้ง ไม่ใช่ต่อสาย — ตระกูลหลักฐาน subsystem novelty
ส่งผลผ่าน "คะแนน" อย่างเดียว ให้ L4 เป็นผู้ตัดสินเพียงจุดเดียวตาม evidence contract

รัน: `docker compose exec hub-backend pytest tests/test_l2_evidence_only.py -v`
"""

from __future__ import annotations

import dataclasses

from app.security.behavior_profiling import BehaviorResult, evaluate_behavior
from app.security.policy_gate import PolicyOutcome


def test_behavior_result_has_no_access_decision_field():
    """ชื่อฟิลด์ที่สื่อถึง "การตัดสินสิทธิ์" ต้องไม่มีใน L2 เลย."""
    names = {f.name for f in dataclasses.fields(BehaviorResult)}
    for bad in ("min_action", "decision", "action", "blocked", "access_decision"):
        assert bad not in names, f"L2 ต้องไม่มีฟิลด์ {bad} — เป็นหน้าที่ของ L4"


def test_policy_gate_min_action_still_exists():
    """ต้องไม่ลบ min_action ของ Policy Gate ตามไปด้วย — อันนั้นคือของจริงที่ใช้งาน."""
    names = {f.name for f in dataclasses.fields(PolicyOutcome)}
    assert "min_action" in names
    assert PolicyOutcome(min_action="challenge").intervenes is True


def _profile(total=500, active_days=250, subs=("HUB",)):
    """โปรไฟล์ที่เคยเห็นแต่ HUB — เลียนแบบเคส U01 ที่ไม่เคยเจอ SUB_A ในชุดฝึก."""
    return {
        "typical_hour": 8,
        "typical_weekend": 0,
        "session_count": total,
        "total": total,
        "active_days": active_days,
        "hour_counts": {8: total},
        "subsystem_counts": {s: total // len(subs) for s in subs},
        "seen_subsystems": set(subs),
        "gap_log_median": 5.0,
        "gap_log_scale": 1.0,
        "signature_counts": {"sig": total},
        "scope_history": [0.0] * total,
    }


def test_new_subsystem_contributes_score_not_a_floor():
    """เข้าระบบที่ไม่เคยใช้ = คะแนนสูงขึ้น แต่ไม่บังคับ action ใดๆ."""
    from app.security.rule_engine import FEAT

    feats = [0.0] * (max(FEAT.values()) + 1)
    feats[FEAT["hour_of_day"]] = 8.0
    r = evaluate_behavior(feats, _profile(), subsystem_id="SUB_A")
    assert not hasattr(r, "min_action")
    assert r.score > 0.0, "ยังต้องเป็นหลักฐาน — แค่ไม่ใช่คำสั่ง"
