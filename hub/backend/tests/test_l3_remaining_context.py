from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import math

import pytest

from app.services.l3_auth_context import build_context, normalize_language, normalize_aaguid
from app.services.l3_post_auth import summarize

NOW = datetime(2026, 10, 3, 10)


def test_aaguid_zero_unknown_and_known_model_change():
    assert normalize_aaguid("00000000-0000-0000-0000-000000000000") is None
    assert normalize_aaguid("invalid") is None
    old, new = str(uuid4()), str(uuid4())
    for current, expected in [(old, 0), (new, 1), (None, 0)]:
        f = build_context(now=NOW, method="passkey", aaguid=current, prior_aaguids=[old]*5)["features"]
        assert f["aaguid_novel"] == expected
    assert build_context(now=NOW, method="passkey", aaguid=new, prior_aaguids=[old]*4)["features"]["prior_aaguid_observed"] == 0


def test_language_priority_and_unknown_headers():
    assert normalize_language("en-US;q=0.5, th-TH;q=0.9") == "th-th"
    assert normalize_language("TH-th, en;q=0.8") == "th-th"
    for raw in [None, "*", "en;q=0", "en;q=nan", "en;q=2", "x"*300]:
        assert normalize_language(raw) is None
    f = build_context(now=NOW, method="google", language="en-US", prior_languages=["th-TH"]*5)["features"]
    assert f["language_known"] == f["prior_language_observed"] == f["language_novel"] == 1


def row(seconds, path="/account/profile", user="u", method="GET", status=200):
    return SimpleNamespace(created_at=NOW+timedelta(seconds=seconds), path=path,
                           user_id=user, method=method, status_code=status)


def test_post_window_excludes_future_anonymous_and_background_requests():
    rows = [row(0), row(30, method="POST", status=403), row(300), row(-1),
            row(20, user=None), row(25, path="/auth/heartbeat"),
            row(26, path="/admin/ml/overview"), row(27, path="/auth/refresh")]
    result = summarize(rows, NOW, NOW+timedelta(minutes=5))
    assert result["request_count"] == 2
    f = result["features"]
    assert f["post_write_fraction"] == f["post_error_fraction"] == .5
    assert f["post_interval_log1p_mean"] == pytest.approx(math.log1p(30))
    assert result["scope"] == "verified_user_hub_requests"


def test_route_ids_do_not_create_fake_diversity():
    result = summarize([row(1, "/users/123"), row(2, "/users/456")], NOW, NOW+timedelta(minutes=5))
    assert result["features"]["post_route_diversity_log1p"] == pytest.approx(math.log1p(1))
    assert summarize([], NOW, NOW+timedelta(minutes=5))["features"]["post_requests_observed"] == 0


def test_post_contract_is_shared_with_offline_model():
    import ast
    from pathlib import Path
    from app.services.l3_post_auth import CONTRACT, FEATURE_NAMES
    path = Path(__file__).resolve().parents[3]/"ml-service/scripts/train_post_auth_candidate.py"
    tree = ast.parse(path.read_text())
    values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id in {"CONTRACT", "FEATURE_NAMES"}}
    assert values["CONTRACT"] == CONTRACT
    assert values["FEATURE_NAMES"] == FEATURE_NAMES


def test_post_observation_flags_truncated_history():
    result = summarize([row(i % 300) for i in range(10001)], NOW, NOW+timedelta(minutes=5))
    assert result["truncated"] is True


def test_post_query_cannot_read_other_accounts_or_future_requests(db):
    from app.models import RequestLog
    from app.services.l3_post_auth import latest_completed_window
    user = uuid4()
    try:
        for owner, at, path in [(user, NOW-timedelta(seconds=30), "/account/profile"),
                                (uuid4(), NOW-timedelta(seconds=20), "/account/profile"),
                                (user, NOW+timedelta(seconds=20), "/account/profile"),
                                (user, NOW-timedelta(seconds=20), "/auth/heartbeat")]:
            db.add(RequestLog(user_id=owner, created_at=at, path=path, method="GET", status_code=200))
        db.flush()
        result = latest_completed_window(db, user, now=NOW)
        assert result["request_count"] == 1
        assert result["to"] == NOW.isoformat()+"Z"
    finally:
        db.rollback()


def test_router_session_fields_match_database_schema():
    import ast
    from pathlib import Path
    from app.models import LoginSession
    fields = set(LoginSession.__table__.columns.keys())
    root = Path(__file__).resolve().parents[1]/"app/routers"
    for filename in ["auth.py", "oauth.py", "passkey.py"]:
        tree = ast.parse((root/filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "LoginSession":
                assert {kw.arg for kw in node.keywords if kw.arg} <= fields
