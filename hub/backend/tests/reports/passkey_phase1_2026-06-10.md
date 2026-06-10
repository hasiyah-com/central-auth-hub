# Passkey Phase 1 — Schema + Registration + Mandatory Backup Codes

**Date**: 2026-06-10
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 1 — Schema + Registration + Mandatory Backup Codes
**Status**: ✅ ALL PASS (10/10 Phase 1, 23/23 Phase 0+1 combined)

---

## Scope

Phase 1 implements the **first half** of the Passkey ceremony — registration only.
Auth (login) flow lands in Phase 2. This phase enforces 3 review improvements:

| Improvement | What we did |
|---|---|
| **#3 Mandatory backup codes** | Auto-generate 10 codes on first Passkey; mandatory acknowledge UX |
| **#4 Lifecycle metadata** | Schema has `device_name`, `nickname_history`, `last_used_*`, `revoked_reason` |
| **#9 Max Passkeys/user** | `register_begin` raises 400 when count >= 10 (review said 5, we use 10) |

Plus Decisions #2 (UV required), #3 (both authenticator types), #10 (counter monitoring scaffold).

---

## Files changed

### Backend — Created
- `hub/backend/app/services/webauthn_service.py` (~210 lines)
  - register_begin, register_complete, count_active, list_for_user
- `hub/backend/app/services/passkey_recovery.py` (~150 lines)
  - generate_backup_codes (10 codes, Argon2id), acknowledge, get_status
- `hub/backend/app/routers/passkey.py` (~210 lines)
  - 4 endpoints: register/{start,finish}, backup-codes/{acknowledge,status}
- `hub/backend/tests/test_passkey_register.py` (10 tests)
- `docs/sql-migrations/2026-06-10-phase1-passkey-tables.sql`

### Backend — Modified
- `hub/backend/requirements.txt` — `webauthn==2.5.0`
- `hub/backend/app/models.py` — `PasskeyCredential` + `PasskeyBackupCode` + `LargeBinary` import
- `hub/backend/app/main.py` — register router under `Passkey` tag

### Frontend — Created
- `hub/frontend/lib/passkey.ts` (~190 lines)
  - isPasskeySupported, isPlatformAuthenticatorAvailable
  - b64url ↔ ArrayBuffer helpers
  - registerPasskey ceremony
  - acknowledgeBackupCodes, fetchBackupCodesStatus
- `hub/frontend/app/(console)/account/security/page.tsx` (~150 lines)
- `hub/frontend/app/(console)/account/security/_components/BackupCodesModal.tsx` (~190 lines)
  - **Mandatory ack UX** — no X / no ESC / require copy OR download + checkbox

---

## SQL migration result

```sql
CREATE TABLE passkey_credentials   (... + 4 indexes)
CREATE TABLE passkey_backup_codes  (... + 2 indexes)
```

```
 passkey_credentials_count | passkey_backup_codes_count
---------------------------+----------------------------
                         0 |                          0
```

Schema is empty (no users have registered yet — first manual register will populate).

---

## API endpoints registered

```
POST /account/passkeys/register/start
POST /account/passkeys/register/finish
POST /account/passkeys/backup-codes/acknowledge
GET  /account/passkeys/backup-codes/status
```

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_register.py -v
```

### Result

```
collected 10 items

tests/test_passkey_register.py::test_register_begin_returns_proper_options PASSED [ 10%]
tests/test_passkey_register.py::test_register_begin_enforces_max PASSED  [ 20%]
tests/test_passkey_register.py::test_count_active_excludes_revoked PASSED [ 30%]
tests/test_passkey_register.py::test_generate_backup_codes_format_and_count PASSED [ 40%]
tests/test_passkey_register.py::test_backup_code_argon2id_verify_round_trip PASSED [ 50%]
tests/test_passkey_register.py::test_generate_twice_without_rotate_raises PASSED [ 60%]
tests/test_passkey_register.py::test_rotate_increments_generation PASSED [ 70%]
tests/test_passkey_register.py::test_acknowledge_marks_unused_codes PASSED [ 80%]
tests/test_passkey_register.py::test_get_status_low_threshold PASSED     [ 90%]
tests/test_passkey_register.py::test_get_status_zero_when_no_codes PASSED [100%]

