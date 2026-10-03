from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import and_

from app.services.risk_session import resolve_challenge_session
from app.services.feature_extraction import _device_signature, TRUSTED_DECISIONS


def test_challenge_queries_original_session_and_owner_not_latest():
    uid, sid = uuid4(), uuid4()
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    original = SimpleNamespace(id=sid)
    query.first.return_value = original
    assert resolve_challenge_session(db, {"session_id": str(sid), "flow": "hub_direct"}, uid) is original
    predicates = [p for call in query.filter.call_args_list for p in call.args]
    compiled = and_(*predicates).compile()
    assert sid in compiled.params.values() and uid in compiled.params.values()
    assert "subsystem_id IS NULL" in str(compiled)
    query.order_by.assert_not_called()


def test_subsystem_challenge_also_checks_subsystem():
    db = MagicMock(); query = db.query.return_value; query.filter.return_value = query
    sub = uuid4()
    resolve_challenge_session(db, {"session_id": str(uuid4()), "flow": "subsystem",
                                  "authreq": {"subsystem_id": str(sub)}}, uuid4())
    predicates = [p for call in query.filter.call_args_list for p in call.args]
    assert sub in and_(*predicates).compile().params.values()


@pytest.mark.parametrize("session_id", [None, "", "invalid"])
def test_legacy_or_invalid_challenge_cannot_trust_latest_session(session_id):
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        resolve_challenge_session(db, {"session_id": session_id, "flow": "hub_direct"}, uuid4())
    assert exc.value.status_code == 410
    db.query.assert_not_called()


def test_missing_or_wrong_owner_session_fails_closed():
    db = MagicMock(); query = db.query.return_value; query.filter.return_value = query
    query.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        resolve_challenge_session(db, {"session_id": str(uuid4()), "flow": "hub_direct"}, uuid4())
    assert exc.value.status_code == 410


def test_desktop_is_not_device_identity_and_browser_updates_are_stable():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
    assert _device_signature(ua) == _device_signature(ua.replace("150.0.0.0", "151.0.0.0"))
    assert _device_signature(ua) != _device_signature(ua + " Edg/150.0.0.0")
    assert "mfa_passed" in TRUSTED_DECISIONS
    assert "would_challenge" not in TRUSTED_DECISIONS
