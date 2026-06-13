"""Subsystem Passkey OAuth path tests (B — plan v3).

ทดสอบ /oauth/passkey/start + /oauth/passkey/finish:
  - flow guard: ต้องมี authreq (hub_state) ก่อน
  - email format validation (SQLi/XSS reject)
  - anti-enumeration: email format ถูก + มี authreq → 200 options
  - finish: missing credential / bad input

หมายเหตุ: full assertion verify (signature) อยู่ใน Phase 6 integration suite
(ต้อง mock authenticator). ที่นี่ทดสอบ guard layers + shared finalizer wiring.

นอกจากนี้ verify ว่า refactor _finalize_subsystem_login ไม่ทำ Google flow พัง
(import + helper signature).
"""

import json
import uuid

import pytest

from app.redis_client import redis_client

START = "/oauth/passkey/start"
FINISH = "/oauth/passkey/finish"


def _seed_authreq(hub_state: str, subsystem_id: str = None) -> None:
    """สร้าง authreq:{hub_state} ใน Redis จำลอง /oauth/authorize."""
    redis_client.setex(
        f"authreq:{hub_state}",
        600,
        json.dumps(
            {
                "client_id": "cli_test",
                "redirect_uri": "http://localhost:9999/cb",
                "state": "subsystem_state_abc",
                "code_challenge": "x" * 43,
                "subsystem_id": subsystem_id or str(uuid.uuid4()),
                "scope": ["email", "name"],
            }
        ),
    )


# ─── flow guard ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_start_without_authreq_returns_400(client):
    """ไม่มี authreq (เรียกนอก flow) → 400."""
    r = client.post(
        START,
        json={"hub_state": "nonexistent" + uuid.uuid4().hex, "email": "a@uni.ac.th"},
    )
    assert r.status_code == 400


@pytest.mark.smoke
def test_finish_without_authreq_returns_400(client):
    r = client.post(
        FINISH,
        json={
            "hub_state": "nonexistent" + uuid.uuid4().hex,
            "email": "a@uni.ac.th",
            "credential": {"rawId": "AAAA"},
        },
    )
    assert r.status_code == 400


# ─── input validation (SQLi / XSS / format) ─────────────────────────────────


@pytest.mark.smoke
@pytest.mark.parametrize(
    "bad", ["notanemail", "x' OR '1'='1", "<script>alert(1)</script>", "a b@x.com"]
)
def test_start_rejects_non_email(client, bad):
    """non-email → 422 (validate ก่อนแตะ Redis/DB)."""
    hs = "hs" + uuid.uuid4().hex
    _seed_authreq(hs)
    try:
        r = client.post(START, json={"hub_state": hs, "email": bad})
        assert r.status_code == 422
    finally:
        redis_client.delete(f"authreq:{hs}")


@pytest.mark.smoke
def test_start_short_hub_state_returns_422(client):
    """hub_state สั้นเกิน (< 8) → 422."""
    r = client.post(START, json={"hub_state": "abc", "email": "a@uni.ac.th"})
    assert r.status_code == 422


# ─── anti-enumeration ───────────────────────────────────────────────────────


