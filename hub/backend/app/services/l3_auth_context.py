"""L3-only candidate inputs. Collection only; never changes the 23-input live model.

UTC point-in-time snapshots, explicit missingness, and same-subsystem method history.
The method is the verified primary login at assessment time, before possible step-up.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.services.feature_time import as_utc_naive

CONTRACT = "l3-auth-context-v2"
FEATURE_NAMES = [
    "recovery_observed", "recovery_log1p_hours",
    "factor_reset_observed", "factor_reset_log1p_hours",
    "auth_method_known", "auth_phishing_resistant",
    "prior_auth_observed", "prior_passkey_rate", "auth_method_departure",
    "aaguid_known", "prior_aaguid_observed", "aaguid_novel",
    "language_known", "prior_language_observed", "language_novel",
]
PASSKEY_METHODS = {"passkey", "discoverable"}
KNOWN_METHODS = PASSKEY_METHODS | {"google", "line", "totp"}
HISTORY_DAYS = 30
MIN_METHOD_HISTORY = 5
MAX_AGE_HOURS = 24 * 365


def normalize_aaguid(value):
    from uuid import UUID
    try:
        parsed = UUID(str(value))
        return str(parsed) if parsed.int else None
    except (ValueError, TypeError, AttributeError):
        return None


def normalize_language(header):
    """Highest-priority valid language tag; wildcard/zero-q/missing are unknown."""
    import re
    if not isinstance(header, str) or len(header) > 256:
        return None
    choices = []
    for order, entry in enumerate(header.split(",")[:10]):
        parts = entry.strip().lower().split(";")
        tag = parts[0].strip()
        if not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", tag):
            continue
        try:
            if len(parts) > 2 or (len(parts) == 2 and not parts[1].strip().startswith("q=")):
                continue
            q = float(parts[1].strip()[2:]) if len(parts) == 2 else 1.0
        except ValueError:
            continue
        if 0 < q <= 1:
            choices.append((q, -order, tag))
    return max(choices)[2] if choices else None


def build_context(*, now, method, recovery_at=None, reset_at=None, prior_methods=(),
                  aaguid=None, language=None, prior_aaguids=(), prior_languages=()):
    now = as_utc_naive(now)
    method = (method or "").strip().lower()
    known = method in KNOWN_METHODS
    prior = [m for m in prior_methods if m in KNOWN_METHODS]
    ready = len(prior) >= MIN_METHOD_HISTORY
    rate = sum(m in PASSKEY_METHODS for m in prior) / len(prior) if ready else 0.0

    def age(timestamp):
        if timestamp is None or as_utc_naive(timestamp) >= now:
            return 0.0, 0.0
        hours = (now - as_utc_naive(timestamp)).total_seconds() / 3600
        return 1.0, math.log1p(min(hours, MAX_AGE_HOURS))

    recovery_seen, recovery_age = age(recovery_at)
    reset_seen, reset_age = age(reset_at)
    values = [recovery_seen, recovery_age, reset_seen, reset_age,
              float(known), float(method in PASSKEY_METHODS), float(ready), rate,
              rate if known and method not in PASSKEY_METHODS and ready else 0.0]
    aaguid = normalize_aaguid(aaguid) if method in PASSKEY_METHODS else None
    language = normalize_language(language)
    known_aaguids = [v for raw in prior_aaguids if (v := normalize_aaguid(raw))]
    known_languages = [v for raw in prior_languages if (v := normalize_language(raw))]
    aaguid_ready = len(known_aaguids) >= MIN_METHOD_HISTORY
    language_ready = len(known_languages) >= MIN_METHOD_HISTORY
    values.extend([float(aaguid is not None), float(aaguid_ready),
                   float(bool(aaguid and aaguid_ready and aaguid not in known_aaguids)),
                   float(language is not None), float(language_ready),
                   float(bool(language and language_ready and language not in known_languages))])
    return {
        "authenticator_aaguid": aaguid, "browser_language": language,
        "contract": CONTRACT, "status": "collection_only",
        "captured_at": now.isoformat() + "Z",
        "method_at_assessment": method if known else None,
        "method_history_days": HISTORY_DAYS, "known_prior_method_count": len(prior),
        "features": dict(zip(FEATURE_NAMES, values)),
    }


def extract_auth_context(db, user_id, method, *, subsystem_id=None, now=None,
                         authenticator_aaguid=None, accept_language=None):
    from sqlalchemy import or_
    from app.models import AuditLog, LoginSession

    now = as_utc_naive(now or datetime.utcnow())
    target = (AuditLog.target_type == "user", AuditLog.target_id == user_id,
              AuditLog.created_at < now)
    # Approval/request/failure events are intentionally not recovery completions.
    recovery = db.query(AuditLog.created_at).filter(*target, or_(
        AuditLog.action == "passkey_recovery_success",
        (AuditLog.action == "account_google_changed") &
        (AuditLog.metadata_json["changed_by"].as_string() == "RECOVERY"),
    )).order_by(AuditLog.created_at.desc()).first()
    reset = db.query(AuditLog.created_at).filter(*target, or_(
        AuditLog.action.in_(["auth_factor_reset_completed", "totp_revoked"]),
        (AuditLog.action == "passkey_admin_reset") &
        (AuditLog.metadata_json["revoked_count"].as_integer() > 0),
    )).order_by(AuditLog.created_at.desc()).first()
    sessions = db.query(LoginSession).filter(
        LoginSession.user_id == user_id,
        LoginSession.subsystem_id == subsystem_id,
        LoginSession.created_at >= now - timedelta(days=HISTORY_DAYS),
        LoginSession.created_at < now,
        LoginSession.jti.isnot(None),
        LoginSession.decision.in_(["allow", "pass", "warn", "would_warn",
                                  "would_block", "would_challenge"]),
    ).all()
    return build_context(now=now, method=method,
                         recovery_at=recovery[0] if recovery else None,
                         reset_at=reset[0] if reset else None,
                         prior_methods=[row.login_method for row in sessions],
                         aaguid=authenticator_aaguid, language=accept_language,
                         prior_aaguids=[((row.risk_breakdown or {}).get("l3_auth_candidate") or {}).get("authenticator_aaguid") for row in sessions],
                         prior_languages=[((row.risk_breakdown or {}).get("l3_auth_candidate") or {}).get("browser_language") for row in sessions])
