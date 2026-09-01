"""L3 — orchestrator เดียว สองมุมมอง (point + sequence).

เดิม L3 กระจายอยู่สองที่ที่ไม่รู้จักกัน:

    /v1/score           IForest 23 ฟีเจอร์ + SHAP  -> คะแนนถูกส่งเข้า aggregate (แตะ access!)
    /v1/sequence-score  IForest residual 18 มิติ   -> monitoring อย่างเดียว แต่ไม่มี SHAP

ผลคือคำกล่าวที่ว่า "L3 ไม่แตะ access decision" จริงเฉพาะครึ่งเดียว และคำอธิบาย
(explainability) ก็มีเฉพาะครึ่งเดียว — คนละครึ่งกัน

ไฟล์นี้รวมสองมุมมองเป็นผล L3 เดียว:

    point view    : IForest 23 ฟีเจอร์  -> "login ครั้งนี้ผิดปกติไหม"   (snapshot)
    sequence view : IForest 18 มิติ     -> "พฤติกรรมช่วงนี้ผิดปกติไหม" (ต่อเนื่อง)

ทั้งสองมุมมองออกทาง `monitoring_decision` เท่านั้น — ไม่มีเส้นทางไหนกลับเข้า
access decision ได้อีก (hub ส่ง IForest เข้า aggregate ด้วย risk_score=0.0)

หน่วยวัดที่เพิ่มเข้ามา:
    unique_to_l3    ต่อเหตุการณ์ — L3 เห็น แต่ L1/L2 ปล่อยผ่าน (คุณค่าที่แท้จริงของ L3)
    duplicate_ratio สะสม        — สัดส่วนที่ L3 ยิงซ้ำกับสิ่งที่ L1/L2 จับได้อยู่แล้ว
"""

from __future__ import annotations

import logging

from app import sequence as SEQ
from app.features import FEATURE_COUNT
from app.model import explainer_status as point_explainer_status
from app.model import predict_with_explanation

logger = logging.getLogger(__name__)

# ── เกณฑ์ของ point view ────────────────────────────────────────────────────
# ตรงกับ THRESHOLD_MFA / THRESHOLD_BLOCK ใน main.py โดยตั้งใจ (ตัวเลขชุดเดียวกัน)
POINT_ANOMALY = 0.50
# ขึ้นธงให้ SOC ใช้เกณฑ์สูงกว่า: โมเดล 23 ฟีเจอร์เทรนบนข้อมูลจำลองและวัด optimism bias
# ไว้แล้ว (ดู exp_final_gate) — ใช้เกณฑ์ 0.50 ขึ้นธงจะท่วม SOC ด้วยสัญญาณที่พิสูจน์
# ไม่ได้ว่าแม่นบน traffic จริง · เป็นค่าของช่องเฝ้าระวังล้วน ไม่กระทบสิทธิ์ผู้ใช้
POINT_INVESTIGATE = 0.70

MONITORING_NORMAL = "normal"
MONITORING_INVESTIGATE = "l3_investigate"

VIEW_POINT = "point_iforest"
VIEW_SEQUENCE = "sequence_residual"

OWNER_POINT = "l3_point"
OWNER_SEQUENCE = "l3_sequence"

TOP_K = 5

# ตัวนับสะสมของ duplicate ratio — ratio ต้องมีตัวหาร จึงเป็นค่าสะสม ไม่ใช่ค่าต่อ event
DUP_FLAGGED_KEY = "l3dup:flagged"
DUP_DUPLICATE_KEY = "l3dup:dup"


def _point_view(features: list[float]) -> dict:
    """IForest 23 ฟีเจอร์ + SHAP — fail-safe: พังแล้วคืน 'ไม่ยิง' ไม่ raise."""
    quiet = {
        "available": False,
        "anomaly_score": 0.0,
        "is_anomaly": False,
        "explanation": [],
        "explainer": point_explainer_status(),
        "error": None,
    }
    if not features or len(features) != FEATURE_COUNT:
        return {**quiet, "error": "invalid_features"}
    try:
        score, explanation = predict_with_explanation(features, top_k=TOP_K)
        return {
            "available": True,
            "anomaly_score": round(float(score), 4),
            "is_anomaly": float(score) >= POINT_ANOMALY,
            "explanation": explanation,
            "explainer": point_explainer_status(),
            "error": None,
        }
    except FileNotFoundError:
        return {**quiet, "error": "model_not_loaded"}
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_unified] point view error: %s", e)
        return {**quiet, "error": f"point_error: {type(e).__name__}"}


