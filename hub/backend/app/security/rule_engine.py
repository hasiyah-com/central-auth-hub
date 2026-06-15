"""Layer 1 — Rule Engine: hard block + risk score จากกฎตายตัว.

จับ known attacks ทันที ไม่ต้องรอ ML.

อ้างอิง:
  - NIST SP 800-63B-4 (2024) — failed login threshold, lockout policy
  - Freeman et al. (2016) — new device/country scoring weights
  - Microsoft Entra ID Protection (2024) — impossible travel
  - Wiefling et al. (2022) — country change pattern
  - OWASP API Security Top 10 (2023) — credential stuffing (API4)
  - Laperdrix et al. (2020) — UA family change signal
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import LoginSession
from app.services.ip_blacklist import is_blacklisted

# ============ Feature index mapping (ต้องตรงกับ feature_extraction.py + features.py) ============
# ⚠️ B27: ลำดับนี้คือ contract — แก้ feature order ที่ feature_extraction.py แล้ว
# ต้องอัปเดต map นี้ด้วย (rule_engine + behavior_profiling อ่าน feature ตาม index)

FEAT = {
    "hour_of_day": 0,
    "day_of_week": 1,
    "hours_from_typical_login_time": 2,
    "is_thailand": 3,
    "is_new_country": 4,
    "country_change_count_30d": 5,
    "is_new_device": 6,
    "is_new_user_agent_family": 7,
    "log_minutes_since_last_login": 8,
    "login_count_24h": 9,
    "failed_logins_24h": 10,
    "passkey_count": 11,
    "passkey_age_days": 12,
    "new_passkey_recently_added": 13,
    "passkey_last_used_days": 14,
    "concurrent_session_count": 15,
    "active_subsystem_count": 16,
    "weekday_usage_score": 17,
    "scope_sensitivity_score": 18,
    "ever_changed_permission": 19,
    "permission_change_age": 20,
    "confirmed_incident_count": 21,
}

# ============ Thresholds ============

HARD_BLOCK_RULES = [
    ("failed_logins_24h", ">=", 10),
    ("login_count_24h", ">=", 50),
    ("country_change_count_30d", ">=", 8),
]

SCORE_RULES = [
    ("is_new_device", "==", 1, 0.30),
    ("is_new_country", "==", 1, 0.30),
    ("is_new_user_agent_family", "==", 1, 0.20),
    ("failed_logins_24h", ">=", 3, 0.20),
    ("is_thailand", "==", 0, 0.10),
]

# Multiple accounts from same IP
MULTI_ACCOUNT_THRESHOLD = 5  # > 5 distinct users from same IP in 1 hour
MULTI_ACCOUNT_SCORE = 0.25
MULTI_ACCOUNT_WINDOW_SEC = 3600  # 1 hour

# Impossible travel
IMPOSSIBLE_TRAVEL_WINDOW_SEC = 3600  # country change within 1 hour


@dataclass
class RuleResult:
    blocked: bool
    score: float
    reasons: list[str] = field(default_factory=list)


def evaluate_rules(
    features: list[float],
    db: Session,
    user_id: str,
    ip: str | None,
    geo_country: str | None,
) -> RuleResult:
    """Layer 1: ประเมินกฎตายตัว → hard block หรือ risk score."""

    # ── IP Blacklist check ──
    if ip and is_blacklisted(db, ip):
        return RuleResult(
            blocked=True,
            score=1.0,
            reasons=[f"ip_blacklisted ({ip})"],
        )

    # ── Impossible Travel ──
    if geo_country and ip:
        impossible = _check_impossible_travel(db, user_id, geo_country)
        if impossible:
            return RuleResult(
                blocked=True,
                score=1.0,
                reasons=[impossible],
            )

    # ── Hard Block rules (from features) ──
    for feat_name, op, threshold in HARD_BLOCK_RULES:
        value = features[FEAT[feat_name]]
        if op == ">=" and value >= threshold:
            return RuleResult(
                blocked=True,
                score=1.0,
                reasons=[f"{feat_name}={value:.0f} >= {threshold} (hard block)"],
            )

    # ── Risk Score rules ──
    score = 0.0
    reasons: list[str] = []

    for feat_name, op, threshold, weight in SCORE_RULES:
        value = features[FEAT[feat_name]]
        hit = (op == ">=" and value >= threshold) or (op == "==" and value == threshold)
        if hit:
            score += weight
            reasons.append(f"{feat_name} (+{weight})")

    # ── Multiple accounts from same IP ──
    if ip:
        multi = _check_multi_account_ip(db, ip)
        if multi > MULTI_ACCOUNT_THRESHOLD:
            score += MULTI_ACCOUNT_SCORE
            reasons.append(
                f"multi_account_ip={multi} > {MULTI_ACCOUNT_THRESHOLD} (+{MULTI_ACCOUNT_SCORE})"
            )

    return RuleResult(blocked=False, score=min(score, 1.0), reasons=reasons)


# ============ Helpers ============


def _check_impossible_travel(
    db: Session, user_id: str, current_country: str
) -> str | None:
    """เช็คว่า user เปลี่ยนประเทศใน < 1 ชม. (impossible travel).
    คืน reason string ถ้า impossible, None ถ้าปกติ.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=IMPOSSIBLE_TRAVEL_WINDOW_SEC)
    last_session = (
        db.query(LoginSession)
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.created_at >= cutoff,
            LoginSession.geo_country.is_not(None),
        )
        .order_by(LoginSession.created_at.desc())
        .first()
    )
    if not last_session:
        return None
    if not last_session.geo_country:
        return None
    if last_session.geo_country.lower() == current_country.lower():
        return None

    time_diff = datetime.utcnow() - last_session.created_at
    hours = time_diff.total_seconds() / 3600

    return (
        f"impossible_travel: {last_session.geo_country} → {current_country} "
        f"in {hours:.1f}h (< 1h)"
    )


def _check_multi_account_ip(db: Session, ip: str) -> int:
    """นับจำนวน distinct user_id จาก IP เดียวกันใน 1 ชม."""
    cutoff = datetime.utcnow() - timedelta(seconds=MULTI_ACCOUNT_WINDOW_SEC)
    result = (
        db.query(func.count(func.distinct(LoginSession.user_id)))
        .filter(
            LoginSession.ip == ip,
            LoginSession.created_at >= cutoff,
        )
        .scalar()
    )
    return result or 0
