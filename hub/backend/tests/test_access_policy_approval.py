"""Security test — access_policy WIDENING needs admin approval (audit run-2 #2).

A developer must not be able to silently widen an admin-approved subsystem's audience
(e.g. explicit -> all) and then harvest the whole user directory via the Roster API.
Widening now routes through the change-request pending-approval path (like scope);
narrowing still applies immediately.

รัน:
    docker compose exec hub-backend pytest tests/test_access_policy_approval.py -v
"""

from __future__ import annotations

import uuid

import pytest

from app.models import Subsystem, SubsystemChangeRequest
from app.services import stepup_cache
from app.services.jwt_service import create_access_token
from app.services.secret_service import hash_secret


# ── unit: widening decision (pure) ──────────────────────────────────────────


@pytest.mark.parametrize(
    "old_p,new_p,widens",
    [
        ("explicit", "all", True),  # the attack: narrowest -> everyone
        ("explicit", "role", True),  # rank increase
        ("role", "all", True),  # rank increase
        ("all", "explicit", False),  # narrowing
        ("all", "role", False),  # narrowing
        ("role", "explicit", False),  # narrowing
        (
            "role",
            "attribute",
            True,
        ),  # same rank, different type -> conservative approve
    ],
)
def test_widens_truth_table(old_p, new_p, widens):
    from app.routers.developer import _access_policy_widens

    assert _access_policy_widens(old_p, None, new_p, None) is widens


# ── endpoint: developer widening -> pending, policy unchanged ────────────────


def _owned_subsystem(db, owner, policy="explicit"):
    s = Subsystem(
        name=f"as-{uuid.uuid4().hex[:6]}",
        client_id=f"cli_{uuid.uuid4().hex[:10]}",
        client_secret_hash=hash_secret("x"),
        redirect_uris=["https://sub.example.com/cb"],
        scope=["email"],
        status="active",
        owner_user_id=owner.id,
        access_policy=policy,
        access_policy_config=None,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _cleanup(db, sub_id):
    db.query(SubsystemChangeRequest).filter(
        SubsystemChangeRequest.subsystem_id == sub_id
    ).delete(synchronize_session=False)
    db.query(Subsystem).filter(Subsystem.id == sub_id).delete(synchronize_session=False)
    db.commit()


def test_developer_widening_creates_pending_not_applied(
    client, db, teacher_user, auth_headers
):
    token, jti = create_access_token(teacher_user)
    stepup_cache.set_granted(str(teacher_user.id), jti, method="passkey")
    sub = _owned_subsystem(db, teacher_user, policy="explicit")
    try:
        r = client.patch(
            f"/developer/subsystems/{sub.id}",
            headers=auth_headers(token),
            json={"access_policy": "all"},
        )
        assert r.status_code == 200, r.text
        # a pending change-request must exist for edit_access_policy
        pend = (
            db.query(SubsystemChangeRequest)
            .filter(
                SubsystemChangeRequest.subsystem_id == sub.id,
                SubsystemChangeRequest.request_type == "edit_access_policy",
                SubsystemChangeRequest.status == "pending",
            )
            .first()
        )
        assert pend is not None, "widening must create a pending change-request"
        # and the policy must NOT have been applied yet
        db.expire_all()
        fresh = db.query(Subsystem).filter(Subsystem.id == sub.id).first()
        assert (
            fresh.access_policy == "explicit"
        ), "policy must not change before approval"
    finally:
        stepup_cache.clear(str(teacher_user.id), jti)
        _cleanup(db, sub.id)


def test_developer_narrowing_applies_immediately(
    client, db, teacher_user, auth_headers
):
    token, jti = create_access_token(teacher_user)
    stepup_cache.set_granted(str(teacher_user.id), jti, method="passkey")
    sub = _owned_subsystem(db, teacher_user, policy="all")
    try:
        r = client.patch(
            f"/developer/subsystems/{sub.id}",
            headers=auth_headers(token),
            json={"access_policy": "explicit"},
        )
        assert r.status_code == 200, r.text
        # narrowing applies immediately — no pending request, policy changed
        pend = (
            db.query(SubsystemChangeRequest)
            .filter(
                SubsystemChangeRequest.subsystem_id == sub.id,
                SubsystemChangeRequest.request_type == "edit_access_policy",
                SubsystemChangeRequest.status == "pending",
            )
            .first()
        )
        assert pend is None, "narrowing should not require approval"
        db.expire_all()
        fresh = db.query(Subsystem).filter(Subsystem.id == sub.id).first()
        assert fresh.access_policy == "explicit"
    finally:
        stepup_cache.clear(str(teacher_user.id), jti)
        _cleanup(db, sub.id)
