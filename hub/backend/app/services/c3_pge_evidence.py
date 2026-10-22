"""Read-only, point-in-time provenance for the C3/PG-E shadow comparison.

A missing link is unknown. Audit metadata is server-written, not request evidence.
Current legacy enrollment routes do not write the linkage: report unknown honestly.
"""
from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

from app.models import AccessList, AuditLog, LoginSession, PasskeyCredential
from app.services.auth_evidence import trusted_history, verified_strong_auth


def _time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def registration_verified(credential, audit, session, now):
    """Only an explicitly linked, earlier strong authorization can qualify.

    First-factor OTP links are not currently recorded by runtime; remain unknown.
    Provenance is not proof of benign intent and never lowers a live decision.
    """
    at, started = _time(credential.created_at), _time(session.created_at)
    audit_at = _time(audit.created_at)
    bd = session.risk_breakdown or {}
    proof = _time((bd.get("authentication") or {}).get("verified_at"))
    metadata = audit.metadata_json or {}
    return bool(
        at and started and audit_at and proof
        and started <= proof < at < now
        and at < started + timedelta(minutes=5)
        and at <= audit_at <= at + timedelta(seconds=5) and audit_at < now
        and str(session.user_id) == str(credential.user_id) == str(audit.actor_id)
        and str(audit.target_id) == str(credential.id)
        and audit.action == "passkey_registered" and audit.target_type == "passkey"
        and str(metadata.get("registration_session_id")) == str(session.id)
        and bd.get("risk_decision", session.decision) not in ("block", "would_block")
        and verified_strong_auth(bd)
    )


def trusted_count_capped(db, user_id, now):
    rows = db.query(
        LoginSession.decision, LoginSession.risk_breakdown,
        LoginSession.is_attack_ip, LoginSession.is_account_takeover,
    ).filter(
        LoginSession.user_id == user_id, LoginSession.created_at < now,
    ).order_by(LoginSession.created_at.desc()).yield_per(100)
    # C3 only distinguishes 0..4 from >=5. Do not truncate untrusted history.
    count = 0
    iterator = iter(rows)
    try:
        for decision, breakdown, attack, takeover in iterator:
            if trusted_history(decision, breakdown, attack, takeover):
                count += 1
                if count == 5:
                    break
    finally:
        close = getattr(iterator, "close", None)
        if close:
            close()
    return count


def count_warn_threshold(times):
    """Same linear p95/ceil convention as the research count_base; no NumPy."""
    if len(times) < 5:
        return None
    times = sorted(times)
    lo, counts = 0, []
    for i, at in enumerate(times):
        while times[lo] < at - timedelta(hours=24):
            lo += 1
        counts.append(i - lo)
    counts.sort()
    position = (len(counts) - 1) * .95
    lower = int(position)
    fraction = position - lower
    upper = min(lower + 1, len(counts) - 1)
    p95 = counts[lower] + fraction * (counts[upper] - counts[lower])
    return max(3, math.ceil(p95) + 2)


def collect(db, user_id, subsystem_id, now, *, recent_passkey, recent_permission):
    window = db.query(LoginSession.created_at).filter(
        LoginSession.user_id == user_id,
        LoginSession.created_at >= now - timedelta(days=30),
        LoginSession.created_at < now,
    ).all()
    facts = {
        "count24h_warn_threshold": count_warn_threshold([at for (at,) in window]),
        "trusted_history_count_capped_at5": trusted_count_capped(db, user_id, now),
        "registration_verified": False, "grant_provenance_recorded": False,
        "registration_status": "unknown" if recent_passkey else "not_recent",
        "permission_status": "unknown" if recent_permission else "not_recent",
        "recent_registration_count": 0, "verified_registration_count": 0,
    }
    if recent_passkey:
        credentials = db.query(PasskeyCredential).filter(
            PasskeyCredential.user_id == user_id,
            PasskeyCredential.revoked_at.is_(None),
            PasskeyCredential.status == "ACTIVE",
            PasskeyCredential.created_at >= now - timedelta(hours=1),
            PasskeyCredential.created_at < now,
        ).all()
        verified = 0
        for credential in credentials:
            audits = db.query(AuditLog).filter(
                AuditLog.action == "passkey_registered", AuditLog.target_type == "passkey",
                AuditLog.actor_id == user_id, AuditLog.target_id == credential.id,
                AuditLog.created_at >= credential.created_at,
                AuditLog.created_at <= credential.created_at + timedelta(seconds=5),
                AuditLog.created_at < now,
            ).all()
            for audit in audits:
                sid = (audit.metadata_json or {}).get("registration_session_id")
                try:
                    sid = UUID(str(sid))
                except (ValueError, TypeError, AttributeError):
                    continue
                session = db.query(LoginSession).filter(
                    LoginSession.id == sid, LoginSession.user_id == user_id,
                    LoginSession.created_at < credential.created_at,
                ).first()
                if session and registration_verified(credential, audit, session, now):
                    verified += 1
                    break
        facts.update(recent_registration_count=len(credentials), verified_registration_count=verified)
        facts["registration_verified"] = bool(credentials and verified == len(credentials))
        if facts["registration_verified"]:
            facts["registration_status"] = "verified_strong_link"
    if recent_permission:
        rows = db.query(AccessList).filter(AccessList.user_id == user_id).all()
        changes = [(t, row) for row in rows for t in (row.granted_at, row.revoked_at)
                   if t is not None and t < now]
        latest = max((t for t, _ in changes), default=None)
        approved = bool(latest and latest >= now - timedelta(days=1) and subsystem_id is not None)
        for at, row in changes:
            if at != latest or not approved:
                continue
            if (at != row.granted_at or row.entry_type != "allow" or not row.granted_by
                    or str(row.subsystem_id) != str(subsystem_id)
                    or (row.revoked_at is not None and row.revoked_at < now)):
                approved = False
                break
            audit = db.query(AuditLog.id).filter(
                AuditLog.action == "admin_grant_user_access", AuditLog.target_type == "user",
                AuditLog.target_id == user_id, AuditLog.actor_id == row.granted_by,
                AuditLog.created_at >= at, AuditLog.created_at <= at + timedelta(seconds=5),
                AuditLog.created_at < now,
                AuditLog.metadata_json["subsystem_id"].as_string() == str(subsystem_id),
            ).first()
            if not audit:
                approved = False
        facts["grant_provenance_recorded"] = approved
        if approved:
            facts["permission_status"] = "matched_server_audit"
    return facts
