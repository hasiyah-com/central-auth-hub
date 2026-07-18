"""Tests — Change Google Account (self-service re-link) + security guards.

ข้อ 3 ของ "ข้อเสนอแนะในการปรับปรุงระบบ": ผู้ใช้เปลี่ยนบัญชี Google (email + sub ใหม่)
โดยยืนยันตัวตนเดิมด้วย **Passkey step-up** + OAuth พิสูจน์ครองบัญชี Google ใหม่.

Design: 3 endpoints (start [passkey-gated] → redirect [browser] → callback [apply]).
Core business logic แยกเป็น `_apply_google_relink()` เพื่อ test guards/apply/revoke/audit
โดยไม่ต้องยิง Google จริง.

RED phase: module `app.routers.account_link` ยังไม่มี → import fail → เทสต์ fail หมด (ถูกต้อง).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models import AuditLog, LoginSession, User
from app.redis_client import redis_client
from app.services import stepup_cache
from app.services.jwt_service import create_access_token, is_revoked


# ─────────────────────────────────────────────────────────────
# Helpers — throwaway users (tests แก้ data → ต้อง cleanup)
# ─────────────────────────────────────────────────────────────


def _mk_user(db, *, email=None, google_sub=None) -> User:
    suffix = uuid.uuid4().hex[:8]
    u = User(
        email=email or f"relink_{suffix}@uni.ac.th",
        google_sub=google_sub or f"gsub_{suffix}",
        full_name=f"Relink Test {suffix}",
        user_type="teacher",
        status="active",
        is_hub_admin=False,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _purge_user(db, user_id) -> None:
    db.query(AuditLog).filter(AuditLog.target_id == user_id).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.actor_id == user_id).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def temp_user(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    _purge_user(db, uid)


@pytest.fixture
def temp_user2(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    _purge_user(db, uid)


# ─────────────────────────────────────────────────────────────
# start endpoint — passkey-only step-up gate
# ─────────────────────────────────────────────────────────────


def test_start_requires_stepup(client, temp_user, auth_headers):
    """ไม่มี step-up grant → 403 stepup_required."""
    token, jti = create_access_token(temp_user)
    stepup_cache.clear(str(temp_user.id), jti)
    r = client.post("/auth/account/change-google/start", headers=auth_headers(token))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "stepup_required"


def test_start_rejects_otp_stepup(client, temp_user, auth_headers):
    """มีแค่ OTP step-up grant → ยัง 403 (action นี้บังคับ passkey)."""
    token, jti = create_access_token(temp_user)
    stepup_cache.set_granted(str(temp_user.id), jti, "otp")
    try:
        r = client.post(
            "/auth/account/change-google/start", headers=auth_headers(token)
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "stepup_required"
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


def test_start_with_passkey_stepup_mints_token(client, temp_user, auth_headers):
    """passkey step-up grant → 200 + start_url + Redis token ถูก mint."""
    token, jti = create_access_token(temp_user)
    stepup_cache.set_granted(str(temp_user.id), jti, "passkey")
    try:
        r = client.post(
            "/auth/account/change-google/start", headers=auth_headers(token)
        )
        assert r.status_code == 200
        body = r.json()
        assert "start_url" in body
        # token ใน URL ต้องมีจริงใน Redis
        t = body["start_url"].split("t=")[-1]
        assert redis_client.exists(f"change_google:{t}") == 1
        redis_client.delete(f"change_google:{t}")
    finally:
        stepup_cache.clear(str(temp_user.id), jti)


# ─────────────────────────────────────────────────────────────
# redirect endpoint — token peek
# ─────────────────────────────────────────────────────────────


def test_redirect_missing_token_400(client):
    """ไม่มี token / หมดอายุ → 400 (ไม่เริ่ม OAuth ให้)."""
    r = client.get(
        "/auth/account/change-google/redirect?t=nonexistent_xyz",
        follow_redirects=False,
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────
# core apply logic — guards + re-link + revoke + audit
# ─────────────────────────────────────────────────────────────


def test_apply_happy_relinks_email_and_sub(db, temp_user, monkeypatch):
    """re-link สำเร็จ: email+sub เปลี่ยน, user.id เดิม, email_verified=True."""
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)

    old_id = temp_user.id
    new_email = f"new_{uuid.uuid4().hex[:8]}@gmail.com"
    new_sub = f"newsub_{uuid.uuid4().hex[:8]}"

    ok, reason = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=new_sub,
        new_email=new_email,
        email_verified=True,
        ip="1.2.3.4",
    )
    assert ok is True, reason
    db.refresh(temp_user)
    assert temp_user.id == old_id  # ← ข้อมูลเดิมอยู่ครบ (PK ไม่เปลี่ยน)
    assert temp_user.email == new_email
    assert temp_user.google_sub == new_sub
    assert temp_user.email_verified is True
    assert temp_user.email_verified_at is not None


def test_apply_rejects_unverified_email(db, temp_user, monkeypatch):
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)
    ok, reason = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub="whatever",
        new_email="x@gmail.com",
        email_verified=False,
        ip="1.2.3.4",
    )
    assert ok is False
    assert reason == "email_not_verified"


def test_apply_rejects_email_taken_by_other(db, temp_user, temp_user2, monkeypatch):
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)
    ok, reason = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=f"newsub_{uuid.uuid4().hex[:8]}",
        new_email=temp_user2.email,  # ← ชนกับ user อื่น
        email_verified=True,
        ip="1.2.3.4",
    )
    assert ok is False
    assert reason == "email_taken"


def test_apply_rejects_sub_taken_by_other(db, temp_user, temp_user2, monkeypatch):
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)
    ok, reason = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=temp_user2.google_sub,  # ← ชนกับ user อื่น
        new_email=f"new_{uuid.uuid4().hex[:8]}@gmail.com",
        email_verified=True,
        ip="1.2.3.4",
    )
    assert ok is False
    assert reason == "sub_taken"


def test_apply_revokes_sessions_and_stepup(db, temp_user, monkeypatch):
    """หลัง re-link: session ถูกปิด + jti revoked + stepup cache ถูกล้าง."""
    from app.routers import account_link

    monkeypatch.setattr(account_link, "_send_alert", lambda *a, **k: None)

    # สร้าง active session + stepup grant
    _tok, jti = create_access_token(temp_user)
    sess = LoginSession(
        user_id=temp_user.id,
        jti=jti,
        created_at=datetime.utcnow(),
    )
    db.add(sess)
    db.commit()
    stepup_cache.set_granted(str(temp_user.id), jti, "passkey")

    ok, _ = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=f"newsub_{uuid.uuid4().hex[:8]}",
        new_email=f"new_{uuid.uuid4().hex[:8]}@gmail.com",
        email_verified=True,
        ip="1.2.3.4",
    )
    assert ok is True
    db.refresh(sess)
    assert sess.logout_at is not None
    assert is_revoked(jti) is True
    assert stepup_cache.check_cached(str(temp_user.id), jti) is None


def test_apply_writes_audit_and_alerts(db, temp_user, monkeypatch):
    """audit row account_google_changed + alert email ไป old+new (2 ครั้ง)."""
    from app.routers import account_link

    calls = []
    monkeypatch.setattr(account_link, "_send_alert", lambda to, **k: calls.append(to))

    old_email = temp_user.email
    new_email = f"new_{uuid.uuid4().hex[:8]}@gmail.com"
    ok, _ = account_link._apply_google_relink(
        db,
        temp_user,
        new_sub=f"newsub_{uuid.uuid4().hex[:8]}",
        new_email=new_email,
        email_verified=True,
        ip="1.2.3.4",
    )
    assert ok is True
    # alert ไปทั้ง old + new
    assert set(calls) == {old_email, new_email}
    # audit row
    row = (
        db.query(AuditLog)
        .filter(
            AuditLog.target_id == temp_user.id,
            AuditLog.action == "account_google_changed",
        )
        .first()
    )
    assert row is not None
    assert row.metadata_json.get("new_email") == new_email
    assert row.metadata_json.get("old_email") == old_email


def test_change_token_is_single_use(db):
    """Redis change_google token = single-use (getdel, B9)."""
    import json

    t = uuid.uuid4().hex
    redis_client.setex(
        f"change_google:{t}", 600, json.dumps({"user_id": "x", "jti": "y"})
    )
    first = redis_client.getdel(f"change_google:{t}")
    second = redis_client.getdel(f"change_google:{t}")
    assert first is not None
    assert second is None
