"""แปลงผลจาก risk_engine เป็นคอลัมน์ของ `login_sessions` — จุดเดียวที่ทำการแปลงนี้.

ทุกเส้นทาง login เรียกฟังก์ชันเดียวกันนี้ ไม่คัดลอกตรรกะไปไว้ที่ router
เหตุผลเดียวกับ B66: ถ้าแต่ละเส้นทางเขียนเอง จะมีเส้นทางที่บันทึกไม่ครบหรือบันทึก
คนละความหมายโดยไม่มีใครรู้ แล้วผลวิจัยที่ได้ก็จะเป็นของประชากรที่ปนกัน

**ไม่มีฟังก์ชันไหนในไฟล์นี้คืนค่าที่ใช้ตัดสินการเข้าถึง** — คืนเฉพาะสิ่งที่เอาไปเก็บ
"""

from __future__ import annotations

from app.config import settings

# ค่าที่บอกว่า login ครั้งนี้ "การตัดสินจริง" มาจากไหน
SOURCE_GOOGLE = "google_callback"
SOURCE_LINE = "line_callback"
SOURCE_OAUTH = "oauth_subsystem"
SOURCE_PASSKEY = "passkey_login"
SOURCE_REFRESH = "refresh_risk_gate"

SOURCES = frozenset(
    {SOURCE_GOOGLE, SOURCE_LINE, SOURCE_OAUTH, SOURCE_PASSKEY, SOURCE_REFRESH}
)


def _num(value):
    """คืน None ไว้เมื่อไม่มีค่า — NULL แปลว่า "ไม่ได้คำนวณ" ไม่ใช่ "ได้ศูนย์" (B51)."""
    return None if value is None else float(value)


def shadow_columns(
    risk: dict,
    *,
    source: str,
    latency_total_ms: int | None = None,
    latency_l3_ms: int | None = None,
) -> dict:
    """ผลจาก `evaluate_login_risk` -> dict สำหรับ splat เข้า `LoginSession(...)`.

    ที่มาของคอนฟิกอ่านจาก settings **ตอนให้คะแนน** ไม่ใช่ตอน query ภายหลัง —
    ถ้าคอนฟิกเปลี่ยนระหว่างวัน แถวเก่าต้องยังบอกได้ว่าตัวเองถูกให้คะแนนด้วยอะไร
    """
    if source not in SOURCES:
        raise ValueError(f"ที่มาของการตัดสินไม่อยู่ในรายการที่ประกาศไว้: {source!r}")

    baseline = risk.get("baseline_shadow") or {}
    hybrid = risk.get("hybrid_shadow") or {}
    l3 = risk.get("l3") or {}
    breakdown = risk.get("breakdown") or {}
    uncalibrated = breakdown.get("uncalibrated_layers")

    return {
        "actual_decision_source": source,
        "baseline_shadow_score": _num(baseline.get("final_risk")),
        "baseline_shadow_decision": baseline.get("decision"),
        "hybrid_shadow_score": _num(hybrid.get("final_risk")),
        "hybrid_shadow_decision": hybrid.get("decision"),
        "l3_changed_shadow_decision": l3.get("changed_shadow_decision"),
        "l3_eligibility": l3.get("eligibility"),
        "l3_n_history": l3.get("n_history"),
        # uncalibrated_layers เป็น list — ว่าง = ทุกชั้นที่นับมีตาราง calibration
        # None (ไม่มีคีย์) = ยังไม่รู้ ไม่ใช่ "calibrate แล้ว"
        "calibrated": None if uncalibrated is None else not uncalibrated,
        "calibration_version": settings.calibration_version,
        "calibration_sha256": settings.calibration_sha256,
        "risk_config_id": settings.risk_config_id,
        "shadow_epoch_id": settings.shadow_epoch_id,
        "scoring_commit": settings.scoring_commit,
        # risk_engine จับเวลาเองตั้งแต่ก่อน Policy Gate — router ส่งค่ามาเองได้
        # เมื่อต้องการนับรวมงานอื่นที่อยู่นอก engine
        "latency_total_ms": (
            latency_total_ms
            if latency_total_ms is not None
            else risk.get("latency_total_ms")
        ),
        "latency_l3_ms": (
            latency_l3_ms if latency_l3_ms is not None else risk.get("latency_l3_ms")
        ),
    }
