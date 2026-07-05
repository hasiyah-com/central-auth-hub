"""Refresh Token tests — short-lived access token + rotating refresh token.

ครอบ:
  - issue()/rotate()/revoke() round-trip (service layer, Redis)
  - รูปแบบ token = "{refresh_id}.{secret}" — secret ไม่เก็บ plaintext (HMAC hash)
  - rotate() single-use — ใช้ซ้ำ (replay) ต้อง fail (atomic getdel, ตาม B9)
  - rotate() token ปลอม/tamper secret ต้อง fail
  - HTTP: POST /auth/refresh — happy path ออก access+refresh ใหม่ + jti/refresh_id
    ใน LoginSession อัปเดต
  - HTTP: POST /auth/refresh ด้วย token ผิด/หมดอายุ → 401
  - HTTP: POST /auth/refresh ด้วย user ที่ status != active → 401
  - POST /auth/logout พร้อม refresh_token ใน body → revoke ทั้งคู่ (access + refresh)
    → refresh token เดิมใช้ rotate ต่อไม่ได้

รัน:
  docker compose exec hub-backend pytest tests/test_refresh_token.py -v
"""

from __future__ import annotations

import pytest

import app.routers.auth as auth_module
from app.models import LoginSession
from app.services import refresh_token_service as rts
from app.services.jwt_service import create_access_token, verify_token


# ─────────────────────────────────────────────────────────────
# Service layer
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_issue_returns_opaque_token_with_id_prefix():
    raw, refresh_id = rts.issue(user_id="user-1", session_id="sess-1")
    assert raw.startswith(refresh_id + ".")
    # secret part ต้องมีความยาวพอ (ไม่ใช่ค่าที่เดาง่าย)
    secret = raw.split(".", 1)[1]
    assert len(secret) >= 32


@pytest.mark.smoke
def test_rotate_roundtrip_returns_user_and_session():
    raw, _refresh_id = rts.issue(user_id="user-42", session_id="sess-42")
    result = rts.rotate(raw)
    assert result is not None
    assert result["user_id"] == "user-42"
    assert result["session_id"] == "sess-42"
    assert result["raw_token"] != raw  # rotation ออก token ใหม่เสมอ
    assert result["refresh_id"]


def test_rotate_is_single_use():
    """ใช้ refresh token ซ้ำ (replay) หลัง rotate แล้ว → ต้อง fail (atomic getdel)."""
    raw, _ = rts.issue(user_id="user-x", session_id="sess-x")
    first = rts.rotate(raw)
    assert first is not None
    # ใช้ token เดิมซ้ำ (ที่ถูก consume ไปแล้ว) → ต้อง None
    second = rts.rotate(raw)
    assert second is None


def test_rotate_rejects_unknown_refresh_id():
    result = rts.rotate("nonexistent-id.somesecret")
    assert result is None


def test_rotate_rejects_tampered_secret():
    raw, refresh_id = rts.issue(user_id="user-y", session_id="sess-y")
    tampered = f"{refresh_id}.wrong-secret-value-not-matching"
    assert rts.rotate(tampered) is None
    # token จริงยังใช้ได้ (ไม่ได้ถูก consume จาก request ปลอม)
    assert rts.rotate(raw) is not None


def test_rotate_rejects_malformed_token():
    assert rts.rotate("no-dot-separator") is None
    assert rts.rotate("") is None


@pytest.mark.smoke
def test_revoke_by_id_prevents_further_rotation():
    raw, refresh_id = rts.issue(user_id="user-z", session_id="sess-z")
    rts.revoke(refresh_id)
    assert rts.rotate(raw) is None


# ─────────────────────────────────────────────────────────────
# HTTP — POST /auth/refresh
# ─────────────────────────────────────────────────────────────


