"""Opt-in policy examples: ordinary activity stays usable, attack evidence still gates."""
import math
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.config import settings
from app.security import rule_engine
from app.security.rule_engine import FEAT, evaluate_rules
from app.security.behavior_profiling import BehaviorResult, evaluate_behavior
from app.security.risk_aggregator import aggregate
from app.security.iforest_scorer import monitoring_only
from app.services.rule_context import RuleContext
from app.services.auth_evidence import authentication_evidence

@pytest.fixture(autouse=True)
def trial(monkeypatch):
    monkeypatch.setattr(settings, 'risk_contextual_trial_enabled', True)

def vector(**values):
    v = [0.0] * 23
    v[FEAT['is_thailand']] = 1
    v[FEAT['permission_change_age']] = 365
    v[FEAT['log_minutes_since_last_login']] = 6
    for key, value in values.items():
        v[FEAT[key]] = value
    return v

def assess(v, profile=None, **kw):
    r = evaluate_rules(v, None, 'u', None, None, context=kw.pop('context', RuleContext()))
    b = evaluate_behavior(v, profile, **kw) if profile else BehaviorResult(0, [])
    return aggregate(r, b, monitoring_only())

def test_temporal_departure_is_scored_once(monkeypatch):
    p = {'total':100, 'hour_counts':{1:100}, 'typical_weekend':0}
    v = vector(hour_of_day=14, hours_from_typical_login_time=11)
    assert assess(v, p).total_score == pytest.approx(.4)
    assert assess(v, p).decision == 'allow'
    monkeypatch.setattr(settings, 'risk_contextual_trial_enabled', False)
    assert assess(v, p).total_score == pytest.approx(.7)
    assert assess(v, p).decision == 'challenge'

def test_device_and_browser_are_one_score():
    assert assess(vector(is_new_device=1, is_new_user_agent_family=1)).total_score == pytest.approx(.3)

@pytest.mark.parametrize('values', [dict(concurrent_session_count=3),dict(active_subsystem_count=2),
    dict(concurrent_session_count=3,active_subsystem_count=2)])
def test_ordinary_session_activity_has_no_mandatory_challenge(values):
    assert assess(vector(**values)).decision == 'allow'

def test_session_with_new_environment_still_gates():
    assert assess(vector(concurrent_session_count=3,is_new_device=1)).decision == 'challenge'

def test_velocity_uses_real_two_minutes_and_needs_context():
    assert assess(vector(login_count_24h=5,log_minutes_since_last_login=math.log(5))).total_score == 0
    assert assess(vector(login_count_24h=5,log_minutes_since_last_login=math.log(1))).decision == 'allow'

def test_new_subsystem_is_score_only():
    p = {'total':100,'subsystem_counts':{'old':100},'seen_subsystems':{'old'}}
    assert assess(vector(), p, subsystem_id='new').decision == 'allow'

def test_independent_signals_and_incident_remain_challenge():
    assert assess(vector(is_new_device=1,new_passkey_recently_added=1)).decision == 'challenge'
    assert assess(vector(confirmed_incident_count=1)).decision == 'challenge'

def test_country_is_not_scored_again_in_behavior():
    d = assess(vector(is_new_country=1), {'total':100})
    assert d.total_score == pytest.approx(.3)
    assert d.decision == 'challenge'

def test_cross_system_risk_requires_real_proof_to_resolve():
    db = MagicMock()
    verified = {'risk_decision':'challenge','authentication':authentication_evidence('passkey',verified=True,user_verified=True)}
    def row(bd,attack=False):
        return SimpleNamespace(risk_score=.8,decision='mfa_passed',risk_breakdown=bd,
            is_attack_ip=attack,is_account_takeover=False)
    db.query.return_value.filter.return_value.all.return_value = [row(verified)]
    assert rule_engine._check_cross_subsystem_risk(db,'u','sub',use_trial=True) is None
    for candidate in (row({'feedback_label':'normal_confirmed'}),row(verified,True)):
        db.query.return_value.filter.return_value.all.return_value = [candidate]
        assert rule_engine._check_cross_subsystem_risk(db,'u','sub',use_trial=True)[0] == pytest.approx(.24)

def test_hard_block_unchanged():
    d = assess(vector(login_count_24h=50))
    assert d.decision == 'block'

def test_legacy_replay_keeps_session_floor():
    assert evaluate_rules(vector(concurrent_session_count=3),None,'u',None,None,
        mode='legacy_replay').min_action == 'challenge'


@pytest.mark.parametrize("trial_enabled", [False, True])
@pytest.mark.parametrize("values", [dict(is_new_device=1), dict(is_new_user_agent_family=1), dict(is_new_device=1, is_new_user_agent_family=1)])
def test_new_environment_requires_challenge(monkeypatch, trial_enabled, values):
    monkeypatch.setattr(settings, "risk_contextual_trial_enabled", trial_enabled)
    d = assess(vector(**values))
    assert d.decision == "challenge"
    assert any("new_environment_stepup" in reason for reason in d.reasons)

def test_browser_version_update_keeps_environment_signature():
    from app.services.feature_extraction import _device_signature, browser_family
    old = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/150.0.0.0 Safari/537.36"
    new = old.replace("150.0.0.0", "154.0.0.0")
    assert _device_signature(old) == _device_signature(new)
    assert browser_family(old) == browser_family(new)
    assert assess(vector()).decision == "allow"
