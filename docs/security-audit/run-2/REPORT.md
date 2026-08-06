# Security Audit — Central Auth Hub (run-2)

Date: 2026-08-03 · Method: security-audit skill (6-phase, 5 parallel hunters) · Builds on run-1

## Executive summary
Run-2 completed the multi-agent parallel hunt that run-1's quota interruption prevented, and extended coverage to surfaces run-1 never touched: the **Go `auth-proxy` SDK**, the **Node client SDK**, the **three subsystems**, and deep **business-logic / access-control** paths. It found **8 confirmed findings — 1 HIGH, 3 MEDIUM, 4 LOW** — none of which are unauthenticated RCE or a full authentication break, but the HIGH defeats an incident-response control and two MEDIUMs defeat documented authZ/RBAC boundaries. The token-verification cores (Hub, both SDKs, all subsystems) were re-verified solid: RS256 pinned, aud/iss/exp enforced, no alg-confusion/alg:none/fail-open, CSPRNG for PKCE/state, timing-safe compares. The LINE-legacy IdP path was investigated and confirmed **not reachable** (empty creds + email-scope bug both 400 before any session).

## Baseline
Compared against Keycloak/Ory (Hub) and `coreos/go-oidc`/`panva/jose`/`openid-client` (SDKs). The SDK token verification matches those libraries' correct usage. The findings cluster where mature IdPs invest specific hardening: durable session revocation (the HIGH), approval workflow on trust-surface widening (access_policy MED), and RP redirect/webhook hygiene (SDK/subsystem LOWs).

## Findings

| # | Severity | Title | Location |
|---|----------|-------|----------|
| 1 | **HIGH** | Admin force-logout doesn't revoke refresh tokens → `/auth/refresh` restores the ejected session ✅ **FIXED 2026-08-03** | `hub/backend/app/routers/admin.py:847`, `auth.py:1476` |
| 2 | **MEDIUM** | Post-approval `access_policy` widening skips admin re-approval → full directory harvest via Roster ✅ **FIXED 2026-08-03** | `developer.py:1176`, `roster.py:46` |
| 3 | **MEDIUM** | Student RBAC bypass: passkey login issues a Hub-direct JWT to students (B19 defeated) ✅ **FIXED 2026-08-03** | `hub/backend/app/routers/passkey.py:928` |
| 4 | **MEDIUM** | Open redirect in Go auth-proxy SDK via `return_to` (`//host` bypass) ✅ **FIXED 2026-08-03** | `hub/sdk/auth-proxy/internal/handler/handler.go:210` |
| 5 | LOW | Grade subsystem webhook not bound to its `client_id` → cross-subsystem replay forces re-auth/mass-logout ✅ **FIXED 2026-08-03** | `hub/subsystem-grade/app/webhook.py:35` |
| 6 | LOW | Webhook signature omits timestamp + no nonce → freshness window replayable (Hub + all receivers) ⏸ **DEFERRED** (see note) | `webhook_dispatcher.py:148` |
| 7 | LOW | Go auth-proxy concurrent-map race on `revokedAt` → proxy crash (DoS) ✅ **FIXED 2026-08-03** | `handler.go:274,327` |
| 8 | LOW | Step-up grant not bound to the action it was earned for (15-min blanket) ⏸ **DEFERRED** (see note) | `critical_action_policy.py:142` |

> **Deferred #6 / #8 — rationale.** Both are cross-cutting hardening with regression/outage risk disproportionate to LOW severity:
> - **#6** requires a *lockstep* signature-scheme change across 6 components (Hub sender + Go SDK + Node SDK + dorm/library/grade receivers); any mismatch silently breaks a subsystem's webhook channel, and the subsystems aren't integration-testable in this environment. Benefit is small (replayed events are idempotent `set_reauth`/`clear_reauth`; the window is already 300s). Recommend doing it as one coordinated change with all receivers deployed together: sign `f"{timestamp}.".encode()+body` on the Hub and verify the same on every receiver (+ optional nonce cache).
> - **#8** is feature-sized: the step-up verify endpoints don't know the target action (only `gate(action)` does), so binding the grant to an action means threading `action` through every step-up endpoint + the frontend and touching the heavily-tested critical-action core. The finding is explicitly a non-boundary defense-in-depth item (every gated action independently re-checks `require_hub_admin`/ownership). Recommend implementing as a scoped feature later (store `action` on the grant; compare in `gate()`).

