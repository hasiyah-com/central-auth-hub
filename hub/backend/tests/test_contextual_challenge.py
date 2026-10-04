from unittest.mock import MagicMock
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.security import rule_engine
from app.security.rule_engine import FEAT, evaluate_rules
from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import monitoring_only
from app.security.risk_aggregator import aggregate
from app.services.rule_context import RuleContext, collect_rule_context


def assess(monkeypatch, context=None, **signals):
    v = [0.0] * 23
    v[FEAT["is_thailand"]] = 1
    v[FEAT["permission_change_age"]] = 365
    for k, value in signals.items():
        v[FEAT[k]] = value
    monkeypatch.setattr(rule_engine, "count_recent_consecutive_auth", lambda *a, **k: signals.get("failed_logins_24h", 0))
    result = evaluate_rules(v, object(), "u", None, None, context=context)
    return result, aggregate(result, BehaviorResult(0, []), monitoring_only())


@pytest.mark.parametrize("signal", ["is_new_device", "is_new_user_agent_family", "new_passkey_recently_added"])
def test_isolated_change_does_not_force_stepup(monkeypatch, signal):
    r, decision = assess(monkeypatch, **{signal: 1})
    assert r.min_action is None
    assert decision.decision == "allow"
    assert r.score > 0


def test_device_and_browser_are_one_signal(monkeypatch):
    r, d = assess(monkeypatch, is_new_device=1, is_new_user_agent_family=1)
    assert r.min_action is None
    assert d.decision == "warn"


def test_independent_changes_require_stepup(monkeypatch):
    r, d = assess(monkeypatch, is_new_device=1, new_passkey_recently_added=1)
    assert r.min_action == "challenge"
    assert d.decision == "challenge"


def test_verified_current_passkey_avoids_redundant_floor(monkeypatch):
    r, d = assess(monkeypatch, RuleContext(strong_primary_verified=True),
                  is_new_device=1, new_passkey_recently_added=1)
    assert r.min_action is None
    assert d.decision == "warn"


def test_approval_excuses_only_matching_permission_signal(monkeypatch):
    r, d = assess(monkeypatch, RuleContext(latest_permission_approved=True),
                  permission_change_age=0, is_new_device=1)
    assert r.min_action is None
    assert d.decision == "warn"
    assert r.score == pytest.approx(.55)


def test_unknown_permission_plus_device_requires_stepup(monkeypatch):
    r, d = assess(monkeypatch, permission_change_age=0, is_new_device=1)
    assert d.decision == "challenge"


def test_recovery_still_requires_stepup_even_with_strong_primary(monkeypatch):
    r, d = assess(monkeypatch, RuleContext(strong_primary_verified=True, recent_recovery_or_reset=True),
                  new_passkey_recently_added=1)
    assert d.decision == "challenge"


def test_three_failures_do_not_force_stepup_with_new_device(monkeypatch):
    r, d = assess(monkeypatch, is_new_device=1, failed_logins_24h=3)
    assert d.decision == "warn"
    assert r.min_action is None


@pytest.mark.parametrize("failed,decision", [(5, "challenge"), (10, "block")])
def test_frequent_failure_unaffected_by_context(monkeypatch, failed, decision):
    r, d = assess(monkeypatch, RuleContext(True, True), failed_logins_24h=failed)
    assert d.decision == decision


def test_score_and_behavior_can_still_require_stepup(monkeypatch):
    r, _ = assess(monkeypatch, RuleContext(True, True), is_new_device=1)
    d = aggregate(r, BehaviorResult(.4, []), monitoring_only())
    assert d.decision == "challenge"


def test_legacy_frozen_floor_stays_unchanged():
    v = [0.0] * 23
    v[FEAT["is_thailand"]] = 1
    v[FEAT["permission_change_age"]] = 365
    v[FEAT["is_new_device"]] = 1
    assert evaluate_rules(v, None, "u", None, None, mode="legacy_replay").min_action == "challenge"


@pytest.mark.parametrize("matched,revoked,expected", [(True, False, True), (False, False, False), (True, True, False)])
def test_approval_evidence_requires_matching_audit(monkeypatch, matched, revoked, expected):
    now = datetime(2026, 10, 3, 12)
    row = SimpleNamespace(granted_at=now-timedelta(minutes=1),
                          revoked_at=now-timedelta(seconds=30) if revoked else None,
                          entry_type="allow", granted_by="admin", subsystem_id="sub")
    db = MagicMock()
    recovery, access, audit = MagicMock(), MagicMock(), MagicMock()
    recovery.filter.return_value.first.return_value = None
    access.filter.return_value.all.return_value = [row]
    audit.filter.return_value.first.return_value = ("audit",) if matched else None
    db.query.side_effect = [recovery, access, audit]
    context = collect_rule_context(db, "u", login_method="google", now=now)
    assert context.latest_permission_approved is expected
    assert context.strong_primary_verified is False
    if not revoked:
        from sqlalchemy import and_
        from sqlalchemy.dialects import postgresql
        filters = audit.filter.call_args.args
        sql = and_(*filters).compile(dialect=postgresql.dialect())
        values = list(sql.params.values())
        assert "admin_grant_user_access" in values
        assert "user" in values and "u" in values and "admin" in values and "sub" in values
        assert row.granted_at in values
        assert row.granted_at + timedelta(seconds=5) in values


def test_past_mfa_not_used_as_current_proof():
    assert collect_rule_context(None, "u", login_method="google").strong_primary_verified is False
