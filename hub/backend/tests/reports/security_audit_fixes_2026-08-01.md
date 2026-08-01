# Security Audit run-1 — Fixes for Findings #1 & #2 (2026-08-01)

Fixes for the two MEDIUM findings from `docs/security-audit/run-1/`. TDD (RED → GREEN).
Test files (permanent): `tests/test_html_injection_status_pages.py`, `tests/test_webhook_ssrf.py`.

## Finding #1 — Stored HTML injection on subsystem status pages (MEDIUM → fixed)

**Defect:** `_suspended_html` / `_maintenance_html` in `app/routers/oauth.py` interpolated
developer-controlled `subsystem.name` (and health `error`) into an f-string with no
HTML-escaping, while the sibling `_login_chooser_html` already escaped it. Served by the
public `/oauth/authorize` when a subsystem is suspended/down → HTML injection (CSP blocks
JS, but `<meta refresh>` redirect / defacement remained).

**Fix:** added module-level `import html`; escape `subsystem_name` (both functions) and the
health `error` + `checked_at` (maintenance) via `html.escape(..., quote=True)` before
interpolation.

**RED (before):**
```
tests/test_html_injection_status_pages.py  4 failed, 1 passed
  (raw <script>alert(1)</script> present in _suspended_html / _maintenance_html output)
```
**GREEN (after):**
```
tests/test_html_injection_status_pages.py  5 passed
  - test_suspended_html_escapes_name
  - test_suspended_html_escapes_meta_refresh
  - test_maintenance_html_escapes_name
  - test_maintenance_html_escapes_health_error
  - test_login_chooser_still_escapes_regression
```

## Finding #2 — Blind SSRF via developer webhook URL (MEDIUM → fixed)

**Defect:** `_resolve_webhook_url` / `_translate_for_docker` in
`app/services/webhook_dispatcher.py` returned the developer-set `access_revoke_webhook_url`
with no allowlist / private-range block (prod passed it through unchanged) → Hub could be
made to POST to `169.254.169.254`, `hub-postgres:5432`, RFC1918, etc.

**Fix:** added `_is_safe_webhook_url` (prod: require https + reject
private/loopback/link-local/reserved/multicast/unspecified via `socket.getaddrinfo` +
`ipaddress`; dev: allow localhost/docker targets — intentional, not the threat model) and a
`_guard` wrapper applied at both return points of `_resolve_webhook_url`. All 3 senders
(`send_access_updated/revoked/restored`) already skip on a `None` URL, so the guard is
centralized. Fail-closed: unresolvable host / bad scheme → blocked + logged.
Residual note (documented in code): TOCTOU/DNS-rebinding between check-time resolve and
httpx request-time resolve; range check is the primary control.

**RED (before):**
```
tests/test_webhook_ssrf.py  10 failed, 1 passed
  (_is_safe_webhook_url missing; _resolve_webhook_url returned metadata/internal URLs)
```
**GREEN (after):**
```
tests/test_webhook_ssrf.py  11 passed
  - prod blocks: 169.254.169.254, 127.0.0.1, 10.0.0.5, 192.168.1.10, non-https, ftp
  - prod allows public https; dev allows localhost
  - _resolve_webhook_url returns None for metadata / internal-service in prod
  - _resolve_webhook_url allows public https in prod
```

## Regression
```
docker compose exec hub-backend pytest \
  tests/test_html_injection_status_pages.py \
  tests/test_webhook_ssrf.py \
  tests/test_client_ip_security.py -q
=> 30 passed
import smoke: app.routers.oauth, app.services.webhook_dispatcher → imports OK
py_compile: OK
```

## Files changed
- `app/routers/oauth.py` — `import html`; escape name/error in `_suspended_html` + `_maintenance_html`.
- `app/services/webhook_dispatcher.py` — `import ipaddress, socket`; add `_is_safe_webhook_url` + `_guard`; gate both `_resolve_webhook_url` returns.
- `tests/test_html_injection_status_pages.py` (new), `tests/test_webhook_ssrf.py` (new).

