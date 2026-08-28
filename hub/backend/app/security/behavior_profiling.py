"""Layer 2 — Behavior Profiling: เทียบพฤติกรรมปัจจุบันกับ baseline ของ user 30 วัน.

อ้างอิง:
  - Wiefling et al. (2022) ACM TOPS — temporal behavior, weekend pattern
  - Freeman et al. (2016) — new device/country scoring
  - F-RBA (2024) — similarity-based feature engineering
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import LoginSession
from app.security.rule_engine import FEAT

# Cold start: ถ้ามี history < MIN_SESSIONS ให้ score คงที่
MIN_SESSIONS = 5
COLD_START_SCORE = 0.20
PROFILE_WINDOW_DAYS = 30

# ── Tier 1 (จาก V8) — rarity per-profile (สถิติล้วน ไม่ใช่ ML) ──
# แนวคิด: rarity = 1 - (count+1)/(total + N) (Laplace smoothing) — เหตุการณ์ที่ผู้ใช้
# "คนนี้" ไม่เคย/แทบไม่เคยทำ → rarity สูง. เก็บมาแก้ 2 จุดอ่อนที่ ablation พบว่าได้ 0%:
#   - hour_rarity      → off_hours (จับ multi-peak รายคน แทน median เดียว)
#   - subsystem novelty → subsystem_lateral (เข้าระบบที่ไม่เคยใช้)
HOUR_BUCKETS = 24
SUBSYSTEM_BUCKETS = 3  # HUB / SUB_A / SUB_B
# ต้องมี history พอก่อนจึงเชื่อ "ไม่เคยเข้าชั่วโมงนี้/ไม่เคยใช้ระบบนี้" (กัน false alarm ช่วง warm-up)
MIN_HISTORY_FOR_RARITY = 20
HOUR_RARITY_THRESHOLD = 0.95  # ชั่วโมงที่แทบไม่เคยเข้า (แยกจาก peak ~0.80-0.90 ได้)
HOUR_RARITY_WEIGHT = 0.30
RARE_SUBSYSTEM_SCORE = 0.15  # เคยใช้แต่นานๆ ที (soft warn) — ไม่บังคับ challenge
NEW_SUBSYSTEM_SCORE = 0.30  # ไม่เคยใช้เลย → +score และ policy floor = challenge

# ── Tier 2 — cadence z-score (velocity รายคน) + signature_rarity (device graded) ──
# soft signal ทั้งคู่ (warn-level, ไม่มี floor) = defense-in-depth เสริม rule
CADENCE_Z_THRESHOLD = 2.5  # login เร็วกว่าปกติของคนนี้ >= 2.5 IQR (z <= -2.5) → velocity
CADENCE_SCORE = 0.25  # velocity ผิดปกติรายคน = signal แรง (ยังไม่ถึง warn 0.5 เอง — กัน FPR)
SIGNATURE_RARITY_THRESHOLD = 0.90  # device ที่ "เคยเห็นแต่นานๆ ที" (ไม่นับเครื่องใหม่ล้วน)
SIGNATURE_SCORE = 0.15  # corroborator อ่อน — มีค่าเมื่อ converge กับ signal อื่น

# ── Tier 3 — scope escalation (ระดับสิทธิ์เทียบปกติ "ของคนนี้") ──
# ช่องว่างที่พบจาก holdout (exp_thr_and_gaps_2026-08-26.md): campaign รูปแบบใหม่ที่
# "ยกระดับ scope" หลบ L1/L2 ได้ 52-58% เพราะ L2 เดิมไม่มีสัญญาณเรื่องระดับสิทธิ์เลย
# (มีแต่ hour/subsystem/cadence/device) · soft signal เพราะยกระดับสิทธิ์เกิดชอบธรรมได้
MIN_HISTORY_FOR_SCOPE = 20
SCOPE_ESCALATION_MARGIN = 0.2  # ต้องเกิน p90 ของตัวเองอย่างน้อยเท่านี้ถึงนับ
SCOPE_ESCALATION_SCORE = 0.25


def _rarity(count: int, total: int, buckets: int) -> float:
    return 1.0 - (count + 1.0) / (total + buckets)


def _quantile(sorted_vals: list[float], q: float) -> float:
    """linear-interpolated quantile (numpy ไม่ต้องมี)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def _robust_center_scale(
    values: list[float], fallback: float = 1.0
) -> tuple[float, float]:
    """median + IQR (มี floor) — ทน outlier กว่า mean/std (แนวคิดจาก V8)."""
    if not values:
        return 0.0, fallback
    s = sorted(values)
    median = _quantile(s, 0.5)
    scale = _quantile(s, 0.75) - _quantile(s, 0.25)
    return median, max(fallback, scale)


