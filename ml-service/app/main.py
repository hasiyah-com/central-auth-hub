"""ML Verifier — FastAPI service สำหรับ scoring login session.

ปรับปรุงตาม API Design Checklist:
  - Versioning      : URI prefix /v1/
  - Naming          : nouns, kebab-case
  - Error Handling  : standard error wrapper (field, reason, request_id)
  - Response Format : {data, meta} wrapper
  - Security        : input validation + range check
  - Documentation   : OpenAPI auto-generated

Endpoints:
  GET  /health                  -> service liveness
  GET  /v1/features-info        -> ดูชื่อ feature + range
  POST /v1/score                -> scoring login session
"""

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.features import FEATURE_COUNT, FEATURE_NAMES, FEATURE_RANGES
from app.model import (
    explainer_status,
    load_model,
    model_loaded,
    predict_with_explanation,
)

# Threshold
THRESHOLD_BLOCK = 0.70
THRESHOLD_MFA = 0.40

app = FastAPI(
    title="ML Verifier",
    description="Isolation Forest สำหรับตรวจ Anomaly Login (research-backed 12 features)",
    version="0.2.0",
)


@app.on_event("startup")
def startup():
    try:
        load_model()
        print("✅ Model loaded")
    except FileNotFoundError as e:
        print(f"⚠️  {e}")


# ============ Standard Error Handler ============


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    """ตอบ error เป็น JSON มาตรฐาน {error: {code, message, request_id, ...}}."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "request_id": str(uuid.uuid4()),
                "path": str(request.url.path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


# ============ Schemas (with strict validation) ============


class ScoreRequest(BaseModel):
    features: list[float] = Field(
        ...,
        description=f"ต้องมี {FEATURE_COUNT} ตัว เรียงตาม /v1/features-info",
        min_length=FEATURE_COUNT,
        max_length=FEATURE_COUNT,
    )

    @field_validator("features")
    @classmethod
    def validate_ranges(cls, v: list[float]) -> list[float]:
        """ตรวจว่าทุก feature อยู่ในช่วงที่กำหนด."""
        if len(v) != FEATURE_COUNT:
            raise ValueError(f"ต้องมี {FEATURE_COUNT} features (ได้ {len(v)})")
        for i, (name, val) in enumerate(zip(FEATURE_NAMES, v)):
            lo, hi = FEATURE_RANGES[name]
            if not (lo <= val <= hi):
                raise ValueError(
                    f"feature[{i}] '{name}' = {val} ไม่อยู่ในช่วง [{lo}, {hi}]"
                )
        return v


class FeatureContribution(BaseModel):
    """SHAP contribution for one feature on one sample.

    `direction`: "anomaly" = pushed score toward anomalous,
                 "normal"  = pushed score toward normal.
    """

    feature: str
    shap: float
    value: float
    direction: str


class ScoreData(BaseModel):
    anomaly_score: float
    decision: str
    thresholds: dict[str, float]
    # SHAP top-k features (max 5) sorted by |contribution|.
    # Empty list when SHAP is unavailable (e.g. shap pkg missing,
    # explainer init failed) — Hub treats this as fail-safe and shows
    # Layer 1+2 reasons only.
    explanation: list[FeatureContribution] = []


class ScoreResponse(BaseModel):
    """Response wrapper {data, meta} — ตามมาตรฐาน API design."""

    data: ScoreData
    meta: dict


# ============ Endpoints ============


@app.get("/health")
def health():
    """liveness + model readiness."""
    return {
        "status": "ok" if model_loaded() else "warning",
        "model": "loaded" if model_loaded() else "not loaded — run train_model",
        "explainer": explainer_status(),  # "ready" | "unavailable" | "uninitialized"
        "version": "0.3.0",
    }


@app.get("/v1/features-info")
def features_info():
    """ดูรายชื่อ + ลำดับ + range ของ feature."""
    return {
        "data": {
            "feature_count": FEATURE_COUNT,
            "features": [
                {
                    "name": name,
                    "index": i,
                    "range": {
                        "min": FEATURE_RANGES[name][0],
                        "max": FEATURE_RANGES[name][1],
                    },
                }
                for i, name in enumerate(FEATURE_NAMES)
            ],
        },
        "meta": {"version": "v1"},
    }


@app.post("/v1/score", response_model=ScoreResponse)
def score(req: ScoreRequest, request: Request):
    """รับ feature vector คืน anomaly score + decision + SHAP explanation.

    Standard response wrapper: {data: {...}, meta: {...}}

    `data.explanation` lists top-5 features by |SHAP contribution|. Empty
    list means SHAP wasn't available (Hub will fall back to Layer 1+2
    reasons only — never crashes).
    """
    try:
        s, explanation = predict_with_explanation(req.features, top_k=5)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if s >= THRESHOLD_BLOCK:
        decision = "block"
    elif s >= THRESHOLD_MFA:
        decision = "mfa"
    else:
        decision = "pass"

    return ScoreResponse(
        data=ScoreData(
            anomaly_score=round(s, 4),
            decision=decision,
            thresholds={"block": THRESHOLD_BLOCK, "mfa": THRESHOLD_MFA},
            explanation=[FeatureContribution(**e) for e in explanation],
        ),
        meta={
            "version": "v1",
            "request_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "feature_count": FEATURE_COUNT,
            "explainer": explainer_status(),
        },
    )


# ============ Backward-compatible (Week 5 old paths) ============


@app.get("/features/info")
def features_info_legacy():
    """[deprecated] ใช้ /v1/features-info แทน."""
    return features_info()


@app.post("/score")
def score_legacy(req: ScoreRequest, request: Request):
    """[deprecated] ใช้ /v1/score แทน — Hub ยังเรียก path นี้ใน Week 5 เก่า."""
    result = score(req, request)
    # คืน flat format ของเดิม (ไม่ wrapped)
    return result.data.model_dump()
