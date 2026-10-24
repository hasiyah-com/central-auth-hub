import asyncio, copy, hashlib, json, math
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import httpx, pytest
from app.config import settings
from app.services import if_candidate_shadow as client
from app.services.feature_time import FEATURE_CONTRACT
from app.security.rule_engine import FEAT, RuleResult
from app.security.behavior_profiling import BehaviorResult

V = [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]
SHA = "71de43c4214f6db5d46dbec8ec7baf31f3d9429af0632fb19c8cd67a419f61ca"


def payload(v=V):
    raw = 0.2
    cut = 0.0918450679660674
    return dict(
        version="if-candidate-shadow-v1",
        mode="shadow",
        status="evaluated",
        applied_to_access=False,
        input_contract=FEATURE_CONTRACT,
        training_semantics="offline-r79-mirror-not-live-certified",
        model_sha256=SHA,
        input_sha256=hashlib.sha256(
            json.dumps([float(x) for x in v], separators=(",", ":")).encode()
        ).hexdigest(),
        raw_score=raw,
        score=1 / (1 + math.exp(-5 * raw)),
        raw_threshold=cut,
        threshold=1 / (1 + math.exp(-5 * cut)),
        flagged=True,
        explanation=[
            dict(feature=n, value=float(v[i]), shap=0.0, direction="normal")
            for n, i in FEAT.items()
        ],
        shap_unit="negative_mean_corrected_path_length_not_risk_points",
    )


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(settings, "l3_candidate_shadow_enabled", True)
    monkeypatch.setattr(
        settings,
        "l3_candidate_shadow_url",
        "http://ml-candidate-shadow:9001/v1/shadow-score",
    )
    monkeypatch.setattr(settings, "l3_candidate_shadow_key", "t" * 32)
    monkeypatch.setattr(settings, "l3_candidate_shadow_model_sha256", SHA)
    monkeypatch.setattr(settings, "l3_candidate_shadow_timeout_seconds", 0.04)


class FakeClient:
    result = None
    calls = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def post(self, url, **kw):
        self.calls.append(kw)
        if isinstance(self.result, Exception):
            raise self.result
        if self.result == "slow":
            await asyncio.sleep(0.5)
        return httpx.Response(200, json=self.result, request=httpx.Request("POST", url))


@pytest.mark.asyncio
async def test_request_same_vector_response_diagnostic_only(monkeypatch):
    FakeClient.result = payload()
    FakeClient.calls = []
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeClient)
    before = copy.deepcopy(V)
    r = await client.evaluate_candidate(V)
    assert V == before and r["applied_to_access"] is False and r["flagged"] is True
    assert (
        FakeClient.calls[0]["json"]["features"] == V
        and "user_id" not in FakeClient.calls[0]["json"]
    )
    assert "decision" not in r and "access_decision" not in r


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("model_sha256", "b" * 64),
        ("applied_to_access", True),
        ("mode", "enforce"),
        ("input_contract", "wrong"),
        ("input_sha256", "b" * 64),
        ("raw_threshold", 0.2),
        ("score", 0.1),
        ("explanation", []),
        ("training_semantics", "unknown"),
    ],
)
async def test_rejects_inconsistent_response(monkeypatch, field, value):
    p = payload()
    p[field] = value
    FakeClient.result = p
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeClient)
    assert (await client.evaluate_candidate(V))["status"] == "invalid_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("timeout"), RuntimeError("internal"), "slow"]
)
async def test_failure_contained_with_deadline(monkeypatch, failure):
    FakeClient.result = failure
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeClient)
    start = asyncio.get_running_loop().time()
    r = await client.evaluate_candidate(V)
    assert r["status"] in ("timeout", "unavailable") and r["applied_to_access"] is False
    assert asyncio.get_running_loop().time() - start < 0.25


@pytest.mark.asyncio
async def test_bulkhead_no_waiting_queue(monkeypatch):
    FakeClient.result = "slow"
    FakeClient.calls = []
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeClient)
    r = await asyncio.gather(*(client.evaluate_candidate(V) for _ in range(20)))
    assert len(FakeClient.calls) == 4 and sum(x["status"] == "busy" for x in r) == 16


@pytest.mark.asyncio
async def test_cancel_releases_slot(monkeypatch):
    FakeClient.result = "slow"
    monkeypatch.setattr(client.httpx, "AsyncClient", FakeClient)
    task = asyncio.create_task(client.evaluate_candidate(V))
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._slots._value == 4


@pytest.mark.asyncio
async def test_off_makes_no_request(monkeypatch):
    monkeypatch.setattr(settings, "l3_candidate_shadow_enabled", False)
    monkeypatch.setattr(
        client.httpx, "AsyncClient", lambda *a, **k: pytest.fail("called when off")
    )
    assert await client.evaluate_candidate(V) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("base_action", ["allow", "warn", "challenge", "block"])
@pytest.mark.parametrize("failure", [False, True])
async def test_full_orchestrator_access_identical(monkeypatch, base_action, failure):
    from app.security import risk_engine as engine
    from app.services.l3_sequence_client import _unified_quiet

    monkeypatch.setattr(settings, "c3_pge_shadow_enabled", False)
    monkeypatch.setattr(settings, "risk_contextual_trial_enabled", False)
    monkeypatch.setattr(settings, "l3_role_calibration_path", "")
    monkeypatch.setattr(settings, "l3_fallback_warn_enabled", True)
    rr = RuleResult(
        base_action == "block",
        0.0,
        [],
        min_action=base_action if base_action in ("warn", "challenge") else None,
    )
    monkeypatch.setattr(engine, "evaluate_rules", lambda *a, **k: rr)
    monkeypatch.setattr(engine, "get_user_profile", lambda *a: None)
    monkeypatch.setattr(
        engine, "evaluate_behavior", lambda *a, **k: BehaviorResult(0.0, [])
    )
    monkeypatch.setattr(engine, "_user_type", lambda *a: "student")
    q = _unified_quiet()
    q["error"] = None
    q["point"].update(available=True, error=None, anomaly_score=0.8)
    monkeypatch.setattr(engine, "_evaluate_l3", AsyncMock(return_value=q))
    call = AsyncMock(
        side_effect=RuntimeError("failed") if failure else None, return_value=payload()
    )
    monkeypatch.setattr(client, "evaluate_candidate", call)
    db = NS(begin_nested=nullcontext)
    monkeypatch.setattr(settings, "l3_candidate_shadow_enabled", False)
    before = await engine.evaluate_login_risk(V, "synthetic", None, None, db)
    monkeypatch.setattr(settings, "l3_candidate_shadow_enabled", True)
    after = await engine.evaluate_login_risk(V, "synthetic", None, None, db)
    clean = copy.deepcopy(after)
    clean["breakdown"].pop("if_candidate_shadow", None)
    assert clean == before
    assert call.await_count == 1
    assert after["breakdown"]["if_candidate_shadow"]["applied_to_access"] is False
    if base_action == "allow":
        assert after["decision"] == "warn"  # original live fallback still applied
