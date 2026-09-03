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

# ── กริดของ gamma: ประกาศสองรอบ บันทึกไว้ทั้งคู่ ──
# pass 1 (2 ก.ย. 2569): (0.0, 0.1, 0.2, 0.35, 0.5)
#   ผล: recall เพิ่มขึ้นแบบ monotone จนถึง 0.5 โดย FPR แทบไม่ขยับ
#        -> ค่าที่เลือกได้ไปติด **ขอบกริด** ซึ่งแปลว่ายังไม่รู้ว่าจุดที่ดีที่สุดอยู่ตรงไหน
# pass 2: ขยายถึง 1.0 แล้วรันซ้ำ **บน validation-tuning เท่านั้น** (holdout ยังไม่ถูกเปิด)
#   การขยายกริดหลังเห็นผลของ tuning เป็นสิ่งที่ tuning split มีไว้ให้ทำ แต่ต้อง
#   บันทึกว่าเป็นรอบที่สอง ไม่ใช่รายงานเหมือนประกาศกริดนี้มาตั้งแต่แรก
#
# หยุดที่ 1.0 เพราะ gamma = 1 คือ R = M + S(1-M) = 1 - (1-M)(1-S) ซึ่งเป็น
# probabilistic OR (noisy-OR) — ปลายทางที่มีความหมายของสูตรนี้ ไม่ใช่เลขที่สุ่มตัด
GAMMA_GRID = (0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)
GAMMA_GRID_PASSES = {
    "pass1": [0.0, 0.1, 0.2, 0.35, 0.5],
    "pass2": [0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0],
    "reason_for_pass2": "ค่าที่เลือกใน pass 1 ไปติดขอบกริด (gamma = 0.5)",
    "upper_endpoint_rationale": "gamma = 1 คือ noisy-OR ของหลักฐานสองชั้น",
}

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
    """FPR ต่ำสุดที่ระบบทำได้ — ดัน threshold ไปเกิน 1.0 แล้ววัดว่าเหลือเท่าไร.

    ส่วนที่เหลือมาจาก Policy Gate ล้วน (deny + min_action) ซึ่ง threshold ไม่มี
    อำนาจลด · ถ้าค่านี้สูงกว่างบ แปลว่าเป้าที่ตั้งไว้ทำไม่ได้ทางโครงสร้าง

    **ห้ามขยับเป้าให้ตรงกับค่าที่ทำได้** — ต้องรายงานว่าเป้าเดิมทำไม่ได้
    พร้อมค่าต่ำสุดที่ทำได้จริงและสาเหตุ ไม่ใช่เขียนเป้าใหม่ให้ผลดูผ่าน
    """
    impossible = {"warn": 1.01, "challenge": 1.01, "block": 1.01}
    m = evaluate_fn(0.0, impossible)
    ch_floor = m["challenge_fpr"]
    blk_floor = m["block_fpr"]
    return {
        "target_fpr": CHALLENGE_FPR_BUDGET,
        "target_attainable": ch_floor <= CHALLENGE_FPR_BUDGET,
        "minimum_attainable_fpr": round(ch_floor, 6),
        "cause": "policy_floor",
        "block": {
            "target_fpr": BLOCK_FPR_BUDGET,
            "target_attainable": blk_floor <= BLOCK_FPR_BUDGET,
            "minimum_attainable_fpr": round(blk_floor, 6),
            "cause": "policy_floor",
        },
        "per_size_minimum_attainable_fpr": {
            str(k): round(v["challenge_fpr"], 6)
            for k, v in m.get("per_size", {}).items()
        },
        "note": (
            "ค่านี้คือ FPR ที่เหลือเมื่อ threshold ถูกดันจนไม่มีเหตุการณ์ใดผ่านเกณฑ์คะแนน "
            "-> มาจาก Policy Gate ล้วน · ถ้า target_attainable=false ห้ามขยับเป้า "
            "ให้รายงานว่าเป้าเดิมทำไม่ได้"
        ),
    }


