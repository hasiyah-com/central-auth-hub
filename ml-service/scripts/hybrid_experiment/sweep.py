"""Grid search บน tuning validation — ทุกจุดวัดผ่าน resolver จริง ไม่ใช่ ROC.

**ข้อผิดพลาดที่โมดูลนี้มีไว้เพื่อไม่ให้เกิด:** การหา "recall ที่ FPR 1%" โดยเลื่อน
threshold บนคะแนนดิบแล้วอ่าน ROC จะได้ตัวเลขที่ระบบจริง **สร้างไม่ได้** เพราะ
การตัดสินจริงไม่ได้มาจากคะแนนอย่างเดียว ยังผ่าน:

    * Policy Gate deny            -> block เสมอ ไม่ว่าคะแนนเท่าไร
    * Policy Gate min_action      -> ยกขึ้นอย่างน้อยระดับหนึ่ง
    * L3 solo cap                 -> ลด block เหลือ challenge เมื่อไม่มีชั้นอื่นยืนยัน

ถ้า Policy Gate สั่ง challenge ไปแล้ว 1.3% ของ login ปกติ การเลื่อน threshold
ให้สูงแค่ไหนก็ลด FPR ต่ำกว่า 1.3% ไม่ได้ -> ต้องรายงานว่า **เป้า 1% ทำไม่ได้**
และบอกค่าที่ใกล้ที่สุดที่ทำได้จริง ห้ามรายงานตัวเลขที่ระบบสร้างไม่ได้

threshold ที่ลองต้องมาจาก **ควอนไทล์ของคะแนน login ปกติ** ไม่ใช่เลขกลมสุ่มเอา
เพราะจุดที่อยู่ระหว่างค่าที่เป็นไปได้จริงคือจุดที่ระบบไปไม่ถึง
"""

from __future__ import annotations

from dataclasses import dataclass, field

GAMMA_GRID = (0.0, 0.1, 0.2, 0.35, 0.5)

# งบ FPR — ประกาศไว้ก่อนรัน ห้ามแก้หลังเห็นผล
CHALLENGE_FPR_BUDGET = 0.01
BLOCK_FPR_BUDGET = 0.002
WARN_FPR_BUDGET = 0.05

# tier ของปริมาณประวัติ — ประกาศไว้ก่อนรันเช่นกัน
# ถ้าหลักฐานไม่พอให้แยก threshold ตาม tier ต้องใช้ชุดเดียวทุกขนาด
MATURITY_TIERS = (
    ("cold", 0, 100),
    ("diagnostic", 100, 500),
    ("developing", 500, 1000),
    ("mature", 1000, 10**9),
)


def tier_of(size: int) -> str:
    for name, lo, hi in MATURITY_TIERS:
        if lo <= size < hi:
            return name
    return MATURITY_TIERS[-1][0]


@dataclass
class OperatingPoint:
    gamma: float
    thresholds: dict
    recall: float = 0.0
    precision: float = 0.0
    challenge_fpr: float = 0.0
    block_fpr: float = 0.0
    warn_fpr: float = 0.0
    l3_effective_unique: float = 0.0
    detail: dict = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return (
            self.challenge_fpr <= CHALLENGE_FPR_BUDGET
            and self.block_fpr <= BLOCK_FPR_BUDGET
        )


