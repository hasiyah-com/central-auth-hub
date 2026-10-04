"""Server-verified authentication evidence, independent of risk decisions."""
from datetime import datetime, timezone

TRUSTED_LEGACY_DECISIONS = {"allow", "pass", "mfa_passed"}

def authentication_evidence(method, *, verified, user_verified=None, counter_regression=False, stage="primary"):
    return {"version": 1, "method": method, "verified": bool(verified),
            "user_verified": user_verified, "counter_regression": bool(counter_regression),
            "stage": stage, "verified_at": datetime.now(timezone.utc).isoformat() if verified else None}

def record_authentication(session, method, *, user_verified=None, counter_regression=False, stage="step_up"):
    bd = dict(session.risk_breakdown or {})
    bd.setdefault("risk_decision", session.decision)
    bd["authentication"] = authentication_evidence(
        method, verified=True, user_verified=user_verified,
        counter_regression=counter_regression, stage=stage)
    session.risk_breakdown = bd

def trusted_history(decision, breakdown, attack_ip=False, takeover=False):
    if attack_ip or takeover:
        return False
    bd = breakdown or {}
    if bd.get("risk_decision", decision) in ("block", "would_block"):
        return False
    evidence = bd.get("authentication")
    if evidence is None:
        return decision in TRUSTED_LEGACY_DECISIONS
    if not evidence.get("verified") or evidence.get("counter_regression"):
        return False
    if evidence.get("method") in ("passkey", "discoverable"):
        return evidence.get("user_verified") is True
    if evidence.get("stage") == "step_up" and evidence.get("method") == "totp":
        return True
    return decision in ("allow", "pass")
