"""L3 sequence channel (config F) — per-user joint-residual anomaly เป็น "ธงเฝ้าระวัง".

ที่มา: tests/reports/l3_sequence_channel_2026-08-26.md
  - L3 บวกคะแนนเข้า aggregate ไม่เวิร์ค (คะแนน stealth ต่ำเกินกว่า bonus 0.15 จะดันถึง warn)
  - เปลี่ยนเป็น surfacing channel (ยิง = warn ตรง) -> campaign surfaced 41%->58% (+16.4pp)
    โดย challenge FPR ไม่ขยับ (1.6%) = ไม่กระทบ UX

กฎที่ test นี้ยึด:
  - ยิงได้สูงสุดแค่ warn (ห้ามแตะ challenge/block — ปล่อยให้ L1/L2 ตัดสิน friction)
  - abstain เมื่อ history < TIER_DIAGNOSTIC · tier กำหนดว่าทำอะไรได้ (แผน §5)
  - fail-safe (B21): input พังต้องไม่ raise
  - default ปิด (settings.l3_sequence_enabled = False) -> ไม่เปลี่ยนพฤติกรรมเดิม

Run: py -m pytest hub/backend/tests/test_l3_sequence.py -v  (หรือรันตรง)
"""

from __future__ import annotations

import random

import pytest

from app.security import l3_sequence as L3

# hub-backend ไม่มี numpy/sklearn โดยตั้งใจ (ML แยกอยู่ ml-service) — ส่วนตัวเลขจึง skip ที่นั่น
# แต่ pure-python (residual/channel/fail-safe) ต้องผ่านทุกที่ เพราะรันจริงใน hub-backend
HAS_ML = L3._numeric() is not None
needs_ml = pytest.mark.skipif(
    not HAS_ML, reason="ต้องมี numpy/sklearn (มีเฉพาะ ml-service)"
)


def normal_raw(rng, n):
    """history ปกติของคนหนึ่ง: gap ~ln(120นาที), scope คงที่, ไม่มี drift."""
    out = []
    for _ in range(n):
        out.append(
            [
                rng.gauss(4.8, 0.35),  # gap_log (~2 ชม.)
                0.8 + rng.gauss(0, 0.02),  # scope
                rng.gauss(5.0, 0.15),  # passkey_age_log
                rng.gauss(0.3, 0.05),  # weekday_usage
                rng.gauss(1.0, 0.4),  # hours_from_typical
                rng.gauss(0.05, 0.02),  # subsystem_rarity
            ]
        )
    return out


def campaign_window(rng):
    """campaign: ทุกมิติ drift ร่วมกันทีละน้อย (แต่ละตัวไม่แรงพอให้ rule ยิง)."""
    return [
        [
            4.8 - 0.55 * k + rng.gauss(0, 0.05),  # cadence เร็วขึ้นเรื่อยๆ
            0.8 + 0.06 * k,  # scope ไต่
            5.0 + 0.10 * k,
            0.3 + 0.07 * k,
            1.0 + 0.7 * k,  # เวลาเบี่ยงขึ้น
            0.05 + 0.09 * k,
        ]
        for k in range(L3.WINDOW)
    ]


def fitted(rng, n=2000):
    """ผู้ใช้ที่ history เยอะพอให้ L3 มีผลจริง (>= TIER_CHALLENGE)."""
    hist = normal_raw(rng, n)
    return L3.fit_user_model(hist), hist


# ── cold start: history น้อยกว่า tier ต่ำสุด → abstain (ไม่ fit เลย) ──
@needs_ml
def test_cold_start_abstains():
    rng = random.Random(1)
    assert L3.fit_user_model(normal_raw(rng, L3.TIER_DIAGNOSTIC - 1)) is None


# ── history พอ → fit ได้ ──
@needs_ml
def test_fits_with_enough_history():
    rng = random.Random(2)
    model, _ = fitted(rng)
    assert model is not None


# ── normal window → ไม่ยิง (คุม FPR) ──
@needs_ml
def test_normal_window_does_not_fire():
    rng = random.Random(3)
    model, hist = fitted(rng)
    fired = sum(
        L3.evaluate_window(model, hist[i - L3.WINDOW : i]).fired
        for i in range(L3.WINDOW, 200)
    )
    assert fired / (200 - L3.WINDOW) <= 0.05, f"normal ยิงบ่อยเกิน: {fired}"


# ── campaign window → ยิง ──
@needs_ml
def test_campaign_window_fires():
    rng = random.Random(4)
    model, _ = fitted(rng)
    res = L3.evaluate_window(model, campaign_window(rng))
    assert res.fired
    assert res.reason == "multivariate_behavioral_anomaly"


# ── ยิงได้สูงสุดแค่ warn — ห้ามแตะ challenge/block ──
@needs_ml
def test_never_escalates_beyond_warn():
    rng = random.Random(5)
    model, _ = fitted(rng)
    res = L3.evaluate_window(model, campaign_window(rng))
    assert L3.apply_channel("allow", res) == "warn"
    assert L3.apply_channel("warn", res) == "warn"
    assert L3.apply_channel("challenge", res) == "challenge"  # ไม่ลด ไม่เพิ่ม
    assert L3.apply_channel("block", res) == "block"


