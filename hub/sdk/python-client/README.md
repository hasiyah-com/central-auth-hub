# Central Auth Hub — Python Client SDK

Official Python SDK — OAuth 2.0 + PKCE + JWT via OIDC Discovery

Sync + async APIs · Framework-agnostic · Python 3.10+

---

## ✅ Features

- **OIDC Discovery** auto-load
- **PKCE S256** (RFC 7636)
- **CSRF state** verify via `hmac.compare_digest`
- **JWT verify** — RS256 + JWKS + auto key rotation
- **Webhook receiver** — HMAC-SHA256 + replay protection
- **Sync + async** APIs (`build_authorize_url` + `build_authorize_url_async`)
- **Works with**: FastAPI, Flask, Django, Starlette, any framework

---

## 📦 Install

```bash
pip install central-auth-hub
```

---

## 🚀 Quick start (FastAPI)

```python
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from central_auth_hub import HubClient

app = FastAPI()
hub = HubClient(
    hub_url="http://localhost:8000",
    client_id="cli_xxx",
    client_secret="sec_xxx",  # pragma: allowlist secret
    redirect_uri="http://localhost:8001/oauth/callback",
)

@app.get("/login")
async def login(request: Request):
    url, state, verifier = await hub.build_authorize_url_async()
    request.session["oauth_state"] = state
    request.session["oauth_verifier"] = verifier
    return RedirectResponse(url)

@app.get("/oauth/callback")
async def callback(request: Request, code: str, state: str):
    expected = request.session.pop("oauth_state", "")
    verifier = request.session.pop("oauth_verifier", "")
    claims = await hub.handle_callback_async(code, state, expected, verifier)
    request.session["user"] = claims
    return RedirectResponse("/")
```

Total: ~20 lines vs ~165 raw.

---

## 🚀 Quick start (Flask — sync)

```python
from flask import Flask, request, session, redirect
from central_auth_hub import HubClient

app = Flask(__name__)
app.secret_key = "x"
hub = HubClient(hub_url=..., client_id=..., client_secret=..., redirect_uri=...)

@app.get("/login")
def login():
    url, state, verifier = hub.build_authorize_url()
    session["oauth"] = {"state": state, "verifier": verifier}
    return redirect(url)

@app.get("/oauth/callback")
def callback():
    ctx = session.pop("oauth", {})
    claims = hub.handle_callback(
        request.args["code"], request.args["state"],
        ctx.get("state", ""), ctx.get("verifier", ""),
    )
    session["user"] = claims
    return redirect("/")
```

---

## 📡 Webhook

```python
from fastapi import FastAPI, Request, HTTPException
from central_auth_hub import verify_webhook, HubError

@app.post("/internal/access-revoked")
async def webhook(request: Request):
    raw = await request.body()
    try:
        payload = verify_webhook(
            shared_key=settings.hub_webhook_shared_key,
            raw_body=raw,
            headers=dict(request.headers),
        )
    except HubError as e:
        raise HTTPException(401, str(e))
    if payload["event"] == "access_revoked":
        ...
    return {"status": "ok"}
```

---

## 🔐 Security model

| Concern | Defense |
|---|---|
| CSRF state | `hmac.compare_digest` constant-time |
| Auth code interception | PKCE S256 (RFC 7636) |
| JWT tampering | RS256 + JWKS via PyJWT |
| Key rotation | auto-refresh on unknown kid |
| Webhook spoofing | HMAC-SHA256 timing-safe |
| Replay attack | timestamp tolerance |

---

## 📚 References

- [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)
- [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) (OAuth 2.0)
- [RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636) (PKCE)
- [RFC 7517](https://datatracker.ietf.org/doc/html/rfc7517) (JWK)
- [RFC 7519](https://datatracker.ietf.org/doc/html/rfc7519) (JWT)
- [PyJWT](https://github.com/jpadilla/pyjwt)

## 📜 License

MIT