def _login_session_for(db, user, jti: str, refresh_id: str):
    sess = LoginSession(
        user_id=user.id,
        subsystem_id=None,
        ip="127.0.0.1",
        user_agent="pytest",
        login_method="google",
        decision="allow",
        jti=jti,
        refresh_id=refresh_id,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


@pytest.mark.smoke
def test_refresh_endpoint_issues_new_access_and_refresh(client, db, admin_user):
    token, jti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="placeholder")
    sess = _login_session_for(db, admin_user, jti, refresh_id)
    # session_id ต้องตรง sess.id จริง — ออก token ใหม่ผูกกับ session จริง
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    db.commit()

    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["refresh_token"] != raw  # rotated

    # access token ใหม่ verify ผ่าน + sub ตรง user
    payload = verify_token(body["access_token"])
    assert payload["sub"] == str(admin_user.id)

    # refresh token เดิมใช้ไม่ได้อีก (single-use)
    r2 = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r2.status_code == 401

    # refresh token ใหม่ยังใช้ต่อได้
    r3 = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r3.status_code == 200


def test_refresh_endpoint_rejects_invalid_token(client):
    r = client.post("/auth/refresh", json={"refresh_token": "garbage.notreal"})
    assert r.status_code == 401


def test_refresh_endpoint_rejects_inactive_user(client, db, admin_user):
    token, jti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="s")
    sess = _login_session_for(db, admin_user, jti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))

    old_status = admin_user.status
    admin_user.status = "suspended"
    db.commit()
    try:
        r = client.post("/auth/refresh", json={"refresh_token": raw})
        assert r.status_code == 401
    finally:
        admin_user.status = old_status
        db.commit()


# ─────────────────────────────────────────────────────────────
# Logout revokes refresh token too
# ─────────────────────────────────────────────────────────────


