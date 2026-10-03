from datetime import datetime, timedelta, timezone
import math
import uuid
from types import SimpleNamespace

import pytest

from app.services.l3_auth_context import build_context, extract_auth_context, FEATURE_NAMES

NOW = datetime(2026, 10, 3, 9)


def test_missing_events_are_masked_not_recent_recovery():
    f = build_context(now=NOW, method="google")["features"]
    assert list(f) == FEATURE_NAMES
    assert f["recovery_observed"] == f["recovery_log1p_hours"] == 0
    assert f["factor_reset_observed"] == 0
    assert f["auth_method_departure"] == 0


def test_successful_recovery_age_and_timezone_are_elapsed_utc():
    at = (NOW - timedelta(hours=2)).replace(tzinfo=timezone.utc)
    f = build_context(now=NOW, method="google", recovery_at=at)["features"]
    assert f["recovery_observed"] == 1
    assert f["recovery_log1p_hours"] == pytest.approx(math.log1p(2))


@pytest.mark.parametrize("offset", [0, 1])
def test_current_or_future_events_never_enter_history(offset):
    f = build_context(now=NOW, method="passkey", recovery_at=NOW + timedelta(hours=offset))["features"]
    assert f["recovery_observed"] == 0


def test_lower_method_only_departs_from_established_passkey_history():
    for method in ["google", "line", "totp"]:
        f = build_context(now=NOW, method=method, prior_methods=["passkey"] * 5)["features"]
        assert f["auth_method_departure"] == 1
    for current, prior in [("google", ["google"] * 5), ("passkey", ["passkey"] * 5),
                           ("google", ["passkey"] * 4), (None, ["passkey"] * 5)]:
        assert build_context(now=NOW, method=current, prior_methods=prior)["features"]["auth_method_departure"] == 0


def test_unknown_history_cannot_satisfy_minimum():
    f = build_context(now=NOW, method="google", prior_methods=[None] * 20 + ["passkey"])["features"]
    assert f["prior_auth_observed"] == 0


def test_queries_use_target_user_completed_events_and_prior_sessions(db):
    from app.models import AuditLog, LoginSession, User
    user = User(email=f"l3ctx-{uuid.uuid4().hex}@example.com", google_sub=uuid.uuid4().hex,
                full_name="L3 context test", user_type="teacher", status="active")
    db.add(user)
    db.flush()
    old_aaguid, new_aaguid = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        for i in range(5):
            db.add(LoginSession(user_id=user.id, subsystem_id=None,
                created_at=NOW - timedelta(days=i+1), login_method="passkey",
                decision="allow", jti=uuid.uuid4().hex,
                risk_breakdown={"l3_auth_candidate": {"authenticator_aaguid": old_aaguid,
                                                       "browser_language": "th-th"}}))
        # Administrator is actor; target is the person whose factors were reset.
        db.add(AuditLog(actor_id=uuid.uuid4(), target_type="user", target_id=user.id,
                        action="passkey_admin_reset", metadata_json={"revoked_count": 1},
                        created_at=NOW-timedelta(hours=3)))
        for action, at in [("passkey_recovery_success", NOW-timedelta(hours=2)),
                           ("passkey_recovery_failed", NOW-timedelta(minutes=1)),
                           ("passkey_recovery_success", NOW+timedelta(hours=1))]:
            db.add(AuditLog(target_type="user", target_id=user.id, action=action, created_at=at))
        db.add(AuditLog(actor_id=user.id, target_type="user", target_id=uuid.uuid4(),
                       action="passkey_recovery_success", created_at=NOW-timedelta(minutes=1)))
        db.add(LoginSession(user_id=user.id, created_at=NOW+timedelta(hours=1),
                            login_method="google", decision="allow", jti=uuid.uuid4().hex))
        db.flush()
        result = extract_auth_context(db, user.id, "google", now=NOW)
        assert result["known_prior_method_count"] == 5
        assert result["features"]["auth_method_departure"] == 1
        assert result["features"]["recovery_log1p_hours"] == pytest.approx(math.log1p(2))
        assert result["features"]["factor_reset_log1p_hours"] == pytest.approx(math.log1p(3))
        extended = extract_auth_context(db, user.id, "passkey", now=NOW,
                                        authenticator_aaguid=new_aaguid, accept_language="en-US")
        assert extended["features"]["aaguid_novel"] == 1
        assert extended["features"]["language_novel"] == 1
    finally:
        db.rollback()


