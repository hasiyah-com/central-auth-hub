"""Collector SQL parity on the isolated CI PostgreSQL database; always rolled back."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from app.models import AccessList, AuditLog, LoginSession, PasskeyCredential, Subsystem, User
from app.services.c3_pge_evidence import collect


@pytest.fixture
def subject(db):
    user = User(email=f"shadow-{uuid4().hex}@example.invalid", full_name="Shadow fixture",
                user_type="teacher", is_hub_admin=True)
    db.add(user)
    db.flush()
    try:
        yield user
    finally:
        db.rollback()


def test_legacy_registration_unknown_then_explicit_link_verified(db, subject):
    now = datetime(2026, 10, 22, 12)
    session = LoginSession(user_id=subject.id, created_at=now-timedelta(seconds=90),
        decision="challenge", risk_breakdown={"risk_decision":"challenge", "authentication": {
            "method":"passkey", "verified":True, "user_verified":True,
            "stage":"step_up", "verified_at":(now-timedelta(seconds=60)).isoformat()+"Z"}})
    credential = PasskeyCredential(user_id=subject.id, credential_id=uuid4().bytes,
        public_key=b"synthetic-fixture", sign_count=0, transports=[], device_name="fixture",
        status="ACTIVE", created_at=now-timedelta(seconds=30))
    db.add_all([session, credential])
    db.flush()
    audit = AuditLog(actor_id=subject.id, action="passkey_registered", target_type="passkey",
        target_id=credential.id, created_at=credential.created_at, metadata_json={})
    db.add(audit)
    db.flush()
    result = collect(db, subject.id, None, now, recent_passkey=True, recent_permission=False)
    assert result["registration_status"] == "unknown"
    assert result["registration_verified"] is False
    audit.metadata_json = {"registration_session_id": str(session.id)}
    db.flush()
    result = collect(db, subject.id, None, now, recent_passkey=True, recent_permission=False)
    assert result["registration_verified"] is True
    assert result["verified_registration_count"] == 1


def test_permission_needs_matching_scope_and_server_audit(db, subject):
    now = datetime(2026, 10, 22, 12)
    sub = Subsystem(name="Shadow fixture", client_id="shadow-"+uuid4().hex,
                    client_secret_hash="synthetic-hash", redirect_uris=[], scope=[])
    db.add(sub)
    db.flush()
    grant = AccessList(user_id=subject.id, subsystem_id=sub.id, granted_by=subject.id,
                       granted_at=now-timedelta(minutes=15), entry_type="allow")
    db.add(grant)
    db.flush()
    kw = dict(recent_passkey=False, recent_permission=True)
    assert not collect(db, subject.id, sub.id, now, **kw)["grant_provenance_recorded"]
    db.add(AuditLog(actor_id=subject.id, action="admin_grant_user_access", target_type="user",
                   target_id=subject.id, created_at=grant.granted_at,
                   metadata_json={"subsystem_id":str(sub.id)}))
    db.flush()
    assert collect(db, subject.id, sub.id, now, **kw)["grant_provenance_recorded"]
    assert not collect(db, subject.id, uuid4(), now, **kw)["grant_provenance_recorded"]
