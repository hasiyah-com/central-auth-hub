"""L2 — subsystem access novelty เป็น "ตระกูลหลักฐานเดียว" (ออกแบบ 6 ก.ย. 2569).

**ปัญหาที่แก้:** `new_subsystem` (+0.30) กับ `scope_escalation` (+0.25) ยิงจาก
ข้อเท็จจริงเดียวกัน (ผู้ใช้เข้าระบบที่ต่างจากรูปแบบเดิม ซึ่งมักมี scope ต่างด้วย)
แล้วถูกบวกรวมเป็น **0.55** = นับหลักฐานซ้ำ

วัดบนข้อมูลจริง (U01 · seed 46 · size 50): 78 จาก 81 เหตุการณ์ปกติที่ถูก challenge
มีทั้งคู่ยิงพร้อมกัน · มวล 0.55 นั้น 49 เหตุการณ์ map ไป ECDF 0.9955 ซึ่งเหนือเกณฑ์
challenge 0.995 แค่ 0.0005 -> FPR ของผู้ใช้คนเดียวพุ่งถึง 16.2% ที่ cold start

**โครงสร้างที่ทดลอง:** `family = WEIGHT * max(C_nov * N, C_scope * S)`

**ตัวแปรนี้ถูกปฏิเสธและถอนออกจาก production แล้ว** (6 ก.ย. 2569) — การทดลอง
บน validation พบว่าประโยชน์ด้าน FPR สูงสุด 0.08 pp ซึ่ง **แยกไม่ออกจากศูนย์** ใน
paired test ขณะที่ recall ของ `subtle_quiet_lateral` ตก 6.7 pp อย่างมีนัย
(ดู `tests/reports/l2_subsystem_family_grid_2026-09-06.md`)

โค้ดย้ายไปอยู่ที่ `ml-service/scripts/hybrid_experiment/l2_family_variant.py`
เพื่อให้ผลลบยังทำซ้ำได้ · เทสชุดนี้จึงคุ้มครอง **ตัวแปรทดลอง** ไม่ใช่ production
และ skip ในคอนเทนเนอร์ (harness ของ ml-service ไม่อยู่ใน path)

สิ่งที่เทสชุดนี้คุ้มครอง:
  1. `max` ไม่ใช่ผลรวม — เหตุการณ์เดียวต้องเป็นหลักฐานชิ้นเดียว
  2. confidence คูณ **แยกกัน** ก่อน max — ระบบที่เคยเห็นแล้วแต่ scope เพิ่มจริง
     ต้องไม่ถูกทำให้เป็นศูนย์เพราะ novelty ยังไม่มั่นใจ
  3. ความมั่นใจของ novelty ขึ้นกับปริมาณประวัติ (rule-of-three heuristic)
  4. ใช้ **จำนวนวันที่ใช้งาน** ไม่ใช่จำนวนแถว — login burst 50 ครั้งในวันเดียว
     ต้องไม่ถูกนับว่ามีข้อมูลเท่ากับ 50 วัน (temporal clustering)
  5. โหมด legacy_additive ยังให้ตัวเลขเดิมเป๊ะ — ไว้เทียบใน experiment บนเส้นทาง
     เดียวกัน (บทเรียน B66: harness ต้องวัดคอนฟิกเดียวกับที่ deploy)

รัน: `docker compose exec hub-backend pytest tests/test_l2_subsystem_family.py -v`
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.security import behavior_profiling as BP
from app.security.rule_engine import FEAT

_here = Path(__file__).resolve()
for _p in _here.parents:
    _cand = _p / "ml-service" / "scripts"
    if _cand.exists():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break

pytest.importorskip(
    "hybrid_experiment.l2_family_variant",
    reason="harness ของ ml-service ไม่อยู่ใน path (ปกติเมื่อรันในคอนเทนเนอร์)",
)

from hybrid_experiment import l2_family_variant as FV  # noqa: E402


def evaluate_behavior(features, profile, subsystem_id=None, user_agent=None):
    """เรียกตัวแปรทดลอง — ไม่ใช่ของ production."""
    return FV.evaluate_behavior_family(BP, features, profile, subsystem_id, user_agent)


N = max(FEAT.values()) + 1
QUIET_HOUR = 8


def vec(scope=0.0, hour=QUIET_HOUR):
    """feature vector ที่ทำให้ **เฉพาะ** ตระกูล subsystem เท่านั้นมีโอกาสยิง."""
    v = [0.0] * N
    v[FEAT["hour_of_day"]] = float(hour)
    v[FEAT["day_of_week"]] = 1.0  # วันธรรมดา ตรงกับ typical_weekend=0
    v[FEAT["hours_from_typical_login_time"]] = 0.0
    v[FEAT["log_minutes_since_last_login"]] = 5.0  # = median ของโปรไฟล์
    v[FEAT["scope_sensitivity_score"]] = float(scope)
    return v


def prof(*, active_days, subs, scope_history, total=None):
    total = total if total is not None else sum(subs.values())
    return {
        "typical_hour": QUIET_HOUR,
        "typical_weekend": 0,
        "session_count": total,
        "total": total,
        "active_days": active_days,
        "hour_counts": {QUIET_HOUR: total},  # ชั่วโมงเดียว -> rarity ไม่ยิง
        "subsystem_counts": dict(subs),
        "seen_subsystems": set(subs),
        "gap_log_median": 5.0,
        "gap_log_scale": 1.0,
        "signature_counts": {},
        "scope_history": list(scope_history),
    }


LONG_HUB_ONLY = prof(active_days=2500, subs={"HUB": 5000}, scope_history=[0.0] * 5000)


# ══════════════ 1. max ไม่ใช่ผลรวม ══════════════
def test_family_uses_max_not_sum():
    """ทั้งสองสมาชิกยิงเต็มพิกัด -> ต้องได้ WEIGHT ไม่ใช่ 0.30 + 0.25."""
    r = evaluate_behavior(vec(scope=0.8), LONG_HUB_ONLY, subsystem_id="SUB_A")
    assert r.score == pytest.approx(FV.SUBSYSTEM_FAMILY_WEIGHT, abs=0.02)
    assert r.score < BP.NEW_SUBSYSTEM_SCORE + BP.SCOPE_ESCALATION_SCORE


def test_production_still_double_counts_by_design():
    """ของจริงยังบวกรวม 0.55 — ยืนยันว่าตัวแปรทดลองถูกถอนออกจริง."""
    r = BP.evaluate_behavior(vec(scope=0.8), LONG_HUB_ONLY, subsystem_id="SUB_A")
    assert r.score == pytest.approx(
        BP.NEW_SUBSYSTEM_SCORE + BP.SCOPE_ESCALATION_SCORE, abs=1e-9
    )


# ══════════════ 2. confidence แยกกันต่อสมาชิก ══════════════
def test_scope_evidence_survives_when_novelty_is_not_credible():
    """subsystem ที่เคยเห็นแล้ว แต่ scope เพิ่มจริง ต้องไม่ถูกทำให้เป็นศูนย์.

    ถ้าใช้ `C * max(N, S)` ด้วย confidence ตัวเดียว หลักฐาน scope ที่ถูกต้องจะถูก
    ความไม่มั่นใจของ novelty กลืนหายไป
    """
    p = prof(
        active_days=200,
        subs={"HUB": 1000, "SUB_A": 1000},  # เคยเห็นทั้งคู่ -> novelty = 0
        scope_history=[0.0] * 2000,
    )
    r = evaluate_behavior(vec(scope=0.8), p, subsystem_id="SUB_A")
    assert r.score > 0.0, "scope escalation จริงต้องยังเป็นหลักฐาน"
    assert any("scope_escalation" in x for x in r.reasons)


# ══════════════ 3. ความมั่นใจขึ้นกับประวัติ ══════════════
def test_novelty_not_credible_at_cold_start():
    """เคส U01 — ประวัติ 25 วัน ไม่พอจะอ้างว่า SUB_A "ไม่เคยใช้"."""
    p = prof(active_days=25, subs={"HUB": 50}, scope_history=[0.0] * 50)
    r = evaluate_behavior(vec(scope=0.0), p, subsystem_id="SUB_A")
    assert r.score == 0.0
    assert not any("subsystem" in x for x in r.reasons)


@pytest.mark.parametrize("days_a,days_b", [(25, 100), (100, 500), (500, 2500)])
def test_novelty_confidence_is_monotone_in_history(days_a, days_b):
    a = prof(active_days=days_a, subs={"HUB": 5000}, scope_history=[0.0] * 5000)
    b = prof(active_days=days_b, subs={"HUB": 5000}, scope_history=[0.0] * 5000)
    ra = evaluate_behavior(vec(), a, subsystem_id="SUB_A")
    rb = evaluate_behavior(vec(), b, subsystem_id="SUB_A")
    assert ra.score < rb.score


def test_rule_of_three_confidence_edges():
    f = FV.rule_of_three_confidence
    assert f(0, 0.05) == 0.0, "ไม่มีประวัติ = ไม่มีความมั่นใจ"
    assert f(-5, 0.05) == 0.0
    assert f(60, 0.05) == 0.0, "3/60 = floor พอดี -> ยังไม่เชื่อ"
    assert 0.0 < f(100, 0.05) < 1.0
    assert f(10**6, 0.05) == pytest.approx(1.0, abs=1e-3)


# ══════════════ 4. effective history = วันที่ใช้งาน ══════════════
def test_burst_of_logins_in_one_day_is_not_treated_as_long_history():
    burst = prof(active_days=1, subs={"HUB": 500}, scope_history=[0.0] * 500)
    spread = prof(active_days=500, subs={"HUB": 500}, scope_history=[0.0] * 500)
    r_burst = evaluate_behavior(vec(), burst, subsystem_id="SUB_A")
    r_spread = evaluate_behavior(vec(), spread, subsystem_id="SUB_A")
    assert r_burst.score == 0.0
    assert r_spread.score > 0.0


def test_profile_without_active_days_falls_back_to_row_count():
    """โปรไฟล์เก่าต้องไม่พัง — ตกกลับไปใช้จำนวนแถว."""
    old = {
        "typical_hour": QUIET_HOUR,
        "typical_weekend": 0,
        "session_count": 500,
        "total": 500,
        "hour_counts": {QUIET_HOUR: 500},
        "subsystem_counts": {"HUB": 500},
        "seen_subsystems": {"HUB"},
        "scope_history": [0.0] * 500,
    }
    assert FV.effective_history(old) == 500
    r = evaluate_behavior(vec(), old, subsystem_id="SUB_A")
    assert r.score > 0.0


# ══════════════ 5. คะแนนไม่เป็นแลตทิซหยาบอีก ══════════════
def test_family_contribution_is_continuous_not_a_lattice():
    """ต้นเหตุความเปราะของ threshold: มวลก้อนใหญ่ที่ค่าเดียว (0.55) คร่อมเกณฑ์พอดี.

    เมื่อคูณ confidence ที่ต่อเนื่อง ค่าที่ได้ต้องกระจาย ไม่กองที่จุดเดียว
    """
    scores = set()
    for d in range(70, 400, 20):
        p = prof(active_days=d, subs={"HUB": 5000}, scope_history=[0.0] * 5000)
        scores.add(round(evaluate_behavior(vec(), p, subsystem_id="SUB_A").score, 4))
    assert len(scores) >= 10, f"ยังกองเป็นแลตทิซ: {sorted(scores)}"
