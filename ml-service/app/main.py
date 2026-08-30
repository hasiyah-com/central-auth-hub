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

import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app import sequence as SEQ
from app.features import FEATURE_COUNT, FEATURE_NAMES, FEATURE_RANGES
from app.model import (
    explainer_status,
    load_model,
    model_loaded,
    predict_with_explanation,
)

# Threshold
# mfa = 0.50 (ปรับจาก 0.40) — normal IF baseline ~0.39-0.45 อยู่ติด 0.40 ทำให้
# login ปกติโดน mfa บ่อยเกิน; 0.50 ตรงกับ hub challenge threshold (risk_aggregator)
THRESHOLD_BLOCK = 0.70
THRESHOLD_MFA = 0.50

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


# ── Redis (L3 sequence history) — lazy + fail-safe ตาม B21 ──
# ml-service อ่าน history เอง เพราะ hub ไม่มี numpy จะคำนวณให้ไม่ได้
# ถ้าไม่ได้ตั้ง REDIS_URL หรือ redis ล่ม -> L3 abstain เงียบๆ ไม่ทำ /v1/score พัง
_REDIS = None


def _redis():
    global _REDIS
    if _REDIS is not None:
        return _REDIS
    try:
        import redis as _r

        _REDIS = _r.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
        )
        _REDIS.ping()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  redis unavailable — L3 sequence abstains: {e}")
        _REDIS = None
    return _REDIS


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
    """liveness + ความพร้อมของทั้งสองโมเดล.

    รายงาน `l3_sequence` ด้วยโดยตั้งใจ (บทเรียน B61): L3 fail-safe แบบ "abstain เงียบ"
    เมื่อต่อ Redis ไม่ได้ — ผลลัพธ์ภายนอกเหมือนกับ "ทำงานปกติแต่ไม่เจออะไร" เป๊ะ
    ถ้าไม่มีจุดให้ตรวจสถานะ จะไม่มีใครรู้ว่ามันไม่เคยทำงานเลย
    """
    redis_ok = _redis() is not None
    return {
        "status": "ok" if model_loaded() else "warning",
        "model": "loaded" if model_loaded() else "not loaded — run train_model",
        "explainer": explainer_status(),  # "ready" | "unavailable" | "uninitialized"
        # L3 sequence channel — โมเดลรายคน ไม่มี artifact (fit ตอน request จาก Redis)
        "l3_sequence": {
            "redis": "ok" if redis_ok else "unavailable",
            "ready": redis_ok,
            "model_version": SEQ.MODEL_VERSION,
            "note": None
            if redis_ok
            else "ตั้ง REDIS_URL ให้ ml-service ไม่งั้น L3 abstain ตลอด (B61)",
        },
        "version": "0.4.0",
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

    `data.explanation` lists **ทุก feature** เรียงตาม |SHAP contribution| (มาก→น้อย).
    Empty list means SHAP wasn't available (Hub will fall back to Layer 1+2
    reasons only — never crashes). UI เลือกแสดง top-N เอง.
    """
    try:
        # ส่ง SHAP ครบทุก feature (UI/dashboard เลือกแสดง top-N หรือทั้งหมดเอง)
        s, explanation = predict_with_explanation(req.features, top_k=FEATURE_COUNT)
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


# ============ L3 sequence channel (per-user residual window) ============


class SequenceRequest(BaseModel):
    """residual 6 มิติของ login ปัจจุบัน — hub คำนวณให้ (pure python ไม่ต้องใช้ numpy)."""

    user_id: str = Field(..., min_length=1, max_length=128)
    residual: list[float] = Field(
        ..., description=f"ต้องมี {SEQ.DIMS} ค่า ตามลำดับใน sequence.py"
    )

    @field_validator("residual")
    @classmethod
    def check_dims(cls, v):
        if len(v) != SEQ.DIMS:
            raise ValueError(f"residual ต้องมี {SEQ.DIMS} ค่า (ได้ {len(v)})")
        return v


@app.post("/v1/sequence-score")
def sequence_score(req: SequenceRequest):
    """L3 sequence channel — ให้คะแนน window ล่าสุดของผู้ใช้คนนี้.

    อ่าน history จาก Redis เอง (key `l3resid:{user_id}` ที่ hub เขียนไว้หลังตัดสิน)
    fail-safe: Redis ล่ม/ไม่มี history -> คืน abstain เงียบๆ (hub ก็ fail-safe ซ้ำอีกชั้น B21)
    """
    r = _redis()
    data = SEQ.score(r, req.user_id, req.residual) if r else dict(SEQ.QUIET)
    return {
        "data": data,
        "meta": {
            "version": "v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "redis": "ok" if r else "unavailable",
        },
    }


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