def test_logout_revokes_refresh_token(client, db, admin_user, auth_headers):
    token, jti = create_access_token(admin_user)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id="s")
    sess = _login_session_for(db, admin_user, jti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(admin_user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    db.commit()

    r = client.post(
        "/auth/logout",
        headers=auth_headers(token),
        json={"refresh_token": raw},
    )
    assert r.status_code == 200

    # refresh token ที่ logout ไปแล้ว rotate ต่อไม่ได้
    assert rts.rotate(raw) is None


# ─────────────────────────────────────────────────────────────
# Risk re-evaluation on refresh (session-hijack detection)
# ─────────────────────────────────────────────────────────────


def _make_session_and_token(db, user):
    """สร้าง LoginSession + refresh token ที่ผูก session_id จริง."""
    raw, refresh_id = rts.issue(user_id=str(user.id), session_id="tmp")
    token, jti = create_access_token(user)
    sess = _login_session_for(db, user, jti, refresh_id)
    raw, refresh_id = rts.issue(user_id=str(user.id), session_id=str(sess.id))
    sess.refresh_id = refresh_id
    db.commit()
    return raw, sess


def _fake_risk(score: float, decision: str):
    async def _f(**kwargs):
        return {
            "score": score,
            "decision": decision,
            "reasons": ["is_new_country", "impossible_travel"],
            "breakdown": {"rule": score, "behavior": 0.0, "iforest": 0.0},
        }

    return _f


def test_refresh_low_risk_issues_normally(client, db, admin_user, monkeypatch):
    """enforce mode + risk ต่ำ → ออก token ปกติ (refresh จากที่เดิม)."""
    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", False)
    monkeypatch.setattr(auth_module, "evaluate_login_risk", _fake_risk(0.1, "allow"))
    raw, _sess = _make_session_and_token(db, admin_user)
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_high_risk_with_passkey_requires_stepup(
    client, db, admin_user, monkeypatch
):
    """enforce mode + risk สูง (challenge) + มี passkey → 200 stepup_required."""
    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", False)
    monkeypatch.setattr(
        auth_module, "evaluate_login_risk", _fake_risk(0.6, "challenge")
    )
    monkeypatch.setattr(auth_module.webauthn_service, "count_active", lambda uid, db: 1)
    raw, _sess = _make_session_and_token(db, admin_user)
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200
    body = r.json()
    assert body["stepup_required"] is True
    assert "risk-stepup" in body["stepup_url"]
    assert "access_token" not in body  # ยังไม่ออก token จนกว่าจะ step-up ผ่าน


def test_refresh_hard_block_forces_relogin(client, db, admin_user, monkeypatch):
    """enforce mode + score >= hard threshold → 401 (ต้อง login ใหม่เต็ม)."""
    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", False)
    monkeypatch.setattr(auth_module, "evaluate_login_risk", _fake_risk(0.95, "block"))
    monkeypatch.setattr(auth_module.webauthn_service, "count_active", lambda uid, db: 1)
    raw, sess = _make_session_and_token(db, admin_user)
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401
    # session ถูกตัด (logout_at set)
    db.refresh(sess)
    assert sess.logout_at is not None


def test_refresh_high_risk_no_passkey_forces_relogin(
    client, db, admin_user, monkeypatch
):
    """enforce mode + risk สูง แต่ไม่มี passkey → 401 (login flow จัดการ enroll เอง)."""
    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", False)
    monkeypatch.setattr(
        auth_module, "evaluate_login_risk", _fake_risk(0.6, "challenge")
    )
    monkeypatch.setattr(auth_module.webauthn_service, "count_active", lambda uid, db: 0)
    raw, _sess = _make_session_and_token(db, admin_user)
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 401


def test_refresh_shadow_mode_high_risk_still_issues(
    client, db, admin_user, monkeypatch
):
    """shadow mode (default) + risk สูง → ยังออก token ปกติ (ไม่ enforce)."""
    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", True)
    monkeypatch.setattr(
        auth_module, "evaluate_login_risk", _fake_risk(0.95, "would_block")
    )
    raw, _sess = _make_session_and_token(db, admin_user)
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_shadow_mode_high_risk_logs_audit_entry(
    client, db, admin_user, monkeypatch
):
    """shadow mode + risk สูง → ไม่ enforce แต่ยัง log audit_logs (append-only
    ต่างจาก LoginSession.risk_* ที่เป็นแค่ current-state เขียนทับได้)."""
    from app.models import AuditLog

    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", True)
    monkeypatch.setattr(
        auth_module, "evaluate_login_risk", _fake_risk(0.95, "would_block")
    )
    raw, _sess = _make_session_and_token(db, admin_user)

    before = (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_id == admin_user.id,
            AuditLog.action == "risk_refresh_would_stepup",
        )
        .count()
    )
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200

    after = (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_id == admin_user.id,
            AuditLog.action == "risk_refresh_would_stepup",
        )
        .count()
    )
    assert after == before + 1

    entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_id == admin_user.id,
            AuditLog.action == "risk_refresh_would_stepup",
        )
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert entry.metadata_json["shadow"] is True
    assert entry.metadata_json["decision"] == "would_block"


def test_refresh_low_risk_shadow_mode_no_audit_entry(
    client, db, admin_user, monkeypatch
):
    """shadow mode + risk ปกติ → ไม่ log อะไรเลย (ไม่ใช่ทุก refresh ที่ควรมี entry)."""
    from app.models import AuditLog

    monkeypatch.setattr(auth_module.settings, "ml_shadow_mode", True)
    monkeypatch.setattr(auth_module, "evaluate_login_risk", _fake_risk(0.1, "allow"))
    raw, _sess = _make_session_and_token(db, admin_user)

    before = db.query(AuditLog).filter(AuditLog.actor_id == admin_user.id).count()
    r = client.post("/auth/refresh", json={"refresh_token": raw})
    assert r.status_code == 200

    after = db.query(AuditLog).filter(AuditLog.actor_id == admin_user.id).count()
    assert after == before  # ไม่เพิ่ม audit entry ตอน risk ปกติ