def threshold_candidates(normal_scores: list[float], n_points: int = 12) -> list[dict]:
    """สร้างชุด threshold จากควอนไทล์ของคะแนน login ปกติ.

    จุดที่เป็นไปได้จริงคือค่าที่คะแนนของ normal ไปถึงเท่านั้น การใช้เลขกลม
    (0.5 / 0.7 / 0.85) ทำให้ได้จุดทำงานที่ไม่สอดคล้องกับการกระจายจริงของระบบ
    """
    import numpy as np

    if not normal_scores:
        return [{"warn": 0.5, "challenge": 0.7, "block": 0.85}]
    arr = np.asarray(sorted(normal_scores), dtype=float)

    def q(p: float) -> float:
        return float(np.quantile(arr, min(max(p, 0.0), 1.0)))

    out: list[dict] = []
    # challenge: ไล่รอบ ๆ งบ FPR ที่ตั้งไว้ · block เข้มกว่าเสมอ · warn ผ่อนกว่าเสมอ
    for ch_fpr in np.linspace(
        CHALLENGE_FPR_BUDGET * 0.2, CHALLENGE_FPR_BUDGET * 2.0, n_points
    ):
        ch = q(1.0 - ch_fpr)
        for blk_mult in (0.25, 0.5):
            blk = q(1.0 - max(ch_fpr * blk_mult, 1e-6))
            for wn_mult in (3.0, 6.0):
                wn = q(1.0 - min(ch_fpr * wn_mult, WARN_FPR_BUDGET))
                if not (wn <= ch <= blk):
                    continue
                cand = {
                    "warn": round(wn, 6),
                    "challenge": round(ch, 6),
                    "block": round(blk, 6),
                }
                if cand not in out:
                    out.append(cand)
    return out or [{"warn": 0.5, "challenge": 0.7, "block": 0.85}]


def attainable_floor(evaluate_fn) -> dict:
    """FPR ต่ำสุดที่ระบบทำได้ — ดันทุก threshold ไปสุดแล้ววัดว่าเหลือเท่าไร.

    ส่วนที่เหลือมาจาก Policy Gate ล้วน (deny + min_action) ซึ่ง threshold
    ไม่มีอำนาจลด · ถ้าค่านี้สูงกว่างบ แปลว่าเป้าที่ตั้งไว้ทำไม่ได้ทางโครงสร้าง
    """
    impossible = {"warn": 1.01, "challenge": 1.01, "block": 1.01}
    s = evaluate_fn(0.0, impossible)
    return {
        "challenge_fpr_floor": s.challenge_fpr,
        "block_fpr_floor": s.block_fpr,
        "warn_fpr_floor": s.warn_fpr,
        "source": "policy_gate_only",
    }


def search(evaluate_fn, normal_scores: list[float]) -> dict:
    """ค้นหา operating point ที่ดีที่สุดภายในงบ FPR.

    `evaluate_fn(gamma, thresholds) -> Summary` ต้องเรียก **resolver จริง**
    (fuse + policy + cap) ไม่ใช่การตัดคะแนนตรง ๆ

    เกณฑ์เลือกตามลำดับ:
        1. FPR อยู่ในงบ (challenge และ block)
        2. recall สูงสุด
        3. precision สูงสุด
        4. gamma ต่ำสุด (โมเดลง่ายกว่าเมื่อผลเท่ากัน)
    """
    floor = attainable_floor(evaluate_fn)
    cands = threshold_candidates(normal_scores)
    points: list[OperatingPoint] = []
    for gamma in GAMMA_GRID:
        for thr in cands:
            s = evaluate_fn(gamma, thr)
            points.append(
                OperatingPoint(
                    gamma=gamma,
                    thresholds=thr,
                    recall=s.recall,
                    precision=s.precision,
                    challenge_fpr=s.challenge_fpr,
                    block_fpr=s.block_fpr,
                    warn_fpr=s.warn_fpr,
                    l3_effective_unique=s.l3_effective_unique,
                )
            )
    eligible = [p for p in points if p.eligible]
    best = None
    if eligible:
        best = max(eligible, key=lambda p: (p.recall, p.precision, -p.gamma))
    return {
        "attainable_floor": floor,
        "budget": {
            "challenge_fpr": CHALLENGE_FPR_BUDGET,
            "block_fpr": BLOCK_FPR_BUDGET,
        },
        "n_candidates": len(points),
        "n_eligible": len(eligible),
        "target_attainable": bool(eligible),
        "best": None if best is None else vars(best),
        "points": [vars(p) for p in points],
    }
