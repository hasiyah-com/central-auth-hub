"""L2 scope escalation — เข้าถึงระดับสิทธิ์สูงกว่าที่ "คนนี้" ใช้เป็นปกติ.

ที่มา: tests/reports/exp_thr_and_gaps_2026-08-26.md
  campaign รูปแบบใหม่ (unseen holdout) หลบ L1/L2 ได้ 29-58% โดยสัญญาณที่ได้มีแค่
  weekend_mismatch (+0.10) ซึ่งอ่อนเกินไป · ตัวที่พลาดมากสุดคือ
    u_subsystem_shuffle 58% · u_scope_only 52%  -> ทั้งคู่ "ยกระดับ scope"

L2 เดิมมี: hour rarity · subsystem novelty/rarity · cadence · device signature
แต่ **ไม่มีอะไรวัด "ระดับสิทธิ์ที่เข้าถึง เทียบกับปกติของคนนั้น"** -> ช่องว่างจริง

กฎที่ยึด: soft signal (ไม่ใช่ floor) เพราะการยกระดับสิทธิ์เกิดขึ้นชอบธรรมได้
Run: py hub/backend/tests/test_behavior_scope_escalation.py
"""

from __future__ import annotations

from app.security.behavior_profiling import evaluate_behavior
from app.security.rule_engine import FEAT


def vec(scope: float):
    v = [0.0] * 23
    v[FEAT["hour_of_day"]] = 12.0
    v[FEAT["day_of_week"]] = 2.0
    v[FEAT["is_thailand"]] = 1.0
    v[FEAT["permission_change_age"]] = 365.0
    v[FEAT["scope_sensitivity_score"]] = scope
    return v


def profile(scopes, **over):
    """โปรไฟล์ที่มีประวัติ scope ของคนนี้."""
    p = {
        "typical_hour": 12,
        "typical_weekend": 0,
        "session_count": len(scopes),
        "total": len(scopes),
        "hour_counts": {12: len(scopes)},
        "subsystem_counts": {"HUB": len(scopes)},
        "seen_subsystems": {"HUB", "SUB_A"},
        "scope_history": list(scopes),
    }
    p.update(over)
    return p


# ผู้ใช้ที่อยู่กับ HUB (scope 0.0) เป็นปกติ
HUB_ONLY = profile([0.0] * 200)
# ผู้ใช้ที่ใช้หลายระดับอยู่แล้ว
MIXED = profile([0.0] * 60 + [0.6] * 70 + [0.8] * 70)


# ── ยกระดับสิทธิ์เกินปกติของคนนี้ → ยิง ──
def test_scope_escalation_fires():
    r = evaluate_behavior(vec(0.8), HUB_ONLY, subsystem_id="SUB_A")
    assert any("scope" in x for x in r.reasons), f"ควรยิง แต่ได้ {r.reasons}"


# ── อยู่ในระดับปกติของตัวเอง → ไม่ยิง ──
def test_normal_scope_no_signal():
    r = evaluate_behavior(vec(0.0), HUB_ONLY, subsystem_id="HUB")
    assert not any("scope" in x for x in r.reasons)


# ── คนที่ใช้หลายระดับอยู่แล้ว → ไม่ยิง (ไม่ลงโทษพฤติกรรมปกติของเขา) ──
def test_mixed_user_not_penalized():
    r = evaluate_behavior(vec(0.8), MIXED, subsystem_id="SUB_A")
    assert not any("scope" in x for x in r.reasons), f"ไม่ควรยิง ได้ {r.reasons}"


# ── soft เท่านั้น — ห้ามตั้ง policy floor (การยกระดับสิทธิ์เกิดชอบธรรมได้) ──
def test_soft_only_no_floor():
    r = evaluate_behavior(vec(0.8), HUB_ONLY, subsystem_id="SUB_A")
    assert r.min_action is None
    assert r.score < 0.5, "ยิงเดี่ยวต้องไม่ถึง warn เอง"


# ── ไม่มี scope_history (profile เก่า) → ไม่พัง ──
def test_backward_compat_no_history():
    old = {"typical_hour": 12, "typical_weekend": 0, "session_count": 100}
    r = evaluate_behavior(vec(0.8), old, subsystem_id="SUB_A")
    assert not any("scope" in x for x in r.reasons)


# ── history น้อยเกิน → ไม่ยิง (ยังไม่รู้ว่าปกติของเขาคืออะไร) ──
def test_short_history_abstains():
    r = evaluate_behavior(vec(0.8), profile([0.0] * 5), subsystem_id="SUB_A")
    assert not any("scope" in x for x in r.reasons)


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
