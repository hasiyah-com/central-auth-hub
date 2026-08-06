# Fixes — audit run-2 #4 (Go open redirect), #5 (grade webhook), #7 (Go concurrent-map)

Date: 2026-08-03. Go verified in `golang:1.23` (build + vet + test `-race`).

## #4 — Go auth-proxy open redirect via return_to (MEDIUM) → fixed
`internal/handler/handler.go` — the `return_to` guard `HasPrefix(target,"/")` accepted
`//evil.com` (protocol-relative → `net/http.Redirect` emits verbatim → off-origin).
Added `safeReturnTo()` (rejects `//` and `/\` in addition to non-`/`), used at both the
callback and logout redirects.
Test: `TestSafeReturnTo` — `//evil.com`, `//evil.com/x`, `/\evil.com`, `https://evil`,
`javascript:x`, `""` all → `/`; `/dashboard`, `/a/b?x=1` preserved.

## #7 — Go auth-proxy concurrent-map race on revokedAt (LOW) → fixed
`revokedAt map[string]int64` was written in `HandleWebhook` and read in `HandleProxy` with
no mutex → Go fatal `concurrent map read and map write` (unrecoverable → proxy crash).
Added `revokedMu sync.RWMutex`; write under `Lock`, read under `RLock`.
Test: `TestRevokedMapConcurrent` (8 webhook writers + 8 readers) passes under `-race`.

## #5 — Grade subsystem webhook not bound to client_id (LOW) → fixed
`hub/subsystem-grade/app/webhook.py` `_verify` verified HMAC + timestamp but never checked
`client_id`; the Hub signs all subsystems' webhooks with one shared key, so a webhook signed
for another subsystem could be replayed to grade (forced re-auth / mass logout). dorm/library
already check this. Added, after JSON parse:
```python
pcid = payload.get("client_id")
if pcid and pcid != settings.grade_client_id:
    raise HTTPException(status_code=400, detail="client_id mismatch")
```
py_compile OK. (Grade subsystem has no live container in this env; change mirrors the proven
dorm/library guard verbatim.)

## Verification
- Go: `go build ./...` BUILD_OK · `go vet ./...` VET_OK · `go test -race ./...` all packages pass.
- Python (Hub regression, all run-2 fixes together): `pytest test_force_logout_refresh
  test_passkey_student_block test_access_policy_approval test_passkey_login
  test_token_revocation test_refresh_token` → **54 passed**.

## Deferred (recommended, not implemented) — see docs/security-audit/run-2/REPORT.md
- **#6** webhook timestamp not signed — lockstep 6-component protocol change; outage risk on
  untestable subsystems; idempotent-event / 300s-window impact. Do as one coordinated change.
- **#8** step-up grant not action-bound — feature-sized; touches the heavily-tested
  critical-action core; non-boundary defense-in-depth.

## Files changed
- `hub/sdk/auth-proxy/internal/handler/handler.go` (safeReturnTo + revokedMu)
- `hub/sdk/auth-proxy/internal/handler/handler_test.go` (TestSafeReturnTo, TestRevokedMapConcurrent)
- `hub/subsystem-grade/app/webhook.py` (client_id bind)

Not committed — user commits.
