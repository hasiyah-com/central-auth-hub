"""Tests for the short-lived, single-use frontend login code exchange."""

import json

from app.routers import auth


def _payload() -> str:
    return json.dumps(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 900,
            "refresh_expires_in": 2_592_000,
        }
    )


def test_frontend_code_exchange_is_single_use(client, monkeypatch):
    code = "a" * 43
    values = {f"{auth.FRONTEND_LOGIN_CODE_PREFIX}{code}": _payload()}

    def fake_getdel(key):
        return values.pop(key, None)

    monkeypatch.setattr(auth.redis_client, "getdel", fake_getdel)

    first = client.post("/auth/frontend/exchange", json={"code": code})
    assert first.status_code == 200
    assert first.json()["access_token"] == "access-token"
    assert first.json()["refresh_token"] == "refresh-token"
    assert first.headers["cache-control"] == "no-store"

    replay = client.post("/auth/frontend/exchange", json={"code": code})
    assert replay.status_code == 400


def test_frontend_code_exchange_rejects_expired_or_unknown_code(client, monkeypatch):
    monkeypatch.setattr(auth.redis_client, "getdel", lambda _key: None)

    response = client.post("/auth/frontend/exchange", json={"code": "b" * 43})

    assert response.status_code == 400
    assert "ถูกใช้แล้ว" in response.json()["detail"]


def test_frontend_code_exchange_rejects_malformed_payload(client, monkeypatch):
    monkeypatch.setattr(auth.redis_client, "getdel", lambda _key: "{bad-json")

    response = client.post("/auth/frontend/exchange", json={"code": "c" * 43})

    assert response.status_code == 400


def test_frontend_code_exchange_fails_closed_when_redis_is_unavailable(
    client, monkeypatch
):
    def fail(_key):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(auth.redis_client, "getdel", fail)

    response = client.post("/auth/frontend/exchange", json={"code": "d" * 43})

    assert response.status_code == 503
