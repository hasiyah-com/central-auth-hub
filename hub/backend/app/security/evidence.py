"""Evidence contract — สิ่งเดียวที่ชั้น L1/L2/L3 ได้รับอนุญาตให้คืนค่า.

สถาปัตยกรรมเป้าหมาย (1 ก.ย. 2569):

    Login Event -> Policy Gate -> Feature Extraction
                                       |
                        +--------------+--------------+
                        |              |              |
                   L1 Rule        L2 Behavior     L3 Anomaly
                        |              |              |
                        +--------------+--------------+
                                       v
                          L4 Hybrid Risk Aggregator
                                       v
                     final_risk_score + access_decision

**L1/L2/L3 ห้ามคืนคำเหล่านี้เด็ดขาด:**
`allow` · `warn` · `challenge` · `block` · `mfa_required` และคู่ `would_*`

เหตุผล: เดิมแต่ละชั้นตัดสินใจเองบางส่วน (L1 มี `blocked`, L1/L2 มี `min_action`,
L3 เคยยก `allow -> warn`) ทำให้ไม่มีจุดเดียวที่รับผิดชอบการตัดสินสิทธิ์ และ
ตรวจสอบย้อนกลับไม่ได้ว่าใครเป็นคนตัดสิน · ตอนนี้ทุกชั้น "ให้หลักฐาน" อย่างเดียว
แล้ว L4 เป็นผู้ตัดสินจุดเดียว (บังคับด้วย tests/test_evidence_contract.py)

**คะแนนต้อง calibrate มาก่อน** — `evidence_score` ของทุกชั้นอยู่บนสเกลเดียวกัน
คือความน่าจะเป็นเชิงประจักษ์ที่ login ปกติจะได้คะแนนไม่เกินค่านี้ (empirical CDF
จากชุด validation) · ห้ามส่งคะแนนดิบของแต่ละชั้นเข้า L4 เพราะสเกลคนละแบบ
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── ระดับหลักฐาน — จงใจไม่ให้ทับกับคำในแกน access decision ──
LEVEL_NONE = "none"
LEVEL_LOW = "low"
LEVEL_MEDIUM = "medium"
LEVEL_HIGH = "high"
LEVEL_EXTREME = "extreme"

EVIDENCE_LEVELS = (LEVEL_NONE, LEVEL_LOW, LEVEL_MEDIUM, LEVEL_HIGH, LEVEL_EXTREME)

# คำที่เป็นของแกน access decision — ชั้นหลักฐานห้ามผลิตคำเหล่านี้
FORBIDDEN_IN_EVIDENCE = frozenset(
    {"allow", "warn", "challenge", "block", "mfa_required"}
    | {f"would_{a}" for a in ("allow", "warn", "challenge", "block")}
)

# ขอบเขตของแต่ละระดับ (บน evidence_score ที่ calibrate แล้ว)
_LEVEL_BOUNDS = (
    (0.30, LEVEL_NONE),
    (0.60, LEVEL_LOW),
    (0.85, LEVEL_MEDIUM),
    (0.97, LEVEL_HIGH),
)


def level_of(score: float) -> str:
    """แปลง evidence_score เป็นระดับ — ใช้เพื่อสื่อสาร ไม่ได้ใช้คำนวณ."""
    for bound, name in _LEVEL_BOUNDS:
        if score < bound:
            return name
    return LEVEL_EXTREME


@dataclass
class Evidence:
    """หลักฐานความเสี่ยงจากชั้นหนึ่ง — ไม่มีการตัดสินใจใดๆ อยู่ในนี้.

    `evidence_score`  0.0–1.0 หลัง calibration (สเกลเดียวกันทุกชั้น)
    `eligible`        ชั้นนี้มีข้อมูลพอจะให้หลักฐานหรือไม่ · False = L4 ต้องไม่นับ
    `abstained`       งดออกความเห็นเพราะ error/timeout/ข้อมูลไม่พอ
                      (แยกจาก eligible=False ที่เป็นเรื่องปริมาณข้อมูลล้วน)
    `raw_score`       คะแนนดิบก่อน calibrate — เก็บไว้ตรวจย้อนเท่านั้น ห้ามนำไปรวม
    """

    layer: str
    evidence_score: float = 0.0
    eligible: bool = True
    abstained: bool = False
    abstain_reason: str | None = None
    reasons: list[str] = field(default_factory=list)
    model_version: str | None = None
    raw_score: float | None = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.evidence_score = min(max(float(self.evidence_score), 0.0), 1.0)

    @property
    def evidence_level(self) -> str:
        return level_of(self.evidence_score)

    @property
    def counts(self) -> bool:
        """L4 นับหลักฐานนี้หรือไม่ — งดออกความเห็นหรือไม่มีสิทธิ์ = ไม่นับ."""
        return self.eligible and not self.abstained

    def to_contract(self) -> dict:
        return {
            "layer": self.layer,
            "evidence_score": round(self.evidence_score, 4),
            "evidence_level": self.evidence_level,
            "eligible": self.eligible,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "reasons": list(self.reasons),
            "model_version": self.model_version,
            "raw_score": None if self.raw_score is None else round(self.raw_score, 4),
        }


def abstain(layer: str, reason: str) -> Evidence:
    """ชั้นนี้ให้หลักฐานไม่ได้ — L4 ต้องทำงานต่อโดยไม่นับชั้นนี้ (ไม่ใช่ถือว่าปลอดภัย)."""
    return Evidence(
        layer=layer,
        evidence_score=0.0,
        eligible=False,
        abstained=True,
        abstain_reason=reason,
    )
