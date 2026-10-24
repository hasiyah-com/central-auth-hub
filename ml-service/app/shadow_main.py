"""Private candidate-only service; never hosts live /v1/score or sequence routes."""

import os, hmac, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features import FEATURE_CONTRACT
from app.shadow_candidate import Candidate, CandidateError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    key = os.getenv("CANDIDATE_SHADOW_KEY", "")
    if len(key) < 32:
        raise RuntimeError("candidate_key_missing_or_short")
    app.state.key = key
    app.state.candidate = Candidate.load(
        os.getenv("CANDIDATE_MODEL_PATH", "/candidate/IF-mixed5.joblib"),
        os.getenv("CANDIDATE_MANIFEST_PATH", "/candidate/manifest.json"),
        os.getenv("CANDIDATE_MANIFEST_SHA256", ""),
    )
    warm = app.state.candidate.evaluate(
        [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]
    )
    if warm["status"] != "evaluated" or len(warm["explanation"]) != 23:
        raise RuntimeError("candidate_shap_warmup_failed")
    yield
    app.state.candidate = None


app = FastAPI(
    title="Research candidate shadow only",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature_contract: str
    features: list[float] = Field(min_length=23, max_length=23)

    @field_validator("feature_contract")
    @classmethod
    def contract(cls, value):
        if value != FEATURE_CONTRACT:
            raise ValueError("feature_contract_mismatch")
        return value


def authorized(value):
    if not value or not hmac.compare_digest(value.encode(), app.state.key.encode()):
        raise HTTPException(401, "unauthorized")


@app.get("/health")
def health():
    c = app.state.candidate
    return dict(
        status="ready",
        mode="shadow",
        applied_to_access=False,
        model_sha256=c.manifest["artifact_sha256"],
    )


@app.post("/v1/shadow-score")
def score(req: Request, x_shadow_key: str | None = Header(default=None)):
    authorized(x_shadow_key)
    try:
        return app.state.candidate.evaluate(req.features)
    except CandidateError:
        raise HTTPException(422, "invalid_candidate_input")
    except Exception:
        log.warning("candidate_score_unavailable")
        raise HTTPException(503, "candidate_unavailable")
