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
from app.security import l3_fallback
from app.security.iforest_scorer import monitoring_only
from app.security.risk_aggregator import aggregate
from app.security.rule_engine import FEAT, evaluate_rules

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
    login_method: str | None = None,
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
    # Staged L3-only research snapshot; no values enter rules/live point/sequence.
    candidate = None
    if login_method is not None:
        from app.services.l3_auth_context import extract_auth_context
        from app.services.feature_time import FEATURE_CONTRACT
        try:
            with db.begin_nested():
                candidate = extract_auth_context(db, user_id, login_method,
                                                 subsystem_id=subsystem_id)
                candidate["user_type"] = _user_type(db, user_id)
            candidate["base_feature_contract"] = FEATURE_CONTRACT
            candidate["base_features"] = {
                name: float(features[index]) for name, index in FEAT.items()
            }
        except Exception:
            logger.exception("L3 auth context collection unavailable user=%s", user_id)
            candidate = {"status": "unavailable", "contract": "l3-auth-context-v1"}

    from app.services.rule_context import RuleContext, collect_rule_context
    context = RuleContext(strong_primary_verified=login_method in ("passkey", "discoverable"))
    if any(features[FEAT[n]] == 1 for n in
           ("is_new_device", "is_new_user_agent_family", "new_passkey_recently_added")) or features[FEAT["permission_change_age"]] <= 1:
        try:
            with db.begin_nested():
                context = collect_rule_context(db, user_id, login_method=login_method)
        except Exception:
            logger.exception("Rule context unavailable user=%s", user_id)
    # ── Layer 1: Rule Engine (+ cross-subsystem risk propagation) ──
    rule_result = evaluate_rules(
        features, db, user_id, ip, geo_country, subsystem_id=subsystem_id, context=context
    )

    if rule_result.blocked:
        # Hard block → ข้าม Layer 2+3 (ไม่ต้องเสียเวลาเรียก ML)
        logger.warning(
            "[risk_engine] hard block user=%s ip=%s reasons=%s",
            user_id,
            ip,
            rule_result.reasons,
        )
        from app.security.behavior_profiling import BehaviorResult

        behavior_result = BehaviorResult(score=0.0, reasons=["skipped (hard block)"])

        # ใช้ monitoring_only() เหมือนเส้นทางหลัก — เดิมสร้าง IForestResult(0,0) ตรงนี้
        # ซึ่งให้ผลเท่ากันทุกประการ แต่ทำให้ผู้ที่ grep หา "aggregate(" เห็นสองรูปแบบ
        # แล้วต้องไล่อ่านว่าเส้นทางไหนบวกคะแนนบ้าง · ใช้ตัวเดียวกันทั้งไฟล์ทำให้
        # ข้อตกลง "IForest ไม่แตะ access" ตรวจได้ด้วยตาจากโค้ดโดยไม่ต้องตามค่า
        decision = aggregate(
            rule_result, behavior_result, monitoring_only(), shadow_mode
        )
        return {
            "decision": decision.decision,
            "score": decision.total_score,
            "reasons": decision.reasons,
            "breakdown": {**decision.breakdown, **({"l3_auth_candidate": candidate} if candidate else {})},
            # hard block ข้าม L3 ไปเลย — คง shape ของ response ให้เท่ากันทุกเส้นทาง
            "iforest_explanation": [],
            "monitoring_decision": "normal",
            "l3_sequence": None,
            "l3": None,
        }

    # ── Layer 2: Behavior Profiling ──
    profile = get_user_profile(db, user_id)
    behavior_result = evaluate_behavior(
        features, profile, subsystem_id=subsystem_id, user_agent=user_agent
    )

    # ── Layer 4: Risk Aggregation — L1 + L2 เท่านั้น ──
    # IForest ไม่บวกเข้าคะแนนความเสี่ยงอีกต่อไป (ดู iforest_scorer.monitoring_only
    # สำหรับเหตุผลเต็ม: การทดลองทุกชุดวัดด้วย NEUTRAL แต่ production เดิมบวกจริงถึง +0.40)
    #
    # ผลพลอยได้ที่สำคัญ: access decision ไม่ขึ้นกับ ml-service อีกต่อไป — ml-service
    # ล่มแล้วการตัดสินสิทธิ์ผู้ใช้ไม่กระทบเลย ต่างจากเดิมที่ "fallback เป็น 0.0"
    # ซึ่งก็คือการเปลี่ยนผลการตัดสินตามสถานะของบริการภายนอกอยู่ดี
    decision = aggregate(rule_result, behavior_result, monitoring_only(), shadow_mode)

    # ── Layer 3 (แกน monitoring) — point view + sequence view รวมเป็นผลเดียว ──
    # B86: L3 residual สะสมประวัติด้วย subsystem_id ชนิดสตริงมาตลอด (count = 0 เสมอ) ·
    # เปลี่ยนชนิดตรงนี้ = เปลี่ยนความหมายประวัติ L3 → งานแยกพร้อมเปลี่ยนคีย์/รุ่น (แบบ B84)
    # จึงคงค่าเดิมไว้โดยเจตนา · ตรึงด้วย test_subsystem_id_type_b86 (ลบเมื่อแก้ L3)
    l3_subsystem_id = str(subsystem_id) if subsystem_id is not None else None
    l3 = await _evaluate_l3(
        user_id, features, profile, l3_subsystem_id, decision.decision
    )
    seq_contract = _sequence_contract(l3)
    if settings.l3_role_calibration_path:
        fallback = _role_percentile_fallback(db, user_id, decision.decision, l3)
        l3["fallback"] = fallback
        # Monitoring only: baseline access score, decision and reasons stay intact.
        l3["monitoring_decision"] = (
            "l3_investigate" if fallback["status"] == "warn" else "normal"
        )

    if l3["is_anomaly"]:
        logger.info(
            "[risk_engine] l3 user=%s detected_by=%s unique=%s monitoring=%s "
            "point=%.3f seq_tier=%s dup_ratio=%s",
            user_id,
            l3["detected_by"],
            l3["unique_to_l3"],
            l3["monitoring_decision"],
            l3["point"]["anomaly_score"],
            l3["sequence"].get("tier"),
            l3["duplicate_ratio"],
        )

    # เก็บลง breakdown (LoginSession.risk_breakdown เป็น JSON — ไม่ต้อง migration)
    # ทำที่นี่จุดเดียวครอบคลุมทุก call site (auth x3, oauth, passkey)
    # `iforest_raw` ยังเก็บค่าจริงไว้เหมือนเดิม — เปลี่ยนแค่ว่ามันไม่ถูกบวกเข้า total
    breakdown = {
        **decision.breakdown,
        "rule_context": context.snapshot(),
        "iforest_raw": round(l3["point"]["anomaly_score"], 4),
        # All login routers persist breakdown, including Hub Google/LINE.
        # Keeping SHAP only in the top-level result loses it on those paths.
        "iforest_explanation": l3["point"]["explanation"],
        "l3": {**_l3_summary(l3), "point_available": bool(l3["point"].get("available"))},
        # Preserve every input even when SHAP is unavailable.
        "l3_point_features": [
            {"feature": name, "value": round(float(features[index]), 4)}
            for name, index in sorted(FEAT.items(), key=lambda item: item[1])
        ],
    }
    # คงคีย์เดิมไว้ให้ replay script + ข้อมูลที่เก็บมาแล้วอ่านต่อได้ · ใส่เฉพาะตอนมีจริง
    # (ปิดแฟล็ก/L3 พัง -> ไม่ใส่ ไม่ใช่ใส่ contract เปล่า — ดู _sequence_contract)
    if candidate is not None:
        breakdown["l3_auth_candidate"] = candidate
    if seq_contract is not None:
        breakdown["l3_sequence"] = seq_contract

    # ── ชั้นที่ 3 เป็นตัวสำรองระดับ warn (เฉพาะเมื่อชั้นที่ 1+2 ตัดสิน allow) ──
    # ยกได้ถึง warn เท่านั้น · ไม่เปลี่ยนคะแนน · L3 ล่ม/ไม่มีคะแนน = คงผลเดิม (fail-safe B21)
    access_decision, access_reasons = decision.decision, list(decision.reasons)
    if settings.l3_fallback_warn_enabled:
        point = l3.get("point") or {}
        usable = (
            not l3.get("error") and point.get("available") and not point.get("error")
        )
        user_type = _user_type(db, user_id)
        access_decision, fb_reason = l3_fallback.apply(
            decision.decision,
            point.get("anomaly_score") if usable else None,
            user_type,
            shadow_mode,
        )
        if fb_reason:
            access_reasons.append(fb_reason)
        breakdown["l3_fallback"] = {
            "applied": fb_reason is not None,
            "threshold": l3_fallback.threshold_for(user_type),
            "user_type": user_type,
        }

    logger.info(
        "[risk_engine] user=%s score=%.3f decision=%s monitoring=%s",
        user_id,
        decision.total_score,
        access_decision,
        l3["monitoring_decision"],
    )

    return {
        # ── แกนที่ 1: access — L1/L2/L4 (+ L3 ตัวสำรองระดับ warn เมื่อเปิดแฟล็ก) ──
        "decision": access_decision,
        "score": decision.total_score,
        "reasons": access_reasons,
        "breakdown": breakdown,
        # SHAP ของ point view (23 ฟีเจอร์) — คีย์เดิม UI/audit ใช้อยู่
        "iforest_explanation": l3["point"]["explanation"],
        # ── แกนที่ 2: monitoring — L3 เท่านั้น ──
        # L3 มีอำนาจแค่ตั้งค่าใน field นี้ ("normal" | "l3_investigate")
        # ห้ามให้ L3 ไปแตะ "decision"/"score"/"reasons" ข้างบนเด็ดขาด
        # (บังคับด้วย tests/test_l3_access_monitoring_split.py)
        "monitoring_decision": l3["monitoring_decision"],
        "l3_sequence": seq_contract,
        "l3": _l3_summary(l3),
    }


