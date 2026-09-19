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
# action ที่ถือว่า "ระบบหยิบเหตุการณ์นี้ขึ้นมา" — ใช้นิยาม effective unique
SURFACED = frozenset({"warn", "challenge", "block"})
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


def is_surfaced(decision: str) -> bool:
    """เหตุการณ์นี้ถูกระบบหยิบขึ้นมาหรือไม่ (ตัด would_ ออกก่อนเทียบ)."""
    return decision.removeprefix("would_") in SURFACED


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


@dataclass(frozen=True)
class ResolverInput:
    """ทุกอย่างที่ต้องใช้แปลง final score -> action โดยไม่ต้องคำนวณหลักฐานใหม่.

    มีไว้เพื่อให้การกวาด threshold (grid search) เรียก **ตัวแก้ผลของ production
    ตัวเดียวกัน** ได้โดยไม่ต้องคำนวณ L1/L2/L3 ใหม่ทุกจุด — ถ้า harness เขียน
    การแปลงคะแนนเป็น action เองจะกลายเป็นสำเนา logic ซึ่งเป็นต้นเหตุของ B66
    """

    final_score: float
    policy_denied: bool = False
    policy_min_action: str | None = None
    primary_layer: str | None = None
    # evidence ของชั้นที่นับได้ทั้งหมด **ยกเว้น** primary — ใช้ตรวจ corroboration
    other_evidence: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        return {
            "final_score": self.final_score,
            "policy_denied": self.policy_denied,
            "policy_min_action": self.policy_min_action,
            "primary_layer": self.primary_layer,
            "other_evidence": list(self.other_evidence),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResolverInput":
        return cls(
            final_score=float(d["final_score"]),
            policy_denied=bool(d.get("policy_denied")),
            policy_min_action=d.get("policy_min_action"),
            primary_layer=d.get("primary_layer"),
            other_evidence=tuple(float(x) for x in d.get("other_evidence") or ()),
        )


def resolve_action(
    inp: ResolverInput, thresholds: dict[str, float]
) -> tuple[str, bool]:
    """คะแนน + ข้อบังคับ -> (action, ถูก cap เพราะชั้นเดียวหรือไม่).

    **จุดเดียวในระบบที่แปลงคะแนนเป็น action** — ทั้ง fuse, fuse_weighted_sum และ
    การทดลองทุกตัวต้องเดินผ่านฟังก์ชันนี้
    """
    if inp.policy_denied:
        return "block", False
    action = _action_for(inp.final_score, thresholds)
    if inp.policy_min_action:
        action = _stronger(action, inp.policy_min_action)
    solo_capped = False
    if action == "block" and inp.primary_layer in SOLO_BLOCK_FORBIDDEN:
        if not any(x >= thresholds["challenge"] for x in inp.other_evidence):
            action = "challenge"
            solo_capped = True
    return action, solo_capped


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
            breakdown={
                **breakdown,
                "final_risk_score": 1.0,
                "fusion": "policy_denied",
                "resolver": ResolverInput(
                    final_score=1.0, policy_denied=True
                ).to_dict(),
            },
        )

    ranked = sorted(counted, key=lambda e: e.evidence_score, reverse=True)
    primary = ranked[0] if ranked else None
    support = ranked[1] if len(ranked) > 1 else None
    m = primary.evidence_score if primary else 0.0
    s = support.evidence_score if support else 0.0
    final = round(m + gamma * s * (1.0 - m), 6)

    resolver = ResolverInput(
        final_score=final,
        policy_denied=False,
        policy_min_action=policy.min_action,
        primary_layer=primary.layer if primary else None,
        other_evidence=tuple(e.evidence_score for e in counted if e is not primary),
    )
    action, solo_capped = resolve_action(resolver, thr)

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
            "resolver": resolver.to_dict(),
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# ทางเลือกสำหรับเปรียบเทียบ — ไม่ใช่ค่าเริ่มต้นของระบบ
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_WEIGHTS = {"rule": 0.40, "behavior": 0.35, "anomaly": 0.25}


def fuse_weighted_sum(
    policy: PolicyOutcome,
    evidences: list[Evidence],
    *,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    shadow_mode: bool = False,
) -> RiskDecision:
    """ผลรวมถ่วงน้ำหนัก — มีไว้**เปรียบเทียบ** กับ max+corroboration เท่านั้น.

    อยู่ในโค้ด production (ไม่ใช่ใน harness) โดยตั้งใจ เพื่อให้การทดลองเรียก
    เส้นทางเดียวกับที่ระบบจะใช้ถ้าเลือกวิธีนี้ และเทสตรวจคุณสมบัติได้เหมือนกัน
    (บทเรียน B66 — harness ที่มีสำเนา logic ทำให้วัดคนละระบบกับที่ deploy)

    ข้อเสียที่คาดไว้และเป็นเหตุผลที่ไม่ได้เลือกเป็นค่าเริ่มต้น: ชั้นที่ไม่เห็นอะไร
    (evidence ต่ำ) จะถ่วงค่าเฉลี่ยลง ทำให้เหตุการณ์ที่มีชั้นเดียวเห็นชัดไม่ถึงเกณฑ์
    """
    thr = thresholds or DEFAULT_THRESHOLDS
    w = weights or DEFAULT_WEIGHTS
    counted = [e for e in evidences if e.counts]

    breakdown: dict = {
        "weights": dict(w),
        "thresholds": dict(thr),
        "policy": policy.to_contract(),
        "evidence": {e.layer: e.to_contract() for e in evidences},
        "abstained_layers": [e.layer for e in evidences if e.abstained],
    }

    if policy.denied:
        return RiskDecision(
            total_score=1.0,
            decision="would_block" if shadow_mode else "block",
            reasons=list(policy.reasons),
            breakdown={
                **breakdown,
                "final_risk_score": 1.0,
                "fusion": "policy_denied",
                "resolver": ResolverInput(
                    final_score=1.0, policy_denied=True
                ).to_dict(),
            },
        )

    # normalize ตามชั้นที่นับได้จริง — ไม่งั้นชั้นที่ abstain จะถ่วงคะแนนลงโดยไม่ควร
    total_w = sum(w.get(e.layer, 0.0) for e in counted)
    final = 0.0
    if total_w > 0:
        final = sum(w.get(e.layer, 0.0) * e.evidence_score for e in counted) / total_w
    final = round(min(max(final, 0.0), 1.0), 6)

    ranked = sorted(counted, key=lambda e: e.evidence_score, reverse=True)
    primary = ranked[0] if ranked else None
    resolver = ResolverInput(
        final_score=final,
        policy_denied=False,
        policy_min_action=policy.min_action,
        primary_layer=primary.layer if primary else None,
        other_evidence=tuple(e.evidence_score for e in counted if e is not primary),
    )
    action, solo_capped = resolve_action(resolver, thr)

    reasons = list(policy.reasons)
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
            "fusion": "weighted_sum",
            "primary_layer": primary.layer if primary else None,
            "solo_block_capped": solo_capped,
            "resolver": resolver.to_dict(),
        },
    )