def _sequence_view(
    redis, user_id: str, residual: list[float], explain: bool = False
) -> dict:
    """IForest residual 18 มิติ + SHAP — abstain เงียบเมื่อประวัติไม่พอ."""
    if not residual:
        # hub ปิดแฟล็ก sequence หรือคำนวณ residual ไม่ได้ -> ไม่ใช่ error
        return {**dict(SEQ.QUIET), "error": None}
    if redis is None:
        return {**dict(SEQ.QUIET), "error": "redis_unavailable"}
    try:
        return {**SEQ.score(redis, user_id, residual, explain=explain), "error": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_unified] sequence view error: %s", e)
        return {**dict(SEQ.QUIET), "error": f"sequence_error: {type(e).__name__}"}


def _sequence_flags(seq: dict) -> bool:
    """sequence ขึ้นธงได้ต่อเมื่อยิง **และ** ประวัติถึง tier ที่เชื่อได้ (warn/challenge)."""
    return bool(seq.get("fired")) and seq.get("eligibility") in ("warn", "challenge")


ATTRIBUTION_CAVEAT = (
    "SHAP attribution ไม่ใช่สาเหตุ และไม่ใช่มิติที่เบี่ยงเบนมากที่สุด — "
    "ความแม่นในการระบุมิติเริ่มลดลงตั้งแต่ช่วงที่คะแนนผ่านเกณฑ์แจ้งเตือน "
    "(ก่อน anomaly score ชนเพดาน) ใช้เพื่อ debug โมเดลเท่านั้น · "
    "ถ้าต้องการรู้ว่ามิติใดต่างจากปกติของผู้ใช้ ให้ดู diagnostic_factors"
)


def _diagnostic_factors(seq: dict, views: list[str]) -> list[dict]:
    """คำอธิบายหลัก — ส่วนเบี่ยงเบนรายมิติเทียบ baseline ของผู้ใช้คนนั้น (B67).

    มาจาก sequence view เท่านั้น เพราะเป็นมุมมองเดียวที่มี baseline รายบุคคล
    ส่วน point view ใช้โมเดลตัวเดียวกับทุกคน จึงไม่มี "ปกติของคนนี้" ให้เทียบ
    """
    if VIEW_SEQUENCE not in views:
        return []
    return [
        {**f, "owner": OWNER_SEQUENCE} for f in (seq.get("diagnostic_factors") or [])
    ][:TOP_K]


def _model_attribution(point: dict, seq: dict, views: list[str]) -> list[dict]:
    """SHAP ของทั้งสองมุมมอง — **ข้อมูลเสริมสำหรับ debug ไม่ใช่คำอธิบายที่ส่งให้ SOC**.

    เดิมฟิลด์นี้ชื่อ `top_factors` ซึ่งอ่านแล้วเข้าใจว่าเป็น "ปัจจัยหลัก" หรือสาเหตุ
    เปลี่ยนชื่อเป็น model_attribution เพื่อไม่ให้สื่อเกินกว่าที่หลักฐานรองรับ (B67)

    `contribution` = สัดส่วนภายในมุมมองของตัวเอง (|shap| / ผลรวม |shap| ของมุมมองนั้น)
    เทียบข้ามมุมมองตรงๆ ไม่ได้ เพราะ SHAP ของสองโมเดลอยู่คนละสเกล

    หมายเหตุขอบเขต: ข้อจำกัดที่วัดไว้เป็นของ sequence view (18 มิติ) ส่วน point view
    (23 คุณลักษณะ) **ยังไม่ได้วัด** ปัญหาแบบเดียวกัน จึงยังสรุปแทนกันไม่ได้
    """
    out: list[dict] = []
    for view, owner, src in (
        (VIEW_POINT, OWNER_POINT, point.get("explanation") or []),
        (VIEW_SEQUENCE, OWNER_SEQUENCE, seq.get("explanation") or []),
    ):
        if view not in views or not src:
            continue
        total = sum(abs(float(f.get("shap") or 0.0)) for f in src) or 1.0
        for f in src:
            shap_v = float(f.get("shap") or 0.0)
            out.append(
                {
                    "feature": f.get("feature"),
                    "owner": owner,
                    "contribution": round(abs(shap_v) / total, 4),
                    "shap": shap_v,
                    "value": f.get("value"),
                    "direction": f.get("direction"),
                }
            )
    out.sort(key=lambda d: d["contribution"], reverse=True)
    return out[:TOP_K]