### 1 — Force-logout doesn't revoke refresh tokens (HIGH) — independently verified
`force_logout_user` blacklists each session's access `jti`, sets `logout_at`, fires webhooks — but never revokes the refresh token, and `/auth/refresh` overwrites `jti`/`refresh_id` and bumps `last_seen_at` **without checking `logout_at`** (only `User.status=='active'`, unchanged by force-logout). A compromised account that's been force-logged-out calls `/auth/refresh` once with its pre-logout refresh token and is fully reinstated with fresh 30-day tokens — repeatable. Self-logout and `_revoke_all_sessions` do revoke the refresh; force-logout is the outlier. **Fix:** revoke `s.refresh_id` in the force-logout loop **and** reject refresh when `sess.logout_at is not None`. Details in `FINDINGS-DETAIL.md`.

### 2 — access_policy widening → directory harvest (MEDIUM) — found by 2 hunters
`PATCH /developer/subsystems/{id}` applies `access_policy`/`access_policy_config` immediately (no `create_change_request`), while `scope`/`redirect_uris`/`allowed_roles` require admin re-approval. A developer widens an admin-approved narrow subsystem to `access_policy="all"`, then `GET /api/v1/roster` (owned API key) dumps all ~100 users' email + user_type incl. admins — the admin's approval, the only gate on directory exposure, is retroactively invalidated. **Fix:** route policy *widening* through the pending-approval path (or reset `status→pending` on policy change).

### 3 — Student RBAC bypass via passkey login (MEDIUM)
Students may enroll a passkey by design (subsystem risk-stepup), but `login_finish`/`login_discoverable_finish` call `create_access_token(result.user)` with **no `user_type=='student'` block** — unlike the Google (auth.py:254) and LINE (auth.py:802) callbacks. A student thus obtains a Hub-direct JWT (`aud=hub.internal`), defeating the B19 layer-1 invariant. Downstream `require_developer`/`require_hub_admin` re-query `user_type`, so `/developer`/`/admin` data stays protected — but a `hub.internal` token exists for a principal that should never hold one (and the Next.js console treats the `hub_token` cookie as authenticated). **Fix:** re-apply the student block at the passkey JWT-issuance points; keep enrollment allowed.

