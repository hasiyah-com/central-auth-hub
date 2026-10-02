"""ชั้นที่ 3 เป็นตัวสำรองระดับ warn — ใช้เมื่อชั้นที่ 1+2 ไม่พบความผิดปกติ (ผลเป็น allow)

ที่มา: การทดลองที่ลงทะเบียนก่อนวัด (l3_fallback_result_2026-10-01 · branch exp/l3-capped-score)
    recall@warn 52.39% → 67.33% (+14.94 [+13.02, +16.78]) · warn FPR 1.22% → 4.14% ·
    challenge FPR และ recall@challenge ไม่เปลี่ยน · ยกเป็น challenge ไม่คุ้ม (+0.17 จุด) จึงไม่ทำ

ไม่นับซ้ำโดยโครงสร้าง: ถ้าชั้นที่ 1+2 จับได้แล้ว (warn ขึ้นไป) จะไม่ใช้คะแนนชั้นที่ 3
ใช้เฉพาะ point view (IForest 23 ฟีเจอร์) · sequence view ยังเป็นแกนเฝ้าระวังอย่างเดียว

เกณฑ์อยู่บนสเกลเดียวกับ `predict_score` (sigmoid(-5·decision_function)) · แยกตามประเภทผู้ใช้ได้
แต่ค่าเริ่มต้นเท่ากันทุกประเภท — การทดลองกับแบบจำลองที่ระบบจริงใช้ไม่พบว่าเกณฑ์ต่อประเภทลด
warn ผิดของอาจารย์ (l3_hybrid_user_result: 6.53% เทียบ 6.58%) · ปรับเมื่อมีหลักฐานจากข้อมูลจริง
"""

from __future__ import annotations

import math

REASON = "l3_fallback_warn"
DEFAULT_THRESHOLD = 0.4606

# ประเภทผู้ใช้ → เกณฑ์ (ค่าเท่ากันโดยเจตนา ดู docstring)
THRESHOLDS_BY_USER_TYPE: dict[str, float] = {
    "student": DEFAULT_THRESHOLD,
    "teacher": DEFAULT_THRESHOLD,
    "staff": DEFAULT_THRESHOLD,
    "admin": DEFAULT_THRESHOLD,
}


def threshold_for(user_type: str | None) -> float:
    return THRESHOLDS_BY_USER_TYPE.get(user_type or "", DEFAULT_THRESHOLD)


def apply(
    decision: str, point_score: float | None, user_type: str | None, shadow_mode: bool
) -> tuple[str, str | None]:
    """คืน (decision ใหม่, เหตุผล) · ยกได้จาก allow เป็น warn/would_warn เท่านั้น."""
    if decision != "allow" or point_score is None or math.isnan(point_score):
        return decision, None
    thr = threshold_for(user_type)
    if point_score < thr:
        return decision, None
    new = "would_warn" if shadow_mode else "warn"
    return new, f"{REASON} (L3 {point_score:.3f} >= {thr:.4f})"
