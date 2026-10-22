"""Real source rules, event evidence reuse and access-channel isolation."""
import copy
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as N
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.config import Settings, settings
from app.security import c3_pge_shadow as shadow, risk_engine, rule_engine
from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import monitoring_only
from app.security.risk_aggregator import aggregate
from app.services.c3_pge_evidence import registration_verified, trusted_count_capped
from app.services.rule_context import RuleContext


def vector(**values):
    v = [0.0] * 23
    v[3], v[8], v[20] = 1, 6, 365
    for name, value in values.items():
        v[rule_engine.FEAT[name]] = value
    return v


def facts(count=2, verified=True):
    return dict(trusted_history_count_capped_at5=count, registration_verified=verified,
                grant_provenance_recorded=verified, registration_status="unknown",
                permission_status="unknown")


@pytest.fixture(autouse=True)
def baseline(monkeypatch):
    monkeypatch.setattr(settings, "risk_contextual_trial_enabled", False)
    monkeypatch.setattr(rule_engine, "is_blacklisted", lambda *a: False)
    monkeypatch.setattr(rule_engine, "_check_impossible_travel", lambda *a: None)
    monkeypatch.setattr(rule_engine, "count_recent_consecutive_auth", lambda *a, **k: 0)


def assess(v, *, count=2, verified=True, behavior=.2, monkeypatch):
    monkeypatch.setattr(shadow, "collect", lambda *a, **k: facts(count, verified))
    cache = {}
    ctx = RuleContext()
    rr = rule_engine.evaluate_rules(v, object(), "u", None, None, context=ctx, _observations=cache)
    br = BehaviorResult(behavior, [])
    base = aggregate(rr, br, monitoring_only())
    before = copy.deepcopy((vars(rr), vars(br), vars(base), v))
    result = shadow.build(db=object(), user_id="u", subsystem_id=None, features=v,
                          ip=None, geo_country=None, context=ctx, baseline_rule=rr,
                          behavior=br, baseline=base, observations=cache)
    assert before == (vars(rr), vars(br), vars(base), v)
    return base, result


def test_default_is_off():
    assert Settings(_env_file=None, c3_pge_shadow_enabled=False).c3_pge_shadow_enabled is False
    assert Settings.model_fields["c3_pge_shadow_enabled"].default is False


def test_c3_only_changes_shadow_for_low_history(monkeypatch):
    base, detail = assess(vector(is_new_device=1, is_new_user_agent_family=1), monkeypatch=monkeypatch)
    assert base.decision == "challenge"
    assert detail["candidate_decision"] == "warn"
    assert detail["applied_to_access"] is False
    assert detail["l3_included"] is False


def test_history_at_five_keeps_existing_floor(monkeypatch):
    base, detail = assess(vector(is_new_device=1, is_new_user_agent_family=1), count=5, monkeypatch=monkeypatch)
    assert base.decision == detail["candidate_decision"] == "challenge"


def test_c2_warning_is_retained_after_dedup(monkeypatch):
    _, detail = assess(vector(is_new_device=1, is_new_user_agent_family=1), behavior=0, monkeypatch=monkeypatch)
    assert detail["candidate_decision"] == "warn"


@pytest.mark.parametrize("values", [dict(is_new_country=1), dict(concurrent_session_count=3), dict(active_subsystem_count=2), dict(confirmed_incident_count=1)])
def test_other_floors_are_not_waived(monkeypatch, values):
    _, detail = assess(vector(is_new_device=1, **values), monkeypatch=monkeypatch)
    assert detail["candidate_decision"] == "challenge"


@pytest.mark.parametrize("values", [dict(new_passkey_recently_added=1), dict(ever_changed_permission=1, permission_change_age=.1)])
def test_unknown_is_visible_not_fabricated_verified(monkeypatch, values):
    _, detail = assess(vector(**values), behavior=0, verified=False, monkeypatch=monkeypatch)
    assert detail["candidate_decision"] == "challenge"
    assert detail["pge_reasons"]
    assert detail["evidence"]["registration_verified"] is False


def test_known_provenance_does_not_lower_other_risks(monkeypatch):
    _, detail = assess(vector(is_new_country=1, new_passkey_recently_added=1), monkeypatch=monkeypatch)
    assert detail["candidate_decision"] == "challenge"


def test_auth_failure_reads_are_reused(monkeypatch):
    calls = []
    monkeypatch.setattr(rule_engine, "count_recent_consecutive_auth", lambda *a, **k: calls.append(k) or 5)
    _, detail = assess(vector(failed_logins_24h=5), monkeypatch=monkeypatch)
    assert detail["candidate_decision"] == "challenge"
    assert len(calls) == 2  # baseline post-factor and total; shadow issues no further reads


def test_missing_shadow_observation_cannot_query_new_state(monkeypatch):
    from types import MappingProxyType
    calls = []
    with pytest.raises(ValueError):
        rule_engine._observe(MappingProxyType({}), "missing", lambda: calls.append(True))
    assert calls == []


