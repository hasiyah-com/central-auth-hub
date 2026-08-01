# Architecture Summary — Central Auth Hub (Phase 1)

## What this is
Centralized **Identity & Permission platform** (senior project) for a university. It is an **OAuth 2.0 Authorization Server / OIDC IdP** plus admin console, with two+ relying-party subsystems. This is the crown-jewel case: the app *is* the auth boundary, so auth-protocol, token-verification, and access-control bugs are the highest-value targets. Comparable baselines: Keycloak, Ory Hydra/Kratos, Authentik, Auth0 (self-hosted IdPs). Calibrate against how those handle redirect_uri allowlisting, PKCE, code single-use, JWT claim checks, session rotation.

## Tech stack
- **Hub backend** (port 8000): Python 3.11, FastAPI, SQLAlchemy, Authlib (Google OIDC), python-jose (JWT RS256), slowapi (rate limit, Redis-backed), Starlette SessionMiddleware.
- **DB**: PostgreSQL 15 (hub_db). **Cache/session/one-time tokens**: Redis 7.
- **Frontend** (port 3000): Next.js 14 App Router + TS; httpOnly `hub_token` cookie + `/api/proxy/[...path]` attaches Bearer to backend.
- **Subsystems**: dorm (8001), library (8002), grade (8003) — FastAPI + Jinja2, OAuth clients, itsdangerous signed-cookie sessions. Separate Postgres each.
- **ML Verifier** (port 9000): FastAPI + IsolationForest + SHAP (Shadow Mode default).

## Trust model / actors
- **student** — OAuth to subsystems only; blocked at Hub-direct `/auth/google/callback`.
- **teacher/staff** — `require_developer`: register subsystems, manage own whitelist.
- **admin** (`is_hub_admin=True`) — `require_hub_admin`: full admin console.
- **subsystem (S2S)** — client_id + client_secret (Argon2id) to `/oauth/token`; API-key for `/roster`.
- Enforcement: `get_current_user` (HTTPBearer to JWT verify), `require_developer`, `require_hub_admin`, `gate("<action>")` (step-up cache: passkey/TOTP), `require_api_key`.

## Auth machinery (audit focus)
- **JWT**: RS256 pinned **server-side** (`algorithms=["RS256"]`), `verify_aud/iss/exp=True`. Hub-direct `aud=hub.internal`; subsystem token `aud=client_id`. `kid` header to `_public_pem_for(kid)` keyset lookup (check: traversal/injection via kid). jti revocation via Redis blacklist after decode. `jwt_service.py:295-320`.
- **OAuth flow**: `/oauth/authorize` validates `redirect_uri in subsystem.redirect_uris` (exact membership, oauth.py:144). PKCE `hmac.compare_digest`. auth_code single-use via Redis `getdel`. Multi-tab: `authreq:{hub_state}` in Redis.
- **Refresh token**: rotating opaque `{id}.{secret}`, HMAC-SHA256 stored, single-use GET-compare-DELETE. `/auth/refresh`.
- **Passkey/WebAuthn** + **TOTP** (pyotp) step-up & login; recovery ladder (backup-code / TOTP / email-OTP). Anti-enumeration: decoy `allowCredentials` (B43), recovery returns opaque True.
- **Session**: Starlette SessionMiddleware (`secret_key`, https_only in prod, SameSite=Lax, max_age 3600) for OAuth state only. Frontend `hub_token`/refresh cookies httpOnly+Lax+Secure(prod).
- **Middleware order** (main.py): SlowAPI to SecurityHeaders to RequestLogger to RequestId to Session to CORS. CORS = env allowlist (`cors_allow_origins`), `allow_credentials=True`, no wildcard (falls back to localhost:3000-3002 in dev).

## Input surfaces
- **Hub routers**: health, auth (`/auth/*` Google+LINE-legacy+refresh+logout+heartbeat+confirm-identity+credentials/setup), oauth (`/oauth/*` authorize/callback/token/continue/passkey/totp/pkce-helper[dev]/test-callback[dev]), developer (`/developer/*` subsystem CRUD + whitelist CSV/bulk + rotate-secret/api-key + transfer-owner), secret (`/secret/retrieve` HMAC token), users+admin+ml_admin (`/admin/*`), roster (API-key), oidc (`.well-known`, userinfo, introspect), passkey, totp, recovery, account_security, account_link, ip_blacklist, api_alerts.
- **Untrusted input**: HTTP bodies/queries/headers (X-Forwarded-For to `get_client_ip`, X-Real-IP), Google OIDC callback, CSV whitelist upload, developer-set webhook URLs (SSRF surface), subsystem client_secret, WebAuthn assertions.
- **Dangerous sinks**: SQLAlchemy ORM (parameterized; LIKE via `_escape_like`), Fernet encrypt (client_secret), HMAC (tokens/webhook sig), httpx (ML/webhook/health/ipsum/LINE — SSRF), Jinja2 (subsystems), file reads (GeoLite2 mmdb, ipsum offline).

## Known-good (from prior pentest this session — 2026-07-31)
Confirmed live: alg=none to 401, HS256-confusion to 401, unauth to 403, SQLi to no-500, path-traversal to 404, open-redirect(evil.com) to 400, rate-limit 429 fires (Redis), anti-enum decoy works, security headers present (CSP/XFO/nosniff), no unhandled 500s, audit trail captures failures. No backdoor/eval/exec/pickle/os.system found.
Open leads to hand hunters: **F1 SSRF** via developer webhook/health URL (internal host reachable, POST signed body); **F2** LIKE wildcard not escaped at `admin.py:2850` + `ip_blacklist.py:50`; **F3** `server: uvicorn` banner + no HSTS on backend.

## Project security rules (B-rules, from CLAUDE.md) — hunters should check adherence
B1 every endpoint has Depends · B3 hmac.compare_digest for secrets · B4 verify_aud · B6 log-commit-raise · B7 audit on failure paths · B9 Redis getdel atomic · B19 RBAC at callback+endpoint · B20 get_client_ip · B21 external fail-safe · B43 passkey enum decoy · B52 cross-domain webhook on revoke.

## Coverage note
This is run-1; no prior audit runs exist. Per skill guidance, coverage improves with repeated runs — a single run finds ~half of total issues. Recommend re-running to catch gaps.
