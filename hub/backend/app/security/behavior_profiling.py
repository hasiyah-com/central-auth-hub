"""Layer 2 — Behavior Profiling: เทียบพฤติกรรมปัจจุบันกับ baseline ของ user 30 วัน.

อ้างอิง:
  - Wiefling et al. (2022) ACM TOPS — temporal behavior, weekend pattern
  - Freeman et al. (2016) — new device/country scoring
  - F-RBA (2024) — similarity-based feature engineering
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import LoginSession
from app.security.rule_engine import FEAT

# Cold start: ถ้ามี history < MIN_SESSIONS ให้ score คงที่
MIN_SESSIONS = 5
COLD_START_SCORE = 0.20
PROFILE_WINDOW_DAYS = 30


@dataclass
class BehaviorResult:
    score: float
    reasons: list[str] = field(default_factory=list)


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

    return {
        "typical_hour": typical_hour,
        "typical_weekend": round(sum(weekends) / len(weekends)),
        "session_count": len(sessions),
    }


def evaluate_behavior(features: list[float], profile: dict | None) -> BehaviorResult:
    """Layer 2: เทียบ features ปัจจุบันกับ user profile.
    ถ้าไม่มี profile (new user) → cold start score.
    """
    if profile is None:
        return BehaviorResult(
            score=COLD_START_SCORE, reasons=["no_history (cold start)"]
        )

    score = 0.0
    reasons: list[str] = []

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
    if features[FEAT["is_new_device"]] == 1:
        score += 0.20
        reasons.append("is_new_device (+0.20)")

    # ── Weekend pattern mismatch ──
    # is_weekend ถูกตัดออกจาก feature vector → derive จาก day_of_week (>=5 = เสาร์/อาทิตย์)
    current_weekend = 1 if features[FEAT["day_of_week"]] >= 5 else 0
    typical_weekend = profile.get("typical_weekend", 0)
    if int(current_weekend) != int(typical_weekend):
        score += 0.10
        reasons.append("weekend_mismatch (+0.10)")

    return BehaviorResult(score=min(score, 1.0), reasons=reasons)
