# Passkey `attestation_verify_failed` — Origin Fix

**Date**: 2026-06-11
**Bug**: ลง passkey ผ่าน subsystem enroll → `attestation_verify_failed` (และ login chooser ก็ fail)
**Status**: ✅ FIXED & VERIFIED (111/111 tests pass)

---

## อาการ

ลง passkey ผ่าน subsystem enroll interstitial → error `attestation_verify_failed`.
Audit: `passkey_register_failed` code=`attestation_verify_failed` phase=`enroll_finish`.

## Root cause — WebAuthn origin mismatch

Backend log (ชัดเจน):
```
InvalidRegistrationResponse('Unexpected client data origin "http://localhost:8000",
expected one of [\'http://localhost:3000\']')
```

WebAuthn ceremony รันที่ origin ของ "หน้าที่เปิดอยู่":
| หน้า | เสิร์ฟจาก | origin ของ ceremony |
|---|---|---|
| `/account/security` (console register) | Next.js | `http://localhost:3000` |
| subsystem chooser login (`/oauth/authorize`) | **Hub** | `http://localhost:8000` |
| subsystem enroll interstitial | **Hub** | `http://localhost:8000` |

`webauthn_origins` config มีแค่ `http://localhost:3000` → ceremony ที่ Hub (port 8000)
โดน reject ทั้ง register (`InvalidRegistrationResponse`) และ login (`InvalidAuthenticationResponse`).

→ **subsystem passkey login + enroll พังทั้งคู่** (console register ที่ :3000 ยังใช้ได้)

## Fix

```python
# config.py — เพิ่ม localhost:8000
webauthn_origins: str = "http://localhost:3000,http://localhost:8000"
```

RP ID = `localhost` (ไม่เปลี่ยน) — port ไม่นับใน RP ID matching → passkey เดียวใช้ได้ทั้ง 2 origin

ไฟล์แก้:
- `app/config.py` — webauthn_origins default + comment อธิบายว่าทำไม 2 origin
- `.env.example` — `WEBAUTHN_ORIGINS=http://localhost:3000,http://localhost:8000`

Verify:
```
_origins() → ['http://localhost:3000', 'http://localhost:8000']
```

## ทำไม test เดิมไม่จับ

Unit tests เดิมทดสอบ guard layers (challenge missing, email format, anti-enum) แต่
**ไม่ได้ exercise WebAuthn ceremony จริง** (ต้อง software authenticator — Phase 6).
origin ถูกตรวจตอน `verify_*_response` เท่านั้น ซึ่ง test ไม่ถึง.

### Regression guard ที่เพิ่ม

`test_webauthn_origins_include_hub_served_origin` — assert `_origins()` มีทั้ง
`localhost:3000` (console) และ `localhost:8000` (Hub pages). จับบั๊กนี้ในอนาคต.

(full software-authenticator ceremony test = Phase 6 — ต้องลง `soft-webauthn`)

## Test result

```bash
docker compose exec -T hub-backend pytest \
  tests/test_oauth_passkey.py tests/test_passkey_register.py \
  tests/test_passkey_login.py tests/test_passkey_security.py \
  tests/test_stepup_cache.py tests/test_critical_action_policy.py \
  tests/test_health.py tests/test_rbac.py tests/test_jwt_service.py \
  tests/test_pkce.py tests/test_secret_service.py tests/test_rate_limit.py
```
```
============================= 111 passed in 19.16s =============================
```

## Manual retry (operator)

```
1. ลบ register fail เดิม (ไม่จำเป็น — ไม่มี row ค้าง เพราะ verify fail ก่อน save)
2. subsystem login → chooser → Continue with Google → เลือก account
3. หน้า "ตั้งค่า Passkey" → กดตั้งค่า → Windows Hello/PIN
   → คราวนี้ผ่าน (origin localhost:8000 อยู่ใน allowlist แล้ว)
4. backup codes modal → save → เข้า subsystem
5. login ครั้งหน้า → chooser → Passkey → กรอก email → ผ่าน
```

## Production note

ตอน deploy prod: `WEBAUTHN_ORIGINS` ต้องมีทุก origin ที่ ceremony รัน เช่น
`https://auth.uni.ac.th` (Hub) + `https://admin.uni.ac.th` (console ถ้าแยก domain).
RP ID = registrable suffix ที่ครอบทุก origin.
