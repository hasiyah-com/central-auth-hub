"""Unit tests — Step-up trusted-session cache (Phase 0, plan v3 Improvement #2)."""

import time
import uuid

import pytest

from app.services import stepup_cache


@pytest.fixture
def user_jti():
    """Random user_id + jti per test — avoid Redis key collision."""
    return str(uuid.uuid4()), str(uuid.uuid4())


@pytest.mark.smoke
def test_set_and_check_returns_payload(user_jti):
    """set_granted() → check_cached() คืน dict ที่มี granted_at + method + ip."""
    uid, jti = user_jti
    stepup_cache.set_granted(uid, jti, method="passkey", ip="1.2.3.4")
    cached = stepup_cache.check_cached(uid, jti)
    assert cached is not None
    assert cached["method"] == "passkey"
    assert cached["ip"] == "1.2.3.4"
    assert "granted_at" in cached
    stepup_cache.clear(uid, jti)


@pytest.mark.smoke
def test_check_returns_none_when_no_grant(user_jti):
    """ไม่เคย set → check_cached() คืน None."""
    uid, jti = user_jti
    assert stepup_cache.check_cached(uid, jti) is None


@pytest.mark.smoke
def test_clear_removes_grant(user_jti):
    """clear() ลบ key → check_cached() คืน None."""
    uid, jti = user_jti
    stepup_cache.set_granted(uid, jti, method="otp")
    assert stepup_cache.check_cached(uid, jti) is not None
    stepup_cache.clear(uid, jti)
    assert stepup_cache.check_cached(uid, jti) is None


@pytest.mark.smoke
def test_ttl_expires_grant(user_jti):
    """TTL หมด → grant หาย."""
    uid, jti = user_jti
    stepup_cache.set_granted(uid, jti, method="passkey", ttl_sec=1)
    assert stepup_cache.check_cached(uid, jti) is not None
    time.sleep(1.2)
    assert stepup_cache.check_cached(uid, jti) is None


@pytest.mark.smoke
def test_clear_all_for_user_removes_multiple(user_jti):
    """clear_all_for_user() ลบทุก jti ของ user เดียวกัน."""
    uid, _ = user_jti
    jtis = [str(uuid.uuid4()) for _ in range(3)]
    for jti in jtis:
        stepup_cache.set_granted(uid, jti, method="passkey")
    deleted = stepup_cache.clear_all_for_user(uid)
    assert deleted == 3
    for jti in jtis:
        assert stepup_cache.check_cached(uid, jti) is None


@pytest.mark.smoke
def test_empty_args_return_none_or_skip(user_jti):
    """Edge: empty user_id/jti ต้องไม่ crash."""
    assert stepup_cache.check_cached("", "x") is None
    assert stepup_cache.check_cached("x", "") is None
    stepup_cache.set_granted("", "x", method="passkey")  # no-op, no exception
    stepup_cache.clear("", "")  # no-op