@pytest.mark.smoke
def test_start_valid_flow_returns_options(client):
    """authreq มี + email format ถูก → 200 + assertion options (แม้ไม่มี Passkey)."""
    hs = "hs" + uuid.uuid4().hex
    _seed_authreq(hs)
    try:
        r = client.post(
            START,
            json={"hub_state": hs, "email": f"ghost-{uuid.uuid4().hex[:6]}@uni.ac.th"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "challenge" in body
        assert body["userVerification"] == "required"
    finally:
        redis_client.delete(f"authreq:{hs}")


# ─── finish guards ──────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_finish_missing_credential_returns_422(client):
    hs = "hs" + uuid.uuid4().hex
    _seed_authreq(hs)
    try:
        r = client.post(FINISH, json={"hub_state": hs, "email": "a@uni.ac.th"})
        assert r.status_code == 422
    finally:
        redis_client.delete(f"authreq:{hs}")


@pytest.mark.smoke
def test_finish_no_challenge_returns_400(client):
    """authreq มี แต่ไม่มี passkey challenge (ไม่ได้เรียก start) → 400."""
    hs = "hs" + uuid.uuid4().hex
    _seed_authreq(hs)
    # เคลียร์ challenge เผื่อค้าง
    email = f"x-{uuid.uuid4().hex[:6]}@uni.ac.th"
    redis_client.delete(f"passkey:auth:challenge:email:{email}")
    try:
        r = client.post(
            FINISH,
            json={"hub_state": hs, "email": email, "credential": {"rawId": "AAAA"}},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "challenge_expired_or_missing"
    finally:
        redis_client.delete(f"authreq:{hs}")


# ─── refactor integrity ─────────────────────────────────────────────────────


@pytest.mark.smoke
def test_finalizer_helper_exists_and_signature():
    """_finalize_subsystem_login ถูก extract แล้ว + เป็น async + รับ params ถูก."""
    import inspect

    from app.routers.oauth import _finalize_subsystem_login

    assert inspect.iscoroutinefunction(_finalize_subsystem_login)
    params = set(inspect.signature(_finalize_subsystem_login).parameters)
    assert {"user", "authreq", "hub_state", "request", "db", "provider"} <= params


@pytest.mark.smoke
def test_oauth_callback_still_imports():
    """Google callback ยัง import ได้หลัง refactor (ไม่ break flow เดิม)."""
    from app.routers.oauth import oauth_callback

    assert oauth_callback is not None


# ─── E: Passkey enrollment interstitial (subsystem users incl. students) ─────

ENROLL_START = "/oauth/passkey/enroll/start"
ENROLL_FINISH = "/oauth/passkey/enroll/finish"
CONTINUE = "/oauth/continue"


def _seed_enroll(hub_state: str, user_id: str, email: str = "x@uni.ac.th") -> None:
    redis_client.setex(
        f"enroll:{hub_state}",
        600,
        json.dumps({"user_id": user_id, "email": email}),
    )


@pytest.mark.smoke
def test_enroll_start_without_context_returns_400(client):
    """ไม่มี enroll context → 400 (กันเรียกนอก flow)."""
    r = client.post(ENROLL_START, json={"hub_state": "noenroll" + uuid.uuid4().hex})
    assert r.status_code == 400


@pytest.mark.smoke
def test_enroll_finish_without_context_returns_400(client):
    r = client.post(
        ENROLL_FINISH,
        json={
            "hub_state": "noenroll" + uuid.uuid4().hex,
            "device_name": "Test",
            "credential": {"id": "x"},
        },
    )
    assert r.status_code == 400


@pytest.mark.smoke
def test_enroll_start_short_hub_state_returns_422(client):
    r = client.post(ENROLL_START, json={"hub_state": "abc"})
    assert r.status_code == 422


@pytest.mark.smoke
def test_enroll_finish_missing_device_name_returns_422(client):
    hs = "hs" + uuid.uuid4().hex
    r = client.post(ENROLL_FINISH, json={"hub_state": hs, "credential": {"id": "x"}})
    assert r.status_code == 422


@pytest.mark.smoke
def test_enroll_start_valid_context_returns_options(client, db):
    """enroll context ถูก → register options (สำหรับ user นั้น)."""
    from app.models import User

    u = User(
        email=f"enroll-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Enroll Tester",
        user_type="student",  # นักศึกษา — เข้า console ไม่ได้ แต่ enroll ผ่าน flow นี้ได้
        identifier=f"65{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    hs = "hs" + uuid.uuid4().hex
    _seed_enroll(hs, str(u.id), u.email)
    try:
        r = client.post(ENROLL_START, json={"hub_state": hs})
        assert r.status_code == 200
        body = r.json()
        assert "challenge" in body
        assert body["rp"]["id"] == "localhost"
        assert body["authenticatorSelection"]["userVerification"] == "required"
    finally:
        redis_client.delete(f"enroll:{hs}")
        db.delete(u)
        db.commit()


@pytest.mark.smoke
def test_continue_without_authreq_returns_400(client):
    r = client.get(CONTINUE, params={"hub_state": "noauthreq" + uuid.uuid4().hex})
    assert r.status_code == 400


@pytest.mark.smoke
def test_continue_without_enroll_context_returns_400(client):
    """มี authreq แต่ไม่มี enroll context → 400."""
    hs = "hs" + uuid.uuid4().hex
    _seed_authreq(hs)
    try:
        r = client.get(CONTINUE, params={"hub_state": hs}, follow_redirects=False)
        assert r.status_code == 400
    finally:
        redis_client.delete(f"authreq:{hs}")


@pytest.mark.smoke
def test_enroll_endpoints_registered():
    """enroll + continue endpoints มีจริงใน app."""
    from app.routers.oauth import (
        oauth_passkey_enroll_start,
        oauth_passkey_enroll_finish,
        oauth_continue,
    )

    assert all(
        x is not None
        for x in (
            oauth_passkey_enroll_start,
            oauth_passkey_enroll_finish,
            oauth_continue,
        )
    )


# ─── Origin allowlist regression (attestation_verify_failed bug) ─────────────


@pytest.mark.smoke
def test_webauthn_origins_include_hub_served_origin():
    """หน้า chooser + enroll เสิร์ฟจาก Hub (localhost:8000) → WebAuthn ceremony
    รันที่ origin นั้น. ถ้า allowlist ไม่มี → attestation/assertion verify fail.

    Regression guard: บั๊ก 2026-06-11 'attestation_verify_failed' เกิดเพราะ
    origins มีแค่ localhost:3000 (Next.js console) ไม่มี localhost:8000.
    """
    from app.services.webauthn_service import _origins

    origins = _origins()
    # console (Next.js) — register ที่ /account/security
    assert "http://localhost:3000" in origins
    # Hub-served pages — subsystem chooser login + enroll interstitial
    assert "http://localhost:8000" in origins, (
        "ต้องมี localhost:8000 — หน้า chooser/enroll เสิร์ฟจาก Hub ที่ port นี้ "
        "(ไม่งั้น attestation_verify_failed)"
    )
