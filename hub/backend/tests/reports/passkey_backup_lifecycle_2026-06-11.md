# Backup Codes Lifecycle + Admin Passkey Overview (A+B+C)

**Date**: 2026-06-11
**Scope**: regenerate (A) + OTP-regen recovery (B) + age/low reminder (C) + admin passkey overview
**Status**: ✅ ALL PASS (121/121 regression)

---

## ปัญหาที่แก้ + design ที่ user ขอ

หลัง recovery testing เจอว่า re-enroll passkey → crash (`RuntimeError: Backup codes already exist`)
+ user เสนอ design: codes ใช้ได้รอบต่อไป / OTP → ลบที่เหลือ + ออกใหม่ / overview ในหน้า users

---

## A — Regenerate backup codes (admin)

```
POST /account/passkeys/backup-codes/regenerate  (admin only)
```
rotate codes → ชุดเก่าตายหมด → ออกชุดใหม่ 10 ตัว (show once).
Frontend: ปุ่ม "🔄 สร้างใหม่" ในหน้า /account/security (ปุ่มเป็นสีเหลืองเมื่อ low).

## B — OTP recovery → ออก codes ใหม่ + auto-heal

1. **email OTP verify** เปลี่ยนจาก revoke เฉยๆ → **revoke passkey + ออก codes ชุดใหม่** (return ใน response)
   - ตรงกับ design: "OTP → ลบที่เหลือ + ได้ใหม่"
   - recover page (ทั้ง Hub + Next.js) แสดง codes ใหม่หลัง OTP สำเร็จ
2. **auto-heal guard** (`ensure_backup_codes`): enroll/register → ออก codes เมื่อ remaining==0
   - ไม่เคยมี → gen 1; usable อยู่ → skip; ใช้หมด → rotate ใหม่
   - **ปิดช่องติดล็อก** (re-enroll หลัง recovery ได้ codes ใหม่อัตโนมัติ) + แก้ crash เดิม

## C — Age + low reminder

หน้า security แสดง "เหลือ X/10" + เตือน "⚠ ใกล้หมด" เมื่อ used≥7/10 (flag `low`).

## Admin Passkey Overview (หน้า Users)

```
GET /admin/users/{id}/passkeys  (admin, read-only)
```
- คอลัมน์ "🔑 ดู" ในตาราง Users → เปิด modal
- Modal: list passkey ของ user (device/last used/country/counter) + backup codes remaining + ปุ่ม **Reset Passkeys**
- ไม่เพิ่มแท็บ sidebar ใหม่ (อยู่ในบริบทหน้า Users — ตามที่ user เลือก)

---

## OTP vs Authenticator (ตอบคำถาม user)

recovery ใช้ **email OTP ต่อ** — ไม่ต้อง pre-enroll, กู้ได้เสมอ.
TOTP (authenticator app) ต้อง scan QR ก่อน → ถ้าไม่เคยตั้ง = กู้ไม่ได้ → ไม่เหมาะ recovery.
TOTP เก็บไว้ step-up Phase 5.

---

## Test result

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_recovery.py -v
```

new tests:
- `test_ensure_backup_codes_auto_heal` — ไม่มี→gen1 / usable→skip / หมด→rotate
- `test_email_otp_verify_returns_new_codes` — OTP → revoke + codes ใหม่ (B)
- `test_regenerate_endpoint_admin_only` — staff 403, admin 200 (A)
- `test_admin_list_passkeys_rbac` — staff 403, admin 200/404 (overview)
- (อัปเดต 4 tests เดิม: email_otp_verify คืน list|None แทน bool)

```
============================= 121 passed in 34.71s =============================
```

---

## Backup codes lifecycle — สรุปกฎ (ตอบ user)

| สถานการณ์ | พฤติกรรม |
|---|---|
| ใช้ code 1 ตัว | ตัวอื่นในชุด**ยังใช้ได้** (single-use ต่อตัว) |
| Regenerate / rotate | ชุดเก่า**ตายทั้งหมด** เหลือชุดล่าสุด |
| Re-enroll หลังใช้หมด/recovery | auto-heal ออกชุดใหม่อัตโนมัติ |
| OTP recovery | revoke passkey + ออก codes ใหม่ |
| **ไม่มี hard expiry 3 เดือน** | ❌ (เสี่ยงล็อก) — ใช้ low reminder แทน |

---

## Security checks

- ✅ regenerate + admin overview = admin-only (RBAC tested)
- ✅ rotate invalidates ชุดเก่า (generation isolation)
- ✅ auto-heal กัน crash + ปิดช่องติดล็อก
- ✅ OTP regen ใช้ rate limit + lockout เดิม
- ✅ admin overview read-only (ไม่ส่ง credential_id/public_key)
- ✅ B6 audit order ทุก path
- ✅ recovery audit trail + PASSKEY_BACKUP_CODES_REGENERATED

---

## Files changed

### Backend
- `services/passkey_recovery.py` — email_otp_verify คืน codes ใหม่; + ensure_backup_codes, remaining_codes, has_backup_codes
- `routers/passkey.py` — auto-heal guard (enroll/register); + regenerate endpoint; OTP verify return codes
- `routers/oauth.py` — auto-heal guard (subsystem enroll); recover page แสดง codes ใหม่
- `routers/admin.py` — + GET /admin/users/{id}/passkeys (overview)

### Frontend
- `lib/passkey.ts` — regenerateBackupCodes, adminListUserPasskeys, adminResetUserPasskeys
- `(console)/account/security/page.tsx` — regenerate button + low styling (A+C)
- `(console)/users/page.tsx` + `_components/UserPasskeyModal.tsx` — passkey column + overview modal
- `auth/passkey/recover/page.tsx` — แสดง codes ใหม่หลัง OTP

---

## Manual test

```
A (admin regenerate):
  /account/security → "🔄 สร้างใหม่" → confirm → modal codes ใหม่

B (OTP recovery → codes ใหม่):
  /oauth/passkey/recover (subsystem) หรือ /auth/passkey/recover (admin)
  → Email OTP → verify → เห็น codes ชุดใหม่บนหน้าจอ

Overview:
  /users → คอลัมน์ "🔑 ดู" → modal เห็น passkey + Reset button

Auto-heal:
  ลบ passkey จนหมด → enroll ใหม่ → ได้ backup codes ชุดใหม่อัตโนมัติ (ไม่ crash)
```
