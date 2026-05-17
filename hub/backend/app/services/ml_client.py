"""ML client — เรียก ML service เพื่อรับ anomaly score.

Fail-safe: ถ้า ML service ล่ม/ช้า ให้ default = pass + 0.0
(เพื่อไม่ให้ทั้งระบบล่มเพราะ ML)
"""
import httpx

from app.config import settings


async def get_anomaly_score(features: list[float]) -> dict:
    """เรียก ML /v1/score คืน {anomaly_score, decision, error?}.

    Args:
        features: list 12 ตัวตามลำดับใน ml-service/app/features.py
    """
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
            return {
                "anomaly_score": data.get("anomaly_score", 0.0),
                "decision": data.get("decision", "pass"),
                "error": None,
            }
    except httpx.TimeoutException:
        return {"anomaly_score": 0.0, "decision": "pass", "error": "ml_timeout"}
    except httpx.HTTPStatusError as e:
        return {"anomaly_score": 0.0, "decision": "pass", "error": f"ml_http_{e.response.status_code}"}
    except Exception as e:
        return {"anomaly_score": 0.0, "decision": "pass", "error": f"ml_unreachable: {type(e).__name__}"}