def test_export_requires_original_snapshot_not_recomputed_inputs():
    from scripts.export_l3_auth_candidates import candidate_row, BASE_NAMES
    from app.services.feature_time import FEATURE_CONTRACT
    c = build_context(now=NOW, method="google")
    c.update(base_feature_contract=FEATURE_CONTRACT,
             base_features={name: 0 for name in BASE_NAMES})
    s = SimpleNamespace(id="s", user_id="u", jti="verified", decision="allow",
                        risk_breakdown={"l3_auth_candidate": c})
    assert len(candidate_row(s, 0)["features"]) == 38
    s.risk_breakdown = {}
    assert candidate_row(s, 0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("collector_fails", [False, True])
async def test_collection_never_changes_hard_block_decision(monkeypatch, collector_fails):
    from contextlib import nullcontext
    from app.security import risk_engine as engine
    from app.security.rule_engine import RuleResult
    from app.services import l3_auth_context as context

    def collect(*args, **kwargs):
        if collector_fails:
            raise RuntimeError("collector unavailable")
        return build_context(now=NOW, method="google", prior_methods=["passkey"]*5)

    monkeypatch.setattr(context, "extract_auth_context", collect)
    monkeypatch.setattr(engine, "_user_type", lambda *a: "teacher")
    monkeypatch.setattr(engine, "evaluate_rules", lambda *a, **k: RuleResult(True, 1.0, ["blocked"]))
    db = SimpleNamespace(begin_nested=nullcontext)
    before = await engine.evaluate_login_risk([0]*23, "u", None, None, db)
    after = await engine.evaluate_login_risk([0]*23, "u", None, None, db, login_method="google")
    assert {k: before[k] for k in ["score", "decision", "reasons"]} == {
        k: after[k] for k in ["score", "decision", "reasons"]}
    assert after["breakdown"]["l3_auth_candidate"]["status"] == (
        "unavailable" if collector_fails else "collection_only")


@pytest.mark.asyncio
async def test_candidate_inputs_never_enter_live_point_or_aggregation(monkeypatch):
    from contextlib import nullcontext
    from app.security import risk_engine as engine
    from app.security.rule_engine import RuleResult
    from app.security.behavior_profiling import BehaviorResult
    from app.services.l3_sequence_client import _unified_quiet
    from app.services import l3_auth_context as context
    from app.config import settings
    seen = []

    async def live_l3(user_id, features, *args):
        seen.append(list(features))
        return _unified_quiet()

    monkeypatch.setattr(engine, "_evaluate_l3", live_l3)
    monkeypatch.setattr(engine, "evaluate_rules", lambda *a, **k: RuleResult(False, .1, []))
    monkeypatch.setattr(engine, "get_user_profile", lambda *a: None)
    monkeypatch.setattr(engine, "evaluate_behavior", lambda *a, **k: BehaviorResult(.2, []))
    monkeypatch.setattr(engine, "_user_type", lambda *a: "teacher")
    monkeypatch.setattr(settings, "l3_fallback_warn_enabled", False)
    monkeypatch.setattr(settings, "l3_role_calibration_path", "")
    monkeypatch.setattr(context, "extract_auth_context", lambda *a, **k:
                        build_context(now=NOW, method="google", prior_methods=["passkey"]*5))
    db = SimpleNamespace(begin_nested=nullcontext)
    before = await engine.evaluate_login_risk([0]*23, "u", None, None, db)
    after = await engine.evaluate_login_risk([0]*23, "u", None, None, db, login_method="google")
    assert seen == [[0]*23, [0]*23]
    assert before["score"] == after["score"] == pytest.approx(.3)
    assert before["decision"] == after["decision"]


def test_ml_and_hub_candidate_contracts_are_identical():
    import ast
    from pathlib import Path
    from app.services.l3_auth_context import CONTRACT
    tree = ast.parse((Path(__file__).resolve().parents[3] /
                      "ml-service/scripts/compare_auth_context.py").read_text())
    literals = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id in {"CONTEXT_NAMES", "CONTEXT_CONTRACT"}}
    assert literals["CONTEXT_NAMES"] == FEATURE_NAMES
    assert literals["CONTEXT_CONTRACT"] == CONTRACT
