"""Phase 1 production port — ทดสอบกฎใหม่ใน rule_engine + policy floor (TDD).

พิสูจน์ว่าฟีเจอร์ที่เดิม "ไม่มีชั้นไหนให้คะแนน" ตอนนี้มีกฎรองรับ และ deterministic
security event บังคับ min action ได้ (policy floor) — โดยไม่ทำให้ normal ถูก flag.

เทสต์แบบ pure: db=None, ip/geo/subsystem_id=None -> evaluate_rules ข้าม DB query
ทั้งหมด (ทุก helper ถูก guard ด้วย if ip / if geo / if subsystem_id) เหลือแค่ feature scoring.

Run:
    py -m pytest hub/backend/tests/test_rule_engine_v2_signals.py -v
"""

from __future__ import annotations

from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import IForestResult
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, evaluate_rules


def base_vector() -> list[float]:
    """เวกเตอร์ 23 ตัวของ login ปกติ (ผู้ใช้เดิม เครื่องเดิม เวลาปกติ)."""
    v = [0.0] * 23
    v[FEAT["hour_of_day"]] = 12.0
    v[FEAT["day_of_week"]] = 2.0
    v[FEAT["is_thailand"]] = 1.0
    v[FEAT["permission_change_age"]] = 365.0  # ไม่เคยเปลี่ยนสิทธิ์
    return v


def rule_score(v: list[float]) -> float:
    return evaluate_rules(v, db=None, user_id="u", ip=None, geo_country=None).score


def rule_result(v: list[float]):
    return evaluate_rules(v, db=None, user_id="u", ip=None, geo_country=None)


# ── normal ต้องคะแนนต่ำ (FPR-safe) ──
def test_normal_vector_scores_zero():
    assert rule_score(base_vector()) == 0.0


# ── ฟีเจอร์ที่เดิมไม่มีเจ้าของ ตอนนี้ต้องให้คะแนน ──
def test_concurrent_sessions_scored():
    v = base_vector()
    v[FEAT["concurrent_session_count"]] = 3.0
    assert rule_score(v) >= 0.25


def test_lateral_active_subsystem_scored():
    v = base_vector()
    v[FEAT["active_subsystem_count"]] = 2.0
    assert rule_score(v) >= 0.20


def test_new_passkey_scored():
    v = base_vector()
    v[FEAT["new_passkey_recently_added"]] = 1.0
    assert rule_score(v) >= 0.30


def test_permission_just_changed_scored():
    v = base_vector()
    v[FEAT["permission_change_age"]] = 0.0  # เพิ่งเปลี่ยนสิทธิ์วันนี้
    assert rule_score(v) >= 0.25


def test_login_burst_scored():
    v = base_vector()
    v[FEAT["login_count_24h"]] = 15.0
    assert rule_score(v) >= 0.20


def test_login_velocity_compound_scored():
    v = base_vector()
    v[FEAT["log_minutes_since_last_login"]] = 1.0  # ล็อกอินถี่มาก
    v[FEAT["login_count_24h"]] = 6.0
    assert rule_score(v) >= 0.25


# ── permission_change_age สูง (ปกติ) ต้องไม่ยิง ──
def test_old_permission_not_scored():
    v = base_vector()
    v[FEAT["permission_change_age"]] = 200.0
    assert rule_score(v) == 0.0


# ── policy floor: deterministic event ต้องบังคับ challenge แม้คะแนนรวมไม่ถึง 0.7 ──
def _decide(v: list[float]) -> str:
    rr = rule_result(v)
    beh = BehaviorResult(score=0.0, reasons=[])
    ifr = IForestResult(raw_score=0.0, risk_score=0.0, label="normal")
    return aggregate(rr, beh, ifr).decision


def test_policy_floor_new_passkey_forces_challenge():
    v = base_vector()
    v[FEAT["new_passkey_recently_added"]] = 1.0  # rule +0.30 เท่านั้น ไม่ถึง 0.7
    assert _decide(v) == "challenge"


def test_policy_floor_permission_change_forces_challenge():
    v = base_vector()
    v[FEAT["permission_change_age"]] = 0.0
    assert _decide(v) == "challenge"


def test_policy_floor_concurrent_forces_challenge():
    v = base_vector()
    v[FEAT["concurrent_session_count"]] = 3.0
    assert _decide(v) == "challenge"


def test_normal_still_allow():
    assert _decide(base_vector()) == "allow"


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
