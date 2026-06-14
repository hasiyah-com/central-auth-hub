"""Risk-triggered MFA challenge — one-time Redis token (B9 atomic pattern).

หลัง 4-Layer RBA ตัดสิน mfa_required → mint() ใน finalizer แล้ว redirect
ผู้ใช้ไปทำ flow (Passkey Re-Auth หรือ Force Enrollment).
ปลาย flow → consume() ดึง payload (atomic, one-time) + ทำ finalize_login.

Redis key shape:
    risk_challenge:{challenge_id}  →  JSON payload

TTL ใน settings.risk_challenge_ttl_sec (default 300s = 5 นาที).

Atomic getdel — กัน replay (B9 same pattern as auth_code).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Literal

from app.config import settings
from app.redis_client import redis_client

log = logging.getLogger(__name__)

_KEY_PREFIX = "risk_challenge"

ChallengeKind = Literal["reauth", "enroll"]


def _key(challenge_id: str) -> str:
    return f"{_KEY_PREFIX}:{challenge_id}"


def mint(
    *,
    user_id: str,
    hub_state: str,
    authreq: dict | None,
    risk_score: float,
    risk_breakdown: dict | None,
    risk_reasons: list | None,
    provider: str,
    kind: ChallengeKind,
    flow: Literal["subsystem", "hub_direct"],
) -> str:
    """Mint a one-time challenge token for risk-triggered MFA.

    Args:
        user_id: User UUID (str)
        hub_state: hub OAuth state (subsystem flow) — "" for hub_direct
        authreq: cached OAuth authorize request — None for hub_direct
        risk_score: aggregated 4-Layer RBA score
        risk_breakdown: {"rule": .., "behavior": .., "iforest": ..}
        risk_reasons: human-readable contributing factors
        provider: "google" | "passkey" | "line"
        kind: "reauth" (user has passkey) | "enroll" (user has none)
        flow: "subsystem" (finalize → auth_code) | "hub_direct" (finalize → Hub JWT)

    Returns:
        challenge_id (urlsafe, 32 bytes) — use as URL param
    """
    challenge_id = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "hub_state": hub_state,
        "authreq": authreq,
        "risk_score": float(risk_score),
        "risk_breakdown": risk_breakdown,
        "risk_reasons": risk_reasons,
        "provider": provider,
        "kind": kind,
        "flow": flow,
        "minted_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.setex(
        _key(challenge_id),
        settings.risk_challenge_ttl_sec,
        json.dumps(payload),
    )
    return challenge_id


def peek(challenge_id: str) -> dict | None:
    """Read challenge without consuming — used by HTML page to show context.

    Returns payload dict or None if expired/missing.
    """
    if not challenge_id:
        return None
    raw = redis_client.get(_key(challenge_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        log.warning("risk_challenge.peek malformed payload for %s", challenge_id)
        return None


def consume(challenge_id: str) -> dict | None:
    """Atomic getdel — one-time use (B9 pattern, same as auth_code).

    Returns payload or None if already used / expired / missing.
    Caller must use this *after* WebAuthn verify passes — never before.
    """
    if not challenge_id:
        return None
    raw = redis_client.getdel(_key(challenge_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        log.warning("risk_challenge.consume malformed payload for %s", challenge_id)
        return None
