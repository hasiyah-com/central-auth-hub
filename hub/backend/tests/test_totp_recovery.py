"""Tests — TOTP recovery + change-google cooldown + audit source + google_sub fix (Phase 2)."""

from __future__ import annotations

import uuid

import pyotp
import pytest

from app.models import AuditLog, LoginSession, User, UserTotpCredential
from app.redis_client import redis_client
from app.services import stepup_cache, totp_service
from app.services.jwt_service import create_access_token


def _mk_user(db, *, active=True) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"rec_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"Rec {s}",
        user_type="teacher",
        status="active" if active else "suspended",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _enable_totp(db, user) -> str:
    secret, _ = totp_service.start_enroll(user.id, db)
    totp_service.confirm_enroll(user.id, pyotp.TOTP(secret).now(), db)
    db.commit()
    return secret


def _purge(db, uid):
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(
        synchronize_session=False
    )
    db.query(UserTotpCredential).filter(UserTotpCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def temp_user(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    redis_client.delete(f"change_google_cooldown:{uid}")
    _purge(db, uid)


# ── TOTP recovery endpoint (public) ──


def test_recover_totp_success_returns_start_url(client, temp_user, db):
    secret = _enable_totp(db, temp_user)
    r = client.post(
        "/auth/passkey/recover/totp",
        json={"email": temp_user.email, "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recovered"] is True and "start_url" in body
    # token ถูก mint ใน Redis + payload source=RECOVERY
    t = body["start_url"].split("t=")[-1]
    import json

    raw = redis_client.get(f"change_google:{t}")
    assert raw and json.loads(raw)["source"] == "RECOVERY"
    redis_client.delete(f"change_google:{t}")


def test_recover_totp_wrong_code_opaque(client, temp_user, db):
    _enable_totp(db, temp_user)
    r = client.post(
        "/auth/passkey/recover/totp",
        json={"email": temp_user.email, "code": "000001"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "recovery_failed"


def test_recover_totp_unknown_email_opaque(client):
    r = client.post(
        "/auth/passkey/recover/totp",
        json={"email": f"ghost_{uuid.uuid4().hex[:6]}@x.com", "code": "123456"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "recovery_failed"


# ── cooldown + source (apply core) ──


def test_apply_sets_cooldown_and_source(db, temp_user, monkeypatch):
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)
    ok, _ = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=f"newsub_{uuid.uuid4().hex[:8]}",
        new_email=f"new_{uuid.uuid4().hex[:8]}@gmail.com",
        email_verified=True,
        ip="1.2.3.4",
        source="RECOVERY",
    )
    assert ok is True
    assert account_link.in_cooldown(str(temp_user.id)) is True
    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.target_id == temp_user.id,
            AuditLog.action == "account_google_changed",
        )
        .first()
    )
    assert row.metadata_json.get("changed_by") == "RECOVERY"


def test_change_google_start_blocked_by_cooldown(client, temp_user, auth_headers):
    from app.routers import account_link

    account_link._set_cooldown(str(temp_user.id))
    token, jti = create_access_token(temp_user)
    stepup_cache.set_granted(str(temp_user.id), jti, "passkey")
    try:
        r = client.post(
            "/auth/account/change-google/start", headers=auth_headers(token)
        )
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "change_google_cooldown"
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


# ── google_sub bug fix (admin update email) ──


def test_admin_update_email_clears_google_sub(client, admin_user, auth_headers, db):
    target = _mk_user(db)
    tid = target.id
    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, "passkey")
    try:
        new_email = f"changed_{uuid.uuid4().hex[:8]}@gmail.com"
        r = client.patch(
            f"/admin/users/{tid}",
            headers=auth_headers(token),
            json={"email": new_email},
        )
        assert r.status_code == 200
        db.expire_all()
        u = db.query(User).filter(User.id == tid).first()
        assert u.email == new_email
        assert u.google_sub is None  # ← เคลียร์แล้ว (bug fix)
        assert u.email_verified is False
    finally:
        stepup_cache.clear(str(admin_user.id), jti)
        _purge(db, tid)
