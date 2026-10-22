"""Persist operational failures separately from a genuine zero anomaly score."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.security.risk_engine import _l3_summary
from app.services import l3_sequence_client as client
from app.services.feature_time import FEATURE_CONTRACT


def test_summary_retains_failure_details():
    value = client._unified_quiet("l3_timeout")
    value["point"]["error"] = "model_not_loaded"
    value["point"]["explainer"] = "unavailable"
    result = _l3_summary(value)
    assert result["error"] == "l3_timeout"
    assert result["point_error"] == "model_not_loaded"
    assert result["point_available"] is False
    assert result["explainer"] == "unavailable"
    assert result["shap_status"] == "point_unavailable"


def test_summary_distinguishes_explain_failure_from_scoring_failure():
    value = client._unified_quiet(None)
    value["point"].update(available=True, explainer="ready", anomaly_score=.49)
    value["sequence"]["error"] = "l3_timeout"
    result = _l3_summary(value)
    assert result["point_available"] is True
    assert result["shap_status"] == "explanation_unavailable"
    assert result["sequence_error"] == "l3_timeout"


def test_summary_retains_successful_shap_and_model_identity():
    value = client._unified_quiet(None)
    value["point"].update(available=True, explainer="ready", model_sha256="a" * 64,
                           explanation=[{"feature": "hour_of_day", "shap": .1}])
    result = _l3_summary(value)
    assert result["shap_status"] == "ready"
    assert result["shap_count"] == 1
    assert result["point_model_sha256"] == "a" * 64


def test_recovered_point_retains_model_hash(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"data": {"anomaly_score": .49, "explanation": []},
        "meta": {"feature_contract": FEATURE_CONTRACT, "model_sha256": "a" * 64,
                 "explainer": "unavailable"}}
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=response)))
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kw: context)
    value = asyncio.run(client._recover_point([0.] * 23, "allow", "l3_timeout"))
    assert value["point"]["available"] is True
    assert value["point"]["model_sha256"] == "a" * 64
    assert value["sequence"]["error"] == "l3_timeout"


def test_recovery_failure_does_not_change_fail_safe(monkeypatch):
    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=httpx.ReadTimeout("test"))
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kw: context)
    value = asyncio.run(client._recover_point([0.] * 23, "allow", "l3_timeout"))
    assert value["point"]["available"] is False
    assert "ReadTimeout" in value["error"]