def eligible(m: dict) -> tuple[bool, list[str]]:
    """ผ่านงบ FPR ทั้ง **ค่ารวม** และ **ทุกขนาดข้อมูล** หรือไม่.

    ต้องตรวจรายขนาดด้วย เพราะจุดทำงานที่ FPR รวม 0.9% แต่ขนาด 50 อยู่ที่ 4%
    แปลว่าผู้ใช้ใหม่รับภาระเกินงบ ทั้งที่ตัวเลขรวมผ่าน
    """
    fails: list[str] = []
    if m["challenge_fpr"] > CHALLENGE_FPR_BUDGET:
        fails.append(f"macro_challenge_fpr={m['challenge_fpr']:.4f}")
    if m["block_fpr"] > BLOCK_FPR_BUDGET:
        fails.append(f"macro_block_fpr={m['block_fpr']:.4f}")
    # งบ warn ถูกประกาศไว้ตั้งแต่ต้นแต่เดิม**ไม่เคยถูกตรวจ** — เป็นช่องโหว่จริง
    # เพราะ recall นับ warn ด้วย จุดทำงานจึงดัน recall ขึ้นได้ด้วยการเตือนถี่ขึ้น
    # โดยไม่มีอะไรฟ้อง (เจอตอนเทียบ B ที่ gamma 1.0: warn FPR 2.40% -> 3.76%)
    if m["warn_fpr"] > WARN_FPR_BUDGET:
        fails.append(f"macro_warn_fpr={m['warn_fpr']:.4f}")
    for size, v in m.get("per_size", {}).items():
        if v["challenge_fpr"] > CHALLENGE_FPR_BUDGET:
            fails.append(f"size{size}_challenge_fpr={v['challenge_fpr']:.4f}")
        if v["block_fpr"] > BLOCK_FPR_BUDGET:
            fails.append(f"size{size}_block_fpr={v['block_fpr']:.4f}")
        if v["warn_fpr"] > WARN_FPR_BUDGET:
            fails.append(f"size{size}_warn_fpr={v['warn_fpr']:.4f}")
    return (not fails), fails


def _point(gamma: float, thr: dict, m: dict) -> dict:
    ok, fails = eligible(m)
    return {
        "gamma": gamma,
        "thresholds": thr,
        "recall": round(m["recall"], 6),
        # recall ที่นับเฉพาะ challenge/block — ต้องรายงานคู่กันเสมอ ไม่งั้นอ่านไม่ออกว่า
        # recall ที่เพิ่มขึ้นมาจากการจับได้จริง หรือมาจากการเตือน (warn) ถี่ขึ้น
        "recall_challenge": round(m["recall_challenge"], 6),
        "precision": round(m["precision"], 6),
        "challenge_fpr": round(m["challenge_fpr"], 6),
        "block_fpr": round(m["block_fpr"], 6),
        "warn_fpr": round(m["warn_fpr"], 6),
        "within_config_l3_counterfactual_unique": round(
            m["within_config_l3_counterfactual_unique"], 6
        ),
        "campaign_surfaced": round(m["campaign_surfaced"], 6),
        "eligible": ok,
        "violations": fails,
        "per_size": {
            str(k): {
                "recall": round(v["recall"], 6),
                "recall_challenge": round(v["recall_challenge"], 6),
                "challenge_fpr": round(v["challenge_fpr"], 6),
                "block_fpr": round(v["block_fpr"], 6),
                "warn_fpr": round(v["warn_fpr"], 6),
            }
            for k, v in m.get("per_size", {}).items()
        },
    }


