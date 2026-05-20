"""In-memory metric counters — nightly cron / /admin/metrics endpoint จะดึงไปใช้ภายหลัง.

ไม่ persist ไป DB ในรอบนี้ — ค่าจะ reset เมื่อ restart container.
"""
from collections import Counter

from app.services.hooks import (
    EVT_LOGIN_FAILURE,
    EVT_LOGIN_SUCCESS,
    EVT_ML_SCORED,
    EVT_OAUTH_AUTHORIZED,
    EVT_OAUTH_FAILURE,
    EVT_TOKEN_ISSUED,
    register,
)

counters: Counter = Counter()
ml_decision_distribution: Counter = Counter()


def _inc_login_success(payload: dict) -> None:
    counters["login_success"] += 1


def _inc_login_failure(payload: dict) -> None:
    counters["login_failure"] += 1
    reason = payload.get("reason", "unknown")
    counters[f"login_failure:{reason}"] += 1


def _inc_token_issued(payload: dict) -> None:
    counters["token_issued"] += 1
    aud = payload.get("aud", "unknown")
    # แยก Hub-direct (hub.internal) กับ subsystem token (client_id)
    bucket = "hub_direct" if aud == "hub.internal" else "subsystem"
    counters[f"token_issued:{bucket}"] += 1


def _inc_oauth_authorized(payload: dict) -> None:
    counters["oauth_authorized"] += 1


def _inc_oauth_failure(payload: dict) -> None:
    counters["oauth_failure"] += 1
    reason = payload.get("reason", "unknown")
    counters[f"oauth_failure:{reason}"] += 1


def _record_ml_decision(payload: dict) -> None:
    counters["ml_scored"] += 1
    decision = payload.get("decision", "unknown")
    ml_decision_distribution[decision] += 1


def register_listeners() -> None:
    register(EVT_LOGIN_SUCCESS, _inc_login_success)
    register(EVT_LOGIN_FAILURE, _inc_login_failure)
    register(EVT_TOKEN_ISSUED, _inc_token_issued)
    register(EVT_OAUTH_AUTHORIZED, _inc_oauth_authorized)
    register(EVT_OAUTH_FAILURE, _inc_oauth_failure)
    register(EVT_ML_SCORED, _record_ml_decision)


def snapshot() -> dict:
    """คืนสถานะปัจจุบัน — สำหรับ /admin/metrics endpoint ในอนาคต."""
    return {
        "counters": dict(counters),
        "ml_decision_distribution": dict(ml_decision_distribution),
    }
