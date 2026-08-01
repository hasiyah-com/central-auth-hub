# Findings Detail — MEDIUM+ (run-1)

## Finding 1 — Stored HTML injection via unescaped subsystem name

### Data flow (input → sink)
1. **Input / storage** — `POST /developer/subsystems` (and `PATCH /developer/subsystems/{id}`), `hub/backend/app/routers/developer.py` — a developer (teacher/staff/admin) sets `Subsystem.name` to an arbitrary string. Stored in DB.
2. **Entrypoint** — `authorize`, `hub/backend/app/routers/oauth.py:76` — public, unauthenticated `GET /oauth/authorize?client_id=…` loads the subsystem by `client_id`.
3. **Branch (suspended)** — `oauth.py:103` — `return HTMLResponse(content=_suspended_html(subsystem_name=subsystem.name), status_code=503)` when `subsystem.status == "suspended"`.
4. **Branch (maintenance)** — `oauth.py:136` — `_maintenance_html(subsystem_name=subsystem.name, health=health)` when the pre-flight health check reports `status == "down"`.
5. **Sink** — `_suspended_html` (`oauth.py:2773`) and `_maintenance_html` (`oauth.py:2718`) — `subsystem_name` (and, in maintenance, `health["error"]`) is interpolated into the returned HTML **f-string with no escaping** (e.g. `<title>{subsystem_name} …</title>` and `<div class="title">{subsystem_name}<br>…`).

Contrast — the correct sibling: `_login_chooser_html` (`oauth.py:2394`):
```python
# esc ชื่อ subsystem (กัน HTML injection — ชื่อมาจาก DB)
safe_name = (subsystem_name.replace("&","&amp;").replace("<","&lt;")
             .replace(">","&gt;").replace('"',"&quot;"))
```

### Trigger request
```
GET /oauth/authorize?client_id=<attacker-owned>&redirect_uri=<registered>&state=x&code_challenge=y HTTP/1.1
Host: <hub>
```
served while the subsystem is suspended (admin) or down (developer stops their own service).

### Payloads
- Redirect/phishing: subsystem name = `<meta http-equiv="refresh" content="0;url=https://evil.example/phish">`
- Defacement overlay: `</div><h1 style="position:fixed;inset:0;background:#fff;z-index:9999">Login: <a href="https://evil.example">continue</a></h1>`

### What the attacker gets
Attacker-controlled markup rendered in the victim's browser under the **trusted Hub origin**. CSP (`default-src 'self'`, no `unsafe-inline`) blocks `<script>`/`onerror=`/external loads, so **no JS execution**; the residual is a `<meta refresh>` redirect to a phishing page and page defacement.

### Baseline comparison
Keycloak/Ory render template values through auto-escaping template engines; server-built HTML with raw interpolation of tenant-controlled names is exactly the case those engines escape by default. Here one function escapes and two do not — an omission, not a design choice.

### Fix
```python
import html as _html
def _suspended_html(subsystem_name: str) -> str:
    safe_name = _html.escape(subsystem_name, quote=True)
    # interpolate {safe_name}
def _maintenance_html(subsystem_name: str, health: dict) -> str:
    safe_name = _html.escape(subsystem_name, quote=True)
    error = _html.escape(health.get("error") or "subsystem ไม่ตอบ health check", quote=True)
    # interpolate {safe_name} and {error}
```

---

## Finding 2 — Blind SSRF via developer-configured webhook URL

### Data flow (input → sink)
1. **Input / storage** — `hub/backend/app/routers/developer.py:333` (register) and `:1150` (PATCH) — developer sets `Subsystem.access_revoke_webhook_url` to an arbitrary URL.
2. **Resolve** — `_resolve_webhook_url`, `hub/backend/app/services/webhook_dispatcher.py:97` — uses the override URL directly; no host validation.
3. **Translate** — `_translate_for_docker`, `webhook_dispatcher.py:61` — in production returns the URL unchanged (`if settings.app_env == "production": return url`); in dev only rewrites `localhost`/`127.0.0.1`. **No private-range or allowlist filter on either path.**
4. **Sink** — `send_access_updated` / `send_access_revoked` / restore, `webhook_dispatcher.py:197,275,350` — `with httpx.Client(timeout=5.0) as client: client.post(url, content=body, headers={signature})`.

### Trigger
```
PATCH /developer/subsystems/{id}
Authorization: Bearer <developer JWT>
{ "access_revoke_webhook_url": "http://169.254.169.254/latest/meta-data/" }
```
then cause an access change on the owned subsystem (add+revoke a whitelist user) to fire dispatch.

### Internal targets reachable from the Hub container
- `http://169.254.169.254/…` (cloud metadata, if deployed on a cloud VM)
- `http://hub-postgres:5432/`, `http://hub-redis:6379/`, other compose services
- any RFC1918 host routable from the backend

### What the attacker gets
A Hub-originated POST to the chosen internal address. Response body is **not** reflected to the attacker and the payload is HMAC-signed, so this is **blind** SSRF: internal-network/port reachability inference (success vs timeout vs connection-refused, observable via the Hub's webhook alert/log state) and forced internal POST traffic — not response exfiltration.

### Baseline comparison
Mature webhook senders (GitHub, Stripe, Keycloak admin webhooks) resolve and block private/link-local ranges and/or pin to a verified domain before sending. That egress filter is the missing layer here.

### Fix
```python
import ipaddress, socket
from urllib.parse import urlparse
def _is_safe_public_url(url: str) -> bool:
    p = urlparse(url)
    if settings.app_env == "production" and p.scheme != "https":
        return False
    try:
        for info in socket.getaddrinfo(p.hostname or "", None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except Exception:
        return False
    return True
```
Call after `_resolve_webhook_url`; skip+log dispatch when unsafe, except the intentional dev docker-service map (guard that behind `app_env != "production"`).
