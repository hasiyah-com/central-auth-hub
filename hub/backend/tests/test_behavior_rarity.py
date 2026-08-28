"""Tier 1 (จาก V8) — เพิ่ม hour_rarity + subsystem_rarity เข้า behavior layer (TDD).

เก็บแนวคิด rarity per-profile ของ V8 (สถิติล้วน ไม่ใช่ ML) มาแก้ 2 จุดอ่อนที่ ablation
พบว่าได้ 0%: off_hours (hour ผิดปกติรายคน) + subsystem_lateral (เข้าระบบที่ไม่เคยใช้)

pure test: db=None ไม่แตะ · profile สร้างเป็น dict ตรงๆ

Run: py -m pytest hub/backend/tests/test_behavior_rarity.py -v
"""

from __future__ import annotations

from collections import Counter

from app.security.behavior_profiling import BehaviorResult, evaluate_behavior
from app.security.iforest_scorer import IForestResult
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, RuleResult


def base_vec(hour=12.0):
    v = [0.0] * 23
    v[FEAT["hour_of_day"]] = hour
    v[FEAT["day_of_week"]] = 2.0
    v[FEAT["is_thailand"]] = 1.0
    v[FEAT["permission_change_age"]] = 365.0
    return v


def profile(hours, subs):
    """สร้าง profile แบบใหม่ (มี hour_counts + subsystem_counts)."""
    return {
        "typical_hour": 8,
        "typical_weekend": 0,
        "session_count": sum(hours.values()),
        "hour_counts": dict(hours),
        "subsystem_counts": dict(subs),
        "seen_subsystems": set(subs),
        "total": sum(hours.values()),
    }


# ── ผู้ใช้กลางวัน (peak 8-9), ใช้ SUB_A เป็นหลัก + HUB บ้าง ──
DAYTIME = profile(
    hours=Counter({8: 800, 9: 700, 13: 400, 16: 300, 10: 200, 14: 200}),
    subs={"SUB_A": 2400, "HUB": 200},
)


# ── hour_rarity: ชั่วโมงปกติ (peak) ต้องไม่ยิง ──
def test_normal_hour_no_rarity():
    r = evaluate_behavior(base_vec(hour=8.0), DAYTIME, subsystem_id="SUB_A")
    assert not any("hour_rarity" in x for x in r.reasons)


# ── hour_rarity: ชั่วโมงที่ไม่เคยเข้า (ตี 3) ต้องยิง ──
def test_offhour_fires_rarity():
    r = evaluate_behavior(base_vec(hour=3.0), DAYTIME, subsystem_id="SUB_A")
    assert any("hour_rarity" in x for x in r.reasons)
    assert r.score >= 0.30


# ── subsystem_lateral: เข้าระบบที่ไม่เคยใช้ (SUB_B) → challenge floor ──
def test_new_subsystem_forces_challenge():
    r = evaluate_behavior(base_vec(hour=8.0), DAYTIME, subsystem_id="SUB_B")
    assert r.min_action == "challenge"
    assert any("subsystem" in x for x in r.reasons)


# ── subsystem ที่ใช้ประจำ (SUB_A) → ไม่ยิง ──
def test_common_subsystem_no_signal():
    r = evaluate_behavior(base_vec(hour=8.0), DAYTIME, subsystem_id="SUB_A")
    assert r.min_action is None
    assert not any("subsystem" in x for x in r.reasons)


# ── subsystem ที่ใช้นานๆ ที (HUB, legit) → soft เท่านั้น ไม่ถึง challenge ──
def test_rare_but_seen_subsystem_soft():
    r = evaluate_behavior(base_vec(hour=8.0), DAYTIME, subsystem_id="HUB")
    assert r.min_action is None  # เคยใช้ = ไม่บังคับ challenge


# ── policy floor ทะลุถึง decision จริง ──
def _decide(v, sub):
    beh = evaluate_behavior(v, DAYTIME, subsystem_id=sub)
    rule = RuleResult(blocked=False, score=0.0, reasons=[])
    ifr = IForestResult(raw_score=0.0, risk_score=0.0, label="normal")
    return aggregate(rule, beh, ifr).decision


def test_lateral_reaches_challenge_end_to_end():
    assert _decide(base_vec(hour=8.0), "SUB_B") == "challenge"


def test_normal_stays_allow():
    assert _decide(base_vec(hour=8.0), "SUB_A") == "allow"


# ── backward compat: profile แบบเก่า (ไม่มี hour_counts) ต้องไม่พัง ──
def test_old_profile_no_crash():
    old = {"typical_hour": 8, "typical_weekend": 0, "session_count": 100}
    r = evaluate_behavior(base_vec(hour=3.0), old, subsystem_id="SUB_B")
    assert isinstance(r, BehaviorResult)  # ไม่ crash, ข้าม rarity


# ── cold start (None) ยังทำงานเดิม ──
def test_cold_start_unchanged():
    r = evaluate_behavior(base_vec(), None)
    assert r.score == 0.20


if __name__ == "__main__":
    import sys

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
