# Security Audit — Central Auth Hub (run-1)

Date: 2026-08-01 · Method: security-audit skill (6-phase) · Target: `hub/backend`, `hub/frontend`, `hub/subsystem-*`, `ml-service`

## Executive summary
Central Auth Hub is a university OAuth 2.0 / OIDC Identity Provider plus admin console — the application *is* the trust boundary, so token, flow, and access-control correctness matter most. **The core auth machinery is solid.** JWT verification pins RS256 server-side and enforces aud/iss/exp; OAuth uses exact `redirect_uri` allowlisting, PKCE via `hmac.compare_digest`, and single-use auth codes (Redis `getdel`); OIDC `userinfo`/`introspect` correctly re-verify signatures and bind tokens to the calling client; rate limiting is Redis-backed and fires; anti-enumeration decoys and audit-on-failure are in place. Live attack probes (alg=none, HS256-confusion, unauth access, SQLi, path traversal, open redirect) were all rejected with no unhandled 500s. No backdoors or dangerous dynamic-execution sinks (`eval`/`exec`/`pickle`/`os.system`) exist.

This run confirmed **3 findings** — 2 MEDIUM, 1 LOW — none of which defeat authentication or the RBAC model. Both MEDIUMs require a semi-trusted **developer** account (teacher/staff/admin) as the starting point and have impact bounded by existing controls (CSP for the HTML injection; blind/no-reflection + signed body for the SSRF). They are real defects worth fixing, not auth bypasses.

> **Coverage caveat.** This is run-1 and the parallel multi-agent hunt (Phase 2) plus the adversarial-validation (Phase 3) and independent-verification (Phase 6) passes were **interrupted by an API session-quota limit** — all six hunting agents terminated early. The findings below were verified single-threaded by reading each code path directly (equivalent rigor, less breadth). Per the skill's own guidance a single run finds ~half of all issues; **re-running the full multi-agent audit after the quota resets is recommended** to reach intended coverage, especially for business-logic and cross-component chains that were only partially explored.

## Baseline
Comparable IdPs: Keycloak, Ory Hydra/Kratos, Authentik. Against that baseline the token/flow controls here are conventional and correct. The two MEDIUM classes (developer-supplied HTML rendered by the server; developer-supplied webhook URL fetched without SSRF filtering) are exactly the spots those products harden with output-escaping and egress allowlists — appropriate places to focus.

## Findings

| # | Severity | Title | Location | Status |
|---|----------|-------|----------|--------|
| 1 | MEDIUM | Stored HTML injection via unescaped subsystem name on suspended/maintenance pages | `hub/backend/app/routers/oauth.py:2718,2773` | ✅ FIXED 2026-08-01 |
| 2 | MEDIUM | Blind SSRF via developer-configured access-revoke webhook URL | `hub/backend/app/services/webhook_dispatcher.py:61,97,197` | ✅ FIXED 2026-08-01 |
| 3 | LOW | LIKE-wildcard injection in admin traffic / IP-blacklist search | `hub/backend/app/routers/admin.py:2850`, `ip_blacklist.py:50` | open (admin-only) |

> **Remediation status.** #1 and #2 fixed via TDD (RED→GREEN) — see `hub/backend/tests/reports/security_audit_fixes_2026-08-01.md`. Tests: `test_html_injection_status_pages.py` (5), `test_webhook_ssrf.py` (11), regression 30 passed. #3 (LOW, admin-only) left open.

### 1 — Stored HTML injection (MEDIUM)
`/oauth/authorize` (public) renders `_suspended_html` (status=suspended, 503) and `_maintenance_html` (health=down) with the subsystem name interpolated into an f-string **without HTML-escaping** — while the sibling `_login_chooser_html` (oauth.py:2394) *does* escape the same value and comments that it must. `subsystem.name` is set by a developer at registration; a developer can self-trigger the maintenance page by taking their own subsystem offline. The page is served to any visitor of the login link.
**Impact:** CSP (`default-src 'self'`, no `unsafe-inline`) blocks JS execution, so this is **not** XSS. Residual is HTML injection: defacement and a `<meta http-equiv="refresh">` redirect (CSP does not restrict it) enabling credential phishing under the trusted Hub origin.
**Fix:** `html.escape(subsystem_name, quote=True)` (and the health `error` string) in both functions — mirror `_login_chooser_html`. See `FINDINGS-DETAIL.md`.

