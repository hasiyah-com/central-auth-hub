"""Tail calibration — เครื่องมือวัด "หางขวา" ของคะแนนความเสี่ยง โดยไม่แตะ ECE.

**ทำไมไม่ใช้ ECE (Expected Calibration Error):** ECE ถามว่า "คะแนน p ตรงกับ
ความน่าจะเป็นจริงที่เป็น attack แค่ไหน" ซึ่งสมเหตุสมผลเฉพาะเมื่อคะแนน **เป็น
probability** · แต่ `final_risk_score` ของระบบนี้เป็น **percentile evidence**
เทียบกับ login ปกติ **ไม่ใช่ probability** — ค่า 0.99 แปลว่า "หายากระดับ 1 ใน 100
ถ้าเป็นคนปกติ" ไม่ใช่ "มั่นใจ 99% ว่าเป็น attack" · การเอา ECE มาใช้จึงลงโทษ
โมเดลด้วยเกณฑ์ที่โมเดลไม่เคยอ้าง (ข้อผิดพลาดของ Round 1 ที่รายงาน ECE 0.607
ของ Config E ราวกับว่าพิสูจน์ว่ามันแย่)

**สิ่งที่ถามแทน — ตรงกับงบ FPR โดยตรง:**

  benign percentile exceedance  ตั้งเกณฑ์ที่ p95/p99/p99.9 ของ login ปกติชุดหนึ่ง
                                แล้ววัดว่า login ปกติ **อีกชุด** เกินเกณฑ์กี่ %
                                ควรใกล้ 5% / 1% / 0.1% ตามนิยาม ถ้าไม่ใกล้ =
                                หางเลื่อน (นี่คือกลไกที่ทำให้ FPR บน holdout
                                สูงกว่าที่จูนไว้บน validation)

  PIT uniformity                Probability Integral Transform: แปลงคะแนนของชุด
                                วัดผลด้วย empirical CDF ของ login ปกติ ถ้าสองชุด
                                มาจาก distribution เดียวกัน ค่าที่ได้ต้องกระจาย
                                uniform[0,1] · วัดความเบี่ยงด้วย KS statistic

stdlib ล้วน (ไม่ใช้ numpy/scipy) เพื่อให้รันได้ทุกที่รวมถึงคอนเทนเนอร์ที่ไม่มี ML dep
"""

from __future__ import annotations

import bisect
import math

# ระดับที่วัด — ผูกกับงบ FPR (challenge <= 1% -> p99 คือจุดที่ต้องเฝ้า)
TAIL_LEVELS = {"p95": 0.95, "p99": 0.99, "p999": 0.999}


def _quantile(sorted_vals: list[float], p: float) -> float:
    """ควอนไทล์แบบ nearest-rank — threshold ที่สัดส่วน p ของข้อมูลอยู่ต่ำกว่าหรือเท่ากับ."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    return sorted_vals[min(int(p * n), n - 1)]


def pit_values(calib_normals: list[float], scores: list[float]) -> list[float]:
    """PIT ของแต่ละ score = สัดส่วนของ calib ที่ **ไม่เกิน** score.

    monotone ไม่ลดตาม score และอยู่ใน [0,1] เสมอ · ใช้ empirical CDF ของ login
    ปกติเป็นตัวแปลง
    """
    q = sorted(float(x) for x in calib_normals)
    n = len(q)
    if n == 0:
        return [0.0 for _ in scores]
    return [bisect.bisect_right(q, float(s)) / n for s in scores]


def benign_exceedance(calib_normals: list[float], eval_normals: list[float]) -> dict:
    """ตั้งเกณฑ์ที่ p95/p99/p99.9 ของ calib แล้ววัดสัดส่วน eval ที่เกินเกณฑ์.

    ถ้า eval มาจาก distribution เดียวกับ calib -> exceedance ต้องใกล้ 1-p
    ถ้า eval หางหนักกว่า (เช่น holdout ต่างจาก validation) -> exceedance สูงกว่า
    """
    q = sorted(float(x) for x in calib_normals)
    ev = [float(x) for x in eval_normals]
    n_ev = len(ev)
    out: dict = {}
    shifted = False
    for name, p in TAIL_LEVELS.items():
        thr = _quantile(q, p)
        nominal = 1.0 - p
        exceed = (sum(1 for x in ev if x > thr) / n_ev) if n_ev else 0.0
        # หางเลื่อนถ้า exceedance เกิน nominal อย่างมีนัย (>1.5 เท่า และ +>0.3pp)
        if exceed > nominal * 1.5 and (exceed - nominal) > 0.003:
            shifted = True
        out[name] = {
            "percentile": p,
            "threshold": round(thr, 6),
            "nominal_exceedance": round(nominal, 6),
            "observed_exceedance": round(exceed, 6),
            "ratio": round(exceed / nominal, 4) if nominal else 0.0,
        }
    out["tail_shift_detected"] = shifted
    out["n_eval"] = n_ev
    out["note"] = (
        "observed_exceedance คือสัดส่วน login ปกติที่เกินเกณฑ์ — ตรงกับ FPR ที่จุดนั้น "
        "ไม่ใช่ probability ของการเป็น attack"
    )
    return out


def _ks_pvalue(d: float, n: int) -> float:
    """p-value เชิงเส้นกำกับของ KS (Kolmogorov distribution) — clamp ใน [0,1]."""
    if n == 0 or d <= 0:
        return 1.0
    t = (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n)) * d
    s = 0.0
    for k in range(1, 101):
        s += (-1) ** (k - 1) * math.exp(-2 * k * k * t * t)
    p = 2 * s
    return min(1.0, max(0.0, p))


def pit_uniformity(calib_normals: list[float], sample: list[float]) -> dict:
    """แปลง sample ด้วย PIT ของ calib แล้ววัดว่าเป็น uniform[0,1] แค่ไหน (KS).

    ks_statistic เล็ก = sample มาจาก distribution เดียวกับ calib
    ks_statistic ใหญ่ = ต่างกัน (distribution shift)
    """
    pit = sorted(pit_values(calib_normals, sample))
    n = len(pit)
    if n == 0:
        return {"ks_statistic": 0.0, "ks_pvalue": 1.0, "n": 0}
    d = 0.0
    for i, p in enumerate(pit):
        d = max(d, (i + 1) / n - p, p - i / n)
    return {
        "ks_statistic": round(d, 6),
        "ks_pvalue": round(_ks_pvalue(d, n), 6),
        "n": n,
        "note": "PIT uniformity — ไม่ใช่ probability calibration · ไม่ใช้ ECE โดยตั้งใจ",
    }


def full_report(
    calib_normals: list[float],
    holdout_normals: list[float],
    validation_normals: list[float] | None = None,
) -> dict:
    """รายงานรวม — exceedance + PIT ของ holdout · เทียบ validation ถ้ามี.

    ใช้ตอบคำถามของ Round 1: "ทำไม FPR บน holdout สูงกว่าที่จูนไว้บน validation"
    """
    report = {
        "holdout_exceedance": benign_exceedance(calib_normals, holdout_normals),
        "holdout_pit_uniformity": pit_uniformity(calib_normals, holdout_normals),
        "calibration_metric": "tail_calibration_v1",
        "explicitly_not_ece": (
            "ไม่ใช้ ECE เพราะ final_risk_score เป็น percentile evidence ไม่ใช่ probability"
        ),
    }
    if validation_normals is not None:
        report["validation_exceedance"] = benign_exceedance(
            calib_normals, validation_normals
        )
        report["validation_pit_uniformity"] = pit_uniformity(
            calib_normals, validation_normals
        )
    return report
