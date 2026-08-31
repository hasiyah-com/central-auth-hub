"""L3 sequence client — เรียก ml-service ให้คะแนน residual window ของผู้ใช้.

ทำไมต้องเรียกข้าม service: hub-backend image ไม่มี numpy/sklearn โดยตั้งใจ
(ML แยก container ตั้งแต่ Week 5) — hub คำนวณ residual เอง (pure python)
แล้วให้ ml-service fit/score ต่อ โดย ml-service อ่าน history จาก Redis เอง

Fail-safe ตาม B21: ml-service ล่ม/ช้า/ตอบผิดรูป -> คืน "ไม่ยิง" + error code
ไม่เคย raise ขึ้น flow login (L1/L2/L4 ตัดสินต่อได้ตามปกติ)
"""

from __future__ import annotations

import httpx

from app.config import settings

QUIET: dict = {
    "fired": False,
    "score": 0.0,
    "raw_score": 0.0,
    "percentile": 0.0,
    "tier": "none",
    "eligibility": "abstain",
    "shadow_decision": None,
    "n_history": 0,
    "model_version": "iforest-l3-seq-v1",
    "explanation": [],
    "error": None,
}

DIMS = 6  # ต้องตรงกับ l3_sequence.DIMS (มี test parity กันไว้)


def _quiet(error: str | None = None) -> dict:
    return {**QUIET, "error": error}