### 2 — Blind SSRF via webhook URL (MEDIUM)
Access-change notifications POST to `subsystem.access_revoke_webhook_url`, a developer-set value. `_translate_for_docker` returns the URL unchanged in production and there is **no allowlist and no private/loopback/link-local block** anywhere on the path, so a developer can point it at `http://169.254.169.254/…`, `http://hub-postgres:5432/`, or any internal host and have the Hub POST to it.
**Impact:** Blind SSRF — the response is not reflected and the body is HMAC-signed, so this is internal-reachability probing and forced internal POSTs, not response exfiltration.
**Fix:** resolve the host and reject private/loopback/link-local/reserved ranges (+ require `https` in prod, ideally pin to the registered redirect_uri origin), keeping the dev docker-service map behind an explicit dev branch. See `FINDINGS-DETAIL.md`.

### 3 — LIKE-wildcard injection (LOW)
`/admin/traffic` search (admin.py:2850) and IP-blacklist search (ip_blacklist.py:50) build `%{q}%` without escaping `%`/`_`, unlike `users.py:_escape_like`. Admin-only, no data boundary crossed — a correctness/consistency defect and a deviation from the project's own LIKE-escaping rule.
**Fix:** reuse `_escape_like` + pass `escape="\\"` to `ilike`.

## Hardening notes (not findings)
- **CSRF defense-in-depth** — already addressed this session: `route.ts` now validates Origin on state-changing methods on top of SameSite=Lax + Bearer.
- **`server: uvicorn` banner** on backend responses — minor version/tech disclosure; strip with `--no-server-header` or at the reverse proxy.
- **No `Strict-Transport-Security`** on backend responses — expected in HTTP dev; ensure the production reverse proxy sets HSTS over HTTPS.
- **OIDC `introspect`/`userinfo`** — verified correct (aud re-bound to caller); no change needed.

## What the codebase does well (calibrates trust in the above)
- JWT: RS256 pinned server-side (`algorithms=["RS256"]`), `verify_aud/iss/exp=True`, jti revocation checked post-decode; `kid` resolves via keyset lookup, not a file path.
- OAuth: exact `redirect_uri` membership check, PKCE `hmac.compare_digest`, auth-code single-use via Redis `getdel`, state/hub_state bound in Redis.
- OIDC `userinfo`/`introspect` re-verify signature and bind the token to the presenting client; cross-client introspection returns `{active:false}`.
- Rate limiting Redis-backed and firing (429 at the configured limits); anti-enumeration decoy `allowCredentials`; recovery returns opaque results.
- Audit-on-failure (B7), `log→commit→raise` ordering (B6), `get_client_ip` XFF-rightmost hardening (this session), no dynamic-exec sinks, no tracked secrets (`.env`/`*.pem`/`keys/` untracked).

## Method / phase status
- **Phase 1 Recon** — `architecture.md` (complete).
- **Phase 2 Hunt** — 6 parallel agents launched (auth-protocol, access-control, injection, business-logic, SSRF/crypto, wildcard/obvious); **all terminated early on session-quota limit.** Leads they surfaced (unescaped subsystem_name; webhook SSRF; OIDC cross-client question) were completed inline.
- **Phase 3 Validate** — done inline by direct code-path reading (adversarial multi-agent pass not run — quota).
- **Phase 4 Report** — this file + `FINDINGS-DETAIL.md`.
- **Phase 5 Structured output** — `findings.json` (3 findings, schema-validated: PASS).
- **Phase 6 Independent verification** — per-finding agents not run (quota); each finding self-verified against source. **Recommend re-running Phases 2/3/6 after quota reset.**
