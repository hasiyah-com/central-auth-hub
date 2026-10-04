from datetime import datetime
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services.auth_failures import consecutive_counts
from app.services import auth_retry

def events(*items):
    return [(action, data, datetime(2026, 10, 4)) for action, data in items]

def test_success_resets_only_factor_used():
    counts = consecutive_counts(events(
        ('stepup_totp_failed', {}), ('passkey_stepup_failed', {}),
        ('stepup_totp_success', {})))
    assert counts == {'totp': 0, 'passkey': 1}

def test_expired_and_cancelled_are_not_wrong_credentials():
    counts = consecutive_counts(events(
        ('risk_mfa_verify_failed', {'method': 'passkey', 'code': 'timeout'}),
        ('risk_mfa_verify_failed', {'method': 'passkey', 'code': 'challenge_expired_or_missing'}),
        ('risk_mfa_verify_failed', {'method': 'passkey', 'code': 'assertion_verify_failed'})))
    assert counts == {'passkey': 1}

def test_regression_does_not_reset_and_email_failures_cannot_block():
    assert consecutive_counts(events(('passkey_stepup_failed', {}),
        ('risk_mfa_passed', {'method': 'passkey', 'counter_regression': True}))) == {'passkey': 1}
    assert consecutive_counts(events(('passkey_login_failed', {})), post_factor_only=True) == {}

def test_oauth_success_requires_verified_passkey_evidence():
    failed = ('passkey_stepup_failed', {})
    assert consecutive_counts(events(failed, ('oauth_authorized', {'provider': 'passkey'}))) == {'passkey': 1}
    data = {'breakdown': {'authentication': {'method': 'passkey', 'verified': True}}}
    assert consecutive_counts(events(failed, ('oauth_authorized', data))) == {'passkey': 0}

def test_backoff_returns_retry_after_and_reset_is_factor_scoped(monkeypatch):
    deleted = []
    monkeypatch.setattr(auth_retry, 'redis_client', SimpleNamespace(
        ttl=lambda key: 30, delete=lambda *keys: deleted.extend(keys)))
    with pytest.raises(HTTPException) as error:
        auth_retry.check('user', 'totp')
    assert error.value.status_code == 429
    assert error.value.headers == {'Retry-After': '30'}
    auth_retry.succeeded('user', 'totp')
    assert deleted == ['auth_retry:user:totp:count', 'auth_retry:user:totp:wait']
