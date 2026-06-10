# Passkey Phase 2 — Login Flow

**Date**: 2026-06-10
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 2 — Login Flow (email-first + counter regression scaffold)
**Status**: ✅ ALL PASS (11/11 Phase 2, 34/34 Phase 0+1+2 combined)

---

## Scope

Phase 2 adds the **login half** of the Passkey ceremony — assertion verify +
JWT issuance. Backbone for:

- **Decision #1** — Email-first (no Discoverable Credential yet)
- **Decision #2** — User Verification REQUIRED
- **Decision #9 + Improvement #10** — Lenient counter regression (log + audit + flag in response, no block)
- **Improvement #1** — `/login/discoverable/start` reserved (501) for Phase 7

LINE button hidden per Q3 (commented out, code preserved in git).

---

## Files changed

### Backend — Modified
- `hub/backend/app/services/webauthn_service.py`
  - + `generate_authentication_options` / `verify_authentication_response` imports
  - + `_auth_challenge_key_email()` helper
  - + `AuthResult` class (user + credential + counter_regression flag)
  - + `auth_begin()` — opaque on unknown email (anti-enumeration)
  - + `auth_complete()` — full verify + lenient counter handling + last_used update
- `hub/backend/app/routers/passkey.py`
  - + `/auth/passkey/login/start` (rate-limit 10/min)
  - + `/auth/passkey/login/finish` (rate-limit 20/min) — issues JWT + LoginSession
  - + `/auth/passkey/login/discoverable/start` → 501 placeholder (Improvement #1)
  - + 3 audit events: PASSKEY_LOGIN_SUCCESS / _FAILED / _COUNTER_REGRESSION

### Backend — Created
- `hub/backend/tests/test_passkey_login.py` (11 tests)

### Frontend — Modified
- `hub/frontend/lib/passkey.ts` (~90 added lines)
  - + `LoginResult` type
  - + `decodeRequestOptions()` + `encodeAssertionCredential()` helpers
  - + `loginWithPasskey()` — full assertion ceremony
- `hub/frontend/app/auth/login/page.tsx`
  - + Passkey button (conditional on `isPasskeySupported()`)
  - + Inline email-first dialog (no separate page — better UX than plan v3 specified)
  - + Friendly Thai error messages for common error codes
  - + LINE button commented out (Q3 decision)

---

## API endpoints registered

```
POST /auth/passkey/login/start
POST /auth/passkey/login/finish
POST /auth/passkey/login/discoverable/start  → 501 Not Implemented (Phase 7+)
```

Combined Passkey endpoint count: **7 endpoints** in OpenAPI.

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_login.py -v
```

### Result

```
collected 11 items

tests/test_passkey_login.py::test_auth_begin_unknown_email_does_not_enumerate PASSED [  9%]
tests/test_passkey_login.py::test_auth_begin_blank_email_raises PASSED   [ 18%]
tests/test_passkey_login.py::test_auth_begin_populates_allow_credentials PASSED [ 27%]
tests/test_passkey_login.py::test_auth_begin_excludes_revoked PASSED     [ 36%]
tests/test_passkey_login.py::test_auth_begin_stores_challenge_in_redis PASSED [ 45%]
tests/test_passkey_login.py::test_auth_complete_blank_email_raises PASSED [ 54%]
tests/test_passkey_login.py::test_auth_complete_missing_credential_raises PASSED [ 63%]
tests/test_passkey_login.py::test_auth_complete_no_challenge_in_redis_raises PASSED [ 72%]
tests/test_passkey_login.py::test_auth_complete_unknown_user_returns_opaque_401 PASSED [ 81%]
tests/test_passkey_login.py::test_auth_complete_bad_rawid_raises PASSED  [ 90%]
tests/test_passkey_login.py::test_auth_complete_unknown_credential_for_user_returns_401 PASSED [100%]

============================== 11 passed in 1.17s ==============================
```

### Combined Phase 0 + 1 + 2

```
============================== 34 passed in 14.73s ==============================
```

---

## Test Coverage Breakdown — Phase 2

### Anti-enumeration / opaque error invariants (4 tests)

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_auth_begin_unknown_email_does_not_enumerate` | Unknown email still returns options (empty allowCredentials) — no 404 leak |
| 2 | `test_auth_complete_unknown_user_returns_opaque_401` | Same error code (`invalid_credential`) for wrong email AND wrong cred — anti-enum |
| 3 | `test_auth_begin_excludes_revoked` | Revoked Passkeys aren't advertised in allowCredentials |
| 4 | `test_auth_begin_stores_challenge_in_redis` | Server-side state, key by email (challenge unguessable client-side) |

### Input validation (4 tests)

| # | Test | What it verifies |
|---|---|---|
| 5 | `test_auth_begin_blank_email_raises` | Empty email → 400 |
| 6 | `test_auth_complete_blank_email_raises` | Empty email in finish → 400 |
| 7 | `test_auth_complete_missing_credential_raises` | None credential → 400 |
| 8 | `test_auth_complete_bad_rawid_raises` | Malformed b64 → 400 |

### Lookup correctness (3 tests)

| # | Test | What it verifies |
|---|---|---|
| 9 | `test_auth_begin_populates_allow_credentials` | Active cred → allowCredentials w/ transports |
| 10 | `test_auth_complete_no_challenge_in_redis_raises` | Challenge expired → 400 (B9 atomic getdel) |
| 11 | `test_auth_complete_unknown_credential_for_user_returns_401` | Right user, wrong rawId → 401 invalid_credential |

---

## Security Checks

- ✅ **B9 (atomic getdel)** — `auth_complete` consumes challenge with `getdel` (prevents replay)
- ✅ **B6 (log → commit → raise)** — `login_finish` audits PASSKEY_LOGIN_FAILED + commits before re-raising
- ✅ **B20 (get_client_ip)** — credential.last_used_ip populated via deps helper
- ✅ **Anti-enumeration**:
  - `auth_begin` for unknown email → still returns options (empty allowCredentials)
  - `auth_complete` opaque 401 for both wrong-email AND wrong-credential paths
- ✅ **UV REQUIRED (Decision #2)** — enforced both in `generate_authentication_options` and `verify_authentication_response(require_user_verification=True)`
- ✅ **Rate limiting** — `/login/start` 10/min, `/login/finish` 20/min (per-IP, slowapi)
- ✅ **Counter regression (Improvement #10)** — lenient: audit + bump counter, NOT raise (avoids cloud-sync false positives)
- ✅ **JWT issuance** — `create_access_token` (aud=hub.internal, RS256, jti for revocation)
- ✅ **LoginSession row** — IP + UA + decision="allow" + jti recorded (ML training feed)
- ✅ **No plaintext credential ever logged** — only credential_id UUID in metadata
- ⚠️ **Discoverable Credential disabled** — `/login/discoverable/start` returns 501 (Phase 7 — Improvement #1)

---

## Reproducible

```bash
# Backend tests
docker compose exec -T hub-backend pytest tests/test_passkey_login.py -v

# Combined
docker compose exec -T hub-backend pytest \
    tests/test_stepup_cache.py \
    tests/test_critical_action_policy.py \
    tests/test_passkey_register.py \
    tests/test_passkey_login.py -v
# → 34 passed

# Verify endpoints
curl -s http://localhost:8000/openapi.json | python -c \
  "import json,sys; d=json.load(sys.stdin); print([p for p in d['paths'] if 'passkey' in p.lower()])"

# Discoverable returns 501
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/auth/passkey/login/discoverable/start
# → 501

# Frontend type check
docker compose exec -T hub-frontend npx tsc --noEmit 2>&1 | grep -E "lib/passkey|auth/login"
# → no errors
```

---

## Manual smoke test (operator)

Pre-req: complete Phase 1 manual test first (have a Passkey registered).

1. **Logout** (delete cookie or clear) → go to `/auth/login`
2. ✅ See "🔑 Sign in with Passkey" button (emerald)
3. Click button → email dialog opens (emerald-tinted)
4. Type your email → click "ดำเนินการต่อ"
5. Browser prompts TouchID / Windows Hello / Passkey choice
6. After verify → redirect to `/dashboard` (or `/developer/subsystems` if not admin)
7. DB verify:
   ```sql
   SELECT action, created_at FROM audit_logs
   WHERE action LIKE 'passkey_login%' ORDER BY created_at DESC LIMIT 3;
   -- Expected: passkey_login_success
   ```
8. DB verify:
   ```sql
   SELECT last_used_at, last_used_ip, sign_count FROM passkey_credentials;
   -- Expected: last_used_at = now, IP populated, sign_count > 0
   ```
9. **Failure paths to manually verify:**
   - Wrong email → "ไม่พบ Passkey ที่ใช้ได้กับ email นี้" (opaque)
   - Cancel TouchID → "Passkey ceremony failed: NotAllowedError..."
   - Wait 6 min between begin and finish → "Session หมดอายุ"

---

## Compliance

- **WebAuthn L3 §7.2** — assertion verification ceremony
- **NIST SP 800-63B §5.1.7** — phishing-resistant authenticator (cryptographic, channel-bound)
- **OWASP ASVS V2.1.5** — error messages must not enumerate accounts
- **RFC 6749 §4.4** — token issuance (Hub JWT after Passkey verify)

---

## Phase 2 — Acceptance criteria

- [x] `auth_begin` + `auth_complete` in `webauthn_service.py`
- [x] `/login/{start,finish}` endpoints registered + rate-limited
- [x] `/login/discoverable/start` returns 501 (API-ready for Phase 7)
- [x] JWT issued + LoginSession row created on success
- [x] PASSKEY_LOGIN_{SUCCESS,FAILED,COUNTER_REGRESSION} audit constants defined
- [x] `loginWithPasskey()` browser helper in `lib/passkey.ts`
- [x] Login page has conditional Passkey button + inline email dialog
- [x] LINE button commented out (Q3 decision)
- [x] 11 Phase 2 tests pass + 34/34 combined with Phase 0+1
- [x] Anti-enumeration verified (3 tests)
- [x] Counter regression scaffold in place (audited but lenient)

---

## Next: Phase 3 — Lifecycle Management (~3 hours)

- [ ] GET /account/passkeys (list with last_used, country)
- [ ] PATCH /account/passkeys/{id} (rename + nickname_history append)
- [ ] DELETE /account/passkeys/{id} (last-Passkey guard + critical action gate)
- [ ] Full security/page.tsx UI with table, rename inline, delete confirm
- [ ] Sidebar nav entry "/account/security"
- [ ] `PasskeyCard.tsx` component
- [ ] ~6 tests
