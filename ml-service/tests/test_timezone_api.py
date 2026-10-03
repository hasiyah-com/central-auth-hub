from fastapi.testclient import TestClient
from app import main as API
from app.features import FEATURE_CONTRACT


def test_legacy_request_cannot_mix_utc_residuals(monkeypatch):
    client = TestClient(API.app)
    response = client.post("/v1/sequence-score", json={
        "user_id": "u", "residual": [0.] * 6})
    assert response.status_code == 422


def test_unified_response_declares_bangkok_contract(monkeypatch):
    monkeypatch.setattr(API, "_redis", lambda: None)
    monkeypatch.setattr(API.L3U, "evaluate", lambda *args, **kw: {"point": {}})
    response = TestClient(API.app).post("/v1/l3-evaluate", json={
        "user_id": "u", "features": [0.] * 23,
        "feature_contract": FEATURE_CONTRACT})
    assert response.status_code == 200
    assert response.json()["data"]["feature_contract"] == FEATURE_CONTRACT
