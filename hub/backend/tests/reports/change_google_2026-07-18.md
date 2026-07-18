# Test Report — Change Google Account (self-service re-link)

**วันที่:** 2026-07-18
**Feature:** ข้อ 3 "ข้อเสนอแนะในการปรับปรุงระบบ" — ผู้ใช้เปลี่ยนบัญชี Google (email + sub ใหม่)
เข้ากับ Hub user เดิม โดยข้อมูล/สิทธิ์/audit/subsystem อยู่ครบ
**แพลน:** `plan/change-google-relink.md`
**Test file:** `tests/test_change_google.py` (11 tests)

> หมายเหตุ TDD: implement เสร็จตอน Docker Desktop down (รัน pytest ไม่ได้) จึงไม่ได้โชว์ RED
> เป็นขั้นแยก — แต่เทสต์เขียน**ก่อน** implementation logic เสร็จ และครอบ security guards ครบทุกเคส
> ตอน Docker กลับมารันได้ ผ่าน 11/11 ทันที + regression 120/120

---

## รันเทสต์ (reproducible)

```bash
docker compose exec hub-backend pytest tests/test_change_google.py -v
```

## ผล — 11/11 PASSED

| # | test | ตรวจอะไร |
|---|---|---|
| 1 | `test_start_requires_stepup` | ไม่มี step-up grant → 403 `stepup_required` |
| 2 | `test_start_rejects_otp_stepup` | มีแค่ **OTP** grant → ยัง 403 (บังคับ passkey) |
| 3 | `test_start_with_passkey_stepup_mints_token` | **passkey** grant → 200 + `start_url` + Redis token ถูก mint |
| 4 | `test_redirect_missing_token_400` | token หมดอายุ/ไม่มี → 400 (ไม่เริ่ม OAuth) |
| 5 | `test_apply_happy_relinks_email_and_sub` | re-link สำเร็จ: email+sub เปลี่ยน, **user.id เดิม**, email_verified=True |
| 6 | `test_apply_rejects_unverified_email` | Google `email_verified=false` → reject |
| 7 | `test_apply_rejects_email_taken_by_other` | email ชน user อื่น → reject (UNIQUE guard) |
| 8 | `test_apply_rejects_sub_taken_by_other` | sub ชน user อื่น → reject (UNIQUE guard) |
| 9 | `test_apply_revokes_sessions_and_stepup` | หลัง re-link: session ปิด + jti revoked + stepup cache ล้าง |
| 10 | `test_apply_writes_audit_and_alerts` | audit `account_google_changed` (old/new) + alert email → old+new (2 ครั้ง) |
| 11 | `test_change_token_is_single_use` | Redis token = single-use (getdel, B9) |

```
collected 11 items
tests/test_change_google.py ...........                                  [100%]
============================== 11 passed in 2.53s ==============================
```

## Security checks (mapping → guards ที่เทสต์ยืนยัน)

| Threat | Control | เทสต์ |
|---|---|---|
| Attacker ผูก Google ตัวเองเข้ากับ user เหยื่อ | passkey step-up บังคับ (ไม่รับ OTP) | #1, #2, #3 |
| Google email ปลอม/ยังไม่ verify | require `email_verified==true` | #6 |
| ยึด email/sub ของคนอื่น | UNIQUE guard ก่อน apply | #7, #8 |
| Replay token | single-use getdel (B9) | #11 |
| session เก่ายังใช้ได้หลังเปลี่ยน identity | force revoke jti + refresh + stepup | #9 |
| เหยื่อไม่รู้ตัว | alert email → old+new + audit | #10 |

## Regression — 120/120 PASSED (blast radius)

```bash
docker compose exec hub-backend pytest \
  tests/test_critical_action_policy.py tests/test_stepup_cache.py \
  tests/test_auth_policy.py tests/test_rbac.py \
  tests/test_passkey_lifecycle.py tests/test_passkey_security.py \
  tests/test_refresh_token.py tests/test_token_revocation.py \
  tests/test_change_google.py -q
# → 120 passed in 15.13s
```

ครอบ module ทั้งหมดที่ change แตะ: CRITICAL_ACTIONS (เพิ่ม `change_google_account`),
stepup_cache, auth-policy, RBAC, passkey lifecycle/security, refresh/revocation.

> full-suite (`pytest .`) crash ที่ `test_e2e_full_stack.py` / `test_l1_oidc.py` — เป็น
> **script-style files เดิม** ที่มี `sys.exit()` module-level (รันเป็น script ไม่ใช่ pytest module)
> ไม่เกี่ยวกับ change นี้

## Frontend

```bash
docker compose exec hub-frontend npx tsc --noEmit -p tsconfig.json   # exit 0
```
AccountView card + `changeGoogleStart` helper + login banner — typecheck ผ่าน

## Live smoke (running container hot-reload)

```
GET  /auth/account/change-google/redirect?t=nope   → 400 (endpoint served, token guard ทำงาน)
POST /auth/account/change-google/start (no auth)    → 403 (endpoint served, gate ทำงาน — ไม่ใช่ 404)
```

## ยังไม่ได้ทดสอบ (ต้อง manual — OAuth จริงกับ Google)

E2E เต็ม (start → Google account picker → callback apply) ต้องมี:
- redirect URI ใน Google Console (B17) + `GOOGLE_CHANGE_REDIRECT_URI` ใน env
- Google test user ≥ 2 บัญชี (B15)

ดู `docs/VM_PENDING_CHANGES.md §4.2` — ทำ manual ตอน deploy