# ── ไม่ยิง → decision เดิมไม่เปลี่ยน ──
def test_no_fire_keeps_decision():
    quiet = L3.L3Result(fired=False, score=0.0, reason=None)
    for d in ("allow", "warn", "challenge", "block"):
        assert L3.apply_channel(d, quiet) == d


# ── fail-safe (B21): input พัง ต้องไม่ raise ──
def test_failsafe_on_bad_input():
    assert L3.fit_user_model([]) is None
    assert L3.fit_user_model([[1.0, 2.0]] * 10) is None  # มิติไม่ครบ
    rng = random.Random(6)
    assert L3.evaluate_window(None, campaign_window(rng)).fired is False  # ไม่มีโมเดล
    if not HAS_ML:
        return
    model, _ = fitted(rng)
    assert L3.evaluate_window(model, []).fired is False  # window ว่าง
    assert L3.evaluate_window(model, [[float("nan")] * 6] * L3.WINDOW).fired is False


# ── residual vector: สร้างจาก features+profile ได้ครบ 6 มิติ ──
def test_residual_vector_shape():
    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["log_minutes_since_last_login"]] = 4.5
    v[FEAT["scope_sensitivity_score"]] = 0.8
    v[FEAT["passkey_age_days"]] = 30.0
    v[FEAT["weekday_usage_score"]] = 0.3
    v[FEAT["hours_from_typical_login_time"]] = 1.0
    prof = {
        "total": 100,
        "subsystem_counts": {"SUB_A": 100},
        "seen_subsystems": {"SUB_A"},
    }
    r = L3.residual_raw(v, prof, subsystem_id="SUB_A")
    assert r is not None and len(r) == L3.DIMS


# ══════════════════════════════════════════════════════════════════════
# แผน l3_isolation_forest_redesign §4/§5/§7/§9 — tier, eligibility, contract
# ══════════════════════════════════════════════════════════════════════


# ── §5 abstention tiers ตามจำนวน trusted history ──
def test_eligibility_tiers():
    assert L3.eligibility(0) == "abstain"
    assert L3.eligibility(L3.TIER_DIAGNOSTIC - 1) == "abstain"
    assert (
        L3.eligibility(L3.TIER_DIAGNOSTIC) == "diagnostic"
    )  # ให้คะแนนแต่ไม่มีผลต่อ decision
    assert L3.eligibility(L3.TIER_WARN) == "warn"  # ยก warn ได้
    assert (
        L3.eligibility(L3.TIER_CHALLENGE) == "challenge"
    )  # พิจารณา would_challenge (shadow)


# ── diagnostic tier: ยิงได้แต่ต้องไม่เปลี่ยน decision ──
@needs_ml
def test_diagnostic_tier_does_not_change_decision():
    rng = random.Random(11)
    model = L3.fit_user_model(normal_raw(rng, 2000), n_history=L3.TIER_DIAGNOSTIC)
    res = L3.evaluate_window(model, campaign_window(rng))
    assert res.fired  # ยังคำนวณ/บันทึกได้
    assert L3.apply_channel("allow", res) == "allow"  # แต่ไม่มีผล


# ── §4 two-tier threshold: extreme (99.9th) แยกจาก anomaly (99th) ──
@needs_ml
def test_two_tier_threshold_and_shadow_decision():
    rng = random.Random(12)
    model, _ = fitted(rng)
    res = L3.evaluate_window(model, campaign_window(rng))
    assert res.tier in ("anomaly", "extreme")
    assert res.shadow_decision in ("would_warn", "would_challenge")
    # extreme ที่ eligibility=challenge -> shadow บอก would_challenge
    if res.tier == "extreme":
        assert res.shadow_decision == "would_challenge"


# ── ความปลอดภัย: แม้ tier=extreme ก็ยก decision จริงได้แค่ warn (ไม่มี friction) ──
@needs_ml
def test_extreme_still_capped_at_warn_in_production():
    rng = random.Random(13)
    model, _ = fitted(rng)
    res = L3.evaluate_window(model, campaign_window(rng))
    assert L3.apply_channel("allow", res) in ("allow", "warn")
    assert L3.apply_channel("challenge", res) == "challenge"


# ── §9 data contract: มีฟิลด์ครบสำหรับ log/replay ──
@needs_ml
def test_contract_fields_present():
    rng = random.Random(14)
    model, _ = fitted(rng)
    res = L3.evaluate_window(model, campaign_window(rng))
    c = L3.to_contract(res, model)
    for k in (
        "eligible",
        "eligibility",
        "raw_score",
        "percentile",
        "decision",
        "tier",
        "model_version",
        "n_history",
    ):
        assert k in c, f"ขาดฟิลด์ {k}"
    assert 0.0 <= c["percentile"] <= 1.0
    assert c["model_version"] == L3.MODEL_VERSION


# ── contract ตอน abstain (ไม่มีโมเดล) ต้องไม่พัง ──
def test_contract_when_abstain():
    c = L3.to_contract(L3.L3Result(fired=False, score=0.0), None)
    assert c["eligible"] is False and c["decision"] is None


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
