"""Database contracts for provisional users, scoped access, and approval."""
from __future__ import annotations

import uuid

from app.models import AccessList, Subsystem, User
from app.services.access_policy import evaluate_access_policy
from app.services.change_request_service import apply_approved
from app.services.provisional_registration import create_provisional_identity


def _sub(db) -> Subsystem:
    subsystem = Subsystem(
        name=f"provisional-{uuid.uuid4().hex[:8]}",
        client_id=f"provisional_{uuid.uuid4().hex}",
        client_secret_hash="test-only",
        redirect_uris=["https://example.test/callback"],
        scope=["email", "name"],
        allowed_roles=["member", "operator"],
        access_policy="explicit",
        status="active",
        self_registration_mode="domain_auto",
        allowed_email_domains=["student.uni.ac.th"],
    )
    db.add(subsystem)
    db.flush()
    return subsystem


def test_self_registration_is_scoped_then_admin_approval_activates_user(db):
    try:
        subsystem = _sub(db)
        email = f"new-{uuid.uuid4().hex}@student.uni.ac.th"
        user, membership, request = create_provisional_identity(
            db,
            subsystem=subsystem,
            email=email,
            full_name="New Student",
            identifier="65000001",
            faculty="Engineering",
            major="Computer Engineering",
            google_sub=f"google-{uuid.uuid4().hex}",
            source="self_registration",
        )
        db.flush()

        assert user.status == "provisional"
        assert user.user_type == "student"
        assert membership.role_in_sub == "member"
        assert membership.source == "self_registration"
        assert request.request_type == "user_registration"
        assert evaluate_access_policy(db, user, subsystem) == (
            True,
            "provisional_explicit",
        )

        other = _sub(db)
        assert evaluate_access_policy(db, user, other)[0] is False

        request.payload = {**request.payload, "approved_user_type": "teacher"}
        result = apply_approved(db, request, subsystem)
        assert result["user_type"] == "teacher"
        assert user.status == "active"
        assert user.user_type == "teacher"
        # A second subsystem review remains safe after central identity approval.
        second_result = apply_approved(db, request, subsystem)
        assert second_result["user_type"] == "teacher"
    finally:
        db.rollback()


def test_developer_invitation_is_idempotent_and_stays_low_role(db):
    try:
        subsystem = _sub(db)
        email = f"invite-{uuid.uuid4().hex}@student.uni.ac.th"
        first = create_provisional_identity(
            db,
            subsystem=subsystem,
            email=email,
            full_name="Invited User",
            identifier=None,
            faculty=None,
            major=None,
            google_sub=None,
            source="developer_invite",
        )
        second = create_provisional_identity(
            db,
            subsystem=subsystem,
            email=email,
            full_name="Invited User",
            identifier=None,
            faculty=None,
            major=None,
            google_sub=None,
            source="developer_invite",
        )
        db.flush()

        assert first[0].id == second[0].id
        assert first[1].id == second[1].id
        assert first[2].id == second[2].id
        assert first[0].status == "provisional"
        assert first[1].role_in_sub == "member"
        assert (
            db.query(AccessList)
            .filter(
                AccessList.subsystem_id == subsystem.id,
                AccessList.user_id == first[0].id,
            )
            .count()
            == 1
        )
        assert db.query(User).filter(User.email == email).count() == 1
    finally:
        db.rollback()