### 4 — Go auth-proxy open redirect (MEDIUM)
`return_to` is guarded only by `HasPrefix(target,"/")`, which accepts `//evil.com`; `net/http.Redirect` emits it verbatim → browser follows off-origin. **Fix:** also reject `//` and `/\`.

### 5–8 (LOW)
- **5 Grade webhook client_id:** dorm/library reject webhooks whose `client_id` ≠ their own; grade doesn't → a shared-key-signed webhook for another subsystem replays to grade, forcing re-auth / mass-logout (self-healing DoS). Add the same guard.
- **6 Webhook replay:** Hub signs `HMAC(body)` only; timestamp is unsigned and there's no nonce, so a captured webhook replays. Sign `timestamp.body` + track nonces.
- **7 Go concurrent-map DoS:** `revokedAt` map read/written across handlers with no mutex → fatal runtime race crashes the proxy. Guard with `sync.RWMutex`.
- **8 Step-up not action-bound:** one step-up = 15-min blanket over all critical actions for that jti; bounded because each action re-checks `require_hub_admin`/ownership (`change_google` correctly re-checks method). Bind grant to action class.

## Hardening notes (not standalone findings)
- **Go auth-proxy session cookie** (`session/cookie.go`): encryption is optional (nil block key → signed-but-readable session holding the raw JWT; HttpOnly/Secure/SameSite are set, so exposure is self-only); `CAH_COOKIE_SECRET` unset silently auto-generates a per-instance key (comment promises a warning that isn't emitted). Default encryption on + fail-fast/warn in prod.
- **Naive-UTC timestamp** in dorm/library webhook receivers (`datetime.utcnow().timestamp()`) — fail-closed skew, align to grade's `datetime.now(timezone.utc)`.
- **Leftover `[LINE_DEBUG]` WARNING log** (auth.py:725-733) prints userinfo keys / `has_email` — remove (marked "ลบทีหลัง").

## What the codebase does well (re-verified in run-2)
- **Token verification everywhere** — Hub, Go SDK (jwx v2 `WithKeySet`+`WithValidate`, RSA-only keyset → alg:none/HS256-confusion fail closed), Node SDK (jose `algorithms:["RS256"]`+iss+aud), all 3 subsystems (RS256 pinned, aud=own client_id, JWKS keyset kid, no fail-open). No alg confusion, alg:none, or fail-open anywhere.
- **PKCE/state** CSPRNG (`crypto/rand`, `crypto.randomBytes`, `secrets.token_urlsafe`) + timing-safe compares (`subtle.ConstantTimeCompare`, `timingSafeEqual`, `hmac.compare_digest`). **Webhook HMAC** timing-safe on all receivers.
- **OAuth** auth-code Redis `getdel`; risk-stepup/force-enroll challenges single-use `getdel` with `kind` enforcement; recovery four-eyes protected by a DB unique constraint; `change_google` requires passkey method specifically.
- **Subsystems** consistent: session `Secure` flag + `validate_production()` fail-fast now present in all three (prior B55 resolved); IDOR-safe (ownership from signed session `hub_user_id`, never a request param); role checks on all staff/librarian/teacher routes; Jinja2 autoescape intact (no `| safe`/`Markup`).
- **Access control** — mass-assignment safe (narrow Pydantic models, no body `setattr` of `owner_user_id`/`status`/`is_hub_admin`); self-approval blocked (only admins auto-approve change-requests); whitelist finalizer filters `revoked_at`, subsystem-scoped; roster API-key scoped + Argon2 constant-time; `admin`/`ml_admin` all `require_hub_admin`.
- **LINE-legacy** unreachable; **dev endpoints** 404-gated in prod; **git history** clean (recent security fixes not reverted, no committed secrets).

## Method / phase status
- **Phase 1** — reused run-1 `architecture.md` + run-2 delta briefing (skip-list + new SDK/subsystem surfaces).
- **Phase 2** — 5 parallel hunters (SDK-auth, subsystems, business-logic, access-control-deep, chained/wildcard); all completed (quota recovered). ~786k hunter tokens.
- **Phase 3** — consolidated duplicate (access_policy found by 2 hunters → merged); each finding validated by direct source read.
- **Phase 4** — this report + `FINDINGS-DETAIL.md`.
- **Phase 5** — `findings.json` (8 confirmed, schema-validated: PASS).
- **Phase 6** — HIGH + both headline MEDIUMs independently re-verified against source by the lead; SDK/webhook LOWs verified by direct read.

## Combined run-1 + run-2 posture
Across both runs: **1 HIGH, 5 MEDIUM, 5 LOW** confirmed. run-1's 2 MEDIUM (HTML injection, webhook SSRF) are fixed+committed+pushed; run-2's HIGH + 3 MEDIUM + LOWs are open. The auth core (JWT/OAuth/PKCE/token-verification) is consistently well-built; the systemic gaps are in **revocation durability** (HIGH #1), **approval-workflow coverage** (MED #2), **RBAC issuance-point consistency** (MED #3), and **RP/webhook hygiene** (SDK/subsystem LOWs).
