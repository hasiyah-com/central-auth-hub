# Central Auth Hub — Auth Proxy (Sidecar)

**Zero-code auth for any HTTP service.**

`cah-auth-proxy` is a Go reverse-proxy sidecar that handles **all** OAuth 2.0 + PKCE + JWT verification before forwarding requests to your upstream service. Subsystem dev writes **0 lines of auth code** — just reads HTTP headers like `X-Hub-User-Email`.

Works with any language / framework: PHP, Node, Python, Go, Ruby, Java, .NET, etc.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Browser                                                    │
└────────────────────────────────────────┬───────────────────┘
                                         │ HTTPS
                                         ▼
┌────────────────────────────────────────────────────────────┐
│  cah-auth-proxy:8000 (Go binary, distroless, ~17MB)         │
│  ────────────────────────────────────────────────────────  │
│  1. Strip incoming X-Hub-User-* headers (security)          │
│  2. Read sealed cookie → verify JWT (jwx + JWKS auto-refresh)│
│  3. No session → 302 to /cah-auth/login                     │
│  4. Inject:                                                 │
│       X-Hub-User-Sub:        <uuid>                        │
│       X-Hub-User-Email:      user@uni.ac.th                │
│       X-Hub-User-Name:       ชื่อ สกุล                       │
│       X-Hub-User-Role:       resident                       │
│       X-Hub-User-Faculty:    วิศวกรรม                       │
│       X-Hub-User-Student-ID: 650001                         │
│  5. Reverse proxy → upstream                               │
└────────────────────────────────────────┬───────────────────┘
                                         │ HTTP (internal)
                                         ▼
┌────────────────────────────────────────────────────────────┐
│  Your subsystem (PHP / Node / Python / etc.)                │
│  Just read $_SERVER['HTTP_X_HUB_USER_EMAIL']                │
└────────────────────────────────────────────────────────────┘
```

---

## ⚙️ Environment variables

| Var | Default | Description |
|---|---|---|
| `CAH_HUB_URL` | `http://hub-backend:8000` | Hub's base URL (Discovery loaded from here) |
| `CAH_CLIENT_ID` | **required** | Your subsystem's client_id from Hub |
| `CAH_CLIENT_SECRET` | **required** | Your subsystem's client_secret |
| `CAH_REDIRECT_URI` | **required** | Public URL = `https://your-app/cah-auth/callback` |
| `CAH_UPSTREAM` | **required** | Internal URL of your subsystem (e.g. `http://my-app:8080`) |
| `CAH_SCOPE` | `openid profile email` | Space- or comma-separated |
| `CAH_LISTEN` | `:8000` | Listen address |
| `CAH_PATH_PREFIX` | `/cah-auth` | Where proxy mounts its endpoints |
| `CAH_COOKIE_NAME` | `cah_session` | Session cookie name |
| `CAH_COOKIE_SECRET` | auto (dev) | Hex-encoded 32-byte HMAC key for cookie auth |
| `CAH_COOKIE_ENCRYPT_KEY` | none | Hex 32-byte key for cookie encryption (optional) |
| `CAH_COOKIE_MAX_AGE` | `1h` | Session lifetime (Go duration format) |
| `CAH_JWKS_CACHE_TTL` | `10m` | JWKS refresh interval |
| `CAH_HTTP_TIMEOUT` | `10s` | Backend HTTP timeout |
| `CAH_WEBHOOK_SHARED_KEY` | none | HMAC key for Hub webhooks |
| `CAH_WEBHOOK_MAX_AGE_SEC` | `300` | Replay window for webhook timestamp |
| `CAH_STRIP_INCOMING_AUTH_HEADERS` | `true` | Strip `X-Hub-User-*` from incoming requests |

---

## 🚀 Quick start with Docker Compose

```yaml
services:
  my-subsystem:
    image: php:8.1-apache
    volumes:
      - ./htdocs:/var/www/html

  auth-proxy:
    image: cah-auth-proxy:latest
    environment:
      CAH_HUB_URL: http://hub-backend:8000
      CAH_CLIENT_ID: cli_xxx
      CAH_CLIENT_SECRET: sec_xxx
      CAH_REDIRECT_URI: http://localhost:8080/cah-auth/callback
      CAH_UPSTREAM: http://my-subsystem
      CAH_COOKIE_SECRET: ${COOKIE_SECRET}    # hex 32 bytes
    ports:
      - "8080:8000"
    depends_on:
      - my-subsystem
    networks:
      - cah-net

networks:
  cah-net:
    external: true
```

### Dev code — 6 lines of PHP

```php
<?php
$email = $_SERVER['HTTP_X_HUB_USER_EMAIL'] ?? null;
$name  = $_SERVER['HTTP_X_HUB_USER_NAME']  ?? null;
$role  = $_SERVER['HTTP_X_HUB_USER_ROLE']  ?? null;
if (!$email) { http_response_code(500); die('No auth context'); }
echo "<h1>Hello $name ($email)</h1><p>Role: $role</p>";
```

**Zero OAuth code.** Proxy handles everything.

---

## 📡 Endpoints exposed by proxy

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Liveness probe (always 200) |
| `/cah-auth/login` | GET | Start OAuth flow (set temp cookie, redirect to Hub) |
| `/cah-auth/callback` | GET | Receive code → exchange → verify JWT → set session |
| `/cah-auth/logout` | GET | Clear session, redirect to `?return_to=` |
| `/cah-auth/webhook/access-revoked` | POST | HMAC-signed webhook from Hub |
| `/*` | ANY | Auth-gated reverse proxy to upstream |

---

## 🔐 Security model

| Concern | Defense |
|---|---|
| CSRF state | `subtle.ConstantTimeCompare` |
| Auth code interception | PKCE S256 (RFC 7636) |
| JWT tampering | RS256 + JWKS via `lestrrat-go/jwx` with auto key-rotation |
| Audience confusion | strict `aud` check |
| Cookie theft | `securecookie` (HMAC + optional AES) + HttpOnly + SameSite=Lax + Secure (HTTPS) |
| **Header forgery** | **Always strip `X-Hub-User-*` from incoming** |
| Webhook spoofing | HMAC-SHA256 + replay protection |
| Open redirect (return_to) | Only accept paths starting with `/` |
| Long-lived sessions | 1h default + JWT exp respected |
| Revocation | webhook updates in-memory blacklist, applied next request |

---

## 📐 Standards

- OpenID Connect Discovery 1.0 (auto-loaded)
- RFC 6749 (OAuth 2.0)
- RFC 7636 (PKCE) — Appendix B vector verified
- RFC 7517 (JWK) / RFC 7519 (JWT)
- Industry pattern: same architecture as **oauth2-proxy** / **Pomerium** / **Cloudflare Access**

---

## 🛠️ Build from source

```bash
# Local Go build
go build -o cah-auth-proxy ./cmd

# Docker (multi-stage → distroless)
docker build -t cah-auth-proxy .

# Image size: ~17 MB
docker images cah-auth-proxy
```

---

## 📜 License

MIT
