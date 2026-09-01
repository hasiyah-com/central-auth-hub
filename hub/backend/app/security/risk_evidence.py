"""แปลงผลของแต่ละชั้นให้เป็น Evidence ที่ calibrate แล้ว — จุดเดียวที่ทำการแปลงนี้.

แยกออกมาจาก risk_engine เพื่อให้เห็นชัดว่า "คะแนนดิบเข้ามาแล้วออกไปเป็นหลักฐาน
บนสเกลเดียวกันตรงไหน" · การทดลองก็เรียกฟังก์ชันชุดเดียวกันนี้ จึงไม่มีทางที่
harness กับ production จะคำนวณคนละแบบ (บทเรียน B66)
"""

from __future__ import annotations

from app.security.calibration import calibrate
from app.security.evidence import Evidence, abstain

LAYER_RULE = "rule"
LAYER_BEHAVIOR = "behavior"
LAYER_ANOMALY = "anomaly"


def _ev(layer: str, cal_layer: str, raw: float, reasons, **kw) -> Evidence:
    c = calibrate(cal_layer, raw)
    return Evidence(
        layer=layer,
        evidence_score=c.value,
        raw_score=raw,
        reasons=list(reasons or []),
        detail={"calibrated": c.calibrated, "calibration_version": c.version, **kw},
    )


def rule_evidence(rule_result) -> Evidence:
    """L1 -> หลักฐาน · `blocked` เดิมกลายเป็นหลักฐานระดับสูงสุด ไม่ใช่คำสั่ง block.

    เหตุผล: `impossible_travel` เป็นการอนุมาน (VPN/roaming ทำให้เกิดได้) จึงไม่ควร
    ปฏิเสธผู้ใช้โดยไม่ผ่าน L4 · ส่วนกรณีที่เป็นข้อบังคับจริง (deny-list, brute-force)
    ถูก Policy Gate ดักไปก่อนหน้านี้แล้ว จึงไม่มาถึงตรงนี้
    """
    raw = 1.0 if getattr(rule_result, "blocked", False) else float(rule_result.score)
    return _ev(LAYER_RULE, "rule", raw, rule_result.reasons)


def behavior_evidence(behavior_result) -> Evidence:
    return _ev(
        LAYER_BEHAVIOR,
        "behavior",
        float(behavior_result.score),
        behavior_result.reasons,
    )


def anomaly_evidence(l3: dict | None) -> Evidence:
    """L3 สองมุมมอง -> หลักฐานเดียว.

    **ใช้ max ไม่ใช่ผลบวก** — สองมุมมองอาจตรวจพบเหตุการณ์เดียวกัน การบวกจะนับซ้ำ
    และดันคะแนนขึ้นโดยไม่มีหลักฐานเพิ่มจริง · การสนับสนุนข้ามชั้นให้ L4 จัดการ
    ผ่านพจน์ corroboration ซึ่งควบคุมด้วย gamma ที่เลือกจาก validation

    มุมมองที่ `eligible=false` (ประวัติไม่พอ) จะไม่ถูกนับ — ไม่ใช่ถือว่าคะแนน 0
    """
    if not l3 or l3.get("error"):
        return abstain(LAYER_ANOMALY, (l3 or {}).get("error") or "l3_unavailable")

    point = l3.get("point") or {}
    seq = l3.get("sequence") or {}
    parts: list[tuple[str, float, float]] = []  # (view, calibrated, raw)

    if point.get("available"):
        raw = float(point.get("anomaly_score") or 0.0)
        parts.append(("point", calibrate("anomaly_point", raw).value, raw))

    # sequence นับได้เฉพาะเมื่อประวัติถึงเกณฑ์ที่ calibrate ไว้
    if seq.get("eligibility") in ("warn", "challenge"):
        raw = float(seq.get("raw_score") or 0.0)
        parts.append(("sequence", calibrate("anomaly_sequence", raw).value, raw))

    if not parts:
        return abstain(LAYER_ANOMALY, "insufficient_history")

    view, best, best_raw = max(parts, key=lambda p: p[1])
    reasons = [f"l3_{view} evidence={best:.3f}"]
    ev = _ev(
        LAYER_ANOMALY,
        "anomaly_" + view,
        best_raw,
        reasons,
        view=view,
        views={v: round(c, 4) for v, c, _ in parts},
    )
    ev.model_version = (l3.get("model_version") or {}).get(view)
    return ev