def _duplicate_stats(redis, flagged: bool, duplicate: bool) -> tuple[float | None, int]:
    """ตัวนับสะสมของ duplicate ratio — fail-safe: redis พัง -> (None, 0).

    นับเฉพาะเหตุการณ์ที่ L3 ขึ้นธง:
        flagged   +1 ทุกครั้งที่ L3 ยิง
        duplicate +1 เมื่อ L1/L2 จับได้อยู่แล้ว (access_decision != allow)

    ratio = duplicate / flagged — ยิ่งต่ำ แปลว่า L3 ยิ่งเห็นสิ่งที่ชั้นอื่นมองไม่เห็น
    เป็นค่า**สะสม** ไม่ใช่ rolling window จึงคืน `duplicate_window` (ตัวหาร) มาด้วย
    เสมอ ไม่งั้นอ่าน ratio 1.00 ไม่ออกว่ามาจาก 1 เหตุการณ์หรือ 1,000 เหตุการณ์
    """
    if redis is None:
        return None, 0
    try:
        if flagged:
            pipe = redis.pipeline()
            pipe.incr(DUP_FLAGGED_KEY)
            if duplicate:
                pipe.incr(DUP_DUPLICATE_KEY)
            pipe.execute()
        n_flagged = int(redis.get(DUP_FLAGGED_KEY) or 0)
        n_dup = int(redis.get(DUP_DUPLICATE_KEY) or 0)
        if n_flagged <= 0:
            return None, 0
        return round(n_dup / n_flagged, 4), n_flagged
    except Exception as e:  # noqa: BLE001
        logger.warning("[l3_unified] duplicate counter error: %s", e)
        return None, 0


def evaluate(
    redis,
    user_id: str,
    features: list[float],
    residual: list[float] | None,
    access_decision: str = "allow",
    explain: bool = False,
) -> dict:
    """ประเมิน L3 ทั้งสองมุมมอง คืนผลเดียว.

    `access_decision` คือผลของ L1/L2/L4 ที่ตัดสิน**เสร็จแล้ว** — รับเข้ามาเพื่อ
    *วัด* ว่า L3 เห็นอะไรที่ชั้นอื่นไม่เห็น (unique_to_l3) เท่านั้น
    **ไม่มีเส้นทางไหนในไฟล์นี้เขียนค่ากลับไปที่ access_decision** — ผลลัพธ์ทั้งหมด
    ออกทาง monitoring_decision อย่างเดียว
    """
    point = _point_view(features)
    seq = _sequence_view(redis, user_id, residual, explain=explain)

    views: list[str] = []
    if point.get("is_anomaly"):
        views.append(VIEW_POINT)
    if _sequence_flags(seq):
        views.append(VIEW_SEQUENCE)

    is_anomaly = bool(views)
    investigate = (
        VIEW_SEQUENCE in views
        or float(point.get("anomaly_score") or 0.0) >= POINT_INVESTIGATE
    )
    unique_to_l3 = is_anomaly and access_decision == "allow"
    dup_ratio, dup_window = _duplicate_stats(
        redis, flagged=is_anomaly, duplicate=is_anomaly and not unique_to_l3
    )

    return {
        "monitoring_decision": (
            MONITORING_INVESTIGATE if investigate else MONITORING_NORMAL
        ),
        "is_anomaly": is_anomaly,
        "unique_to_l3": unique_to_l3,
        "detected_by": views,
        "duplicate_ratio": dup_ratio,
        "duplicate_window": dup_window,
        # คำอธิบายหลักที่ส่งให้ SOC — ตอบว่า "ส่วนใดต่างจาก baseline ของผู้ใช้นี้"
        "diagnostic_factors": _diagnostic_factors(seq, views),
        "diagnostic_method": seq.get("diagnostic_method") or SEQ.DIAGNOSTIC_METHOD,
        "baseline_version": seq.get("baseline_version") or SEQ.BASELINE_VERSION,
        # SHAP — debug เท่านั้น ห้ามตีความเป็นสาเหตุ (B67)
        "model_attribution": _model_attribution(point, seq, views),
        "model_attribution_caveat": ATTRIBUTION_CAVEAT,
        # ผลดิบของแต่ละมุมมอง — เก็บไว้ replay/ตรวจย้อน (ไม่ใช้ตัดสินอะไรเพิ่ม)
        "point": point,
        "sequence": seq,
        "model_version": {
            "point": "iforest-23feat",
            "sequence": SEQ.MODEL_VERSION,
        },
    }
