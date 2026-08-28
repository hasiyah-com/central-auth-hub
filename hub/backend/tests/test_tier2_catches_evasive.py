"""Tier 2 — พิสูจน์ว่า cadence + signature_rarity จับ attack "เนียน" ที่ rule global พลาด.

V2 attack เป็น single-event แรง → rule จับหมดแล้ว (Tier 2 เลยไม่เพิ่ม recall บน V2)
คุณค่าจริงของ Tier 2 คือ **graded accumulator**: signal อ่อนหลายตัวที่แต่ละตัวไม่ทริป rule/threshold
เลย แต่พอ *converge* กัน (+ iforest score เล็กน้อยที่ stealth attack มักมี) → ทะลุ `warn`
เผยตัว attack ให้ monitor ได้ ขณะที่ไม่มี Tier 2 = allow เงียบ

soft signal ตัวเดียวไม่ทะลุ threshold เอง (จงใจ — กัน FPR) — ต้อง converge

Run: py hub/backend/tests/test_tier2_catches_evasive.py
"""

from __future__ import annotations

from app.security.behavior_profiling import evaluate_behavior
from app.security.iforest_scorer import IForestResult
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, evaluate_rules

RANK = {"allow": 0, "warn": 1, "challenge": 2, "block": 3}
SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537"

# ผู้ใช้ที่ปกติ login ห่างเป็นวัน (median ln(gap)=8 ~2 วัน) ใช้เครื่อง chrome เป็นหลัก
SLOW_USER = {
    "typical_hour": 12,
    "typical_weekend": 0,
    "session_count": 120,
    "total": 120,
    "hour_counts": {12: 70, 13: 50},
    "subsystem_counts": {"SUB_A": 120},
    "seen_subsystems": {"SUB_A"},
    "gap_log_median": 8.0,
    "gap_log_scale": 1.0,
    "signature_counts": {
        "Windows 10|desktop|Chrome": 116,
        "macOS 10.15|desktop|Safari": 4,
    },
}


def vec(gap_log=8.0):
    v = [0.0] * 23
    v[FEAT["hour_of_day"]] = 12.0
    v[FEAT["day_of_week"]] = 2.0
    v[FEAT["is_thailand"]] = 1.0
    v[FEAT["permission_change_age"]] = 365.0
    v[FEAT["log_minutes_since_last_login"]] = gap_log
    v[FEAT["login_count_24h"]] = 4.0  # < 5 → rule velocity ไม่ทริป
    v[FEAT["is_new_device"]] = 0.0  # เคยเห็นเครื่อง → is_new_device rule เงียบ (B56)
    return v


def _strip(p):  # profile baseline (ไม่มี field Tier 2)
    return {
        k: v
        for k, v in p.items()
        if k not in ("gap_log_median", "gap_log_scale", "signature_counts")
    }


def decide(v, ua, mild_iforest, tier2):
    rule = evaluate_rules(v, db=None, user_id="u", ip=None, geo_country=None)
    beh = evaluate_behavior(
        v,
        SLOW_USER if tier2 else _strip(SLOW_USER),
        subsystem_id="SUB_A",
        user_agent=ua if tier2 else None,
    )
    ifr = IForestResult(raw_score=0.0, risk_score=mild_iforest, label="mild")
    return aggregate(rule, beh, ifr).decision, rule


# ── 1. personalized velocity tips a mild anomaly ──
# login ~20 นาที (gap_log=3, เหนือ rule log_min<=2) + iforest อ่อน 0.25 →
#   baseline: 0.25 = allow · +cadence 0.25 = 0.50 = warn
def test_cadence_tips_mild_anomaly_over_warn():
    v = vec(gap_log=3.0)
    base, rule = decide(v, CHROME, 0.25, tier2=False)
    full, _ = decide(v, CHROME, 0.25, tier2=True)
    assert not rule.reasons, f"rule ควรเงียบ ได้ {rule.reasons}"
    assert base == "allow"
    assert RANK[full] >= RANK["warn"], f"cadence ควร tip เป็น warn ได้ {full}"


# ── 2. signature เป็น corroborator ตัวชี้ขาดใน convergence ──
# fast cadence (0.25) + iforest อ่อน 0.15 = 0.40 (allow) → +rare device (0.15) = 0.55 (warn)
def test_signature_is_the_tipping_corroborator():
    v = vec(gap_log=3.0)
    # เปิด Tier 2 แต่ใช้ chrome (device ปกติ) → cadence 0.25 + iforest 0.15 = 0.40 allow
    no_sig, _ = decide(v, CHROME, 0.15, tier2=True)
    # เปลี่ยนเป็น safari (rare-seen) → +signature 0.15 = 0.55 warn
    with_sig, _ = decide(v, SAFARI, 0.15, tier2=True)
    assert no_sig == "allow", f"ยังไม่ควรทะลุ ได้ {no_sig}"
    assert RANK[with_sig] >= RANK["warn"], f"signature ควร tip เป็น warn ได้ {with_sig}"


# ── 3. control: login ปกติทุกอย่าง → ไม่มี false alarm ──
def test_normal_login_no_false_alarm():
    v = vec(gap_log=8.0)  # gap ปกติ
    full, _ = decide(v, CHROME, 0.0, tier2=True)
    assert full == "allow", f"login ปกติต้อง allow ได้ {full}"


# ── 4. soft signal ตัวเดียว (ไม่มี corroboration) ต้องไม่ทะลุ warn (กัน FPR) ──
def test_single_soft_signal_stays_allow():
    v = vec(gap_log=3.0)  # cadence อย่างเดียว, iforest 0
    full, _ = decide(v, CHROME, 0.0, tier2=True)
    assert full == "allow", f"cadence เดี่ยวไม่ควรทะลุ ได้ {full}"


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
