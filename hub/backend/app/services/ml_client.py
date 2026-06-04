"""ML client — เรียก ML service เพื่อรับ anomaly score.

Fail-safe: ถ้า ML service ล่ม/ช้า ให้ default = pass + 0.0
(เพื่อไม่ให้ทั้งระบบล่มเพราะ ML)
"""

import time

import httpx

from app.config import settings
from app.services.hooks import EVT_ML_SCORED, emit


async def get_anomaly_score(features: list[float]) -> dict:
    """เรียก ML /v1/score คืน {anomaly_score, decision, explanation, error?}.

    Args:
        features: list 12 ตัวตามลำดับใน ml-service/app/features.py

    Returns dict with:
      - anomaly_score: float 0-1
      - decision: "pass" | "mfa" | "block"
      - explanation: list[dict] — top-5 SHAP contributions
        ([] when ML returns nothing or unavailable)
      - error: None on success, error code string on failure
    """
    started = time.perf_counter()
    result: dict
    try:
        async with httpx.AsyncClient(timeout=settings.ml_timeout_seconds) as client:
            r = await client.post(
                f"{settings.ml_service_url}/v1/score",
                json={"features": features},
            )
            r.raise_for_status()
            body = r.json()
            # support both new wrapped {data, meta} และ legacy flat
            data = body.get("data", body)
            result = {
                "anomaly_score": data.get("anomaly_score", 0.0),
                "decision": data.get("decision", "pass"),
                # SHAP explanation — fail-safe to [] if ML didn't include it
                # (legacy ML version, or shap pkg missing in container).
                "explanation": data.get("explanation", []),
                "error": None,
            }
    except httpx.TimeoutException:
        result = {
            "anomaly_score": 0.0,
            "decision": "pass",
            "explanation": [],
            "error": "ml_timeout",
        }
    except httpx.HTTPStatusError as e:
        result = {
            "anomaly_score": 0.0,
            "decision": "pass",
            "explanation": [],
            "error": f"ml_http_{e.response.status_code}",
        }
    except Exception as e:
        result = {
            "anomaly_score": 0.0,
            "decision": "pass",
            "explanation": [],
            "error": f"ml_unreachable: {type(e).__name__}",
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    await emit(
        EVT_ML_SCORED,
        {
            "anomaly_score": result["anomaly_score"],
            "decision": result["decision"],
            "error": result["error"],
            "latency_ms": latency_ms,
        },
    )
    return result
