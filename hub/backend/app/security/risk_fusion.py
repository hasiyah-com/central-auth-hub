"""L4 Hybrid Risk Aggregator — จุดเดียวที่สร้าง final_risk_score และ access_decision.

ไม่มีองค์ประกอบอื่นในระบบที่ได้รับอนุญาตให้ตัดสินการเข้าถึง ยกเว้น Policy Gate
ซึ่งเป็นข้อบังคับตายตัว ไม่ใช่การประเมินความเสี่ยง

**ทำไมไม่ใช้ weighted average:** วัดแล้วพบว่าคะแนนต่ำของชั้นที่ไม่เห็นอะไรจะ
เจือจางสัญญาณของชั้นที่เห็น — เหตุการณ์ที่ L3 เห็นชัดคนเดียวถูกกลบจนไม่ถึงเกณฑ์
(เป็นเหตุผลเดิมที่ทำให้ต้องยก decision ตรงๆ ซึ่งผิดสถาปัตยกรรม)

**สูตรที่ใช้ — max + corroboration:**

    R = M + γ · S · (1 − M)

    M = หลักฐานที่แรงที่สุด · S = หลักฐานอันดับสอง · γ = น้ำหนักการสนับสนุน

อ่านได้ว่า "เชื่อหลักฐานที่แรงที่สุดเป็นหลัก แล้วให้หลักฐานอันดับสองดันเพิ่มได้
ตามสัดส่วนของช่องว่างที่เหลือ" — ชั้นเดียวที่เห็นชัดจึงไม่ถูกกลบ และสองชั้นที่
เห็นตรงกันได้คะแนนสูงกว่าชั้นเดียว โดยไม่มีทางเกิน 1.0 (ต่างจากการบวกตรงๆ)

`γ` และ threshold **ต้องเลือกจาก validation แล้ว freeze ก่อนแตะ final holdout**
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.security.evidence import Evidence
from app.security.policy_gate import PolicyOutcome

# ── ค่าเริ่มต้น — ต้องถูกแทนที่ด้วยค่าที่เลือกจาก validation ก่อนใช้จริง ──
DEFAULT_GAMMA = 0.35
DEFAULT_THRESHOLDS = {"warn": 0.50, "challenge": 0.70, "block": 0.85}

ACTIONS = ("allow", "warn", "challenge", "block")
_RANK = {a: i for i, a in enumerate(ACTIONS)}

# ชั้นที่ **ห้ามปฏิเสธผู้ใช้ด้วยตัวคนเดียว** ในระยะแรก
# เหตุผล: ตัวเลขประสิทธิภาพของ L3 มาจากข้อมูลจำลอง ยังไม่ผ่าน production replay
# ที่มากพอ · ให้ยกได้สูงสุดถึง challenge (ยืนยันตัวตนเพิ่ม) ซึ่งผู้ใช้แก้ไขเองได้
SOLO_BLOCK_FORBIDDEN = frozenset({"anomaly"})


@dataclass
class RiskDecision:
    total_score: float
    decision: str
    reasons: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)


def _stronger(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def _action_for(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["block"]:
        return "block"
    if score >= thresholds["challenge"]:
        return "challenge"
    if score >= thresholds["warn"]:
        return "warn"
    return "allow"


def fuse(
    policy: PolicyOutcome,
    evidences: list[Evidence],
    *,
    gamma: float = DEFAULT_GAMMA,
    thresholds: dict[str, float] | None = None,
    shadow_mode: bool = False,
) -> RiskDecision:
    """รวมหลักฐานทุกชั้น -> final_risk_score + access_decision.

    ลำดับการตัดสิน:
      1. Policy Gate ปฏิเสธ -> block ทันที (ไม่ใช่ความเสี่ยง เป็นข้อบังคับ)
      2. รวมหลักฐานที่ **นับได้** ด้วย max + corroboration
      3. เทียบ threshold -> action
      4. ยกขึ้นตาม Policy Gate `min_action` (ข้อบังคับ ไม่ใช่คะแนน)
      5. บังคับข้อจำกัด: ชั้นที่ห้าม block เดี่ยว -> ลดเหลือ challenge
      6. shadow mode -> เติม would_ นำหน้า
    """
    thr = thresholds or DEFAULT_THRESHOLDS
    counted = [e for e in evidences if e.counts]
    abstained = [e for e in evidences if e.abstained]

    breakdown: dict = {
        "gamma": gamma,
        "thresholds": dict(thr),
        "policy": policy.to_contract(),
        "evidence": {e.layer: e.to_contract() for e in evidences},
        "abstained_layers": [e.layer for e in abstained],
        "uncalibrated_layers": [
            e.layer for e in counted if e.detail.get("calibrated") is False
        ],
    }

    if policy.denied:
        return RiskDecision(
            total_score=1.0,
            decision="would_block" if shadow_mode else "block",
            reasons=list(policy.reasons),
            breakdown={**breakdown, "final_risk_score": 1.0, "fusion": "policy_denied"},
        )

    ranked = sorted(counted, key=lambda e: e.evidence_score, reverse=True)
    primary = ranked[0] if ranked else None
    support = ranked[1] if len(ranked) > 1 else None
    m = primary.evidence_score if primary else 0.0
    s = support.evidence_score if support else 0.0
    final = round(m + gamma * s * (1.0 - m), 6)

    action = _action_for(final, thr)

    # ── ข้อบังคับจาก Policy Gate ยกขึ้นได้ แต่ลดลงไม่ได้ ──
    if policy.min_action:
        action = _stronger(action, policy.min_action)

    # ── ชั้นที่ห้าม block เดี่ยว ──
    solo_capped = False
    if action == "block" and primary is not None:
        corroborating = [
            e
            for e in counted
            if e is not primary and e.evidence_score >= thr["challenge"]
        ]
        if primary.layer in SOLO_BLOCK_FORBIDDEN and not corroborating:
            action = "challenge"
            solo_capped = True

    reasons: list[str] = list(policy.reasons)
    for e in ranked:
        reasons.extend(e.reasons)

    decision = f"would_{action}" if (shadow_mode and action != "allow") else action
    return RiskDecision(
        total_score=final,
        decision=decision,
        reasons=reasons,
        breakdown={
            **breakdown,
            "final_risk_score": final,
            "fusion": "max_corroboration",
            "primary_layer": primary.layer if primary else None,
            "primary_evidence": round(m, 4),
            "support_layer": support.layer if support else None,
            "support_evidence": round(s, 4),
            "solo_block_capped": solo_capped,
        },
    )
