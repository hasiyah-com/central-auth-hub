"""Server-side evidence for contextual step-up; never trust client flags or old MFA rows."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.models import AccessList, AuditLog


@dataclass(frozen=True)
class RuleContext:
    strong_primary_verified: bool = False
    latest_permission_approved: bool = False
    recent_recovery_or_reset: bool = False
    evidence_status: str = "unknown"

    def snapshot(self):
        return {"policy_version": "contextual-challenge-v1", **asdict(self)}


def collect_rule_context(db, user_id, *, login_method=None, now=None):
    # Methods come from successful server verification, never a request field.
    strong = login_method in ("passkey", "discoverable")
    now = now or datetime.utcnow()
    if db is None:
        return RuleContext(strong_primary_verified=strong)
    cutoff = now - timedelta(days=1)
    recovery = db.query(AuditLog.id).filter(
        AuditLog.target_type == "user", AuditLog.target_id == user_id,
        AuditLog.created_at >= cutoff, AuditLog.created_at < now,
        AuditLog.action.in_(["passkey_recovery_success", "auth_factor_reset_completed",
                            "passkey_admin_reset", "totp_revoked"]),
    ).first()
    # Match the latest change used by feature_extraction, across all subsystems.
    rows = db.query(AccessList).filter(AccessList.user_id == user_id).all()
    changes = [(t, row) for row in rows for t in (row.granted_at, row.revoked_at)
               if t is not None and t < now]
    approved = False
    if changes:
        latest = max(t for t, _ in changes)
        # Tied changes must ALL have evidence; an unrelated approval cannot excuse one.
        approved = latest >= cutoff
        for t, row in changes:
            if t != latest or not approved:
                continue
            # Only explicit admin grants recorded by this application qualify.
            # Revocation and older/unknown provenance never count as an approved grant.
            if t != row.granted_at or row.revoked_at is not None or row.entry_type != "allow":
                approved = False
                break
            audit = db.query(AuditLog.id).filter(
                AuditLog.action == "admin_grant_user_access",
                AuditLog.target_type == "user", AuditLog.target_id == user_id,
                AuditLog.actor_id == row.granted_by, AuditLog.actor_id.isnot(None),
                AuditLog.created_at >= t, AuditLog.created_at <= t + timedelta(seconds=5),
                AuditLog.created_at < now,
                AuditLog.metadata_json["subsystem_id"].as_string() == str(row.subsystem_id),
            ).first()
            if not audit:
                approved = False
    return RuleContext(strong, approved, bool(recovery), "available")
