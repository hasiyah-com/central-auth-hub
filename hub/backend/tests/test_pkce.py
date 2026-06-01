"""Unit tests for PKCE service (RFC 7636)."""

import pytest

from app.services.pkce import generate_pkce_pair, verify_pkce


@pytest.mark.smoke
def test_pkce_pair_round_trip():
    """generate_pkce_pair() → verify_pkce() ผ่าน."""
    verifier, challenge = generate_pkce_pair()
    assert isinstance(verifier, str)
    assert isinstance(challenge, str)
    assert len(verifier) >= 43  # RFC 7636: 43-128 chars
    assert verify_pkce(verifier, challenge) is True


@pytest.mark.smoke
def test_pkce_rejects_wrong_verifier():
    """verifier ที่ผิด → verify_pkce return False."""
    _, challenge = generate_pkce_pair()
    bad_verifier, _ = generate_pkce_pair()
    assert verify_pkce(bad_verifier, challenge) is False


@pytest.mark.smoke
def test_pkce_uses_constant_time_compare():
    """ตรวจ implementation: ต้องใช้ hmac.compare_digest (กัน timing attack)."""
    import inspect

    from app.services import pkce

    src = inspect.getsource(pkce.verify_pkce)
    assert (
        "compare_digest" in src
    ), "verify_pkce ต้องใช้ hmac.compare_digest ห้ามใช้ == (timing attack)"
