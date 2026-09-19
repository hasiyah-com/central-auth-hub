"""Config A–F — แต่ละตัวเรียก **เส้นทาง production จริง** ห้ามมีสำเนา logic.

ที่มา (B66): harness เดิม (`exp_final_gate.py`) มี `_decide()` ที่คัดลอกเกณฑ์
การตัดสินมาไว้เอง และเรียก `aggregate(rule, beh, NEUTRAL)` ซึ่งต่างจากที่
production เรียกจริง -> วัดคนละระบบกับที่ให้บริการ โดยไม่มีใครรู้ตัว

กติกาของไฟล์นี้:
    * ห้ามเขียน threshold / สูตรรวมคะแนน / calibration / decision mapping ซ้ำ
    * ทุกอย่างต้อง import จาก app.security.*
    * ถ้าอยากทดลองวิธีรวมคะแนนแบบใหม่ ให้เพิ่มใน risk_fusion.py แล้วเรียกจากที่นี่

คำถามที่แต่ละคู่ตอบ:
    A vs B   ผลจากการเปลี่ยน L4 (legacy aggregate -> max+corroboration)
    B vs C   คุณค่าของ point-all
    B vs D   คุณค่าของ sequence
    B vs E   คุณค่ารวมของ L3
    E vs F   ผลของวิธี fusion (max+corroboration vs weighted sum)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.security.evidence import Evidence, abstain
from app.security.iforest_scorer import map_score
from app.security.policy_gate import PolicyOutcome
from app.security.risk_aggregator import aggregate as legacy_aggregate
from app.security.risk_evidence import behavior_evidence, rule_evidence
from app.security.risk_fusion import RiskDecision, fuse, fuse_weighted_sum

LAYER_ANOMALY = "anomaly"

# มุมมองของ L3 ที่แต่ละ config เปิดใช้
VIEW_POINT = "point"
VIEW_SEQUENCE = "sequence"


@dataclass
class L3Scores:
    """คะแนน L3 ดิบของหนึ่งเหตุการณ์ — harness เป็นผู้คำนวณ (ต้องใช้ numpy)."""

    point_raw: float | None = None
    sequence_raw: float | None = None
    sequence_eligible: bool = False


@dataclass
class ExpConfig:
    key: str
    name: str
    question: str
    views: tuple[str, ...] = ()
    fusion: str = "max_corroboration"  # max_corroboration | weighted_sum | legacy
    _run: Callable | None = field(default=None, repr=False)


def _anomaly_evidence(l3: L3Scores, views: tuple[str, ...], calibrate_fn) -> Evidence:
    """L3 -> หลักฐานเดียว · รวมสองมุมมองด้วย max ไม่ใช่ผลบวก (กันนับซ้ำ).

    `calibrate_fn(layer, raw) -> float` ฉีดเข้ามาเพื่อให้ใช้ ECDF ของ split ปัจจุบัน
    ไม่ใช่ตาราง production (ซึ่งอาจยังไม่มี หรือมาจากรอบอื่น)
    """
    parts: list[tuple[str, float, float]] = []
    if VIEW_POINT in views and l3.point_raw is not None:
        parts.append(
            ("point", calibrate_fn("anomaly_point", l3.point_raw), l3.point_raw)
        )
    if VIEW_SEQUENCE in views and l3.sequence_eligible and l3.sequence_raw is not None:
        parts.append(
            (
                "sequence",
                calibrate_fn("anomaly_sequence", l3.sequence_raw),
                l3.sequence_raw,
            )
        )
    if not parts:
        return abstain(LAYER_ANOMALY, "no_eligible_view")
    view, cal, raw = max(parts, key=lambda p: p[1])
    return Evidence(
        layer=LAYER_ANOMALY,
        evidence_score=cal,
        raw_score=raw,
        reasons=[f"l3_{view}"],
        detail={"view": view, "views": {v: round(c, 4) for v, c, _ in parts}},
    )


def evaluate(
    cfg: ExpConfig,
    policy: PolicyOutcome,
    rule_result,
    behavior_result,
    l3: L3Scores,
    *,
    calibrate_fn,
    gamma: float,
    thresholds: dict[str, float],
) -> RiskDecision:
    """ประเมินหนึ่งเหตุการณ์ตาม config — ทุกเส้นทางเรียกโค้ด production."""
    if cfg.fusion == "legacy":
        # ระบบเดิมทั้งดุ้น: ผลบวกคะแนนดิบ + map_score + threshold ชุดเดิม
        # ใช้ตอบว่า "ระบบเก่าทำได้เท่าไร" เท่านั้น ไม่ใช่ทางเลือกที่จะ deploy
        ifo = map_score(l3.point_raw or 0.0)
        return legacy_aggregate(rule_result, behavior_result, ifo, False)

    evidences = [
        rule_evidence(rule_result),
        behavior_evidence(behavior_result),
    ]
    # calibrate ด้วย ECDF ของ split ปัจจุบัน (แทนตาราง production)
    for e in evidences:
        e.evidence_score = calibrate_fn(e.layer, e.raw_score or 0.0)

    if cfg.views:
        evidences.append(_anomaly_evidence(l3, cfg.views, calibrate_fn))

    if cfg.fusion == "weighted_sum":
        return fuse_weighted_sum(policy, evidences, thresholds=thresholds)
    return fuse(policy, evidences, gamma=gamma, thresholds=thresholds)


CONFIGS: dict[str, ExpConfig] = {
    "A": ExpConfig("A", "Legacy aggregate", "ระบบเก่าทำได้เท่าไร", (), "legacy"),
    "B": ExpConfig("B", "L4 ใหม่ + L1/L2", "fusion ใหม่กระทบอะไร", ()),
    "C": ExpConfig("C", "B + L3 point-all", "all-feature IF เพิ่มอะไร", (VIEW_POINT,)),
    "D": ExpConfig("D", "B + L3 sequence", "sequence เพิ่มอะไร", (VIEW_SEQUENCE,)),
    "E": ExpConfig(
        "E", "B + point-all + sequence", "candidate หลัก", (VIEW_POINT, VIEW_SEQUENCE)
    ),
    "F": ExpConfig(
        "F",
        "Weighted sum + L3 สองมุมมอง",
        "เปรียบเทียบวิธี fusion",
        (VIEW_POINT, VIEW_SEQUENCE),
        "weighted_sum",
    ),
}

ORDER = ["A", "B", "C", "D", "E", "F"]

# คู่เปรียบเทียบที่ต้องรายงาน — ถ้าไม่แยก A กับ B จะไม่รู้ว่าผลเปลี่ยนเพราะ L3
# หรือเพราะเปลี่ยนวิธีรวมคะแนน
COMPARISONS = [
    ("A", "B", "ผลจากการเปลี่ยน L4"),
    ("B", "C", "คุณค่าของ point-all"),
    ("B", "D", "คุณค่าของ sequence"),
    ("B", "E", "คุณค่ารวมของ L3"),
    ("E", "F", "ผลของวิธี fusion"),
]
