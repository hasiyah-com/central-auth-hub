from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import l3_sequence_client as client
from app.services.feature_time import FEATURE_CONTRACT


class _ClientContext:
    calls = []
    timeouts = []

    def __init__(self, *args, **kwargs):
        self.timeouts.append(kwargs.get("timeout"))
        outcome = self.calls.pop(0)
        self.post = AsyncMock(
            side_effect=outcome if isinstance(outcome, Exception) else None,
            return_value=None if isinstance(outcome, Exception) else outcome,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _response(score=.61):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": {
            "anomaly_score": score,
            "explanation": [
                {"feature": "hour_of_day", "value": 22, "shap": .12,
                 "direction": "anomaly"}
            ],
        },
        "meta": {"feature_contract": FEATURE_CONTRACT, "explainer": "ready"},
    }
    return response


@pytest.mark.asyncio
async def test_unified_timeout_recovers_point_score_and_shap(monkeypatch):
    _ClientContext.calls = [httpx.ReadTimeout("sequence slow"), _response()]
    _ClientContext.timeouts = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _ClientContext)

    result = await client.evaluate_l3("user", [0.] * 23, [0.] * 6, "allow")

    assert result["error"] is None
    assert result["point"]["available"] is True
    assert result["point"]["anomaly_score"] == .61
    assert len(result["point"]["explanation"]) == 1
    assert result["sequence"]["error"] == "l3_timeout"
    assert result["unique_to_l3"] is True
    assert _ClientContext.timeouts == [
        client.settings.l3_timeout_seconds,
        client.settings.ml_timeout_seconds,
    ]


@pytest.mark.asyncio
async def test_unified_point_unavailable_retries_independent_point(monkeypatch):
    unified = MagicMock()
    unified.raise_for_status.return_value = None
    unified.json.return_value = {
        "data": {
            "feature_contract": FEATURE_CONTRACT,
            "point": {
                "available": False,
                "anomaly_score": 0,
                "error": "model_not_loaded",
            },
            "sequence": {},
        }
    }
    _ClientContext.calls = [unified, _response(.58)]
    _ClientContext.timeouts = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _ClientContext)

    result = await client.evaluate_l3("user", [0.] * 23, None, "allow")

    assert result["point"]["available"] is True
    assert result["point"]["anomaly_score"] == .58
    assert result["sequence"]["error"] == "l3_point: model_not_loaded"
    assert _ClientContext.timeouts[-1] == client.settings.ml_timeout_seconds


@pytest.mark.asyncio
async def test_point_recovery_remains_fail_safe_when_service_is_down(monkeypatch):
    _ClientContext.calls = [httpx.ReadTimeout("unified"), httpx.ReadTimeout("point")]
    _ClientContext.timeouts = []
    monkeypatch.setattr(client.httpx, "AsyncClient", _ClientContext)

    result = await client.evaluate_l3("user", [0.] * 23, [0.] * 6, "allow")

    assert result["point"]["available"] is False
    assert result["point"]["anomaly_score"] == 0
    assert result["error"].startswith("l3_timeout; point_recovery:")
