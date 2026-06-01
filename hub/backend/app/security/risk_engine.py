"""Risk Engine — Orchestrator สำหรับ 4-Layer Hybrid RBA.

เรียกจาก oauth.py ตอน login เพื่อประเมินความเสี่ยง.
รวม Layer 1 (Rule) + Layer 2 (Behavior) + Layer 3 (IForest) + Layer 4 (Aggregation).

อ้างอิง:
  - RISK_SCORING_SYSTEM.md
  - hybrid_rba_architecture_rules_and_research_th.md
  - Freeman et al. (2016), Wiefling et al. (2022), F-RBA (2024)
"""

import logging

from sqlalchemy.orm import Session

from app.security.behavior_profiling import evaluate_behavior, get_user_profile
from app.security.iforest_scorer import IForestResult, map_score
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import evaluate_rules
from app.services.ml_client import get_anomaly_score

logger = logging.getLogger(__name__)


async def evaluate_login_risk(
    features: list[float],
    user_id: str,
    ip: str | None,
    geo_country: str | None,
    db: Session,
    shadow_mode: bool = False,
) -> dict:
    """ประเมินความเสี่ยงของ login 4 ชั้น.

    Returns dict:
        {
            "decision": "allow" | "warn" | "challenge" | "block" | "would_*",
            "score": 0.0–1.0,
            "reasons": ["is_new_device (+0.30)", ...],
            "breakdown": {"rule": 0.3, "behavior": 0.2, "iforest": 0.1, "iforest_raw": 0.45},
        }
    """
    # ── Layer 1: Rule Engine ──
    rule_result = evaluate_rules(features, db, user_id, ip, geo_country)

    if rule_result.blocked:
        # Hard block → ข้าม Layer 2+3 (ไม่ต้องเสียเวลาเรียก ML)
        logger.warning(
            "[risk_engine] hard block user=%s ip=%s reasons=%s",
            user_id,
            ip,
            rule_result.reasons,
        )
        # ยังต้อง map iforest score เป็น 0 สำหรับ breakdown
        iforest_result = IForestResult(raw_score=0.0, risk_score=0.0, label="skipped")
        from app.security.behavior_profiling import BehaviorResult

        behavior_result = BehaviorResult(score=0.0, reasons=["skipped (hard block)"])

        decision = aggregate(rule_result, behavior_result, iforest_result, shadow_mode)
        return {
            "decision": decision.decision,
            "score": decision.total_score,
            "reasons": decision.reasons,
            "breakdown": decision.breakdown,
        }

    # ── Layer 2: Behavior Profiling ──
    profile = get_user_profile(db, user_id)
    behavior_result = evaluate_behavior(features, profile)

    # ── Layer 3: Isolation Forest (fail-safe ตาม B21) ──
    try:
        ml_result = await get_anomaly_score(features)
        iforest_result = map_score(ml_result["anomaly_score"])
    except Exception as e:
        logger.warning("[risk_engine] ML service error: %s — fallback to 0.0", e)
        iforest_result = IForestResult(raw_score=0.0, risk_score=0.0, label="error")

    # ── Layer 4: Risk Aggregation ──
    decision = aggregate(rule_result, behavior_result, iforest_result, shadow_mode)

    logger.info(
        "[risk_engine] user=%s score=%.3f decision=%s breakdown=%s",
        user_id,
        decision.total_score,
        decision.decision,
        decision.breakdown,
    )

    return {
        "decision": decision.decision,
        "score": decision.total_score,
        "reasons": decision.reasons,
        "breakdown": decision.breakdown,
    }
