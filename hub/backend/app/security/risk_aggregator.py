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

# Calibrated จาก real-data (Phase 2.1, scripts/calibrate_thresholds.py):
# ML-driven normal score p90=0.6 p95=0.7 → challenge 0.7 ทำให้ FPR 24%→5.8%
# (เดิม block 0.8/challenge 0.5/warn 0.3 ทำ FPR สูงบน real data)
THRESHOLDS = {
    "block": 0.85,
    "challenge": 0.7,
    "warn": 0.5,
}

# block ต้องมีหลักฐาน — คะแนนรวมถึงเกณฑ์ block แต่ไม่มีกฎ hard block ยิง → challenge
SCORE_BLOCK_CAPPED_REASON = "score_block_capped (ไม่มีหลักฐาน hard block → challenge)"

# ลำดับความเข้มของ decision (ใช้บังคับ policy floor)
_ACTION_ORDER = ["allow", "warn", "challenge", "block"]


def _max_action(a: str, b: str) -> str:
    """คืน action ที่เข้มกว่าระหว่าง a, b."""
    return a if _ACTION_ORDER.index(a) >= _ACTION_ORDER.index(b) else b


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

    Shadow mode: observe block only; challenge still requires authentication.
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
    # คะแนนถึงเกณฑ์ block แต่ไม่มีกฎ hard block ยิง (ถ้ายิงจะออกไปตั้งแต่ rule.blocked
    # ด้านบน) → challenge: คะแนนรวมจากพฤติกรรม (ผิดเวลา ระบบย่อยใหม่ scope สูง)
    # ไม่ใช่หลักฐานการโจมตี · คะแนนยังบันทึกตามจริง
    score_block_capped = total >= THRESHOLDS["block"]
    if score_block_capped:
        raw_decision = "challenge"
    elif total >= THRESHOLDS["challenge"]:
        raw_decision = "challenge"
    elif total >= THRESHOLDS["warn"]:
        raw_decision = "warn"
    else:
        raw_decision = "allow"

    # ── Policy floor (B60) ──
    # Confirmed/compound signals (contextual change, concurrent, velocity)
    # enforce the evaluated min action even below the score threshold —
    # ไม่งั้นเหตุการณ์ที่ควร step-up ถูกลดเหลือ allow เพราะขาดคะแนนจากชั้นอื่น
    if getattr(rule, "min_action", None):
        raw_decision = _max_action(raw_decision, rule.min_action)
    # behavior layer ก็ตั้ง floor ได้ (subsystem ที่ไม่เคยใช้ = deterministic fact, Tier 1)
    if getattr(behavior, "min_action", None):
        raw_decision = _max_action(raw_decision, behavior.min_action)

    # Shadow mode prefix
    if shadow_mode and raw_decision == "block":
        decision = f"would_{raw_decision}"
    else:
        decision = raw_decision

    return RiskDecision(
        total_score=total,
        decision=decision,
        reasons=rule.reasons
        + behavior.reasons
        + ([SCORE_BLOCK_CAPPED_REASON] if score_block_capped else []),
        breakdown={
            "rule": round(rule.score, 4),
            "behavior": round(behavior.score, 4),
            "iforest": round(iforest.risk_score, 4),
            "iforest_raw": round(iforest.raw_score, 4),
        },
    )