def test_contextual_trial_is_not_silently_combined(monkeypatch):
    monkeypatch.setattr(shadow, "collect", lambda *a, **k: pytest.fail("must not query"))
    detail = shadow.build(db=None, user_id="u", subsystem_id=None, features=vector(), ip=None,
                          geo_country=None, context=RuleContext(), baseline_rule=N(blocked=False),
                          behavior=None, baseline=None, observations={}, contextual_trial=True)
    assert detail["status"] == "incompatible_contextual_trial"


def test_hard_block_does_not_collect_history(monkeypatch):
    monkeypatch.setattr(shadow, "collect", lambda *a, **k: pytest.fail("must not query"))
    detail = risk_engine._evaluate_c3_shadow(True, baseline_rule=N(blocked=True))
    assert detail["would_decision"] == "would_block"


def test_off_has_no_shadow_import_or_reads(monkeypatch):
    monkeypatch.setattr(shadow, "build", lambda **k: pytest.fail("must not evaluate"))
    assert risk_engine._evaluate_c3_shadow(False) is None


def test_shadow_failure_is_contained(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("test failure")
    monkeypatch.setattr(shadow, "build", fail)
    db = MagicMock()
    detail = risk_engine._evaluate_c3_shadow(True, db=db, baseline_rule=N(blocked=False))
    assert detail["status"] == "unavailable"
    assert detail["applied_to_access"] is False
    assert db.begin_nested.call_count == 1
    db.rollback.assert_not_called()
    db.commit.assert_not_called()


def registration_fixture():
    now = datetime(2026, 10, 22, 12)
    uid, cid, sid = uuid4(), uuid4(), uuid4()
    cred = N(id=cid, user_id=uid, created_at=now-timedelta(seconds=30))
    audit = N(action="passkey_registered", target_type="passkey", target_id=cid, actor_id=uid,
              created_at=cred.created_at, metadata_json={"registration_session_id": str(sid)})
    session = N(id=sid, user_id=uid, created_at=now-timedelta(seconds=90), decision="challenge",
                risk_breakdown={"risk_decision":"challenge", "authentication": {
                    "method":"passkey", "verified":True, "user_verified":True,
                    "verified_at":(now-timedelta(seconds=60)).isoformat()+"Z", "stage":"step_up"}})
    return cred, audit, session, now


def test_actual_prior_strong_registration_link():
    assert registration_verified(*registration_fixture())


@pytest.mark.parametrize("case", ["missing_link", "wrong_user", "wrong_credential", "future_proof", "expired", "blocked", "not_verified", "counter_regression"])
def test_registration_unknown_cannot_gain_verified_status(case):
    cred, audit, session, now = registration_fixture()
    if case == "missing_link":
        audit.metadata_json = {}
    if case == "wrong_user":
        session.user_id = uuid4()
    if case == "wrong_credential":
        audit.target_id = uuid4()
    if case == "future_proof":
        session.risk_breakdown["authentication"]["verified_at"] = now.isoformat()
    if case == "expired":
        session.created_at -= timedelta(minutes=10)
    if case == "blocked":
        session.risk_breakdown["risk_decision"] = "block"
    if case == "not_verified":
        session.risk_breakdown["authentication"]["verified"] = False
    if case == "counter_regression":
        session.risk_breakdown["authentication"]["counter_regression"] = True
    assert not registration_verified(cred, audit, session, now)


def test_trusted_count_does_not_truncate_untrusted_rows():
    db = MagicMock()
    rows = [("challenge",{},False,False)]*100 + [("allow",{},False,False)]*5
    db.query.return_value.filter.return_value.order_by.return_value.yield_per.return_value = rows
    assert trusted_count_capped(db, uuid4(), datetime.utcnow()) == 5


@pytest.mark.parametrize("fail", [False, True])
def test_full_orchestrator_access_is_identical_with_shadow(monkeypatch, fail):
    from app.services import rule_context
    from app.services.l3_sequence_client import _unified_quiet
    monkeypatch.setattr(settings, "l3_role_calibration_path", "")
    monkeypatch.setattr(settings, "l3_fallback_warn_enabled", False)
    monkeypatch.setattr(settings, "l3_decision_trial_enabled", False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda *a: {})
    monkeypatch.setattr(risk_engine, "evaluate_behavior", lambda *a, **k: BehaviorResult(.2, []))
    monkeypatch.setattr(rule_context, "collect_rule_context", lambda *a, **k: RuleContext())
    async def l3(*a):
        return _unified_quiet()
    monkeypatch.setattr(risk_engine, "_evaluate_l3", l3)
    def evidence(*a, **kw):
        if fail:
            raise RuntimeError("evidence unavailable")
        return facts()
    monkeypatch.setattr(shadow, "collect", evidence)
    v = vector(is_new_device=1, is_new_user_agent_family=1)
    monkeypatch.setattr(settings, "c3_pge_shadow_enabled", False)
    old = asyncio.run(risk_engine.evaluate_login_risk(v, "u", None, None, MagicMock()))
    monkeypatch.setattr(settings, "c3_pge_shadow_enabled", True)
    new = asyncio.run(risk_engine.evaluate_login_risk(v, "u", None, None, MagicMock()))
    detail = new["breakdown"].pop("c3_pge_shadow")
    assert new == old
    assert detail["status"] == ("unavailable" if fail else "evaluated")
