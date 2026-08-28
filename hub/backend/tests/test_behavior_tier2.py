"""Tier 2 (จาก V8) — cadence z-score (velocity รายคน) + signature_rarity (device graded).

soft signal ทั้งคู่ (warn-level, ไม่มี policy floor) = defense-in-depth เสริม rule:
  - cadence: `_robust_center_scale` บน gap history → จับ login ที่เร็วผิดปกติ*สำหรับคนนี้*
             (ดีกว่า rule global log_min<=2: คนที่ปกติ login ห่างเป็นวัน จู่ๆ ถี่ = ผิดปกติ)
  - signature_rarity: เฉพาะ device ที่ "เคยเห็นแต่นานๆ ที" (ไม่ทับ is_new_device rule = B56)

Run: py -m pytest hub/backend/tests/test_behavior_tier2.py -v  (หรือรันตรงๆ)
"""

from __future__ import annotations


from app.security.behavior_profiling import evaluate_behavior
from app.security.rule_engine import FEAT

WIN_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537"
MAC_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605"


def base_vec(gap_log=8.0, hour=12.0):
    v = [0.0] * 23
    v[FEAT["hour_of_day"]] = hour
    v[FEAT["day_of_week"]] = 2.0
    v[FEAT["is_thailand"]] = 1.0
    v[FEAT["permission_change_age"]] = 365.0
    v[FEAT["log_minutes_since_last_login"]] = gap_log
    return v


def profile(**over):
    p = {
        "typical_hour": 12,
        "typical_weekend": 0,
        "session_count": 100,
        "total": 100,
        "hour_counts": {12: 60, 13: 40},
        "subsystem_counts": {"SUB_A": 100},
        "seen_subsystems": {"SUB_A"},
        # gap ปกติของคนนี้: median ln(gap)=8 (~2 วัน), IQR scale 1.0
        "gap_log_median": 8.0,
        "gap_log_scale": 1.0,
        "signature_counts": {
            "Windows 10|desktop|Chrome": 95,
            "macOS 10.15|desktop|Safari": 5,
        },
    }
    p.update(over)
    return p


# ── cadence: login ห่างปกติ (gap_log ~ median) → ไม่ยิง ──
def test_normal_cadence_no_signal():
    r = evaluate_behavior(base_vec(gap_log=8.0), profile(), subsystem_id="SUB_A")
    assert not any("cadence" in x for x in r.reasons)


# ── cadence: login เร็วผิดปกติสำหรับคนนี้ (gap_log=2 << median 8) → ยิง soft ──
def test_fast_cadence_fires():
    r = evaluate_behavior(base_vec(gap_log=2.0), profile(), subsystem_id="SUB_A")
    assert any("cadence" in x for x in r.reasons)
    assert 0.10 <= r.score <= 0.30  # soft เท่านั้น
    assert r.min_action is None  # ไม่มี floor


# ── cadence: login ช้ากว่าปกติ (gap ใหญ่) → ไม่ยิง (velocity สนใจแค่เร็วเกิน) ──
def test_slow_cadence_no_signal():
    r = evaluate_behavior(base_vec(gap_log=12.0), profile(), subsystem_id="SUB_A")
    assert not any("cadence" in x for x in r.reasons)


# ── signature: เครื่องประจำ (chrome, 95%) → ไม่ยิง ──
def test_common_signature_no_signal():
    r = evaluate_behavior(
        base_vec(), profile(), subsystem_id="SUB_A", user_agent=WIN_CHROME
    )
    assert not any("signature" in x for x in r.reasons)


# ── signature: เครื่องที่เคยเห็นแต่นานๆ ที (safari 5%) → ยิง soft ──
def test_rare_seen_signature_fires():
    r = evaluate_behavior(
        base_vec(), profile(), subsystem_id="SUB_A", user_agent=MAC_SAFARI
    )
    assert any("signature" in x for x in r.reasons)
    assert r.min_action is None


# ── signature: เครื่องใหม่ล้วน (ไม่เคยเห็น) → behavior ไม่ยิง (ปล่อย is_new_device rule = B56) ──
def test_new_signature_deferred_to_rule():
    linux = "Mozilla/5.0 (X11; Linux x86_64) Firefox/121"
    r = evaluate_behavior(base_vec(), profile(), subsystem_id="SUB_A", user_agent=linux)
    assert not any("signature" in x for x in r.reasons)  # ไม่ทับ rule


# ── backward compat: profile เก่า (ไม่มี gap/signature) + ไม่ส่ง user_agent → ไม่พัง ──
def test_old_profile_and_no_ua():
    r = evaluate_behavior(
        base_vec(gap_log=2.0),
        {"typical_hour": 8, "typical_weekend": 0, "session_count": 50},
    )
    assert not any("cadence" in x or "signature" in x for x in r.reasons)


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
