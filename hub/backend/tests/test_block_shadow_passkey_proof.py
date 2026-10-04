"""Passkey proof must survive risk Challenge without trusting suspicious credentials."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from starlette.requests import Request
from app.routers import passkey


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,regression,expected", [
    ("challenge", False, "mfa_passed"),
    ("warn", False, "mfa_passed"),
    ("would_block", False, "would_block"),
    ("challenge", True, "challenge"),
])
async def test_passkey_proof_keeps_risk_assessment(monkeypatch, decision, regression, expected):
    monkeypatch.setattr(passkey, "get_client_ip", lambda request: "203.0.113.1")
    monkeypatch.setattr(passkey, "lookup_geo", lambda ip: (None, None))
    monkeypatch.setattr(passkey, "extract_session_features", lambda *a, **kw: [0.] * 23)
    monkeypatch.setattr(passkey, "evaluate_login_risk", AsyncMock(return_value={
        "score": .9, "decision": decision, "breakdown": {"iforest_raw": .46},
        "reasons": ["test"], "iforest_explanation": [],
    }))
    monkeypatch.setattr(passkey, "maybe_alert_ml_risk", lambda **kw: None)
    monkeypatch.setattr(passkey, "is_blacklisted", lambda *a: False)
    request = Request({"type": "http", "headers": [(b"user-agent", b"Chrome/154.0")],
                       "client": ("203.0.113.1", 1234)})
    result = SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4(), email="test@example.com"),
                             counter_regression=regression)
    session = await passkey._build_login_session(result, request, "test-jti", None, "passkey")
    assert session.decision == expected
    assert session.risk_score >= .9
    assert session.risk_breakdown["risk_decision"] == decision