def search(evaluate_fn, normal_scores: list[float], gammas=GAMMA_GRID) -> dict:
    """ค้นหา operating point ที่ดีที่สุดภายในงบ FPR (macro across seed x size x user).

    `evaluate_fn(gamma, thresholds) -> macro dict` ต้องเรียก **resolver จริง**
    ของ production ไม่ใช่การตัดคะแนนตรงๆ

    เกณฑ์เลือกตามลำดับ:
        1. FPR อยู่ในงบ ทั้งค่ารวมและทุกขนาด
        2. macro recall สูงสุด
        3. precision สูงสุด
        4. gamma ต่ำสุด (โมเดลง่ายกว่าเมื่อผลเท่ากัน)
    """
    floor = attainable_floor(evaluate_fn)
    cands = threshold_candidates(normal_scores)
    points = [_point(g, thr, evaluate_fn(g, thr)) for g in gammas for thr in cands]
    ok_points = [p for p in points if p["eligible"]]
    best = None
    if ok_points:
        best = max(ok_points, key=lambda p: (p["recall"], p["precision"], -p["gamma"]))
    return {
        "attainable_floor": floor,
        "budget": {
            "challenge_fpr": CHALLENGE_FPR_BUDGET,
            "block_fpr": BLOCK_FPR_BUDGET,
            "warn_fpr": WARN_FPR_BUDGET,
        },
        "selection_rule": "macro recall -> precision -> gamma ต่ำสุด · FPR ต้องผ่านทุกขนาด",
        "gamma_grid": list(gammas),
        "n_candidates": len(points),
        "n_eligible": len(ok_points),
        "target_attainable": bool(ok_points),
        "best": best,
        "points": points,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Round 2 — common-FPR operating point (เทียบข้ามสถาปัตยกรรมที่ FPR ร่วม)
#
# ที่มา: Round 1 บอกว่า "เทียบที่ challenge FPR 1% ไม่ได้ เพราะ legacy floor 1.2467%"
# ทางแก้ที่ถูกคือเทียบที่ common FPR **ที่สูงกว่า floor** เช่น 1.5% — ทุก config
# ถูกดันให้ทำงานที่ FPR เดียวกัน แล้วเทียบ recall กันตรงๆ
# ══════════════════════════════════════════════════════════════════════════════


def _linear_threshold_grid(n_points: int = 60) -> list[dict]:
    """ชุด threshold แบบเชิงเส้นเมื่อไม่มีคะแนน normal ให้อ้างควอนไทล์ (ใช้ในเทส/ทั่วไป)."""
    out: list[dict] = []
    for i in range(n_points):
        ch = 0.5 + (0.99995 - 0.5) * i / (n_points - 1)
        blk = ch + (1.0 - ch) * 0.5
        wn = ch * 0.9
        out.append(
            {"warn": round(wn, 6), "challenge": round(ch, 6), "block": round(blk, 6)}
        )
    return out


def operating_point_at_fpr(
    evaluate_fn,
    target_fpr: float,
    *,
    gamma: float,
    normal_scores: list[float] | None = None,
) -> dict:
    """หาจุดทำงานที่ challenge FPR **ไม่เกิน** target แล้วได้ recall สูงสุด.

    `evaluate_fn(gamma, thresholds) -> macro dict` ต้องเรียก resolver ของ production
    (เหมือน sweep.search) · ถ้าไม่มีจุดใดถึงเป้า คืน attained=False พร้อม
    minimum_attainable_fpr — **ห้ามขยับเป้า** ให้รายงานว่าเป้านั้นทำไม่ได้
    """
    cands = (
        threshold_candidates(normal_scores)
        if normal_scores
        else _linear_threshold_grid()
    )
    rows = []
    for thr in cands:
        m = evaluate_fn(gamma, thr)
        rows.append((thr, m))
    eligible = [(thr, m) for thr, m in rows if m["challenge_fpr"] <= target_fpr + 1e-12]
    if not eligible:
        floor = min(m["challenge_fpr"] for _, m in rows) if rows else 1.0
        return {
            "attained": False,
            "target_fpr": target_fpr,
            "gamma": gamma,
            "minimum_attainable_fpr": round(floor, 6),
            "note": (
                "ไม่มีจุดทำงานที่ FPR ถึงเป้า — ห้ามขยับเป้า ให้รายงานว่าทำไม่ได้ "
                "พร้อมค่าต่ำสุดที่ทำได้จริง"
            ),
        }
    thr, m = max(
        eligible,
        key=lambda x: (
            x[1]["recall"],
            x[1].get("recall_challenge", 0.0),
            x[1]["precision"],
        ),
    )
    return {
        "attained": True,
        "target_fpr": target_fpr,
        "gamma": gamma,
        "thresholds": thr,
        "recall": round(m["recall"], 6),
        "recall_challenge": round(m.get("recall_challenge", 0.0), 6),
        "precision": round(m["precision"], 6),
        "challenge_fpr": round(m["challenge_fpr"], 6),
        "block_fpr": round(m["block_fpr"], 6),
        "warn_fpr": round(m["warn_fpr"], 6),
        "within_config_l3_counterfactual_unique": round(
            m.get("within_config_l3_counterfactual_unique", 0.0), 6
        ),
    }
