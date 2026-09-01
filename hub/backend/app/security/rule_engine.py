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

from app.config import settings
from app.models import LoginSession
from app.services.ip_blacklist import is_blacklisted

# policy floor ranking (ใช้แปลง min action <-> อันดับ)
_ACTION_RANK = {"warn": 1, "challenge": 2, "block": 3}
_RANK_ACTION = {v: k for k, v in _ACTION_RANK.items()}

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
    "impossible_travel_score": 22,
}

# ============ Thresholds ============

HARD_BLOCK_RULES = [
    ("failed_logins_24h", ">=", 10),
    ("login_count_24h", ">=", 50),
    ("country_change_count_30d", ">=", 8),
]

# ── กฎของ L1 — ต้องประกาศ `kind` ให้ชัดทุกข้อ ห้ามอนุมาน ──
#
# kind = "policy_floor"   ข้อเท็จจริงที่ตรวจได้แน่นอน -> บังคับ step-up เสมอ
#                         (Policy Gate เป็นผู้บังคับ ไม่ใช่ชั้นให้คะแนน)
# kind = "risk_evidence"  เพิ่มน้ำหนักหลักฐานอย่างเดียว ให้ L4 ตัดสิน
#
# **ทำไมต้องประกาศแทนการอนุมานจาก min_action:** ถ้าอนุมานว่า "กฎที่มี min_action
# = policy floor" การแก้น้ำหนักคะแนนของกฎใดกฎหนึ่งจะเปลี่ยนนโยบายการเข้าถึงไปด้วย
# โดยไม่มีใครตั้งใจ · ตัวอย่างจริง: `impossible_travel_score` เคยถูกอนุมานเป็น
# policy floor ทั้งที่เป็นการ **อนุมาน** (VPN / roaming / GeoIP คลาดเคลื่อน)
# จึงต้องเป็นหลักฐาน ไม่ใช่ข้อบังคับ
SCORE_RULES_SPEC = [
    # ── Device — ข้อเท็จจริงตายตัว ──
    {
        "id": "new_device",
        "feature": "is_new_device",
        "op": "==",
        "threshold": 1,
        "weight": 0.30,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    {
        "id": "new_ua_family",
        "feature": "is_new_user_agent_family",
        "op": "==",
        "threshold": 1,
        "weight": 0.20,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    # ── Geo ──
    {
        "id": "new_country",
        "feature": "is_new_country",
        "op": "==",
        "threshold": 1,
        "weight": 0.30,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    {
        "id": "foreign",
        "feature": "is_thailand",
        "op": "==",
        "threshold": 0,
        "weight": 0.10,
        "kind": "risk_evidence",
        "min_action": None,
    },
    # การอนุมาน ไม่ใช่ข้อเท็จจริง -> หลักฐาน (แก้ 2 ก.ย. 2569)
    {
        "id": "impossible_travel",
        "feature": "impossible_travel_score",
        "op": ">=",
        "threshold": 0.5,
        "weight": 0.30,
        "kind": "risk_evidence",
        "min_action": None,
    },
    # ── Brute force ──
    {
        "id": "failed_5",
        "feature": "failed_logins_24h",
        "op": ">=",
        "threshold": 5,
        "weight": 0.30,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    {
        "id": "failed_3",
        "feature": "failed_logins_24h",
        "op": ">=",
        "threshold": 3,
        "weight": 0.20,
        "kind": "risk_evidence",
        "min_action": None,
    },
    # ── Velocity ──
    {
        "id": "login_burst",
        "feature": "login_count_24h",
        "op": ">=",
        "threshold": 15,
        "weight": 0.20,
        "kind": "risk_evidence",
        "min_action": None,
    },
    # ── Session ──
    {
        "id": "concurrent",
        "feature": "concurrent_session_count",
        "op": ">=",
        "threshold": 3,
        "weight": 0.25,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    {
        "id": "lateral",
        "feature": "active_subsystem_count",
        "op": ">=",
        "threshold": 2,
        "weight": 0.20,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    # ── Credential ──
    {
        "id": "new_passkey",
        "feature": "new_passkey_recently_added",
        "op": "==",
        "threshold": 1,
        "weight": 0.30,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    # ── Privilege ──
    {
        "id": "perm_fresh",
        "feature": "permission_change_age",
        "op": "<=",
        "threshold": 1,
        "weight": 0.25,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
    {
        "id": "perm_recent",
        "feature": "permission_change_age",
        "op": "<=",
        "threshold": 7,
        "weight": 0.10,
        "kind": "risk_evidence",
        "min_action": None,
    },
    # ── History — label จริงจากผู้ดูแล ──
    {
        "id": "prior_incident",
        "feature": "confirmed_incident_count",
        "op": ">=",
        "threshold": 1,
        "weight": 0.40,
        "kind": "policy_floor",
        "min_action": "challenge",
    },
]

RULE_KINDS = ("policy_floor", "risk_evidence")

# รูปแบบ tuple เดิม — คงไว้ให้โค้ดที่มีอยู่ใช้ต่อได้ (derive จาก spec ไม่พิมพ์ซ้ำ)
SCORE_RULES = [
    (r["feature"], r["op"], r["threshold"], r["weight"], r["min_action"])
    for r in SCORE_RULES_SPEC
]

# Multiple accounts from same IP
MULTI_ACCOUNT_THRESHOLD = 5  # > 5 distinct users from same IP in 1 hour
MULTI_ACCOUNT_SCORE = 0.25
MULTI_ACCOUNT_WINDOW_SEC = 3600  # 1 hour

# Impossible travel
IMPOSSIBLE_TRAVEL_WINDOW_SEC = 3600  # country change within 1 hour

# Cross-subsystem risk propagation — ระบบย่อยอื่นเพิ่งมี login เสี่ยง → ระบบนี้เข้มขึ้น
# (ทำเป็น rule ไม่ใช่ ML feature เพื่อเลี่ยง feedback loop: ไม่เอา risk_score ไป train)
CROSS_SUBSYSTEM_WINDOW_MIN = 30  # ดู login ของระบบอื่นใน 30 นาทีล่าสุด
CROSS_SUBSYSTEM_RISK_THRESHOLD = 0.6  # ระบบอื่นเสี่ยง >= 0.6 ถึง escalate
CROSS_SUBSYSTEM_BOOST_FACTOR = 0.3  # boost = recent_max_risk * factor (graded)


@dataclass
class RuleResult:
    blocked: bool
    score: float
    reasons: list[str] = field(default_factory=list)
    # policy floor — min action ที่บังคับแม้คะแนนรวมไม่ถึง threshold (deterministic
    # security event เช่น เครื่องใหม่/passkey ใหม่/สิทธิ์เพิ่งเปลี่ยน). None = ไม่บังคับ.
    min_action: str | None = None


def evaluate_rules(
    features: list[float],
    db: Session,
    user_id: str,
    ip: str | None,
    geo_country: str | None,
    subsystem_id=None,
) -> RuleResult:
    """Layer 1: ประเมินกฎตายตัว → hard block หรือ risk score.

    subsystem_id: ระบบย่อยที่กำลัง login (ใช้ cross-subsystem risk propagation —
    ถ้าระบบอื่นเพิ่งเสี่ยง → escalate ระบบนี้). None = Hub-direct (ไม่ propagate)
    """

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
    floor_rank = 0  # policy floor: 0=none 1=warn 2=challenge 3=block

    for feat_name, op, threshold, weight, min_act in SCORE_RULES:
        value = features[FEAT[feat_name]]
        hit = (
            (op == ">=" and value >= threshold)
            or (op == "==" and value == threshold)
            or (op == "<=" and value <= threshold)
        )
        if hit:
            score += weight
            reasons.append(f"{feat_name} (+{weight})")
            if min_act:
                floor_rank = max(floor_rank, _ACTION_RANK[min_act])

    # ── Velocity compound (B60): ล็อกอินถี่มาก + จำนวนสูง = credential stuffing/replay ──
    # ต้องเป็น compound (2 ฟีเจอร์) จึงอยู่นอก SCORE_RULES ที่เป็น single-feature
    if (
        features[FEAT["log_minutes_since_last_login"]] <= 2.0
        and features[FEAT["login_count_24h"]] >= 5
    ):
        score += 0.25
        reasons.append("login_velocity (+0.25)")
        floor_rank = max(floor_rank, _ACTION_RANK["challenge"])

    # ── Geo (เพิ่ม): login จาก "ประเทศใหม่ที่เป็นต่างประเทศ" (ไม่ใช่แค่ domestic ใหม่) ──
    # is_new_country(0.3)+is_thailand=0(0.1)+new_foreign(0.3) = 0.7 → ถึงเกณฑ์ challenge (step-up MFA)
    # แก้ปัญหา single-column country-change ที่เดิม score แค่ 0.4 (จับไม่ถึงเกณฑ์)
    if features[FEAT["is_new_country"]] == 1 and features[FEAT["is_thailand"]] == 0:
        score += 0.30
        reasons.append("new_foreign_country (+0.30)")

    # ── Cross-subsystem risk propagation ──
    # ระบบย่อยอื่นเพิ่งมี login เสี่ยงสูง (เช่น ระบบ 1 ได้ 0.7) → พอ user เข้าระบบนี้
    # ให้ "ระแวง" มากขึ้น (escalate). Hub เห็น login ทุกระบบใน DB เดียว → ทำได้
    if subsystem_id is not None:
        cross = _check_cross_subsystem_risk(db, user_id, subsystem_id)
        if cross:
            boost, reason = cross
            score += boost
            reasons.append(reason)

    # ── Multiple accounts from same IP ──
    # ⚠️ ปิดเมื่ออยู่หลัง campus/office NAT ร่วม (settings.shared_nat) — ทุกคนใช้ IP
    # เดียวกัน กฎนี้จะยิงใส่ login ปกติ ~26% โดยไม่ได้บ่งชี้ attack จริง (B60)
    if ip and not settings.shared_nat:
        multi = _check_multi_account_ip(db, ip)
        if multi > MULTI_ACCOUNT_THRESHOLD:
            score += MULTI_ACCOUNT_SCORE
            reasons.append(
                f"multi_account_ip={multi} > {MULTI_ACCOUNT_THRESHOLD} (+{MULTI_ACCOUNT_SCORE})"
            )

    min_action = _RANK_ACTION.get(floor_rank)
    return RuleResult(
        blocked=False, score=min(score, 1.0), reasons=reasons, min_action=min_action
    )


# ============ Helpers ============


def _check_cross_subsystem_risk(
    db: Session, user_id: str, current_subsystem_id
) -> tuple[float, str] | None:
    """ระบบย่อย *อื่น* เพิ่งมี login เสี่ยงสูงไหม (risk propagation ระหว่างระบบ).

    ดู max(risk_score) ของ login ใน subsystem อื่น (≠ current) ภายใน window.
    ถ้า >= threshold คืน (boost, reason) — boost แปรตามความเสี่ยง (graded).
    None ถ้าไม่มี/ไม่ถึงเกณฑ์.

    หมายเหตุ: ใช้ risk_score ที่ inference-time เป็น "policy" — ไม่เอาไป train โมเดล
    (เลี่ยง feedback loop). Explainable: โผล่ใน rule reasons.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=CROSS_SUBSYSTEM_WINDOW_MIN)
    recent_max = (
        db.query(func.max(LoginSession.risk_score))
        .filter(
            LoginSession.user_id == user_id,
            LoginSession.subsystem_id.is_not(None),
            LoginSession.subsystem_id != current_subsystem_id,
            LoginSession.created_at >= cutoff,
            LoginSession.risk_score.is_not(None),
        )
        .scalar()
    )
    if recent_max is None:
        return None
    recent_max = float(recent_max)
    if recent_max < CROSS_SUBSYSTEM_RISK_THRESHOLD:
        return None
    boost = round(recent_max * CROSS_SUBSYSTEM_BOOST_FACTOR, 2)
    reason = (
        f"cross_subsystem_risk: ระบบอื่นเสี่ยง {recent_max:.2f} "
        f"ใน {CROSS_SUBSYSTEM_WINDOW_MIN} นาที (+{boost})"
    )
    return boost, reason


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
