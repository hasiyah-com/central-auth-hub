from types import SimpleNamespace

from app.routers.passkey import _risk_email_otp_allowed, _risk_stepup_html


def render(**methods):
    return _risk_stepup_html(
        challenge_id="challenge_123456",
        user_email="user@example.com",
        risk_score=0.7,
        reasons=[],
        nonce="nonce",
        **methods,
    )


def test_email_otp_is_rendered_as_last_resort():
    html = render(has_passkey=False, has_totp=False, allow_email_otp=True)
    assert "Email OTP · ทางเลือกสุดท้าย" in html
    assert "/auth/passkey/risk-stepup/otp/start" in html
    assert "/auth/passkey/risk-stepup/otp/verify" in html
    assert 'const INITIAL_FACTOR = "email_otp"' in html


def test_email_otp_is_not_rendered_with_a_strong_factor():
    html = render(has_passkey=True, has_totp=False, allow_email_otp=False)
    assert "Email OTP · ทางเลือกสุดท้าย" not in html
    assert 'id="sendEmailOtp"' not in html


def test_policy_allows_email_only_when_no_usable_strong_factor(monkeypatch):
    user = SimpleNamespace(id="user-1")
    monkeypatch.setattr("app.routers.passkey.get_auth_policy", lambda _db: {"passkey": False})
    monkeypatch.setattr("app.routers.passkey.webauthn_service.count_active", lambda *_: 1)
    monkeypatch.setattr("app.routers.passkey.totp_service.is_enabled", lambda *_: False)
    assert _risk_email_otp_allowed(user, object()) is True
    monkeypatch.setattr("app.routers.passkey.totp_service.is_enabled", lambda *_: True)
    assert _risk_email_otp_allowed(user, object()) is False
    monkeypatch.setattr("app.routers.passkey.get_auth_policy", lambda _db: {"passkey": True})
    monkeypatch.setattr("app.routers.passkey.totp_service.is_enabled", lambda *_: False)
    assert _risk_email_otp_allowed(user, object()) is False
