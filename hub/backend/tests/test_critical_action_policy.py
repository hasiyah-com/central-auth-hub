"""Unit tests — Critical Action Policy gate (Phase 0, plan v3 Improvement #8)."""

import uuid

import pytest

from app.services import critical_action_policy as cap
from app.services import stepup_cache


@pytest.mark.smoke
def test_critical_actions_set_complete():
    """7 core actions (plan §6.3) ต้องอยู่ครบใน CRITICAL_ACTIONS.

    ใช้ subset check (ไม่ใช่ == เป๊ะ) — set ขยายได้ (risk-challenge เพิ่ม
    create_user/subsystem_*/whitelist_*/session_revoke ฯลฯ) โดยไม่ทำ test พัง
    ตราบใดที่ 7 core ยังอยู่.
    """
    core = {
        "delete_passkey",
        "register_new_passkey",
        "regenerate_backup_codes",
        "rotate_oauth_secret",
        "promote_to_admin",
        "bulk_permission_change",
        "admin_reset",
    }
    assert (
        core <= cap.CRITICAL_ACTIONS
    ), f"core actions หาย: {core - cap.CRITICAL_ACTIONS}"


@pytest.mark.smoke
def test_is_critical_recognizes_listed_actions():
    assert cap.is_critical("delete_passkey") is True
    assert cap.is_critical("promote_to_admin") is True
    assert cap.is_critical("view_dashboard") is False
    assert cap.is_critical("") is False


@pytest.mark.smoke
def test_gate_factory_returns_callable():
    """gate(action) → callable dependency function."""
    dep = cap.gate("delete_passkey")
    assert callable(dep)
    assert dep.__name__ == "gate_delete_passkey"


@pytest.mark.smoke
def test_gate_warns_on_unknown_action(caplog):
    """gate() ด้วย action ที่ไม่อยู่ใน list → log warning (typo guard)."""
    import logging

    with caplog.at_level(logging.WARNING):
        cap.gate("delete_passkey_typo")
    assert any("CRITICAL_ACTIONS" in r.message for r in caplog.records)


@pytest.mark.smoke
def test_stepup_cache_integration():
    """Gate logic — ใช้ stepup_cache.check_cached() จริง.

    Test ไม่ผ่าน FastAPI request (จะมี integration test แยกใน Phase 5)
    แค่ verify ว่า import + helper ทำงานได้
    """
    uid = str(uuid.uuid4())
    jti = str(uuid.uuid4())

    # ก่อน set → cache miss
    assert stepup_cache.check_cached(uid, jti) is None

    # set → cache hit
    stepup_cache.set_granted(uid, jti, method="passkey", ip="1.2.3.4")
    cached = stepup_cache.check_cached(uid, jti)
    assert cached is not None
    assert cached["method"] == "passkey"

    # cleanup
    stepup_cache.clear(uid, jti)


@pytest.mark.smoke
def test_jti_extraction_helper_safe_on_garbage():
    """_extract_jti(None) → None (ไม่ raise)"""
    assert cap._extract_jti(None) is None


@pytest.mark.smoke
def test_passkey_settings_loaded():
    """Phase 0.1 verify — config มี webauthn_* + stepup_*"""
    from app.config import settings

    assert settings.webauthn_rp_id == "localhost"  # Q1 decision
    assert settings.webauthn_max_passkeys_per_user == 10  # Improvement #9 adjusted
    assert settings.stepup_cache_ttl_sec == 900  # Q7 decision (15 นาที)
    assert settings.stepup_counter_regression_risk_boost == 0.2  # Improvement #10