def _user_type(db, user_id) -> str | None:
    """ประเภทผู้ใช้สำหรับเกณฑ์ของตัวสำรอง · ไม่มี db/หาไม่เจอ = None (ใช้เกณฑ์ค่าเริ่มต้น)."""
    if db is None:
        return None
    try:
        from app.models import User

        return db.query(User.user_type).filter(User.id == user_id).scalar()
    except Exception as e:  # noqa: BLE001
        logger.warning("[risk_engine] user_type lookup error: %s", e)
        return None


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
    summary = {k: l3[k] for k in _L3_SUMMARY_KEYS}
    if "fallback" in l3:
        summary["fallback"] = l3["fallback"]
    return summary


def _role_percentile_fallback(db, user_id, baseline_decision, l3):
    from app.security.l3_percentile_fallback import evaluate_file, _quiet

    if baseline_decision != "allow":
        return _quiet("skipped", "baseline_not_allow", None)
    point = l3.get("point", {})
    if l3.get("error") or not point.get("available") or point.get("error"):
        return _quiet("abstain", "point_unavailable", None)
    try:
        from app.models import User

        role = db.query(User.user_type).filter(User.id == user_id).scalar()
        return evaluate_file(
            settings.l3_role_calibration_path, baseline_decision, role,
            point.get("anomaly_score"), point.get("model_sha256"),
        )
    except Exception:  # noqa: BLE001
        logger.exception("L3 role fallback unavailable")
        return _quiet("abstain", "role_lookup_unavailable", None)


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
    access_decision: str,
) -> dict:
    """เรียก L3 ทั้งสองมุมมองในครั้งเดียว.

    `access_decision` ส่งเข้าไปเพื่อให้ ml-service **วัด** ว่า L3 เห็นอะไรที่ L1/L2
    ไม่เห็น (unique_to_l3 / duplicate_ratio) เท่านั้น — ผลที่คืนมาไม่มีฟิลด์ access
    decision เลย จึงไม่มีทางไหลกลับไปเปลี่ยนสิทธิ์ผู้ใช้

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
        l3 = await evaluate_l3(user_id, features, resid, access_decision)
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
