"""Tests — Always-2FA (user choice) + admin-forced + TOTP at risk-stepup + account security API.

แผน: plan/always-2fa-user-choice.md
ครอบ:
  - mfa_policy.is_second_factor_required — รวม risk-based + Always-2FA เป็น gate เดียว
  - mfa_policy.has_second_factor — passkey OR TOTP (เลือกทาง risk-stepup vs force-enroll)
  - User.effective_mfa_always — admin บังคับ
  - POST /auth/passkey/risk-stepup/verify-totp — ยืนยันด้วย TOTP ที่ด่าน risk
  - Account security API (status / PATCH / dismiss-onboarding) + admin ปิดไม่ได้
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pyotp
import pytest

from app.models import AuditLog, PasskeyCredential, User, UserTotpCredential
from app.services import mfa_policy, risk_challenge, totp_service
from app.services.jwt_service import create_access_token


def _mk_user(db, *, admin=False, mfa_always=False) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"a2f_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"A2F {s}",
        user_type="admin" if admin else "teacher",
        status="active",
        is_hub_admin=admin,
        mfa_always=mfa_always,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _purge(db, uid):
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
def temp_user(db):
    u = _mk_user(db)
    uid = u.id
    yield u
    _purge(db, uid)


def _enable_totp(db, user) -> str:
    secret, _ = totp_service.start_enroll(user.id, db)
    totp_service.confirm_enroll(user.id, pyotp.TOTP(secret).now(), db)
    db.commit()
    return secret


# ── 1. is_second_factor_required — gate เดียว ────────────────────────────────


def test_always_on_user_required_even_low_risk(temp_user, db):
    temp_user.mfa_always = True
    db.commit()
    assert (
        mfa_policy.is_second_factor_required(
            temp_user, actual_decision="pass", enforcing=True, is_hard_block=False
        )
        is True
    )


def test_admin_required_even_without_opt_in(db):
    admin = _mk_user(db, admin=True, mfa_always=False)
    try:
        assert admin.effective_mfa_always is True
        assert (
            mfa_policy.is_second_factor_required(
                admin, actual_decision="pass", enforcing=True, is_hard_block=False
            )
            is True
        )
    finally:
        _purge(db, admin.id)


def test_normal_user_low_risk_not_required(temp_user):
    """Regression — non-admin, mfa_always=False, risk ต่ำ → ไม่ต้อง (flow เดิมไม่เปลี่ยน)."""
    assert (
        mfa_policy.is_second_factor_required(
            temp_user, actual_decision="pass", enforcing=True, is_hard_block=False
        )
        is False
    )


def test_always_on_works_in_shadow_mode(temp_user, db):
    """Always-2FA = user pref → ทำงานแม้ shadow (enforcing=False)."""
    temp_user.mfa_always = True
    db.commit()
    assert (
        mfa_policy.is_second_factor_required(
            temp_user, actual_decision="pass", enforcing=False, is_hard_block=False
        )
        is True
    )


def test_risk_mfa_still_works_for_normal_user(temp_user):
    """risk decision=challenge + enforce → required (ทางเดิม)."""
    assert (
        mfa_policy.is_second_factor_required(
            temp_user, actual_decision="challenge", enforcing=True, is_hard_block=False
        )
        is True
    )


def test_hard_block_returns_false(temp_user, db):
    """hard block ชนะ — ไม่ใช่ mfa (flow แยกจัดการ 403) แม้ always-on."""
    temp_user.mfa_always = True
    db.commit()
    assert (
        mfa_policy.is_second_factor_required(
            temp_user, actual_decision="block", enforcing=True, is_hard_block=True
        )
        is False
    )


# ── 2. has_second_factor — passkey OR TOTP ───────────────────────────────────


def test_has_second_factor_none(temp_user, db):
    assert mfa_policy.has_second_factor(temp_user, db) is False


def test_has_second_factor_totp_only(temp_user, db):
    _enable_totp(db, temp_user)
    assert mfa_policy.has_second_factor(temp_user, db) is True


def test_has_second_factor_passkey_only(temp_user, db):
    db.add(
        PasskeyCredential(
            user_id=temp_user.id,
            credential_id=uuid.uuid4().bytes + uuid.uuid4().bytes,
            public_key=b"\x00" * 32,
            sign_count=0,
            device_name="iPhone",
            status="ACTIVE",
        )
    )
    db.commit()
    assert mfa_policy.has_second_factor(temp_user, db) is True


# ── 3. TOTP ที่ด่าน risk-stepup ──────────────────────────────────────────────


def _mint_reauth(user):
    return risk_challenge.mint(
        user_id=str(user.id),
        hub_state="",
        authreq=None,
        risk_score=0.6,
        risk_breakdown={},
        risk_reasons=["always_2fa"],
        provider="hub_direct",
        kind="reauth",
        flow="hub_direct",
    )


def test_risk_stepup_verify_totp_success(client, temp_user, db):
    secret = _enable_totp(db, temp_user)
    cid = _mint_reauth(temp_user)
    try:
        r = client.post(
            "/auth/passkey/risk-stepup/verify-totp",
            json={"challenge_id": cid, "code": pyotp.TOTP(secret).now()},
        )
        assert r.status_code == 200
        assert "redirect_url" in r.json()
        # challenge ถูก consume แล้ว (replay ไม่ได้)
        assert risk_challenge.peek(cid) is None
    finally:
        risk_challenge.consume(cid)


def test_risk_stepup_verify_totp_wrong_code_opaque(client, temp_user, db):
    _enable_totp(db, temp_user)
    cid = _mint_reauth(temp_user)
    try:
        r = client.post(
            "/auth/passkey/risk-stepup/verify-totp",
            json={"challenge_id": cid, "code": "000001"},
        )
        assert r.status_code in (400, 401)
        # challenge ยังอยู่ (ไม่ consume ตอน fail)
        assert risk_challenge.peek(cid) is not None
    finally:
        risk_challenge.consume(cid)


def test_risk_stepup_verify_totp_replay_410(client, temp_user, db):
    secret = _enable_totp(db, temp_user)
    cid = _mint_reauth(temp_user)
    try:
        r1 = client.post(
            "/auth/passkey/risk-stepup/verify-totp",
            json={"challenge_id": cid, "code": pyotp.TOTP(secret).now()},
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/auth/passkey/risk-stepup/verify-totp",
            json={"challenge_id": cid, "code": pyotp.TOTP(secret).now()},
        )
        assert r2.status_code == 410
    finally:
        risk_challenge.consume(cid)


def test_risk_stepup_page_shows_totp_when_enabled(client, temp_user, db):
    _enable_totp(db, temp_user)
    cid = _mint_reauth(temp_user)
    try:
        r = client.get("/auth/passkey/risk-stepup", params={"challenge": cid})
        assert r.status_code == 200
        assert "verify-totp" in r.text  # TOTP section ฝังในหน้า
    finally:
        risk_challenge.consume(cid)


# ── 4. Account security API ──────────────────────────────────────────────────


def test_security_status_returns_flags(client, temp_user, auth_headers):
    token, _ = create_access_token(temp_user)
    r = client.get("/auth/account/security-status", headers=auth_headers(token))
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_always"] is False
    assert body["has_passkey"] is False
    assert body["has_totp"] is False
    assert body["is_admin"] is False
    assert body["effective_mfa_always"] is False


def test_patch_security_enables_always(client, temp_user, auth_headers, db):
    token, _ = create_access_token(temp_user)
    r = client.patch(
        "/auth/account/security",
        headers=auth_headers(token),
        json={"mfa_always": True, "mfa_preferred_factor": "totp"},
    )
    assert r.status_code == 200
    db.expire_all()
    u = db.query(User).filter(User.id == temp_user.id).first()
    assert u.mfa_always is True and u.mfa_preferred_factor == "totp"


def test_admin_cannot_disable_always(client, db, auth_headers):
    admin = _mk_user(db, admin=True, mfa_always=True)
    try:
        token, _ = create_access_token(admin)
        client.patch(
            "/auth/account/security",
            headers=auth_headers(token),
            json={"mfa_always": False},
        )
        # ปฏิเสธ หรือ ignore — แต่ค่าต้องยังเป็น True (effective บังคับ)
        db.expire_all()
        u = db.query(User).filter(User.id == admin.id).first()
        assert u.effective_mfa_always is True
    finally:
        _purge(db, admin.id)


# ── 5. should_prompt_setup — เตือน / ข้าม 7 วัน / ไม่ถามอีก ─────────────────


def test_should_prompt_when_no_factor(temp_user, db):
    assert mfa_policy.should_prompt_setup(temp_user, db) is True


def test_should_not_prompt_when_has_factor(temp_user, db):
    _enable_totp(db, temp_user)
    assert mfa_policy.should_prompt_setup(temp_user, db) is False


def test_should_not_prompt_when_dismissed(temp_user, db):
    temp_user.security_onboarding_dismissed = True
    db.commit()
    assert mfa_policy.should_prompt_setup(temp_user, db) is False


def test_snooze_suppresses_then_reminds_again(temp_user, db):
    """กด 'ข้าม' → เงียบ 7 วัน → พ้นกำหนดกลับมาเตือนใหม่ (ไม่บล็อก ไม่หายถาวร)."""
    mfa_policy.snooze_onboarding(temp_user)
    db.commit()
    assert mfa_policy.should_prompt_setup(temp_user, db) is False
    # ย้อนเวลา snooze ให้หมดอายุ → กลับมาเตือน
    temp_user.security_onboarding_snoozed_until = datetime.utcnow() - timedelta(
        minutes=1
    )
    db.commit()
    assert mfa_policy.should_prompt_setup(temp_user, db) is True


def test_snooze_default_is_seven_days(temp_user, db):
    before = datetime.utcnow()
    mfa_policy.snooze_onboarding(temp_user)
    db.commit()  # อย่าทิ้ง pending change ค้าง session (teardown purge จะชน)
    delta = temp_user.security_onboarding_snoozed_until - before
    assert 6.9 < delta.total_seconds() / 86400 < 7.1


def test_skip_endpoint_sets_snooze(client, temp_user, auth_headers, db):
    token, _ = create_access_token(temp_user)
    r = client.post(
        "/auth/account/security/snooze-onboarding", headers=auth_headers(token)
    )
    assert r.status_code == 200
    db.expire_all()
    u = db.query(User).filter(User.id == temp_user.id).first()
    assert u.security_onboarding_snoozed_until is not None
    assert mfa_policy.should_prompt_setup(u, db) is False


# ── 6. OAuth interstitial — TOTP enroll ด้วย hub_state (ไม่มี JWT / นักศึกษาใช้ได้) ──


def _seed_enroll_ctx(user) -> str:
    """จำลอง enroll context ที่ oauth callback สร้างหลัง Google identify."""
    import json as _json

    from app.redis_client import redis_client

    state = "hs_" + uuid.uuid4().hex
    redis_client.setex(
        f"enroll:{state}",
        600,
        _json.dumps({"user_id": str(user.id), "email": user.email}),
    )
    return state


def test_interstitial_totp_enroll_start_returns_qr(client, temp_user):
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        r = client.post("/oauth/totp/enroll/start", json={"hub_state": state})
        assert r.status_code == 200
        body = r.json()
        assert body["secret"] and body["otpauth_uri"].startswith("otpauth://")
        assert body["qr_svg"].startswith("<svg")  # render ฝั่ง server (CSP-safe)
    finally:
        redis_client.delete(f"enroll:{state}")


def test_interstitial_totp_enroll_verify_activates(client, temp_user, db):
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        secret = client.post(
            "/oauth/totp/enroll/start", json={"hub_state": state}
        ).json()["secret"]
        r = client.post(
            "/oauth/totp/enroll/verify",
            json={"hub_state": state, "code": pyotp.TOTP(secret).now()},
        )
        assert r.status_code == 200 and r.json()["enabled"] is True
        db.expire_all()
        assert totp_service.is_enabled(temp_user.id, db) is True
    finally:
        redis_client.delete(f"enroll:{state}")


def test_interstitial_totp_wrong_code_400(client, temp_user):
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        client.post("/oauth/totp/enroll/start", json={"hub_state": state})
        r = client.post(
            "/oauth/totp/enroll/verify", json={"hub_state": state, "code": "000001"}
        )
        assert r.status_code == 400
    finally:
        redis_client.delete(f"enroll:{state}")


def test_interstitial_totp_expired_state_400(client):
    r = client.post("/oauth/totp/enroll/start", json={"hub_state": "hs_does_not_exist"})
    assert r.status_code == 400


def test_interstitial_checkbox_enables_always_2fa(client, temp_user, db):
    """ติ๊ก 'ขอยืนยันทุกครั้ง' ในหน้า enroll → เปิด mfa_always.

    ทางเดียวที่ **นักศึกษา** ตั้ง Always-2FA ได้ (เข้า /account ไม่ได้)
    """
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        assert temp_user.mfa_always is False
        secret = client.post(
            "/oauth/totp/enroll/start", json={"hub_state": state}
        ).json()["secret"]
        r = client.post(
            "/oauth/totp/enroll/verify",
            json={
                "hub_state": state,
                "code": pyotp.TOTP(secret).now(),
                "mfa_always": True,
            },
        )
        assert r.status_code == 200
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.mfa_always is True
    finally:
        redis_client.delete(f"enroll:{state}")


def test_interstitial_unchecked_leaves_always_off(client, temp_user, db):
    """ไม่ติ๊ก → ไม่เปิด (opt-in เท่านั้น)."""
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        secret = client.post(
            "/oauth/totp/enroll/start", json={"hub_state": state}
        ).json()["secret"]
        r = client.post(
            "/oauth/totp/enroll/verify",
            json={"hub_state": state, "code": pyotp.TOTP(secret).now()},
        )
        assert r.status_code == 200
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.mfa_always is False
    finally:
        redis_client.delete(f"enroll:{state}")


def test_enable_always_without_reenrolling(client, temp_user, db):
    """มี factor อยู่แล้ว → เปิด Always-2FA ได้เลย ไม่ต้องเพิ่ม passkey/TOTP ซ้ำ."""
    from app.redis_client import redis_client

    _enable_totp(db, temp_user)  # มี factor แล้ว
    state = _seed_enroll_ctx(temp_user)
    try:
        r = client.post("/oauth/security/always-2fa", json={"hub_state": state})
        assert r.status_code == 200 and r.json()["mfa_always"] is True
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.mfa_always is True
    finally:
        redis_client.delete(f"enroll:{state}")


def test_enable_always_rejected_without_factor(client, temp_user, db):
    """ไม่มี factor เลย → เปิด Always-2FA ไม่ได้ (ไม่งั้นล็อกตัวเองออกจากระบบ)."""
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        r = client.post("/oauth/security/always-2fa", json={"hub_state": state})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "no_factor"
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.mfa_always is False
    finally:
        redis_client.delete(f"enroll:{state}")


def test_interstitial_cannot_disable_always(client, temp_user, db):
    """หน้า enroll เปิดได้อย่างเดียว — ปิดไม่ได้ (กัน attacker ยึด enroll context
    ไปปลดการป้องกันของเหยื่อ; การปิดต้องทำที่ /account ผ่าน step-up)."""
    from app.redis_client import redis_client

    temp_user.mfa_always = True
    db.commit()
    state = _seed_enroll_ctx(temp_user)
    try:
        secret = client.post(
            "/oauth/totp/enroll/start", json={"hub_state": state}
        ).json()["secret"]
        client.post(
            "/oauth/totp/enroll/verify",
            json={
                "hub_state": state,
                "code": pyotp.TOTP(secret).now(),
                "mfa_always": False,  # พยายามปิด
            },
        )
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.mfa_always is True, "ต้องยังเปิดอยู่ — ปิดผ่านหน้านี้ไม่ได้"
    finally:
        redis_client.delete(f"enroll:{state}")


# ── 7. Standalone setup (ปุ่ม "เพิ่มการยืนยันตัวตน") — ไม่มี authreq ────────


def test_continue_standalone_shows_done_page(client, temp_user, db):
    """ไม่มี authreq (ไม่ได้มาจาก subsystem) → หน้าสรุป ไม่ใช่ 400/redirect."""
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    _enable_totp(db, temp_user)
    try:
        r = client.get(
            "/oauth/continue", params={"hub_state": state}, follow_redirects=False
        )
        assert r.status_code == 200
        assert "ตั้งค่าเรียบร้อย" in r.text
    finally:
        redis_client.delete(f"enroll:{state}")


def test_continue_standalone_skip_sets_snooze(client, temp_user, db):
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        r = client.get(
            "/oauth/continue",
            params={"hub_state": state, "action": "skip"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.security_onboarding_snoozed_until is not None
        assert mfa_policy.should_prompt_setup(u, db) is False
    finally:
        redis_client.delete(f"enroll:{state}")


def test_continue_standalone_never_dismisses(client, temp_user, db):
    from app.redis_client import redis_client

    state = _seed_enroll_ctx(temp_user)
    try:
        r = client.get(
            "/oauth/continue",
            params={"hub_state": state, "action": "never"},
            follow_redirects=False,
        )
        assert r.status_code == 200
        db.expire_all()
        u = db.query(User).filter(User.id == temp_user.id).first()
        assert u.security_onboarding_dismissed is True
        assert mfa_policy.should_prompt_setup(u, db) is False
    finally:
        redis_client.delete(f"enroll:{state}")


def test_credentials_setup_start_redirects_to_google(client):
    """ปุ่ม 'เพิ่มการยืนยันตัวตน' → redirect ไป Google (reuse redirect URI เดิม)."""
    r = client.get("/auth/credentials/setup", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers.get("location", "")


def test_dismiss_onboarding_sets_flag(client, temp_user, auth_headers, db):
    token, _ = create_access_token(temp_user)
    r = client.post(
        "/auth/account/security/dismiss-onboarding", headers=auth_headers(token)
    )
    assert r.status_code == 200
    db.expire_all()
    u = db.query(User).filter(User.id == temp_user.id).first()
    assert u.security_onboarding_dismissed is True
