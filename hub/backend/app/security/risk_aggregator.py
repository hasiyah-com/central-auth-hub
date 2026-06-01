"""Layer 4 — Risk Aggregation: รวม score จาก 3 ชั้น → ตัดสินครั้งเดียว.

อ้างอิง:
  - Freeman et al. (2016) — risk score aggregation, decision thresholds
  - F-RBA (2024) — multi-layer scoring architecture
"""

from dataclasses import dataclass, field

from app.security.rule_engine import RuleResult
from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import IForestResult

# ============ Decision Thresholds ============

THRESHOLDS = {
    "block": 0.8,
    "challenge": 0.5,
    "warn": 0.3,
}


@dataclass
class RiskDecision:
    total_score: float
    decision: str  # block / challenge / warn / allow
    reasons: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)


def aggregate(
    rule: RuleResult,
    behavior: BehaviorResult,
    iforest: IForestResult,
    shadow_mode: bool = False,
) -> RiskDecision:
    """รวม 3 ชั้น → final decision.

    Shadow mode: เปลี่ยน block/challenge/warn เป็น would_* (ไม่บังคับจริง).
    """
    # Hard block ชนะทุกอย่าง
    if rule.blocked:
        decision = "would_block" if shadow_mode else "block"
        return RiskDecision(
            total_score=1.0,
            decision=decision,
            reasons=rule.reasons,
            breakdown={
                "rule": rule.score,
                "behavior": 0.0,
                "iforest": 0.0,
                "iforest_raw": iforest.raw_score,
            },
        )

    # Aggregate scores
    total = round(rule.score + behavior.score + iforest.risk_score, 4)
    total = min(total, 1.0)

    # Determine decision
    if total >= THRESHOLDS["block"]:
        raw_decision = "block"
    elif total >= THRESHOLDS["challenge"]:
        raw_decision = "challenge"
    elif total >= THRESHOLDS["warn"]:
        raw_decision = "warn"
    else:
        raw_decision = "allow"

    # Shadow mode prefix
    if shadow_mode and raw_decision != "allow":
        decision = f"would_{raw_decision}"
    else:
        decision = raw_decision

    return RiskDecision(
        total_score=total,
        decision=decision,
        reasons=rule.reasons + behavior.reasons,
        breakdown={
            "rule": round(rule.score, 4),
            "behavior": round(behavior.score, 4),
            "iforest": round(iforest.risk_score, 4),
            "iforest_raw": round(iforest.raw_score, 4),
        },
    )