def _coerce(data: dict) -> dict:
    """บังคับชนิดข้อมูลจาก payload ภายนอก — ผิดรูปแค่ไหนก็ต้องได้ dict ที่ใช้ต่อได้."""

    def _f(key: str) -> float:
        try:
            return float(data.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _s(key: str) -> str | None:
        v = data.get(key)
        return v if isinstance(v, str) else None

    try:
        n_hist = int(data.get("n_history") or 0)
    except (TypeError, ValueError):
        n_hist = 0
    return {
        "fired": data.get("fired") is True,
        "score": _f("score"),
        "raw_score": _f("raw_score"),
        "percentile": _f("percentile"),
        "tier": _s("tier") or "none",
        "eligibility": _s("eligibility") or "abstain",
        "shadow_decision": _s("shadow_decision"),
        "n_history": n_hist,
        "model_version": _s("model_version") or QUIET["model_version"],
        # SHAP ของ view นี้ — ml-service คำนวณให้แม้ตอน "ไม่ยิง" (ใช้ตรวจสอบ/ไล่ปัญหา)
        # ต่างจาก top_factors ที่รวมเฉพาะ view ที่ยิงจริง
        "explanation": data.get("explanation")
        if isinstance(data.get("explanation"), list)
        else [],
        "error": None,
    }


async def get_sequence_score(user_id: str, residual: list[float] | None) -> dict:
    """POST /v1/sequence-score — คืน dict เดียวกับ contract ของ L3 (+ error).

    residual ผิดรูป -> ไม่ยิง HTTP เลย (ประหยัด latency ของ login path)
    """
    if not user_id or not residual or len(residual) != DIMS:
        return _quiet("invalid_residual")
    try:
        async with httpx.AsyncClient(timeout=settings.l3_timeout_seconds) as client:
            r = await client.post(
                f"{settings.ml_service_url}/v1/sequence-score",
                json={
                    "user_id": str(user_id),
                    "residual": [float(x) for x in residual] if residual else None,
                },
            )
            r.raise_for_status()
            body = r.json()
            return _coerce(body.get("data", body) or {})
    except httpx.TimeoutException:
        return _quiet("l3_timeout")
    except httpx.HTTPStatusError as e:
        return _quiet(f"l3_http_{e.response.status_code}")
    except Exception as e:  # noqa: BLE001
        return _quiet(f"l3_unreachable: {type(e).__name__}")


# ══════════════════════ L3 unified (point + sequence ครั้งเดียว) ══════════════════════

UNIFIED_QUIET: dict = {
    "monitoring_decision": "normal",
    "is_anomaly": False,
    "unique_to_l3": False,
    "detected_by": [],
    "duplicate_ratio": None,
    "duplicate_window": 0,
    "top_factors": [],
    "point": {
        "available": False,
        "anomaly_score": 0.0,
        "is_anomaly": False,
        "explanation": [],
        "error": None,
        "explainer": None,
    },
    "sequence": dict(QUIET),
    "model_version": {},
    "error": None,
}

_MONITORING_VALUES = ("normal", "l3_investigate")


def _unified_quiet(error: str | None = None) -> dict:
    import copy

    return {**copy.deepcopy(UNIFIED_QUIET), "error": error}


def _coerce_unified(data: dict) -> dict:
    """บังคับชนิดของ payload รวม — ml-service ตอบผิดรูปแค่ไหนก็ต้องได้ dict ที่ใช้ต่อได้.

    สำคัญเป็นพิเศษกับ `monitoring_decision`: ถ้า ml-service (หรือใครก็ตามที่ยิงเข้ามา)
    ส่งคำในโลกของ access decision กลับมา เช่น "challenge"/"block" ต้องถูกปัดเป็น
    "normal" ที่นี่ — ไม่ปล่อยให้คำแปลกปลอมไหลเข้าไปถึง risk_engine
    """
    mon = data.get("monitoring_decision")
    factors = data.get("top_factors")
    detected = data.get("detected_by")

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    try:
        dup_window = int(data.get("duplicate_window") or 0)
    except (TypeError, ValueError):
        dup_window = 0

    point = data.get("point") if isinstance(data.get("point"), dict) else {}
    seq = data.get("sequence") if isinstance(data.get("sequence"), dict) else {}
    return {
        "monitoring_decision": mon if mon in _MONITORING_VALUES else "normal",
        "is_anomaly": data.get("is_anomaly") is True,
        "unique_to_l3": data.get("unique_to_l3") is True,
        "detected_by": [x for x in detected if isinstance(x, str)]
        if isinstance(detected, list)
        else [],
        "duplicate_ratio": _num(data.get("duplicate_ratio")),
        "duplicate_window": dup_window,
        "top_factors": [f for f in factors if isinstance(f, dict)]
        if isinstance(factors, list)
        else [],
        "point": {
            "available": point.get("available") is True,
            "anomaly_score": _num(point.get("anomaly_score")) or 0.0,
            "is_anomaly": point.get("is_anomaly") is True,
            "explanation": point.get("explanation")
            if isinstance(point.get("explanation"), list)
            else [],
            "error": point.get("error")
            if isinstance(point.get("error"), str)
            else None,
            # สถานะ SHAP — ต้องเห็นจากฝั่ง hub ด้วย ไม่ใช่แค่ /health ของ ml-service
            # (B61: fail-safe ที่เงียบสนิทคือ fail-safe ที่ไม่มีใครรู้ว่ามันไม่ทำงาน)
            "explainer": point.get("explainer")
            if isinstance(point.get("explainer"), str)
            else None,
        },
        "sequence": _coerce(seq),
        "model_version": data.get("model_version")
        if isinstance(data.get("model_version"), dict)
        else {},
        "error": None,
    }


async def evaluate_l3(
    user_id: str,
    features: list[float],
    residual: list[float] | None,
    access_decision: str = "allow",
) -> dict:
    """POST /v1/l3-evaluate — L3 ทั้งสองมุมมองในครั้งเดียว.

    `access_decision` ส่งไปเพื่อให้ ml-service *วัด* unique_to_l3 ได้ — ไม่ใช่เพื่อ
    ให้แก้ค่านั้น ผลที่คืนมาไม่มีฟิลด์ access decision เลย (ถ้ามี ก็ถูก _coerce ตัดทิ้ง)

    Fail-safe B21: ล่ม/ช้า/ผิดรูป -> คืน quiet + error code ไม่ raise ขึ้น login flow
    """
    if not user_id:
        return _unified_quiet("invalid_user")
    # residual ว่างได้ — sequence view จะ abstain แต่ point view ยังต้องทำงาน
    if residual is not None and len(residual) != DIMS:
        residual = None
    try:
        async with httpx.AsyncClient(timeout=settings.l3_timeout_seconds) as client:
            r = await client.post(
                f"{settings.ml_service_url}/v1/l3-evaluate",
                json={
                    "user_id": str(user_id),
                    "features": [float(x) for x in features],
                    "residual": [float(x) for x in residual] if residual else None,
                    "access_decision": str(access_decision),
                },
            )
            r.raise_for_status()
            body = r.json()
            return _coerce_unified(body.get("data", body) or {})
    except httpx.TimeoutException:
        return _unified_quiet("l3_timeout")
    except httpx.HTTPStatusError as e:
        return _unified_quiet(f"l3_http_{e.response.status_code}")
    except Exception as e:  # noqa: BLE001
        return _unified_quiet(f"l3_unreachable: {type(e).__name__}")
