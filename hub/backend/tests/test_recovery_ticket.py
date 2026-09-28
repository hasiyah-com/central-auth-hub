"""Tests — Recovery Ticket (four-eyes) + Credential Management (Phase 3)."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

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
from app.services import mfa_service, stepup_cache, totp_service
from app.services.secret_service import encrypt_secret
from app.services.jwt_service import create_access_token
from app.redis_client import redis_client
from app.routers.account_link import _restore_recovery_token
from app.routers import recovery as recovery_router


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


# 1x1 PNG — หลักฐานจำลองสำหรับ API tests
_PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"test-recovery-evidence"
).decode()


def _request_payload(email: str) -> dict:
    return {
        "email": email,
        "credential_type": "TOTP",
        "reason": "lost phone",
        "evidence_type": "student_card",
        "evidence_mime": "image/png",
        "evidence_image": _PNG,
    }


def test_request_creates_pending_ticket(client, victim, db):
    r = client.post(
        "/auth/recovery/request",
        json=_request_payload(victim.email),
    )
    assert r.status_code == 200 and r.json()["submitted"] is True
    t = db.query(RecoveryTicket).filter(RecoveryTicket.user_id == victim.id).first()
    assert t and t.status == "pending" and t.recovery_level == "NORMAL"


def test_request_unknown_email_opaque_no_ticket(client, db):
    email = f"ghost_{uuid.uuid4().hex[:6]}@x.com"
    r = client.post("/auth/recovery/request", json=_request_payload(email))
    assert r.status_code == 200 and r.json()["submitted"] is True
    assert (
        db.query(RecoveryTicket).filter(RecoveryTicket.email == email).first() is None
    )


def test_request_returns_tracking_credential_and_status(client, victim):
    created = client.post(
        "/auth/recovery/request", json=_request_payload(victim.email)
    )
    assert created.status_code == 200
    receipt = created.json()
    assert receipt["ticket_id"] and receipt["tracking_secret"]

    status = client.post(
        "/auth/recovery/status",
        json={
            "ticket_id": receipt["ticket_id"],
            "tracking_secret": receipt["tracking_secret"],
        },
    )
    assert status.status_code == 200
    assert status.json()["status"] == "pending"


def test_alternate_email_otp_reports_delivery_failure(client, monkeypatch):
    monkeypatch.setattr(mfa_service, "send_otp_email", lambda *_args, **_kwargs: False)
    response = client.post(
        "/auth/recovery/alternate-email/start",
        json={"email": "owner@uni.ac.th", "alternate_email": "backup@example.com"},
    )
    assert response.status_code == 503
    assert "ระบบอีเมลยังไม่พร้อมใช้งาน" in response.json()["detail"]


def test_alternate_email_otp_confirms_real_delivery(client, monkeypatch):
    sent_to = []
    monkeypatch.setattr(
        mfa_service,
        "send_otp_email",
        lambda email, *_args, **_kwargs: sent_to.append(email) or True,
    )
    response = client.post(
        "/auth/recovery/alternate-email/start",
        json={"email": "owner@uni.ac.th", "alternate_email": "backup@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert sent_to == ["backup@example.com"]


def test_recovery_page_has_clipboard_fallback(client):
    response = client.get("/auth/recovery/ticket")
    assert response.status_code == 200
    assert 'id="ticketOut"' not in response.text
    assert 'id="secretOut"' not in response.text
    assert "ข้อมูลติดตามคำขอพร้อมคัดลอก" in response.text
    assert response.text.count('id="copyReceipt"') == 1
    assert 'document.execCommand("copy")' in response.text
    assert "String.fromCharCode(10)" in response.text
    assert 'textContent+"\\nTracking secret:' not in response.text
    assert 'value="blocked_account_appeal"' in response.text
    assert 'get("topic")' in response.text


def test_blocked_account_appeal_alerts_and_reactivates(
    client, victim, admin_user, auth_headers, db, monkeypatch
):
    victim.status = "suspended"
    db.commit()
    alerts = []
    monkeypatch.setattr(
        recovery_router,
        "send_alert",
        lambda **kwargs: alerts.append(kwargs) or True,
    )

    payload = _request_payload(victim.email)
    payload.update(
        request_kind="blocked_account_appeal",
        credential_type=None,
        reason="บัญชีถูกระงับโดยไม่ทราบสาเหตุ",
    )
    created = client.post("/auth/recovery/request", json=payload)
    assert created.status_code == 200
    ticket = (
        db.query(RecoveryTicket)
        .filter(RecoveryTicket.user_id == victim.id)
        .order_by(RecoveryTicket.created_at.desc())
        .first()
    )
    assert ticket.request_kind == "blocked_account_appeal"
    assert alerts[0]["kind"] == "recovery.blocked_account_appeal_requested"

    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, "passkey")
    try:
        approved = client.post(
            f"/admin/recovery-tickets/{ticket.id}/approve",
            headers=auth_headers(token),
            json={"evidence_type": "student_card", "remark": "identity verified"},
        )
        assert approved.status_code == 200
        assert approved.json()["account_unblocked"] is True
        db.refresh(victim)
        db.refresh(ticket)
        assert victim.status == "active"
        assert ticket.status == "approved"
        assert alerts[-1]["kind"] == "recovery.blocked_account_appeal_approved"
    finally:
        stepup_cache.clear(str(admin_user.id), jti)


def test_admin_can_view_recovery_evidence_as_image(
    client, victim, admin_user, auth_headers, db
):
    ticket = RecoveryTicket(
        user_id=victim.id,
        email=victim.email,
        recovery_level="NORMAL",
        status="pending",
        evidence_type="student_card",
        evidence_mime="image/png",
        evidence_encrypted=encrypt_secret(_PNG),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    token, _ = create_access_token(admin_user)

    response = client.get(
        f"/admin/recovery-tickets/{ticket.id}/evidence",
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "no-store, private"
    assert response.content == base64.b64decode(_PNG)


# ── admin approve — NORMAL (1) ──


def test_approve_normal_issues_link(client, victim, admin_user, auth_headers, db):
    db.add(
        RecoveryTicket(
            user_id=victim.id,
            email=victim.email,
            recovery_level="NORMAL",
            status="pending",
            evidence_type="student_card",
            evidence_mime="image/png",
            evidence_encrypted=encrypt_secret(_PNG),
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
        expires = t.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        remaining = (expires - datetime.now(timezone.utc)).total_seconds()
        assert 86300 <= remaining <= 86400

        # A deploy/Redis restart must not invalidate a still-valid recovery link.
        link_token = parse_qs(urlparse(r.json()["relink_url"]).query)["t"][0]
        redis_client.delete(f"change_google:{link_token}")
        assert _restore_recovery_token(db, link_token) is True
        assert redis_client.ttl(f"change_google:{link_token}") > 86300
        redis_client.delete(f"change_google:{link_token}")
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
                evidence_type="citizen_id",
                evidence_mime="image/png",
                evidence_encrypted=encrypt_secret(_PNG),
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
