import hashlib, json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from test_shadow_candidate import bundle
from app import shadow_main

V = [12, 1, 1, 1, 0, 1, 0, 0, 5, 1, 0, 1, 100, 0, 1, 0, 0, 0.8, 0.8, 0, 365, 0, 0]


@pytest.fixture
def env(bundle, monkeypatch):
    _, a, p, d = bundle
    for key, value in {
        "CANDIDATE_MODEL_PATH": str(a),
        "CANDIDATE_MANIFEST_PATH": str(p),
        "CANDIDATE_MANIFEST_SHA256": d,
        "CANDIDATE_SHADOW_KEY": "k" * 32,
    }.items():
        monkeypatch.setenv(key, value)
    return bundle


def post(client, **kw):
    return client.post(
        "/v1/shadow-score",
        json={"features": V, "feature_contract": "rba-23-bangkok-v1", **kw},
        headers={"X-Shadow-Key": "k" * 32},
    )


def test_actual_HTTP23values_and_no_live_endpoint(env):
    with TestClient(shadow_main.app) as client:
        a = post(client)
        b = post(client)
        assert a.status_code == 200 and a.json() == b.json()
        assert (
            len(a.json()["explanation"]) == 23
            and a.json()["applied_to_access"] is False
        )
        assert client.get("/health").json()["model_sha256"] == a.json()["model_sha256"]
        assert client.post("/v1/score", json={}).status_code == 404


def test_authentication_is_required(env):
    with TestClient(shadow_main.app) as client:
        for key in ["", "wrong"]:
            assert (
                client.post(
                    "/v1/shadow-score",
                    json={"features": V, "feature_contract": "rba-23-bangkok-v1"},
                    headers={"X-Shadow-Key": key},
                ).status_code
                == 401
            )


@pytest.mark.parametrize(
    "extra",
    [
        {"features": V[:22]},
        {"features": [999.0] * 23},
        {"feature_contract": "wrong"},
        {"user_id": "must_not_send_identity"},
    ],
)
def test_malformed_input(env, extra):
    with TestClient(shadow_main.app) as client:
        assert post(client, **extra).status_code == 422


@pytest.mark.parametrize(
    "key,value",
    [
        ("CANDIDATE_SHADOW_KEY", "short"),
        ("CANDIDATE_MANIFEST_SHA256", "0" * 64),
        ("CANDIDATE_MODEL_PATH", "/missing/candidate.joblib"),
    ],
)
def test_startup_fails_for_bad_configuration(env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises((RuntimeError, ValueError)):
        with TestClient(shadow_main.app):
            pass


def test_internal_score_failure_is_service503(env, monkeypatch):
    with TestClient(shadow_main.app) as client:

        def fail(*a):
            raise RuntimeError("not exposed")

        monkeypatch.setattr(shadow_main.app.state.candidate, "evaluate", fail)
        r = post(client)
        assert r.status_code == 503 and "not exposed" not in r.text