Finding #3 (LOW, admin-only LIKE wildcard) left as-is per scope ("แก้ #1 + #2").

---

## Aikido scan follow-up (dependency findings) — 2026-08-01

Triaged Aikido results; fixed the two real/actionable items ("ทำ #1 + #2 ก่อน").

### #1 — Next.js CVE-2025-29927 (middleware auth bypass) → fixed
- `hub/frontend/package.json`: `next 14.2.15 → 14.2.35` (latest 14.2.x; fix ships in ≥14.2.25).
- `npm install` on host updated `package-lock.json` (node_modules/next = 14.2.35, verified).
- In-context severity MEDIUM: middleware.ts gates ADMIN_PATHS/DEV_PATHS, but real data authz is enforced at the backend (`require_hub_admin`/`require_developer` on every `/api/proxy` call), so the bypass defeated only the UX gate. Bump closes the CVE regardless.
- **Container note:** compose mounts `./hub/frontend:/app` with an anonymous `/app/node_modules` volume, so the running `hub-frontend` container keeps the image's 14.2.15 until `docker compose build hub-frontend` (or rebuild). Host package.json+lockfile now at 14.2.35.

### #2 — Frontend missing CSP/HSTS → fixed
- `hub/frontend/next.config.js`: added `headers()` returning CSP + HSTS(prod) + X-Frame-Options DENY + X-Content-Type-Options nosniff + Referrer-Policy + Permissions-Policy for `/:path*`.
- CSP tuned to the app: `style-src`/`font-src` allow Google Fonts; `img-src data: blob:` + `worker-src blob:` for amcharts5/qrcode; `connect-src 'self'` (all client fetches go through same-origin `/api/proxy` — verified no direct browser→backend fetch). dev adds `'unsafe-eval'` + `ws:` (React Fast Refresh/HMR); prod adds `upgrade-insecure-requests` + HSTS. `'unsafe-inline'` on script-src is required (Next App Router inline hydration, no nonce via static headers).
- **Live verification** (dev container restarted): `curl http://localhost:3000/login` returns all 5 headers; browser console shows **no CSP violations**; login page renders fully (Google login / credentials-setup / passkey-recovery intact).

### #3 — starlette CVEs on subsystems + ml-service → fixed
- `hub/subsystem-dorm|library|grade/requirements.txt` + `ml-service/requirements.txt`:
  `fastapi 0.115.0 → 0.118.0` and added explicit `starlette==0.48.0` pin — mirrors the
  Hub's known-good trio (closes CVE-2024-47874 / CVE-2025-54121 / CVE-2025-62727 / PYSEC-2026-161).
- **Verified:** `pip install --dry-run -r requirements.txt` (dorm) in `python:3.11-slim` →
  PIP_EXIT=0 (full set resolves with fastapi 0.118 + starlette 0.48 + pydantic 2.9.2, no conflict).
- **Rebuild note:** subsystem + ml containers must be rebuilt to pick up the pins
  (`docker compose -f docker-compose.dorm.yml build` etc.).

### #4 — Go toolchain EOL + x/crypto bump → fixed
- `hub/sdk/auth-proxy/go.mod`: `go 1.22 → 1.23`; `golang.org/x/crypto v0.29.0 → v0.31.0`
  (+ `x/sys → v0.28.0`) via `go get` + `go mod tidy` (go.sum regenerated) in `golang:1.23`.
- Note: CVE-2024-45337 path (`x/crypto/ssh`) was never present — bump is hygiene + clears the
  scanner flag.
- **Verified** in `golang:1.23`: `go build ./...` BUILD_OK, `go vet ./...` VET_OK,
  `go test ./...` → all packages pass (auth / handler / session).

### Triaged as noise (no action)
- `golang.org/x/crypto` "authz bypass" (CVE-2024-45337) — **false positive**: `x/crypto/ssh` not imported.
- "CSP not set / HSTS missing @ github.com" — misattributed to GitHub's own pages; Hub backend already sets CSP (and frontend now does too, see #2).

Not committed — user commits.
