"""Risk Engine — Orchestrator สำหรับ 4-Layer Hybrid RBA.

เรียกจาก oauth.py ตอน login เพื่อประเมินความเสี่ยง.
Policy Gate (ข้อบังคับ) -> หลักฐานจาก L1/L2/L3 (calibrate แล้ว) -> L4 ตัดสินจุดเดียว
L1/L2/L3 ไม่มีอำนาจตัดสินการเข้าถึงเลย (บังคับด้วย tests/test_evidence_contract.py)

อ้างอิง:
  - RISK_SCORING_SYSTEM.md
  - hybrid_rba_architecture_rules_and_research_th.md
  - Freeman et al. (2016), Wiefling et al. (2022), F-RBA (2024)
"""

import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.security.behavior_profiling import evaluate_behavior, get_user_profile
from app.security.policy_gate import evaluate_policy
from app.security.risk_evidence import (
    anomaly_evidence,
    behavior_evidence,
    rule_evidence,
)
from app.security.risk_fusion import fuse
from app.security.rule_engine import evaluate_rules

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
    """ประเมินความเสี่ยงของ login — Policy Gate + หลักฐาน 3 ชั้น + L4 ตัดสินจุดเดียว.

    สถาปัตยกรรม (1 ก.ย. 2569):

        Policy Gate  ->  ข้อบังคับตายตัว (deny / บังคับ step-up)
        L1 / L2 / L3 ->  หลักฐานความเสี่ยงที่ calibrate แล้ว (ไม่ตัดสินอะไรเลย)
        L4           ->  final_risk_score + access_decision  <- จุดเดียวที่ตัดสิน

    Returns dict — คีย์เดิมคงไว้ให้ router ที่มีอยู่ใช้ต่อได้ไม่ต้องแก้
    """
    # ── 0. Policy Gate — ข้อบังคับ ไม่ใช่การคาดการณ์ ──
    policy = evaluate_policy(features, db, user_id, ip, geo_country)
    if policy.denied:
        logger.warning(
            "[risk_engine] policy denied user=%s ip=%s policy=%s reasons=%s",
            user_id,
            ip,
            policy.policy,
            policy.reasons,
        )
        decision = fuse(policy, [], shadow_mode=shadow_mode)
        return _result(decision, l3=None, evidences=[])

    # ── 1. L1 Rule evidence ──
    rule_result = evaluate_rules(
        features, db, user_id, ip, geo_country, subsystem_id=subsystem_id
    )

    # ── 2. L2 Behavior evidence ──
    profile = get_user_profile(db, user_id)
    behavior_result = evaluate_behavior(
        features, profile, subsystem_id=subsystem_id, user_agent=user_agent
    )

    # ── 3. L3 Anomaly evidence (สองมุมมอง) ──
    mode = (settings.l3_mode or "shadow").strip().lower()
    l3 = None
    if mode != "off":
        l3 = await _evaluate_l3(user_id, features, profile, subsystem_id)

    evidences = [
        rule_evidence(rule_result),
        behavior_evidence(behavior_result),
    ]
    anomaly = anomaly_evidence(l3)
    if mode != "hybrid_stepup":
        # shadow: เก็บหลักฐานไว้ดู แต่ L4 ต้องไม่นับ — ทำให้ผลเท่ากับ baseline เป๊ะ
        anomaly.eligible = False
        anomaly.abstain_reason = anomaly.abstain_reason or f"l3_mode={mode}"
    evidences.append(anomaly)

    # ── 4. L4 — จุดเดียวที่สร้าง final_risk_score และ access_decision ──
    thresholds = {
        "warn": settings.l4_threshold_warn,
        "challenge": settings.l4_threshold_challenge,
        "block": settings.l4_threshold_block,
    }
    kw = dict(gamma=settings.l4_gamma, thresholds=thresholds, shadow_mode=shadow_mode)
    decision = fuse(policy, evidences, **kw)

    # ── วัดว่า L3 เปลี่ยนการตัดสินจริงหรือไม่ (L3 effective unique) ──
    # เทียบกับผลที่ได้ถ้ามีแค่ L1/L2 · เป็นตัวเลขที่ตอบว่า "ชั้นนี้คุ้มไหม" ตรงที่สุด
    # คำนวณที่นี่เพราะ ณ ตอนเรียก L3 ยังไม่มีการตัดสินให้เทียบ
    baseline = fuse(policy, [e for e in evidences if e.layer != "anomaly"], **kw)
    decision.breakdown["l1l2_only_decision"] = baseline.decision
    decision.breakdown["l1l2_only_score"] = baseline.total_score
    decision.breakdown["l3_changed_decision"] = decision.decision != baseline.decision

    logger.info(
        "[risk_engine] user=%s risk=%.3f decision=%s primary=%s l3_mode=%s",
        user_id,
        decision.total_score,
        decision.decision,
        decision.breakdown.get("primary_layer"),
        mode,
    )
    return _result(decision, l3, evidences)