============================= 10 passed in 11.69s ==============================
```

### Combined Phase 0 + Phase 1

```
============================= 23 passed in 11.11s ==============================
```

---

## Test Coverage Breakdown

### `test_passkey_register.py` — 10 tests

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_register_begin_returns_proper_options` | options.rp.id=localhost, UV=required, residentKey=preferred, no attachment restriction |
| 2 | `test_register_begin_enforces_max` | count >= max → 400 max_passkeys_exceeded (Improvement #9) |
| 3 | `test_count_active_excludes_revoked` | revoked_at IS NOT NULL ignored from count |
| 4 | `test_generate_backup_codes_format_and_count` | 10 codes, AB3D-7K9P format, no ambiguous chars |
| 5 | `test_backup_code_argon2id_verify_round_trip` | plaintext verifies against exactly one hash |
| 6 | `test_generate_twice_without_rotate_raises` | second call w/o rotate=True → RuntimeError |
| 7 | `test_rotate_increments_generation` | rotate=True → new gen, old + new coexist |
| 8 | `test_acknowledge_marks_unused_codes` | acknowledged_at set on all 10 unused rows |
| 9 | `test_get_status_low_threshold` | 6 used → low=False; 7 used → low=True (Improvement #7) |
| 10 | `test_get_status_zero_when_no_codes` | generation=0, total=0, low=False edge case |

---

## Security checks

- ✅ **B6 (log → commit → raise order)** — router's register_finish logs PASSKEY_REGISTER_FAILED *before* re-raising HTTPException
- ✅ **B9 (atomic getdel for one-time tokens)** — register_complete uses Redis `getdel` for challenge (prevents replay)
- ✅ **B20 (get_client_ip)** — all audit `log_action` calls use `get_client_ip(request)` not `request.client.host`
- ✅ **Argon2id hashing** — backup codes stored with `secret_service.hash_secret` (reuse, parameters memory=64MB, t=3)
- ✅ **constant-time verify** — Argon2 `_ph.verify` (in `verify_secret`) is constant-time
- ✅ **Challenge expiry** — Redis TTL = `webauthn_challenge_ttl_sec` (300s default)
- ✅ **Resident key PREFERRED** — future-proof for Discoverable Credentials (Improvement #1 Phase 7)
- ✅ **userVerification REQUIRED** — Decision #2; enforced both in client options and `verify_registration_response`
- ✅ **No ambiguous chars in backup codes** — alphabet excludes `0/1/I/O` (transcription-safe)
- ⚠️ **Mandatory ack enforced client-side only** — server can detect un-acknowledged state but doesn't actively prevent further use (acceptable: codes already issued and saved by user)
- ⚠️ **Origin allowlist** — currently `http://localhost:3000` only; production needs HTTPS origin in env

---

## Mandatory Backup Codes UX (Improvement #3)

Frontend `BackupCodesModal.tsx` enforces:

| Step | Required action |
|---|---|
| 1 | Modal opens automatically after first register success |
| 2 | No close X / no ESC trap / `beforeunload` warning if user tries to leave |
| 3 | Must click "Copy" OR "Download" (.txt file) — buttons turn green when used |
| 4 | Must tick acknowledgment checkbox (disabled until step 3 done) |
| 5 | "Confirm I Saved Them" button → POST /backup-codes/acknowledge → modal closes |

Server complement (`PASSKEY_BACKUP_CODES_ACKNOWLEDGED` audit) provides forensic trail.

---

## Compliance

- **WebAuthn L3 §4.1** — registration ceremony attestation verification
- **FIDO Alliance Best Practices §3.4** — User Verification required for high-assurance
- **NIST SP 800-63B §5.1.9** — multi-factor cryptographic device requirements
- **OWASP ASVS V2.1.10** — backup codes single-use + hashed at rest

---

## Reproducible

```bash
# 1. Apply migration (idempotent — CREATE IF NOT EXISTS)
docker exec -i hub-postgres psql -U hub -d hub_db \
  < docs/sql-migrations/2026-06-10-phase1-passkey-tables.sql

# 2. Verify webauthn lib installed
docker compose exec -T hub-backend python -c \
  "import webauthn; print(webauthn.__version__)"
# → 2.5.0

# 3. Run Phase 1 tests
docker compose exec -T hub-backend pytest tests/test_passkey_register.py -v

# 4. Run combined Phase 0 + 1
docker compose exec -T hub-backend pytest \
    tests/test_stepup_cache.py \
    tests/test_critical_action_policy.py \
    tests/test_passkey_register.py -v
# → 23 passed

# 5. Verify endpoints registered
curl -s http://localhost:8000/openapi.json | python -c \
  "import json,sys; d=json.load(sys.stdin); print([p for p in d['paths'] if 'passkey' in p.lower()])"

# 6. Frontend type check
docker compose exec -T hub-frontend npx tsc --noEmit 2>&1 | grep -E "lib/passkey|account/security"
# → no errors
```

---

## Manual smoke test (browser-required — operator runs)

Login Google → navigate `/account/security`:

- [ ] "เบราว์เซอร์รองรับ Passkey" banner shows (if Chrome/Edge/Safari)
- [ ] Type device name → click "ลงทะเบียน Passkey"
- [ ] Browser prompts TouchID / Windows Hello / passkey choice
- [ ] On success: BackupCodesModal pops up
- [ ] Try to close → blocked
- [ ] Copy button → turns green
- [ ] Tick checkbox → "Confirm" button enabled
- [ ] Click confirm → modal closes
- [ ] DB: `SELECT * FROM passkey_credentials` → 1 row with device_name
- [ ] DB: `SELECT COUNT(*) FROM passkey_backup_codes WHERE acknowledged_at IS NOT NULL` → 10
- [ ] Audit: `SELECT action FROM audit_logs WHERE action LIKE 'passkey%'` → 3 rows
  (passkey_registered, passkey_backup_codes_generated, passkey_backup_codes_acknowledged)

---

## Phase 1 — Acceptance criteria

- [x] webauthn 2.5.0 installed + verifiable import
- [x] DB tables `passkey_credentials` + `passkey_backup_codes` created with all indexes
- [x] register_begin enforces max 10 (Improvement #9)
- [x] register_complete uses atomic `getdel` for challenge (B9)
- [x] First-register auto-generates 10 backup codes (Improvement #3 — server)
- [x] BackupCodesModal blocks close until ack (Improvement #3 — client)
- [x] Argon2id storage for backup codes (verify round-trip passes)
- [x] All 10 Phase 1 tests pass + 23/23 combined with Phase 0
- [x] Endpoints registered + visible in OpenAPI
- [x] No TypeScript errors in new files

---

## Next: Phase 2 — Login Flow (~3 hours)

- [ ] `webauthn_service.auth_begin` + `auth_complete` (counter regression handling)
- [ ] Router: `/auth/passkey/login/{start,finish}` + 501 placeholder for `discoverable/start`
- [ ] Frontend: Passkey button on login page + `auth/passkey/page.tsx`
- [ ] Audit: `PASSKEY_LOGIN_SUCCESS` / `_FAILED` / `_COUNTER_REGRESSION`

Manual smoke after Phase 2: logout → login via Passkey → JWT issued → dashboard.
