# Passkey Phase 0 — Foundation Test Report

**Date**: 2026-06-10
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 0 — Foundation (review "Must Have" + email backfill)
**Status**: ✅ ALL PASS (13/13)

---

## Scope

Phase 0 ทำ infrastructure foundation ก่อนเริ่ม WebAuthn — ตามคำแนะนำใน
`PASSKEY_DESIGN2.txt` (review) ที่ระบุ:

> ก่อนเริ่มพัฒนา Passkey จริง ควรดำเนินการ Phase 1 (Must Have) ให้ครบก่อน

3 รายการ Foundation ที่ Plan v3 จัดอยู่ใน Phase 0:
- **Improvement #2** — Step-up Session Cache (`stepup_cache.py`)
- **Improvement #6** — Environment Separation (config + .env)
- **Improvement #8** — Critical Action Policy Layer (`critical_action_policy.py`)

บวก Decision #10 — บังคับ verify email ก่อนใช้ระบบ → SQL migration

---

## Files changed

### Created
- `hub/backend/app/services/stepup_cache.py` (~95 lines)
- `hub/backend/app/services/critical_action_policy.py` (~120 lines)
- `hub/backend/tests/test_stepup_cache.py` (6 tests)
- `hub/backend/tests/test_critical_action_policy.py` (7 tests)
- `docs/sql-migrations/2026-06-10-phase0-email-verified.sql`

### Modified
- `hub/backend/app/config.py` — เพิ่ม 8 settings (webauthn_*, stepup_*)
- `hub/backend/app/models.py` — `User.email_verified` + `email_verified_at`
- `.env.example` — เพิ่ม WebAuthn + Stepup sections

### SQL migration
```sql
ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP;
UPDATE users SET email_verified = true, email_verified_at = ...
WHERE google_sub IS NOT NULL;
```

**Migration result (2026-06-10):**
```
 verified | unverified | total
----------+------------+-------
        4 |        100 |   104
```
- 4 Gmail admins (with google_sub) → verified
- 100 seeded @uni.ac.th + @hub.local users → unverified (correct — never logged in)

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest \
    tests/test_stepup_cache.py \
    tests/test_critical_action_policy.py -v
```

### Result

```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-8.3.3, pluggy-1.6.0
collected 13 items

tests/test_stepup_cache.py::test_set_and_check_returns_payload PASSED    [  7%]
tests/test_stepup_cache.py::test_check_returns_none_when_no_grant PASSED [ 15%]
tests/test_stepup_cache.py::test_clear_removes_grant PASSED              [ 23%]
tests/test_stepup_cache.py::test_ttl_expires_grant PASSED                [ 30%]
tests/test_stepup_cache.py::test_clear_all_for_user_removes_multiple PASSED [ 38%]
tests/test_stepup_cache.py::test_empty_args_return_none_or_skip PASSED   [ 46%]
tests/test_critical_action_policy.py::test_critical_actions_set_complete PASSED [ 53%]
tests/test_critical_action_policy.py::test_is_critical_recognizes_listed_actions PASSED [ 61%]
tests/test_critical_action_policy.py::test_gate_factory_returns_callable PASSED [ 69%]
tests/test_critical_action_policy.py::test_gate_warns_on_unknown_action PASSED [ 76%]
tests/test_critical_action_policy.py::test_stepup_cache_integration PASSED [ 84%]
tests/test_critical_action_policy.py::test_jti_extraction_helper_safe_on_garbage PASSED [ 92%]
tests/test_critical_action_policy.py::test_passkey_settings_loaded PASSED [100%]

============================== 13 passed in 2.56s ==============================
```

---

## Test Coverage Breakdown

### `test_stepup_cache.py` (6 tests — Improvement #2)

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_set_and_check_returns_payload` | Round-trip: set_granted → check_cached → payload มี method+ip+granted_at |
| 2 | `test_check_returns_none_when_no_grant` | ไม่เคย set → None (ไม่ false-positive) |
| 3 | `test_clear_removes_grant` | clear() ลบ key → cache miss |
| 4 | `test_ttl_expires_grant` | TTL 1s → sleep 1.2s → cache miss (Redis TTL ทำงานจริง) |
| 5 | `test_clear_all_for_user_removes_multiple` | clear_all_for_user() ใช้ SCAN — ลบ 3 jti ได้ครบ |
| 6 | `test_empty_args_return_none_or_skip` | Edge: empty string ไม่ crash |

