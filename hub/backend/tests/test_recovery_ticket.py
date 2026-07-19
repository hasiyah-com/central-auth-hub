"""Tests — Recovery Ticket (four-eyes) + Credential Management (Phase 3)."""

from __future__ import annotations

import uuid

import pyotp
import pytest

from app.models import (
    AuditLog,
    PasskeyCredential,
    RecoveryTicket,
    RecoveryTicketApproval,
    User,
    UserTotpCredential,
)
from app.services import stepup_cache, totp_service
from app.services.jwt_service import create_access_token


def _mk_user(db, *, is_admin=False) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"tk_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"TK {s}",
        user_type="admin" if is_admin else "teacher",
        status="active",
        is_hub_admin=is_admin,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _purge(db, uid):
    db.query(RecoveryTicketApproval).filter(
        RecoveryTicketApproval.admin_id == uid
    ).delete(synchronize_session=False)
    tickets = db.query(RecoveryTicket).filter(RecoveryTicket.user_id == uid).all()
    for t in tickets:
        db.query(RecoveryTicketApproval).filter(
            RecoveryTicketApproval.ticket_id == t.id
        ).delete(synchronize_session=False)
    db.query(RecoveryTicket).filter(RecoveryTicket.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(
        synchronize_session=False
    )
    db.query(UserTotpCredential).filter(UserTotpCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def victim(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    _purge(db, uid)


# ── request (public, opaque) ──


def test_request_creates_pending_ticket(client, victim, db):
    r = client.post(
        "/auth/recovery/request",
        json={"email": victim.email, "credential_type": "TOTP", "reason": "lost phone"},
    )
    assert r.status_code == 200 and r.json()["submitted"] is True
    t = db.query(RecoveryTicket).filter(RecoveryTicket.user_id == victim.id).first()
    assert t and t.status == "pending" and t.recovery_level == "NORMAL"


def test_request_unknown_email_opaque_no_ticket(client, db):
    email = f"ghost_{uuid.uuid4().hex[:6]}@x.com"
    r = client.post("/auth/recovery/request", json={"email": email})
    assert r.status_code == 200 and r.json()["submitted"] is True
    assert (
        db.query(RecoveryTicket).filter(RecoveryTicket.email == email).first() is None
    )


# ── admin approve — NORMAL (1) ──


def test_approve_normal_issues_link(client, victim, admin_user, auth_headers, db):
    db.add(
        RecoveryTicket(
            user_id=victim.id,
            email=victim.email,
            recovery_level="NORMAL",
            status="pending",
        )
    )
    db.commit()
    tid = (
        db.query(RecoveryTicket).filter(RecoveryTicket.user_id == victim.id).first().id
    )
    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, "passkey")
    try:
        r = client.post(
            f"/admin/recovery-tickets/{tid}/approve",
            headers=auth_headers(token),
            json={"evidence_type": "student_card", "remark": "verified in person"},
        )
        assert r.status_code == 200 and r.json()["approved"] is True
        assert "relink_url" in r.json()
        t = db.query(RecoveryTicket).filter(RecoveryTicket.id == tid).first()
        db.refresh(t)
        assert t.status == "approved" and t.link_token
    finally:
        stepup_cache.clear(str(admin_user.id), jti)


# ── admin approve — HIGH four-eyes (2 different admins) ──


def test_approve_high_requires_two_admins(client, db, auth_headers):
    victim2 = _mk_user(db, is_admin=True)  # is_hub_admin → HIGH
    admin_a = _mk_user(db, is_admin=True)
    admin_b = _mk_user(db, is_admin=True)
    try:
        db.add(
            RecoveryTicket(
                user_id=victim2.id,
                email=victim2.email,
                recovery_level="HIGH",
                status="pending",
            )
        )
        db.commit()
        tid = (
            db.query(RecoveryTicket)
            .filter(RecoveryTicket.user_id == victim2.id)
            .first()
            .id
        )

        ta, ja = create_access_token(admin_a)
        tb, jb = create_access_token(admin_b)
        stepup_cache.set_granted(str(admin_a.id), ja, "passkey")
        stepup_cache.set_granted(str(admin_b.id), jb, "passkey")

        # admin A → 1/2 awaiting
        r1 = client.post(
            f"/admin/recovery-tickets/{tid}/approve",
            headers=auth_headers(ta),
            json={"evidence_type": "citizen_id"},
        )
        assert (
            r1.status_code == 200 and r1.json().get("awaiting_second_approval") is True
        )

        # admin A ซ้ำ → 409 (ต้องต่างคน)
        r_dup = client.post(
            f"/admin/recovery-tickets/{tid}/approve",
            headers=auth_headers(ta),
            json={"evidence_type": "citizen_id"},
        )
        assert r_dup.status_code == 409

        # admin B → 2/2 → link
        r2 = client.post(
            f"/admin/recovery-tickets/{tid}/approve",
            headers=auth_headers(tb),
            json={"evidence_type": "citizen_id"},
        )
        assert r2.status_code == 200 and r2.json().get("approved") is True
        stepup_cache.clear(str(admin_a.id), ja)
        stepup_cache.clear(str(admin_b.id), jb)
    finally:
        for u in (victim2, admin_a, admin_b):
            _purge(db, u.id)


def test_non_admin_cannot_list_tickets(client, teacher_user, auth_headers):
    token, _ = create_access_token(teacher_user)
    r = client.get("/admin/recovery-tickets", headers=auth_headers(token))
    assert r.status_code in (401, 403)


# ── Credential Management ──


def test_credentials_lists_google_passkey_totp(
    client, victim, admin_user, auth_headers, db
):
    # เปิด TOTP + เพิ่ม passkey ให้ victim
    secret, _ = totp_service.start_enroll(victim.id, db)
    totp_service.confirm_enroll(victim.id, pyotp.TOTP(secret).now(), db)
    db.add(
        PasskeyCredential(
            user_id=victim.id,
            credential_id=uuid.uuid4().bytes + uuid.uuid4().bytes,
            public_key=b"\x00" * 32,
            sign_count=0,
            device_name="iPhone",
            status="ACTIVE",
        )
    )
    db.commit()
    token, _ = create_access_token(admin_user)
    r = client.get(f"/admin/users/{victim.id}/credentials", headers=auth_headers(token))
    assert r.status_code == 200
    body = r.json()
    types = {c["credential_type"] for c in body["credentials"]}
    assert types == {"GOOGLE", "PASSKEY", "TOTP"}
    assert body["recovery_ready"] is True  # มี ACTIVE passkey/totp
