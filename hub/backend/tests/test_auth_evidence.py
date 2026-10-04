from app.services.auth_evidence import authentication_evidence, record_authentication, trusted_history
from types import SimpleNamespace
import pytest

@pytest.mark.parametrize('uv,regression,attack,takeover,expected', [
    (True, False, False, False, True),
    (None, False, False, False, False),
    (False, False, False, False, False),
    (True, True, False, False, False),
    (True, False, True, False, False),
    (True, False, False, True, False),
])
def test_verified_history_requires_actual_uv_and_no_severe_signals(uv, regression, attack, takeover, expected):
    bd = {'risk_decision': 'challenge', 'authentication': authentication_evidence(
        'passkey', verified=True, user_verified=uv, counter_regression=regression)}
    assert trusted_history('challenge', bd, attack, takeover) is expected

def test_shadow_block_does_not_establish_trust():
    bd = {'risk_decision': 'would_block', 'authentication': authentication_evidence('passkey', verified=True, user_verified=True)}
    assert not trusted_history('mfa_passed', bd)

def test_feedback_alone_is_not_authentication():
    assert not trusted_history('challenge', {'feedback_label': 'normal_confirmed'})

def test_stepup_preserves_original_risk():
    session = SimpleNamespace(decision='challenge', risk_breakdown={'rule': .6, 'risk_shadow_decision': 'would_challenge'})
    record_authentication(session, 'totp')
    assert session.risk_breakdown['risk_decision'] == 'challenge'
    assert session.risk_breakdown['risk_shadow_decision'] == 'would_challenge'
    assert session.risk_breakdown['authentication']['user_verified'] is None
    assert trusted_history('mfa_passed', session.risk_breakdown)