@dataclass
class BehaviorResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    min_action: str | None = (
        None  # policy floor จาก behavior (subsystem ที่ไม่เคยใช้, Tier 1)
    )


def get_user_profile(db: Session, user_id: str) -> dict | None:
    """สร้าง behavior profile จาก login history 30 วัน.
    คืน None ถ้า history ไม่เพียงพอ (cold start).
    """
    since = datetime.utcnow() - timedelta(days=PROFILE_WINDOW_DAYS)
    sessions = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.created_at >= since,
        )
        .all()
    )

    if len(sessions) < MIN_SESSIONS:
        return None

    hours = [s.created_at.hour for s in sessions]
    weekends = [1 if s.created_at.weekday() >= 5 else 0 for s in sessions]

    # Mode ของ hour (เวลาที่ login บ่อยที่สุด)
    from statistics import mode as stats_mode

    try:
        typical_hour = stats_mode(hours)
    except Exception:
        typical_hour = 12  # fallback

    # ── Tier 1: histogram รายคน สำหรับ rarity (hour + subsystem) ──
    hour_counts = dict(Counter(hours))
    subsystem_counts = dict(
        Counter(s.subsystem_id for s in sessions if s.subsystem_id is not None)
    )

    # ── Tier 2: gap distribution (cadence) + device signature counts ──
    import math

    from app.services.feature_extraction import _device_signature

    ordered = sorted(sessions, key=lambda s: s.created_at)
    gap_logs = [
        math.log(max((b.created_at - a.created_at).total_seconds() / 60.0, 0.5))
        for a, b in zip(ordered, ordered[1:])
    ]
    gap_median, gap_scale = _robust_center_scale(gap_logs)
    signature_counts = dict(
        Counter(_device_signature(s.user_agent) for s in sessions if s.user_agent)
    )
    # ระดับสิทธิ์ที่ผู้ใช้คนนี้เข้าถึงเป็นปกติ (ไว้ตรวจ escalation)
    # ต้องใช้สูตรเดียวกับ feature_extraction ไม่งั้นเทียบกับ scope_sensitivity_score ไม่ตรง
    # Hub-direct (subsystem_id NULL) = 0.0
    from app.models import Subsystem
    from app.services.feature_extraction import _SCOPE_WEIGHTS

    sub_ids = {s.subsystem_id for s in sessions if s.subsystem_id is not None}
    scope_map: dict = {}
    if sub_ids:
        for sid, sc in db.query(Subsystem.id, Subsystem.scope).filter(
            Subsystem.id.in_(sub_ids)
        ):
            scope_map[sid] = (
                min(1.0, sum(_SCOPE_WEIGHTS.get(x, 0.1) for x in sc)) if sc else 0.0
            )
    scope_history = [
        0.0 if s.subsystem_id is None else scope_map.get(s.subsystem_id, 0.0)
        for s in sessions
    ]

    return {
        "typical_hour": typical_hour,
        "typical_weekend": round(sum(weekends) / len(weekends)),
        "session_count": len(sessions),
        "hour_counts": hour_counts,
        "subsystem_counts": subsystem_counts,
        "seen_subsystems": set(subsystem_counts),
        "total": len(sessions),
        "gap_log_median": gap_median,
        "gap_log_scale": gap_scale,
        "signature_counts": signature_counts,
        "scope_history": scope_history,
    }


