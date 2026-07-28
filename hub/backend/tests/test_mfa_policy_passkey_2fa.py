"""Tests — Always-2FA นับตามความแข็งแรงของ factor (passkey = ผ่าน 2FA ในตัว).

บริบท: admin ตั้ง Always-2FA (effective_mfa_always) แต่ login ด้วย passkey ไม่เด้ง
step-up ซ้ำ — เป็น **ดีไซน์โดยตั้งใจ** ไม่ใช่บั๊ก: passkey (WebAuthn + user verification)
เป็น strong factor MFA-grade ในตัวเดียว (NIST SP 800-63B AAL2+). Google OAuth เดี่ยว =
primary อ่อน → ต้อง step-up. test นี้ล็อกกฎไว้กัน "แก้ผิด" ทีหลัง.

รัน: docker compose exec hub-backend pytest tests/test_mfa_policy_passkey_2fa.py -v
"""

from __future__ import annotations

from app.services import mfa_policy


# ── login_method_satisfies_2fa: passkey ผ่าน / federated ต้อง step-up ──


def test_passkey_login_satisfies_2fa():
    assert mfa_policy.login_method_satisfies_2fa("passkey") is True


def test_discoverable_passkey_login_satisfies_2fa():
    assert mfa_policy.login_method_satisfies_2fa("discoverable") is True


def test_google_login_does_not_satisfy_2fa():
    """Google = federated primary เดี่ยว → ต้อง step-up factor ที่สอง."""
    assert mfa_policy.login_method_satisfies_2fa("google") is False


def test_unknown_or_none_method_does_not_satisfy():
    assert mfa_policy.login_method_satisfies_2fa(None) is False
    assert mfa_policy.login_method_satisfies_2fa("totp") is False


def test_strong_methods_are_documented_constant():
    """STRONG_LOGIN_METHODS เป็น source of truth — ต้องมี passkey + discoverable."""
    assert "passkey" in mfa_policy.STRONG_LOGIN_METHODS
    assert "discoverable" in mfa_policy.STRONG_LOGIN_METHODS


# ── ความสัมพันธ์กับ is_second_factor_required (federated flow) ──


class _FakeUser:
    def __init__(self, effective_mfa_always: bool):
        self.effective_mfa_always = effective_mfa_always


def test_federated_gate_still_requires_2fa_for_always_user():
    """flow federated (Google): always-2FA user ยังต้อง step-up (helper แยกกันคนละจุด)."""
    admin = _FakeUser(effective_mfa_always=True)
    assert (
        mfa_policy.is_second_factor_required(
            admin, actual_decision="warn", enforcing=False, is_hard_block=False
        )
        is True
    )


def test_federated_gate_hard_block_wins():
    admin = _FakeUser(effective_mfa_always=True)
    assert (
        mfa_policy.is_second_factor_required(
            admin, actual_decision="block", enforcing=True, is_hard_block=True
        )
        is False
    )
