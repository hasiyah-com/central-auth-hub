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

from app.config import settings
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
    subsystem_id=None,
    user_agent: str | None = None,
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
    # ── Layer 1: Rule Engine (+ cross-subsystem risk propagation) ──
    rule_result = evaluate_rules(
        features, db, user_id, ip, geo_country, subsystem_id=subsystem_id
    )

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
            # hard block ข้าม L3 ไปเลย — คง shape ของ response ให้เท่ากันทุกเส้นทาง
            "monitoring_decision": "normal",
            "l3_sequence": None,
        }

    # ── Layer 2: Behavior Profiling ──
    profile = get_user_profile(db, user_id)
    behavior_result = evaluate_behavior(
        features, profile, subsystem_id=subsystem_id, user_agent=user_agent
    )

    # ── Layer 3: Isolation Forest (fail-safe ตาม B21) ──
    # SHAP explanation is passed through from ML service. If ML service is
    # offline / older version without SHAP, explanation will be [] — Layer
    # 1+2 reasons still drive the explainability story.
    try:
        ml_result = await get_anomaly_score(features)
        iforest_result = map_score(
            ml_result["anomaly_score"],
            explanation=ml_result.get("explanation", []),
        )
    except Exception as e:
        logger.warning("[risk_engine] ML service error: %s — fallback to 0.0", e)
        iforest_result = IForestResult(raw_score=0.0, risk_score=0.0, label="error")

    # ── Layer 4: Risk Aggregation ──
    decision = aggregate(rule_result, behavior_result, iforest_result, shadow_mode)

    # ── L3 sequence channel — "ธงเฝ้าระวัง" (ยกได้สูงสุดแค่ warn, ไม่แตะ challenge/block) ──
    # แยกจาก aggregate โดยตั้งใจ: joint-residual ของ stealth campaign มีคะแนนรวมต่ำเกินกว่า
    # การบวกคะแนนจะดันถึง warn ได้ (ดู reports/l3_sequence_channel_2026-08-26.md) จึงยกระดับ
    # ตรงๆ แทน · fail-safe ตาม B21 — พังแล้วไม่กระทบ decision เดิม
    l3_monitoring: str = "normal"
    l3_contract: dict | None = None
    if settings.l3_sequence_enabled:
        try:
            from app.redis_client import redis_client
            from app.security import l3_sequence

            # numeric core อยู่ที่ ml-service (hub image ไม่มี numpy/sklearn โดยตั้งใจ)
            # hub คำนวณ residual เอง (pure python) → ml-service fit/score → คืน contract
            seq, resid = await l3_sequence.evaluate_login_remote(
                redis_client, user_id, features, profile, subsystem_id
            )
            l3_contract = l3_sequence.to_contract(seq, None)
            l3_monitoring = l3_contract["monitoring_decision"]
            if seq.fired:
                # log ครบตาม data contract — ใช้วัด raw vs effective ตอน production replay
                logger.info(
                    "[risk_engine] l3_sequence user=%s tier=%s pct=%.3f raw=%.3f "
                    "elig=%s monitoring=%s shadow=%s",
                    user_id,
                    seq.tier,
                    seq.percentile,
                    seq.raw_score,
                    seq.eligibility,
                    l3_monitoring,
                    seq.shadow_decision,
                )
            # บันทึกหลังตัดสิน — เป็น history ของครั้งถัดไป (ไม่ปนเข้า window ที่เพิ่งใช้)
            l3_sequence.record_residual(redis_client, user_id, resid)
        except Exception as e:  # noqa: BLE001
            logger.warning("[risk_engine] l3_sequence error: %s", e)

    # เก็บ contract ลง breakdown (LoginSession.risk_breakdown เป็น JSON — ไม่ต้อง migration)
    # ทำที่นี่จุดเดียวครอบคลุมทุก call site (auth ×3, oauth, passkey)
    # จำเป็นสำหรับ production replay: ถ้าเก็บแค่ decision จะแยก raw (L3 ยิง) ออกจาก
    # effective (decision เปลี่ยน) ไม่ได้ — การทดลองพบว่าสองค่านี้ต่างกันมาก (16.3% vs 0.2%)
    if l3_contract is not None:
        decision.breakdown = {**decision.breakdown, "l3_sequence": l3_contract}

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
        # SHAP top-k features from Layer 3 — UI uses this in SessionDetailPanel,
        # audit log includes when score is high.
        "iforest_explanation": iforest_result.explanation,
        # ── แกนที่สองของระบบ: monitoring ไม่ใช่ access ──
        # L3 มีอำนาจแค่ตั้งค่าใน field นี้ ("normal" | "l3_investigate") เท่านั้น
        # ห้ามให้ L3 ไปแตะ "decision"/"score"/"reasons" ข้างบนเด็ดขาด
        # (บังคับด้วย tests/test_l3_access_monitoring_split.py)
        "monitoring_decision": l3_monitoring,
        # data contract ต่อ login (raw_score/percentile/tier/eligibility/model_version)
        # -> เก็บลง log/audit เพื่อวัด raw vs effective unique ตอน production replay
        "l3_sequence": l3_contract,
    }
