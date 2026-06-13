# Passkey Phase 4 — Recovery

**Date**: 2026-06-11
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 4 — Recovery (backup code → email OTP → admin) — Decision #6 + Improvement #7
**Status**: ✅ ALL PASS (143/143 รวม regression)

---

## Scope

กู้บัญชีเมื่อทำ Passkey หาย — Decision #6 priority order:
**backup code → email OTP → admin reset**

ทุก recovery = **revoke passkey ทั้งหมด** (lock down device หาย) → user login Google
(fallback) → enroll passkey ใหม่. **ไม่ออก JWT จาก recovery** (กัน abuse + รองรับทุก
user_type รวมนักศึกษา).

---

## Flows

| วิธี | endpoint | reason | rate limit |
|---|---|---|---|
| Backup code | POST /auth/passkey/recover/backup-code | backup_recovery | 5/min |
| Email OTP start | POST /auth/passkey/recover/email-otp/start | — | 3/min |
| Email OTP verify | POST /auth/passkey/recover/email-otp/verify | email_recovery | 5/min |
| Admin reset | POST /admin/users/{id}/reset-passkeys | admin_reset | (admin) |

---

## Service (passkey_recovery.py)

| Function | หน้าที่ |
|---|---|
| `_normalize_code` | 'ab3d7k9p' / 'AB3D-7K9P' / 'ab3d 7k9p' → 'AB3D-7K9P' |
| `_revoke_all_passkeys(reason)` | soft-revoke active passkeys ทั้งหมด |
| `verify_backup_code` | verify (current gen, unused) → mark used + revoke all |
| `email_otp_begin` | สร้าง OTP + ส่ง email (opaque — anti-enum) — Redis 5 นาที |
| `email_otp_verify` | verify + revoke; lockout 5 ครั้งผิด |
| `admin_reset_passkeys` | revoke all (reason=admin_reset) |

Email OTP reuse `mfa_service` (generate_otp/hash_otp/verify_otp — HMAC-SHA256 constant-time).
OTP state ใน Redis (`passkey:recover:otp:{email}`) — ไม่ใช้ MFAChallenge (ไม่มี login_session).

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_recovery.py -v
```

### test_passkey_recovery.py — 18 tests

```
test_normalize_code_variants PASSED
test_verify_backup_code_success_revokes_all PASSED
test_verify_backup_code_normalized_input PASSED
test_verify_backup_code_reuse_fails PASSED
test_verify_backup_code_wrong_fails PASSED
test_verify_backup_code_no_codes_fails PASSED
test_verify_backup_code_only_current_generation PASSED
test_email_otp_begin_opaque PASSED
test_email_otp_verify_success_revokes PASSED
test_email_otp_verify_wrong_increments PASSED
test_email_otp_verify_lockout PASSED
test_email_otp_verify_no_challenge_fails PASSED
test_admin_reset_revokes_all PASSED
test_admin_reset_endpoint_requires_admin PASSED
test_admin_reset_endpoint_no_token PASSED
test_recover_backup_code_opaque_on_unknown PASSED
test_recover_backup_code_rejects_non_email PASSED
test_recover_email_otp_start_opaque PASSED

============================== 18 passed in 16.02s ==============================
```

### Full regression
```
============================= 143 passed in 35.59s =============================
```

---

## Security checks

- ✅ **Anti-enumeration** — backup code unknown email → 400 recovery_failed (เหมือน code ผิด); email OTP start → 200 sent เสมอ
- ✅ **Argon2id verify** — backup code เทียบ hash (reuse secret_service)
- ✅ **One-time codes** — used_at + used_ip + used_ua, reuse → fail
- ✅ **Generation isolation** — rotate แล้ว code เก่าใช้ไม่ได้
- ✅ **OTP lockout** — 5 ครั้งผิด → ลบ key (ต้อง begin ใหม่)
- ✅ **OTP constant-time** — mfa_service.verify_otp (hmac.compare_digest)
- ✅ **Rate limit** — backup 5/min, otp start 3/min, verify 5/min
- ✅ **EmailStr validation** — non-email → 422
- ✅ **Admin reset RBAC** — require_hub_admin (staff/no-token → 403)
- ✅ **Recovery audit trail (Improvement #7)** — STARTED → BACKUP_CODE_USED / VIA_* → SUCCESS / FAILED
- ✅ **B6 audit order** — log → commit → raise ทุก path
- ✅ **No JWT issued** — recovery แค่ lock down, user login ปกติแล้ว enroll ใหม่ (กัน abuse)
- ✅ **Code normalization** — lowercase/no-dash/space ก็ใช้ได้ (UX)

---

## Audit events (Improvement #7 — full trail)

```python
PASSKEY_RECOVERY_STARTED
PASSKEY_RECOVERY_SUCCESS
PASSKEY_RECOVERY_FAILED
PASSKEY_RECOVERY_VIA_BACKUP_CODE
PASSKEY_RECOVERY_VIA_EMAIL_OTP
BACKUP_CODE_USED
passkey_admin_reset
```

---

## Frontend

- `auth/passkey/recover/page.tsx` — tabs: Backup Code / Email OTP, email input,
  success → link ไป login. ทั้งสองทาง → revoke all → "login Google แล้วตั้งค่าใหม่"
- `lib/passkey.ts` — recoverWithBackupCode / recoverEmailOtpStart / recoverEmailOtpVerify
- `auth/login/page.tsx` — ลิงก์ "ทำ Passkey หาย? กู้บัญชี"

middleware: `/api/proxy/auth/passkey/` (รวม recover) เป็น public แล้ว (จาก Phase 2)

---

## Manual test (operator)

```
Backup code:
1. มี passkey + backup codes → จด code 1 อัน
2. /auth/passkey/recover → tab Backup Code → email + code → กู้บัญชี
3. → "Passkey ทั้งหมดถูกลบแล้ว" → DB: passkey ทุกตัว revoked_reason=backup_recovery
4. login Google → /account/security → passkey หาย → enroll ใหม่

Admin reset:
1. admin → POST /admin/users/{id}/reset-passkeys (Swagger/curl ด้วย admin token)
2. → revoke passkey ของ user นั้น → audit passkey_admin_reset

Email OTP: ต้องตั้ง SMTP ใน .env (SMTP_USER/PASSWORD) ถึงจะได้ email จริง
```

---

## Phase 4 — Acceptance criteria

- [x] backup code recovery (verify + revoke all + one-time + generation isolation)
- [x] email OTP recovery (begin/verify + lockout + anti-enum)
- [x] admin reset passkeys (admin-only)
- [x] recovery audit trail (Improvement #7 — 7 events)
- [x] anti-enumeration (opaque responses)
- [x] frontend recovery page + login link
- [x] 18 recovery tests + 143/143 regression

---

## ครบ Passkey roadmap ตอนนี้

| Phase | สถานะ |
|---|---|
| 0 Foundation | ✅ |
| 1 Register + backup codes | ✅ |
| 2 Login | ✅ |
| B+A+E Subsystem (chooser+enroll) | ✅ |
| 3 Lifecycle (list/rename/delete) | ✅ |
| **4 Recovery** | ✅ **(นี่)** |
| 5 Step-up + ML + critical gate | ⏳ next |
| 6 Integration tests (soft-webauthn) | ⏳ |
| 7 Discoverable + force adoption | ⏳ |
