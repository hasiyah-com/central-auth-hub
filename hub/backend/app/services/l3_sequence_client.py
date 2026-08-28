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
        "error": None,
    }


async def get_sequence_score(user_id: str, residual: list[float] | None) -> dict:
    """POST /v1/sequence-score — คืน dict เดียวกับ contract ของ L3 (+ error).

    residual ผิดรูป -> ไม่ยิง HTTP เลย (ประหยัด latency ของ login path)
    """
    if not user_id or not residual or len(residual) != DIMS:
        return _quiet("invalid_residual")
    try:
        async with httpx.AsyncClient(timeout=settings.ml_timeout_seconds) as client:
            r = await client.post(
                f"{settings.ml_service_url}/v1/sequence-score",
                json={
                    "user_id": str(user_id),
                    "residual": [float(x) for x in residual],
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
