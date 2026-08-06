# Architecture Summary — Central Auth Hub (Phase 1, run-2 delta)

**Read run-1's briefing first:** `docs/security-audit/run-1/architecture.md` (full trust model, JWT/OAuth machinery, routers, B-rules). This file is the run-2 DELTA: what to skip, and the surfaces run-1 did NOT reach.

## Run-1 findings — DO NOT re-report (already fixed/known)
1. **[fixed] Stored HTML injection** — `_suspended_html`/`_maintenance_html` unescaped subsystem name (oauth.py). Now escaped.
2. **[fixed] Blind SSRF** — developer webhook URL, no private-range block (webhook_dispatcher.py). Now guarded (`_is_safe_webhook_url`).
3. **[known LOW] LIKE-wildcard** — admin.py:2850 / ip_blacklist.py:50 (admin-only). Not yet fixed; don't re-report unless higher impact found.

Run-1 also VERIFIED-SOLID (don't waste time re-confirming): JWT RS256 pinned + aud/iss/exp; OIDC userinfo/introspect re-verify sig + bind aud to caller (cross-client introspect blocked); OAuth redirect_uri exact-match; PKCE hmac.compare_digest; auth-code Redis getdel; rate-limit Redis-backed; anti-enum decoys; no eval/exec/pickle/os.system; no tracked secrets.

## Run-1 was QUOTA-INTERRUPTED — these classes were barely explored (PRIMARY run-2 targets)
- **Business logic** — OAuth state machine (skip/replay steps, /oauth/continue action=skip/never), MFA/Always-2FA/force-enroll/risk-stepup bypass, recovery ladder replay/cross-user ticket, token lifecycle ordering (logout→refresh revoke, force-logout webhook B52), whitelist races, secret rotation reuse.
- **Chained / cross-component trust** — multi-step chains, second-order, scope escalation, git history (reverted fixes/commented auth).
- **Wildcard** — weird/half-finished code, undocumented endpoints, LINE-legacy IdP still in backend (reachable?), API-usable-but-frontend-never-calls.

## NEW surfaces Aikido revealed — NOT in run-1 scope at all (high-value, audit fresh)
These implement the SAME auth protocol as the Hub but on the CLIENT side — token verification, PKCE, state, session cookies. Client-side verification defects = account takeover in the relying party.

### Go `auth-proxy` SDK — `hub/sdk/auth-proxy/`
Reverse-proxy that authenticates users against the Hub for a protected app. Audit:
- `internal/auth/verify.go` — JWT verification (uses `github.com/lestrrat-go/jwx/v2`). Check: alg pinned? aud/iss/exp/nonce checked? JWKS fetch (discovery.go) — kid/jku trust? key cache poisoning?
- `internal/auth/pkce.go` — verifier/challenge generation (CSPRNG? `crypto/rand`?).
- `internal/auth/state.go` — OAuth state (CSPRNG? bound? verified?).
- `internal/session/cookie.go` — `github.com/gorilla/securecookie` (hashKey/blockKey source — hardcoded/weak? rotation?). HttpOnly/Secure/SameSite set?
- `internal/handler/handler.go` — callback flow, redirect handling (open redirect on `return`/`next`?), token exchange.
- `internal/config/config.go` — secret/key loading (env? defaults? fail-open?).

### Node client SDK — `hub/sdk/node-client/src/`
- `jwtVerifier.ts` — JWT verify (alg pin? aud/iss/exp? JWKS `jku`/`kid` trust? algorithm confusion?).
- `pkce.ts`, `state.ts` — randomness (crypto.randomBytes vs Math.random?), compare (timingSafeEqual vs ==?).
- `tokenExchange.ts` — code+verifier exchange, secret handling.
- `webhookReceiver.ts` — HMAC signature verify of Hub webhooks (timing-safe compare? replay/timestamp check? which key?).
- `discovery.ts` — OIDC discovery / JWKS fetch (TLS verify? cache poisoning?).

### Subsystems — `hub/subsystem-dorm|library|grade/`
Relying-party OAuth clients (FastAPI + Jinja2). Audit each:
- `app/services/hub_client.py` — PKCE + token exchange + JWKS verify (10-min cache). Check: JWT aud=own client_id verified? JWKS kid trust? cache poisoning? state bound?
- `app/services/session.py` — itsdangerous signed cookie (HttpOnly/SameSite/Secure per subsystem — B55 flagged a subsystem forgetting session_cookie_secure). Fixation on login?
- `app/routers/*` — business logic authz: dorm reservation (reserve/cancel/staff approve), library borrow/return/librarian, grade (teacher-only view?). IDOR on reservation/borrow/grade by another user's hub_user_id? Jinja2 autoescape on? `| safe`?
- Webhook receiver (`/internal/access-*`) — HMAC verify of Hub webhooks (timing-safe? replay?).

## Baseline
Client-side: compare Go/Node SDK verification to `coreos/go-oidc`, `panva/jose`, `openid-client`. The SDK is a RELYING PARTY — do NOT fault it for lacking redirect_uri allowlisting or code issuance (those are the Hub's job); DO fault token-verification defects (alg confusion, missing aud/iss/exp/nonce), weak PKCE/state RNG, non-timing-safe compares, and insecure session cookies.

## Coverage note
Run-2 of 2. Weight toward business-logic, the SDKs, and subsystems (run-1 covered Hub injection/authz/token/SSRF). Skip the run-1 findings above.