def evaluate_behavior(
    features: list[float],
    profile: dict | None,
    subsystem_id: str | None = None,
    user_agent: str | None = None,
) -> BehaviorResult:
    """Layer 2: เทียบ features ปัจจุบันกับ user profile.
    ถ้าไม่มี profile (new user) → cold start score.

    subsystem_id: ระบบที่กำลัง login เข้า (Tier 1 — subsystem novelty รายคน).
    user_agent: UA ปัจจุบัน (Tier 2 — signature_rarity รายคน).
    """
    if profile is None:
        return BehaviorResult(
            score=COLD_START_SCORE, reasons=["no_history (cold start)"]
        )

    score = 0.0
    reasons: list[str] = []
    min_action: str | None = None

    # ── Temporal: hours from typical login time ──
    hours_diff = features[FEAT["hours_from_typical_login_time"]]
    if hours_diff >= 10:
        score += 0.40
        reasons.append(f"hours_diff={hours_diff:.1f} >= 10 (+0.40)")
    elif hours_diff >= 6:
        score += 0.20
        reasons.append(f"hours_diff={hours_diff:.1f} >= 6 (+0.20)")

    # ── Geographic: new country ──
    if features[FEAT["is_new_country"]] == 1:
        score += 0.30
        reasons.append("is_new_country (+0.30)")

    # ── Device: new device ──
    # ตัดออกจาก Layer 2 โดยตั้งใจ (B56) — is_new_device ถูกให้คะแนนที่ Rule Engine
    # (Layer 1, +0.30) อยู่แล้ว การนับซ้ำที่นี่ (+0.20) ทำให้ flag เดียวรวมเป็น 0.5 →
    # เครื่องใหม่ (หรือแค่ browser อัปเดต build) ดัน score ถึงเกณฑ์ MFA เองโดยไม่มี signal อื่น

    # ── Weekend pattern mismatch ──
    # is_weekend ถูกตัดออกจาก feature vector → derive จาก day_of_week (>=5 = เสาร์/อาทิตย์)
    current_weekend = 1 if features[FEAT["day_of_week"]] >= 5 else 0
    typical_weekend = profile.get("typical_weekend", 0)
    if int(current_weekend) != int(typical_weekend):
        score += 0.10
        reasons.append("weekend_mismatch (+0.10)")

    # ── Tier 1: hour_rarity (per-profile histogram, จับ off_hours แบบ multi-peak) ──
    # ต่างจาก hours_from_typical (median เดียว): rarity ดูจากทั้ง histogram → ผู้ใช้ที่มี
    # หลาย peak (เช้า/บ่าย/ค่ำ) ไม่ถูก flag ผิด แต่ชั่วโมงที่ไม่เคยเข้าเลย = rarity สูง
    hour_counts = profile.get("hour_counts")
    total = profile.get("total") or profile.get("session_count") or 0
    if hour_counts and total >= MIN_HISTORY_FOR_RARITY:
        h = int(features[FEAT["hour_of_day"]]) % 24
        hr = _rarity(hour_counts.get(h, 0), total, HOUR_BUCKETS)
        if hr >= HOUR_RARITY_THRESHOLD:
            score += HOUR_RARITY_WEIGHT
            reasons.append(
                f"hour_rarity={hr:.2f} (hour {h} ไม่เคยเข้า, +{HOUR_RARITY_WEIGHT:.2f})"
            )

    # ── Tier 1: subsystem novelty (เข้าระบบที่ไม่เคยใช้ = deterministic → challenge floor) ──
    sub_counts = profile.get("subsystem_counts")
    if subsystem_id and sub_counts is not None and total >= MIN_HISTORY_FOR_RARITY:
        seen = profile.get("seen_subsystems") or set(sub_counts)
        if subsystem_id not in seen:
            # ไม่เคยใช้ระบบนี้เลย → เหตุการณ์แน่นอน ไม่ใช่แค่คะแนน → policy floor
            score += NEW_SUBSYSTEM_SCORE
            min_action = "challenge"
            reasons.append(
                f"new_subsystem={subsystem_id} (ไม่เคยใช้, +{NEW_SUBSYSTEM_SCORE:.2f} floor=challenge)"
            )
        else:
            sr = _rarity(sub_counts.get(subsystem_id, 0), total, SUBSYSTEM_BUCKETS)
            if sr >= HOUR_RARITY_THRESHOLD:  # เคยใช้แต่นานๆ ที → soft warn เท่านั้น
                score += RARE_SUBSYSTEM_SCORE
                reasons.append(
                    f"subsystem_rarity={sr:.2f} ({subsystem_id} ใช้นานๆ ที, +{RARE_SUBSYSTEM_SCORE:.2f})"
                )

    # ── Tier 2: cadence z-score (velocity รายคน — personalized) ──
    # เทียบ gap ปัจจุบันกับ distribution ของ "คนนี้" (median+IQR) แทน threshold global —
    # คนที่ปกติ login ห่างเป็นวัน จู่ๆ login ถี่ = ผิดปกติสำหรับเขา แม้ไม่ทริป rule log_min<=2
    gap_scale = profile.get("gap_log_scale")
    if gap_scale and total >= MIN_HISTORY_FOR_RARITY:
        cur_gap = features[FEAT["log_minutes_since_last_login"]]
        z = (cur_gap - profile["gap_log_median"]) / gap_scale
        if z <= -CADENCE_Z_THRESHOLD:  # เร็วกว่าปกติมาก (negative = gap เล็กกว่า median)
            score += CADENCE_SCORE
            reasons.append(
                f"cadence_fast z={z:.1f} (login เร็วผิดปกติสำหรับคนนี้, +{CADENCE_SCORE:.2f})"
            )

    # ── Tier 2: signature_rarity (device ที่เคยเห็นแต่นานๆ ที) ──
    # เฉพาะ "seen-but-rare" — เครื่องใหม่ล้วน (count=0) ปล่อยให้ is_new_device rule จัดการ (B56)
    sig_counts = profile.get("signature_counts")
    if user_agent and sig_counts and total >= MIN_HISTORY_FOR_RARITY:
        from app.services.feature_extraction import _device_signature

        cur_sig = _device_signature(user_agent)
        seen = sig_counts.get(cur_sig, 0)
        if seen > 0:  # เคยเห็น → พิจารณา rarity (ไม่ทับ rule ที่ดูเครื่องใหม่)
            sig_r = _rarity(seen, total, max(len(sig_counts), 2))
            if sig_r >= SIGNATURE_RARITY_THRESHOLD:
                score += SIGNATURE_SCORE
                reasons.append(
                    f"signature_rarity={sig_r:.2f} (device เคยใช้นานๆ ที, +{SIGNATURE_SCORE:.2f})"
                )

    # ── Tier 3: scope escalation — เข้าถึงสิทธิ์สูงกว่า "ปกติของคนนี้" ──
    hist = profile.get("scope_history")
    if hist and len(hist) >= MIN_HISTORY_FOR_SCOPE:
        cur = float(features[FEAT["scope_sensitivity_score"]])
        srt = sorted(hist)
        p90 = srt[min(len(srt) - 1, int(0.9 * len(srt)))]
        if cur - p90 >= SCOPE_ESCALATION_MARGIN:
            score += SCOPE_ESCALATION_SCORE
            reasons.append(
                f"scope_escalation {cur:.2f} > p90 {p90:.2f} ของคนนี้ "
                f"(+{SCOPE_ESCALATION_SCORE:.2f})"
            )

    return BehaviorResult(score=min(score, 1.0), reasons=reasons, min_action=min_action)
