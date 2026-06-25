"""Tests — Global Auth Policy (เลือกวิธี login: Google / Passkey).

ครอบคลุม:
  - Service layer: get/set default, validate ≥1 (กัน lockout), round-trip
  - HTTP: public GET /auth/policy, admin GET/PUT /admin/auth-policy
  - Step-up gate (PUT เป็น critical action)
  - Enforcement: ปิด google → /auth/google/login 403; ปิด passkey → passkey start 403
  - Subsystem login chooser render ตาม policy (ซ่อนปุ่มที่ปิด)
  - Invariant: ปิดทั้งคู่ → 400 (ไม่บันทึก)

หมายเหตุ: ใช้ live dev DB (ตาม conftest). ทุก test ที่แก้ policy จะ restore
กลับ {google:True, passkey:True} ผ่าน fixture `policy_guard` → idempotent.

รัน:
  docker compose exec hub-backend pytest tests/test_auth_policy.py -v
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.services import auth_policy
from app.services import stepup_cache
from app.services.jwt_service import create_access_token
from app.routers.oauth import _login_chooser_html


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def policy_guard():
    """Snapshot policy ก่อน test แล้ว restore เป็น both-True หลัง test.

    กัน test ที่แก้ policy ทำให้ระบบค้างในสถานะปิดวิธีใดวิธีหนึ่ง.
    """
    yield
    s = SessionLocal()
    try:
        auth_policy.set_auth_policy(s, google=True, passkey=True, actor_id=None)
        s.commit()
    finally:
        s.close()


def _admin_token_with_stepup(admin_user) -> str:
    """ออก JWT ให้ admin + grant step-up สำหรับ jti นั้น → ผ่าน critical-action gate."""
    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, method="passkey", ip="127.0.0.1")
    return token


# ─────────────────────────────────────────────────────────────
# Service layer
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_get_policy_returns_dict(db):
    p = auth_policy.get_auth_policy(db)
    assert set(p.keys()) == {"google", "passkey"}
    assert isinstance(p["google"], bool)
    assert isinstance(p["passkey"], bool)


def test_set_and_get_roundtrip(db, policy_guard):
    auth_policy.set_auth_policy(db, google=True, passkey=False, actor_id=None)
    db.commit()
    p = auth_policy.get_auth_policy(db)
    assert p == {"google": True, "passkey": False}

    auth_policy.set_auth_policy(db, google=False, passkey=True, actor_id=None)
    db.commit()
    p = auth_policy.get_auth_policy(db)
    assert p == {"google": False, "passkey": True}


def test_set_both_false_raises(db, policy_guard):
    """Invariant — ปิดทั้งคู่ไม่ได้ (กัน lockout ทั้งระบบ)."""
    with pytest.raises(ValueError):
        auth_policy.set_auth_policy(db, google=False, passkey=False, actor_id=None)


# ─────────────────────────────────────────────────────────────
# HTTP — public read
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_public_policy_endpoint(client):
    """GET /auth/policy — public (ไม่ต้อง auth) → คืน {google, passkey}."""
    r = client.get("/auth/policy")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"google", "passkey"}


# ─────────────────────────────────────────────────────────────
# HTTP — admin GET/PUT
# ─────────────────────────────────────────────────────────────


def test_admin_get_requires_auth(client):
    """GET /admin/auth-policy ไม่มี token → 401/403."""
    r = client.get("/admin/auth-policy")
    assert r.status_code in (401, 403)


def test_admin_get_with_admin(client, admin_token, auth_headers):
    r = client.get("/admin/auth-policy", headers=auth_headers(admin_token))
    assert r.status_code == 200
    assert set(r.json().keys()) == {"google", "passkey"}


def test_put_without_stepup_returns_403(client, admin_token, auth_headers):
    """PUT เป็น critical action — ไม่มี step-up grant → 403 stepup_required."""
    r = client.put(
        "/admin/auth-policy",
        headers=auth_headers(admin_token),
        json={"google": True, "passkey": True},
    )
    assert r.status_code == 403
    detail = r.json().get("detail")
    assert isinstance(detail, dict) and detail.get("code") == "stepup_required"


def test_put_both_false_rejected(client, admin_user, auth_headers, policy_guard):
    """ปิดทั้งคู่ → 400 (ไม่บันทึก)."""
    token = _admin_token_with_stepup(admin_user)
    r = client.put(
        "/admin/auth-policy",
        headers=auth_headers(token),
        json={"google": False, "passkey": False},
    )
    assert r.status_code == 400


def test_put_noop_no_kick(client, admin_user, auth_headers, policy_guard):
    """ตั้งค่าเท่าเดิม → changed=False, ไม่ตัด session."""
    # set baseline = both true
    s = SessionLocal()
    auth_policy.set_auth_policy(s, google=True, passkey=True, actor_id=None)
    s.commit()
    s.close()

    token = _admin_token_with_stepup(admin_user)
    r = client.put(
        "/admin/auth-policy",
        headers=auth_headers(token),
        json={"google": True, "passkey": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is False
    assert body["total_sessions_closed"] == 0


def test_put_real_change_persists(client, admin_user, auth_headers, policy_guard):
    """เปลี่ยนจริง (ปิด passkey) → changed=True + persist + GET สะท้อนค่าใหม่."""
    # baseline both true
    s = SessionLocal()
    auth_policy.set_auth_policy(s, google=True, passkey=True, actor_id=None)
    s.commit()
    s.close()

    token = _admin_token_with_stepup(admin_user)
    r = client.put(
        "/admin/auth-policy",
        headers=auth_headers(token),
        json={"google": True, "passkey": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["changed"] is True
    assert body["policy"] == {"google": True, "passkey": False}
    assert "total_sessions_closed" in body

    # persist ตรวจผ่าน public endpoint
    r2 = client.get("/auth/policy")
    assert r2.json() == {"google": True, "passkey": False}


# ─────────────────────────────────────────────────────────────
# Enforcement at login endpoints
# ─────────────────────────────────────────────────────────────


def test_enforce_google_disabled(client, db, policy_guard):
    """ปิด google → GET /auth/google/login = 403."""
    auth_policy.set_auth_policy(db, google=False, passkey=True, actor_id=None)
    db.commit()
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code == 403


def test_enforce_passkey_disabled(client, db, policy_guard):
    """ปิด passkey → POST /auth/passkey/login/start = 403."""
    auth_policy.set_auth_policy(db, google=True, passkey=False, actor_id=None)
    db.commit()
    r = client.post("/auth/passkey/login/start", json={"email": "nobody@uni.ac.th"})
    assert r.status_code == 403


def test_enforce_passkey_discoverable_disabled(client, db, policy_guard):
    """ปิด passkey → discoverable start = 403."""
    auth_policy.set_auth_policy(db, google=True, passkey=False, actor_id=None)
    db.commit()
    r = client.post("/auth/passkey/login/discoverable/start")
    assert r.status_code == 403


def test_google_login_works_when_enabled(client, db, policy_guard):
    """เปิด google → /auth/google/login redirect (302/307) ไป Google."""
    auth_policy.set_auth_policy(db, google=True, passkey=True, actor_id=None)
    db.commit()
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307)


# ─────────────────────────────────────────────────────────────
# Subsystem login chooser rendering
# ─────────────────────────────────────────────────────────────


def _markers(html: str) -> dict:
    return {
        "passkey_btn": 'id="pkToggle"' in html,
        "google_btn": 'href="/oauth/authorize/google' in html,
        "divider": 'class="divider stagger s3"' in html,
        "recover": "passkey/recover" in html,
    }


def test_chooser_both_enabled():
    m = _markers(_login_chooser_html("st", "Test", "nc", True, True))
    assert m == {
        "passkey_btn": True,
        "google_btn": True,
        "divider": True,
        "recover": True,
    }


def test_chooser_google_only():
    m = _markers(_login_chooser_html("st", "Test", "nc", True, False))
    assert m["passkey_btn"] is False
    assert m["google_btn"] is True
    assert m["divider"] is False  # ไม่มี "หรือ" เมื่อเหลือวิธีเดียว
    assert m["recover"] is False


def test_chooser_passkey_only():
    m = _markers(_login_chooser_html("st", "Test", "nc", False, True))
    assert m["passkey_btn"] is True
    assert m["google_btn"] is False
    assert m["divider"] is False
    assert m["recover"] is True


def test_chooser_js_guarded_when_passkey_off():
    """passkey ปิด → JS ต้องมี guard `if (toggle)` กัน null crash."""
    html = _login_chooser_html("st", "Test", "nc", True, False)
    assert "if (toggle)" in html