### `test_critical_action_policy.py` (7 tests — Improvement #8)

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_critical_actions_set_complete` | CRITICAL_ACTIONS = 7 actions ตาม plan § 6.3 |
| 2 | `test_is_critical_recognizes_listed_actions` | True/False matching |
| 3 | `test_gate_factory_returns_callable` | gate(action) → callable, __name__=gate_{action} |
| 4 | `test_gate_warns_on_unknown_action` | typo guard: log warning |
| 5 | `test_stepup_cache_integration` | Gate ↔ Cache integration |
| 6 | `test_jti_extraction_helper_safe_on_garbage` | None-safe (defensive) |
| 7 | `test_passkey_settings_loaded` | Q1/Q7/Improvement #9/#10 settings ถูก load |

---

## Security Checks

- ✅ **B9 (atomic getdel pattern)** — stepup_cache.clear() ใช้ Redis DEL (atomic)
- ✅ **B20 (get_client_ip)** — stepup_cache.set_granted() รับ ip param, รอ caller pass `get_client_ip(request)`
- ✅ **B4 (verify_aud)** — critical_action_policy ใช้ `verify_signature: False` แค่อ่าน jti, signature verify ทำใน get_current_user แล้ว (defense-in-depth)
- ✅ **B21 (fail-safe)** — `_extract_jti` ถ้า decode fail → return None → gate raise 403 (fail-closed, ปลอดภัย)
- ✅ **Token tampering**: gate ตรวจ jti จาก token ที่ get_current_user verify signature แล้ว → ปลอม jti ไม่ได้
- ⚠️ **Rate limit**: ยังไม่ได้ใส่ rate-limit บน /auth/passkey/stepup (จะใส่ใน Phase 5)

---

## Compliance

- **NIST SP 800-63B §5.2.3** — step-up via biometric/cryptographic credential (Passkey)
- **WebAuthn L3 §5.1.3** — RP ID strategy: localhost dev → migrate prod
- **OWASP ASVS V2.7.4** — sensitive ops require re-auth (Improvement #8 critical action)

---

## Reproducible

```bash
# 1. Apply migration
docker exec -i hub-postgres psql -U hub -d hub_db \
  < docs/sql-migrations/2026-06-10-phase0-email-verified.sql

# 2. Run tests
docker compose exec -T hub-backend pytest \
    tests/test_stepup_cache.py \
    tests/test_critical_action_policy.py -v

# 3. Verify config
docker compose exec hub-backend python -c \
  "from app.config import settings; print(settings.webauthn_rp_id, settings.stepup_cache_ttl_sec)"
# expected: localhost 900
```

---

## Decisions verified (Q1-Q7 locked 2026-06-10)

| Q | Decision | Verified in test |
|---|---|---|
| Q1 | RP ID = localhost | `test_passkey_settings_loaded` |
| Q4 | Backfill Google users | SQL migration result (4 verified) |
| Q7 | Stepup TTL = 900s | `test_passkey_settings_loaded` |
| Improvement #9 | max 10 Passkeys/user | `test_passkey_settings_loaded` |
| Improvement #10 | Counter regression +0.2 risk | `test_passkey_settings_loaded` |

---

## Phase 0 — Acceptance criteria

- [x] `services/stepup_cache.py` — set/check/clear/clear_all_for_user works (6/6 tests pass)
- [x] `services/critical_action_policy.py` — gate() + CRITICAL_ACTIONS complete (7/7 tests pass)
- [x] `config.py` — 8 new settings loaded (verified in test)
- [x] `.env.example` — WebAuthn + Stepup sections present
- [x] DB migration applied (4 users backfilled)
- [x] `User.email_verified` column present (verified via ORM)

---

## Next: Phase 1 — Schema + Registration + Mandatory Backup Codes (~6 hours)

Pre-requisites for Phase 1:
- ✅ Step-up cache available (Phase 0)
- ✅ Critical action gate available (Phase 0 — Phase 1 register endpoint จะใช้ `gate("register_new_passkey")`)
- ✅ Email verification column available (Phase 0)
- ⏳ Add `webauthn==2.5.0` to requirements.txt
- ⏳ Create `passkey_credentials` + `passkey_backup_codes` tables
- ⏳ Mandatory `BackupCodesModal.tsx` (Improvement #3)
