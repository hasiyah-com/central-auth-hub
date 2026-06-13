# Backup Codes — Email Reminder + OTP Regenerate-only + Ack UX

**Date**: 2026-06-11
**Scope**: low-codes email + OTP regenerate (ไม่ revoke passkey) + codes ack UX
**Status**: ✅ ALL PASS (124/124 regression)

---

## สิ่งที่ทำ (ตาม design ที่ user ขอ)

### 1. OTP regenerate-only (ไม่ revoke passkey)

แยก 2 OTP purpose ผ่าน **purpose binding** (เก็บใน Redis):
| Flow | endpoint | passkey | codes |
|---|---|---|---|
| Recovery | `/auth/passkey/recover/email-otp/*` | revoke | ใหม่ |
| **Regenerate** | `/auth/passkey/backup-codes/regen-otp/*` | **คงไว้** | ใหม่ |

**Purpose binding:** OTP ที่ขอเพื่อ regenerate ใช้กับ recovery verify **ไม่ได้** (และกลับกัน)
→ กัน "แค่อยากได้ codes ใหม่ ดันเสีย passkey"

### 2. Email เตือนเมื่อ codes ใกล้หมด

`verify_backup_code` → หลัง consume ถ้า remaining ≤ 3 → ส่ง email เตือน + ลิงก์ recover.
**ไม่ส่งตัว codes ทาง email** (security) — แค่เตือน + ลิงก์ไปยืนยัน OTP รับชุดใหม่บนหน้าจอ.

### 3. Codes display = ack UX (ตาม user)

codes ใหม่ (recovery/regen) → **copy/download + checkbox + ยืนยัน → login** (เหมือนหน้าได้ codes ครั้งแรก)
- Next.js recover page: `_CodesAck` component
- Hub recover page: ack UX ใน `done()` + tab "ขอ codes ใหม่"

---

## ทำไมไม่ส่ง backup codes ทาง email (decision)

user ถาม "ส่ง codes ทาง email ดีไหม" → **ไม่ส่ง** เพราะ:
- codes อยู่ถาวรใน inbox → ใครเปิด email เจอ = ยึดบัญชีได้ 10 ครั้ง
- ถ้า OTP ก็ email + codes ก็ email → email = single point of failure (ทำลายเหตุผล backup codes)
- GitHub/Google ไม่ส่ง codes ทาง email — แสดงบนจอ + download เท่านั้น

→ email = เตือน + ลิงก์ + OTP. codes = บนจอ (ack UX).

---

## OTP vs Authenticator (ตอบ user)

recovery/regen ใช้ **email OTP** — ไม่ต้อง pre-enroll, ทุกคนใช้ได้.
TOTP (authenticator) ต้อง scan QR ก่อน → ไม่เหมาะ recovery (ถ้าไม่เคยตั้ง = ใช้ไม่ได้). เก็บไว้ step-up Phase 5.

---

## Test result

new tests:
- `test_regen_otp_no_passkey_revoke` — regen OTP → codes ใหม่ + **passkey ยังอยู่**
- `test_otp_purpose_binding` — regen OTP ใช้กับ recovery ไม่ได้ (mismatch → None)
- `test_regen_otp_endpoints_registered` — regen start opaque (anti-enum)

```
tests/test_passkey_recovery.py → 26 passed
full regression → 124 passed in 43.04s
```

---

## Security checks

- ✅ **Purpose binding** — regen OTP ≠ recovery OTP (กัน revoke passkey โดยไม่ตั้งใจ)
- ✅ **ไม่ส่ง codes ทาง email** — email แค่เตือน + ลิงก์ + OTP
- ✅ **regen ไม่ revoke passkey** — test ยืนยัน count_active คงเดิม
- ✅ **anti-enum** — regen start opaque, OTP mismatch → fail เงียบ
- ✅ **rate limit + lockout** — เดิม (3/5 per min, 5 attempts)
- ✅ **ack UX mandatory** — ต้อง copy/download + checkbox ก่อนยืนยัน
- ✅ **email fail-safe** — ส่ง email ไม่ได้ ไม่ทำให้ flow ล่ม

---

## Files changed

### Backend
- `services/passkey_recovery.py` — purpose binding (begin/verify), regen-only path, `_maybe_send_low_codes_email`
- `routers/passkey.py` — regen-otp/{start,verify} endpoints
- `routers/oauth.py` — Hub recover page: tab "ขอ codes ใหม่" + ack UX ใน done()

### Frontend
- `lib/passkey.ts` — regenOtpStart, regenOtpVerify
- `auth/passkey/recover/page.tsx` — 3 modes (backup/OTP/regen) + CodesAck
- `auth/passkey/recover/_CodesAck.tsx` — codes ack component (copy/download/checkbox/ยืนยัน→login)

---

## Manual test

```
Regen (codes ใกล้หมด/หาย, passkey ยังอยู่):
  recover page → tab "ขอ codes ใหม่" → email → OTP
  → codes ใหม่ + ack UX → ยืนยัน → login
  → passkey เดิมยังใช้ login ได้ (ไม่ถูกลบ)

Recovery (device หาย):
  tab "กู้ OTP" → email → OTP → revoke passkey + codes ใหม่ + ack UX

Email เตือน (ต้องตั้ง SMTP):
  ใช้ backup code จนเหลือ ≤3 → ได้ email "codes ใกล้หมด" + ลิงก์
```

---

## Backup codes lifecycle — สรุปสุดท้าย

| สถานการณ์ | กลไก |
|---|---|
| ใช้ 1 code | ตัวอื่นยังใช้ได้ (single-use ต่อตัว) |
| codes ใกล้หมด | email เตือน + ลิงก์ regen |
| อยากได้ codes ใหม่ (passkey อยู่) | regen OTP → codes ใหม่ (ไม่เสีย passkey) |
| device หาย | recovery (backup code / OTP) → revoke + codes ใหม่ |
| codes ทาง email | ❌ ไม่ส่ง (security) — บนจอ + ack |
| hard expiry | ❌ ไม่มี (เสี่ยงล็อก) |
