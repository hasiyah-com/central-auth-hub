"""Risk-Triggered Passkey Flow tests (Week 9-10).

ทดสอบ wiring ของ:
  - risk_challenge service (mint/peek/consume/replay/expire)
  - webauthn_service.in_grace_period (grace period logic)
  - /auth/passkey/risk-stepup endpoints (Re-Auth path guards)
  - /auth/passkey/force-enroll endpoints (Force Enroll path guards + OTP gate)
  - config thresholds (0.85 hard block, 7-day grace)

ไม่ครอบคลุม full WebAuthn ceremony — ใช้ test_passkey_ceremony.py แยก.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.config import settings
from app.models import User
from app.services import risk_challenge, webauthn_service
from app.services.mfa_service import generate_otp, hash_otp, verify_otp


# ─── Config — confirm settings loaded ─────────────────────────────────────


def test_config_risk_block_hard_threshold_is_085():
    assert settings.risk_block_hard_threshold == 0.85


def test_config_grace_period_is_7_days():
    assert settings.passkey_grace_period_days == 7


def test_config_risk_challenge_ttl_is_5min():
    assert settings.risk_challenge_ttl_sec == 300


# ─── risk_challenge service ───────────────────────────────────────────────


def _mint_helper(user_id="u-test", kind="reauth", flow="subsystem"):
    return risk_challenge.mint(
        user_id=user_id,
        hub_state="hs_xyz",
        authreq={"client_id": "cli_x", "subsystem_id": "sub_x"},
        risk_score=0.72,
        risk_breakdown={"rule": 0.3, "iforest": 0.2},
        risk_reasons=["is_new_device"],
        provider="google",
        kind=kind,
        flow=flow,
    )


def test_risk_challenge_mint_returns_urlsafe_token():
    cid = _mint_helper()
    assert isinstance(cid, str) and len(cid) >= 32


def test_risk_challenge_peek_returns_payload_without_consuming():
    cid = _mint_helper(user_id="u-peek")
    p1 = risk_challenge.peek(cid)
    p2 = risk_challenge.peek(cid)
    assert p1 is not None and p2 is not None
    assert p1["user_id"] == "u-peek"
    assert p1["kind"] == "reauth"


def test_risk_challenge_consume_returns_payload_once():
    cid = _mint_helper(user_id="u-consume")
    consumed = risk_challenge.consume(cid)
    assert consumed is not None
    assert consumed["user_id"] == "u-consume"


def test_risk_challenge_replay_after_consume_returns_none():
    """B9 pattern — atomic getdel กัน replay."""
    cid = _mint_helper(user_id="u-replay")
    risk_challenge.consume(cid)
    assert risk_challenge.consume(cid) is None
    assert risk_challenge.peek(cid) is None


def test_risk_challenge_consume_unknown_id_returns_none():
    assert risk_challenge.consume("does_not_exist_xyz") is None


def test_risk_challenge_peek_unknown_id_returns_none():
    assert risk_challenge.peek("does_not_exist_xyz") is None


def test_risk_challenge_payload_contains_required_fields():
    cid = _mint_helper(user_id="u-fields")
    p = risk_challenge.peek(cid)
    assert set(p.keys()) >= {
        "user_id",
        "hub_state",
        "authreq",
        "risk_score",
        "risk_breakdown",
        "risk_reasons",
        "provider",
        "kind",
        "flow",
        "minted_at",
    }


# ─── webauthn_service.in_grace_period ──────────────────────────────────────


def test_in_grace_period_new_user_no_passkey_true(db, monkeypatch):
    """User created < 7d + no passkey → grace = True."""
    u = User(
        email="grace-new@uni.ac.th",
        google_sub="grace-new-sub",
        full_name="Grace New",
        user_type="student",
        identifier="GR001",
        status="active",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2),
    )
    db.add(u)
    db.flush()
    try:
        # ไม่มี passkey (default) → True
        assert webauthn_service.in_grace_period(u, db) is True
        # adoption_status คืน in_grace_period flag + grace_days_remaining
        st = webauthn_service.adoption_status(u, db)
        assert st["in_grace_period"] is True
        assert st["grace_days_remaining"] == 5  # 7 - 2
        assert st["days_since_signup"] == 2
    finally:
        db.delete(u)
        db.flush()


def test_in_grace_period_old_user_no_passkey_false(db):
    """User created > 7d + no passkey → grace = False (ต้อง force enroll)."""
    u = User(
        email="grace-old@uni.ac.th",
        google_sub="grace-old-sub",
        full_name="Grace Old",
        user_type="student",
        identifier="GR002",
        status="active",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30),
    )
    db.add(u)
    db.flush()
    try:
        assert webauthn_service.in_grace_period(u, db) is False
        st = webauthn_service.adoption_status(u, db)
        assert st["in_grace_period"] is False
        assert st["grace_days_remaining"] == 0
    finally:
        db.delete(u)
        db.flush()


# ─── Risk Re-Auth endpoint guards ──────────────────────────────────────────


def test_risk_stepup_page_missing_challenge_returns_410(client):
    r = client.get("/auth/passkey/risk-stepup", params={"challenge": "does_not_exist"})
    assert r.status_code == 410


def test_risk_stepup_start_wrong_kind_returns_400(client, student_user):
    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.6,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="enroll",  # WRONG — risk-stepup ต้องเป็น reauth
        flow="hub_direct",
    )
    r = client.post("/auth/passkey/risk-stepup/start", json={"challenge_id": cid})
    assert r.status_code == 400
    risk_challenge.consume(cid)  # cleanup


def test_risk_stepup_verify_wrong_kind_returns_400(client, student_user):
    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.6,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="enroll",
        flow="hub_direct",
    )
    r = client.post(
        "/auth/passkey/risk-stepup/verify",
        json={"challenge_id": cid, "credential": {}},
    )
    assert r.status_code == 400
    risk_challenge.consume(cid)


def test_risk_stepup_page_renders_reasons_and_score(client, student_user):
    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.731,
        risk_breakdown={"rule": 0.4},
        risk_reasons=["is_new_country", "off_hours"],
        provider="hub_direct",
        kind="reauth",
        flow="hub_direct",
    )
    try:
        r = client.get("/auth/passkey/risk-stepup", params={"challenge": cid})
        assert r.status_code == 200
        assert "is_new_country" in r.text
        assert "off_hours" in r.text
        assert "0.731" in r.text
        assert "ยืนยันตัวตน" in r.text
        # browser-unsupported message ฝังในหน้า
        assert "เบราว์เซอร์นี้ไม่รองรับ Passkey" in r.text
        assert "Account Recovery" in r.text
    finally:
        risk_challenge.consume(cid)


# ─── Force Enrollment endpoint guards ──────────────────────────────────────


def test_force_enroll_page_wrong_kind_returns_400(client, student_user):
    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.6,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="reauth",  # WRONG — force-enroll ต้องเป็น enroll
        flow="hub_direct",
    )
    try:
        r = client.get("/auth/passkey/force-enroll", params={"challenge": cid})
        assert r.status_code == 400
    finally:
        risk_challenge.consume(cid)


def test_force_enroll_register_start_requires_otp_passed(client, student_user):
    """B45 — Force Enrollment ต้องผ่าน OTP ก่อน register/start (กัน attacker enroll).

    เรียก /register/start โดยไม่ส่ง OTP ก่อน → 403.
    """
    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.78,
        risk_breakdown={},
        risk_reasons=["new_country"],
        provider="hub_direct",
        kind="enroll",
        flow="hub_direct",
    )
    try:
        r = client.post(
            "/auth/passkey/force-enroll/register/start",
            json={"challenge_id": cid},
        )
        assert r.status_code == 403
        detail = r.json().get("detail")
        # detail อาจเป็น dict (rich) หรือ string — ครอบคลุมทั้งคู่
        assert "otp" in str(detail).lower()
    finally:
        risk_challenge.consume(cid)


def test_force_enroll_send_otp_creates_redis_hash(client, student_user, db):
    """ตรวจว่า send-otp endpoint สร้าง hash ใน Redis (ไม่ตรวจ email จริง)."""
    from app.redis_client import redis_client

    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.7,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="enroll",
        flow="hub_direct",
    )
    try:
        r = client.post(
            "/auth/passkey/force-enroll/send-otp",
            json={"challenge_id": cid},
        )
        assert r.status_code == 200
        assert r.json()["sent"] is True
        # Redis key ต้องมี hash
        h = redis_client.get(f"force_enroll_otp:{cid}")
        assert h is not None
        # ทำความสะอาด
        redis_client.delete(f"force_enroll_otp:{cid}")
    finally:
        risk_challenge.consume(cid)


def test_force_enroll_verify_otp_wrong_returns_401(client, student_user):
    """OTP ผิด → 401."""
    from app.redis_client import redis_client

    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.7,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="enroll",
        flow="hub_direct",
    )
    try:
        # ตั้ง OTP hash จริงเป็น "111111"
        redis_client.setex(f"force_enroll_otp:{cid}", 300, hash_otp("111111"))
        # ส่ง OTP ผิด
        r = client.post(
            "/auth/passkey/force-enroll/verify-otp",
            json={"challenge_id": cid, "otp": "999999"},
        )
        assert r.status_code == 401
        # passed flag ไม่ควรถูก set
        assert redis_client.get(f"force_enroll_otp_passed:{cid}") is None
        redis_client.delete(f"force_enroll_otp:{cid}")
    finally:
        risk_challenge.consume(cid)


def test_force_enroll_verify_otp_correct_sets_passed_flag(client, student_user):
    """OTP ถูก → passed flag ถูก set + OTP hash ถูกลบ."""
    from app.redis_client import redis_client

    cid = risk_challenge.mint(
        user_id=str(student_user.id),
        hub_state="",
        authreq=None,
        risk_score=0.7,
        risk_breakdown={},
        risk_reasons=[],
        provider="hub_direct",
        kind="enroll",
        flow="hub_direct",
    )
    correct_otp = "222222"
    try:
        redis_client.setex(f"force_enroll_otp:{cid}", 300, hash_otp(correct_otp))
        r = client.post(
            "/auth/passkey/force-enroll/verify-otp",
            json={"challenge_id": cid, "otp": correct_otp},
        )
        assert r.status_code == 200
        assert r.json()["verified"] is True
        # passed flag set + OTP hash ถูกลบ
        assert redis_client.get(f"force_enroll_otp_passed:{cid}") is not None
        assert redis_client.get(f"force_enroll_otp:{cid}") is None
        redis_client.delete(f"force_enroll_otp_passed:{cid}")
    finally:
        risk_challenge.consume(cid)


# ─── MFA OTP service still functional (regression check) ───────────────────


def test_mfa_otp_service_hash_verify_roundtrip():
    """ตรวจว่า OTP service ยังใช้งานได้ (force-enroll reuse pattern เดียวกัน)."""
    otp = generate_otp()
    assert len(otp) == 6 and otp.isdigit()
    h = hash_otp(otp)
    assert verify_otp(h, otp) is True
    assert verify_otp(h, "000000") is False