def _result(decision, l3: dict | None, evidences: list) -> dict:
    """รูปแบบผลลัพธ์ — คีย์เดิมคงไว้ทั้งหมดเพื่อไม่ให้ router ต้องแก้."""
    point = (l3 or {}).get("point") or {}
    seq_contract = _sequence_contract(l3) if l3 else None
    by_layer = {e.layer: e for e in evidences}

    def _ev_score(layer: str) -> float:
        e = by_layer.get(layer)
        return round(e.evidence_score, 4) if (e and e.counts) else 0.0

    def _raw(layer: str) -> float:
        e = by_layer.get(layer)
        return round(float(e.raw_score or 0.0), 4) if e else 0.0

    breakdown = {
        **decision.breakdown,
        # ── คีย์เดิมที่ dashboard/incident_service อ่านอยู่ ──
        # ⚠️ ความหมายเปลี่ยน: เดิมเป็นคะแนนดิบของชั้น ตอนนี้เป็น **หลักฐานที่
        # calibrate แล้ว** (สเกลเดียวกันทุกชั้น) · ค่าดิบย้ายไปอยู่ที่ *_raw
        "rule": _ev_score("rule"),
        "behavior": _ev_score("behavior"),
        "iforest": _ev_score("anomaly"),
        "rule_raw": _raw("rule"),
        "behavior_raw": _raw("behavior"),
        "iforest_raw": round(float(point.get("anomaly_score") or 0.0), 4),
    }
    if seq_contract is not None:
        breakdown["l3_sequence"] = seq_contract
    if l3 is not None:
        breakdown["l3"] = _l3_summary(l3)

    return {
        # ── แกนเดียวของการตัดสิน — มาจาก L4 เท่านั้น ──
        "decision": decision.decision,
        "score": decision.total_score,
        "reasons": decision.reasons,
        "breakdown": breakdown,
        "iforest_explanation": point.get("explanation") or [],
        # ── ข้อมูลเฝ้าระวัง (ไม่ใช่การตัดสิน) ──
        "monitoring_decision": (l3 or {}).get("monitoring_decision") or "normal",
        "l3_sequence": seq_contract,
        "l3": _l3_summary(l3) if l3 else None,
        "evidence": {e.layer: e.to_contract() for e in evidences},
    }


# ══════════════════════════════════════════════════════════════════════════════
# Layer 3 helpers — ทุกเส้นทาง fail-safe (B21): พังแล้วคืนค่าเงียบ ไม่ raise
# ══════════════════════════════════════════════════════════════════════════════

_L3_SUMMARY_KEYS = (
    "monitoring_decision",
    "is_anomaly",
    "unique_to_l3",
    "detected_by",
    "duplicate_ratio",
    "duplicate_window",
    "diagnostic_factors",
    "diagnostic_method",
    "baseline_version",
    "model_version",
)


def _l3_summary(l3: dict) -> dict:
    """ส่วนที่เก็บลง log/replay — ตัดผลดิบของแต่ละมุมมองออก (ยาวเกินจำเป็น)."""
    return {k: l3[k] for k in _L3_SUMMARY_KEYS}


def _sequence_contract(l3: dict) -> dict | None:
    """contract ของ sequence view ในรูปแบบเดิม — replay script ที่มีอยู่อ่านต่อได้.

    คืน None เมื่อ **ปิดแฟล็ก** หรือ **L3 พัง** — ตั้งใจแยก "พัง" ออกจาก "abstain"
    ให้ขาด: ทั้งสองกรณีคืน fired=False เหมือนกัน ถ้าบันทึกเป็น contract ทั้งคู่
    การ replay จะนับ L3 ที่ล่มว่าเป็น "ตัดสินใจไม่ยิงอย่างถูกต้อง" ซึ่งเป็นตัวเลข
    ที่หลอกตัวเอง (บทเรียนเดียวกับ B61 — fail-safe ที่เงียบจนไม่มีใครรู้ว่ามันไม่ทำงาน)
    """
    try:
        from app.security import l3_sequence

        if not settings.l3_sequence_enabled or l3.get("error"):
            return None
        return l3_sequence.to_contract(
            l3_sequence.result_from_payload(l3["sequence"]), None
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[risk_engine] sequence contract error: %s", e)
        return None


async def _evaluate_l3(
    user_id: str,
    features: list[float],
    profile: dict | None,
    subsystem_id,
) -> dict:
    """เรียก L3 ทั้งสองมุมมองในครั้งเดียว.

    **ไม่ส่ง access_decision เข้าไปแล้ว** — ในสถาปัตยกรรมใหม่ยังไม่มีการตัดสินใดๆ
    ณ จุดที่เรียก L3 (L4 ตัดสินทีหลัง) · การวัดว่า L3 เห็นอะไรที่ L1/L2 ไม่เห็น
    ย้ายมาคำนวณที่ hub หลัง fusion โดยเทียบผลของ L1/L2 อย่างเดียวกับผลรวม
    ซึ่งเป็นนิยามที่ตรงกว่าเดิม (วัด "เปลี่ยนการตัดสินจริงไหม" ไม่ใช่แค่ "ยิงตอน allow")

    residual คำนวณที่ hub (pure python — image ไม่มี numpy โดยตั้งใจ) แล้วบันทึก
    **หลัง**ตัดสินเสร็จ เพื่อไม่ให้ปนเข้า window ที่เพิ่งใช้ตัดสิน
    """
    from app.services.l3_sequence_client import _unified_quiet, evaluate_l3

    resid = None
    try:
        if settings.l3_sequence_enabled:
            from app.security import l3_sequence

            resid = l3_sequence.residual_raw(features, profile, subsystem_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[risk_engine] residual error: %s", e)

    try:
        l3 = await evaluate_l3(user_id, features, resid)
    except Exception as e:  # noqa: BLE001
        logger.warning("[risk_engine] l3 evaluate error: %s", e)
        l3 = _unified_quiet(f"l3_error: {type(e).__name__}")

    if l3.get("error"):
        logger.warning("[risk_engine] l3 degraded: %s", l3["error"])

    if resid is not None:
        try:
            from app.redis_client import redis_client
            from app.security import l3_sequence

            l3_sequence.record_residual(redis_client, user_id, resid)
        except Exception as e:  # noqa: BLE001
            logger.warning("[risk_engine] record_residual error: %s", e)
    return l3
