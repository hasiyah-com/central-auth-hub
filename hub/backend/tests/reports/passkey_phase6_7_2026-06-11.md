# Passkey Phase 6 + 7 — Integration Tests, CI, Discoverable Login, Force Adoption

**Date**: 2026-06-11
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phases**: 6 (full ceremony integration + CI) + 7 (Discoverable Credentials + force adoption)
**Status**: ✅ ALL PASS (164/164 backend regression)

---

## Phase 6 — Full WebAuthn ceremony integration tests

### Software authenticator (soft-webauthn)
- `tests/passkey_ceremony.py` — `UVSoftWebauthnDevice` (subclass ที่ set UV flag
  `\x45` create / `\x05` get — soft-webauthn default ไม่ set UV ซึ่งระบบเราบังคับ)
  + bridge helpers (JSON options ↔ soft bytes ↔ verify dict)
  + `do_register / do_login / do_stepup`
- `soft-webauthn==0.1.4` เพิ่มใน requirements.txt (baked เข้า image)

### `tests/test_passkey_ceremony.py` — 13 tests (รัน ceremony เต็ม, verify signature จริง)

| Test | ครอบ |
|---|---|
| register_full_ceremony_saves_credential | attestation verify → save COSE public key, sign_count |
| register_then_duplicate_excluded | excludeCredentials ทำงาน |
| login_full_ceremony_verifies_signature | signature verify, sign_count 0→1, no regression |
| login_sign_count_advances_each_time | 3 login → count [1,2,3] |
| login_foreign_device_rejected | device อื่น → 401 invalid_credential |
| login_after_revoke_rejected | revoked → 401 |
| **counter_regression_detected** | clone (count ไม่เดิน) → regression flag + lenient allow |
| stepup_full_ceremony | step-up assertion เต็ม |
| stepup_no_passkey_raises | 400 no_passkey |
| discoverable_login_identifies_by_userhandle | login ไม่กรอก email |
| discoverable_foreign_device_rejected | 401 |
| adoption_status_optin_default | nudge=false |
| adoption_status_nudge_when_overdue | nudge logic |

### 🐛 Bug จับได้ (integration test only)

**Counter regression lenient เป็น dead code** — `py_webauthn.verify_authentication_response`
มี built-in sign-count check ที่ **raise เอง** เมื่อ `new <= current` → code lenient ของเรา
(Improvement #10) ไม่เคยทำงาน → counter regression จริงๆ ถูก block ไม่ใช่ lenient

**แก้:** pass `credential_current_sign_count=0` ให้ py_webauthn ข้าม strict check แล้ว
เราทำ lenient check เอง (auth_complete + stepup_complete + discoverable_complete).
unit tests เดิมจับไม่ได้เพราะไม่ได้รัน ceremony จริง — **นี่คือคุณค่าของ Phase 6**

### CI — `.github/workflows/backend-ci.yml`
- postgres:15 + redis:7 services
- generate RS256 keys (openssl) → seed users → pytest
- env: ML unreachable (fail-safe B21), GeoIP missing (neutral), WEBAUTHN_ORIGINS 2 ports
- exclude standalone sys.exit scripts (test_e2e_full_stack, test_l1_oidc*)

---

## Phase 7 — Discoverable Credentials + Force Adoption

### Discoverable login (Improvement #1) — wire 501 → real

```
POST /auth/passkey/login/discoverable/start   → options (allowCredentials ว่าง)
POST /auth/passkey/login/discoverable/finish  → JWT (identify จาก userHandle)
```

- login **ไม่ต้องกรอก email** — browser โชว์ resident keys, authenticator คืน
  userHandle (= user.id จาก register_begin)
- backend: identify จาก userHandle → **ตรวจ credential เป็นของ user นั้นจริง**
  (กัน userHandle ปลอม) → verify signature → JWT
- challenge keyed by challenge value (ยังไม่รู้ user), atomic getdel (B9)
- frontend: ปุ่ม "🔓 เข้าโดยไม่กรอก email" ในหน้า login (admin)

### Force adoption (Q5) — soft enforcement
```
config: passkey_required_after_days (0 = opt-in default)
GET /auth/passkey/adoption → {has_passkey, nudge, days_since_signup, required_after_days}
```
- nudge=true ถ้า after>0 + account เกิน N วัน + ยังไม่มี passkey
- **ไม่ block** — frontend ใช้ flag เตือน/พาไปตั้งค่า (soft, ตาม Q5 = opt-in ตลอด)

---

## E2E verification (full stack ผ่าน proxy)

```
discoverable/start ผ่าน /api/proxy → 200 challenge (public flow)
register → login → stepup → discoverable ceremony chain → ✅ ทั้งหมด
sign_count เดินหน้าถูก, counter regression detect ได้, userHandle identify ได้
```

Passkey endpoints รวม: **28 endpoints** (register/login/lifecycle/recovery/regen/stepup/
discoverable/adoption/enroll/subsystem/admin)

---

## Bug sweep (รอบนี้ + สะสม)

| Bug | สถานะ |
|---|---|
| counter regression lenient = dead code (py_webauthn block ก่อน) | ✅ แก้ (pass 0) |
| webauthn module หายหลัง container recreate | ✅ rebuild image (baked) |
| WEBAUTHN_ORIGINS ใน .env ขาด :8000 | ✅ เพิ่ม |
| soft-webauthn UV flag ไม่ set | ✅ UVSoftWebauthnDevice |

---

## Test result

```bash
docker compose exec -T hub-backend pytest tests/test_passkey_*.py tests/test_oauth_passkey.py \
  tests/test_stepup_cache.py tests/test_critical_action_policy.py tests/test_rbac.py \
  tests/test_health.py tests/test_jwt_service.py tests/test_pkce.py \
  tests/test_secret_service.py tests/test_rate_limit.py
```
```
============================= 164 passed in 47.29s =============================
```

---

## Security checks

- ✅ **Full ceremony verify** — signature/challenge/origin/RP ID/UV/sign_count ตรวจจริง
- ✅ **Counter regression** — lenient (allow + flag + risk boost), ไม่ block (Decision #9)
- ✅ **Discoverable userHandle** — ตรวจ credential ↔ user ตรงกัน (กัน userHandle ปลอม)
- ✅ **Discoverable challenge** — atomic getdel, server-issued (กัน replay)
- ✅ **Foreign/revoked device** — 401 ทั้ง email-first และ discoverable
- ✅ **Force adoption soft** — nudge ไม่ block (Q5 opt-in)
- ✅ **CI** — fail-safe ML/GeoIP, seeded users, isolated services

---

## Files changed

### Backend
- `services/webauthn_service.py` — discoverable_begin/complete, adoption_status, counter-regression fix (pass 0) ×3
- `routers/passkey.py` — discoverable start/finish, adoption endpoint
- `config.py` — passkey_required_after_days
- `requirements.txt` — soft-webauthn==0.1.4
- `tests/passkey_ceremony.py` — **ใหม่** (UV soft device + bridge)
- `tests/test_passkey_ceremony.py` — **ใหม่** (13 ceremony tests)

### CI
- `.github/workflows/backend-ci.yml` — **ใหม่**

### Frontend
- `lib/passkey.ts` — loginWithPasskeyDiscoverable
- `auth/login/page.tsx` — discoverable button + refactor (persistAndRedirect/friendlyErr)

---

## Passkey roadmap — COMPLETE

| Phase | สถานะ |
|---|---|
| 0 Foundation | ✅ |
| 1 Register + backup codes | ✅ |
| 2 Login | ✅ |
| 3 Lifecycle | ✅ |
| 4 Recovery + backup lifecycle | ✅ |
| 5 Step-up + ML + critical gate | ✅ |
| **6 Integration tests + CI** | ✅ |
| **7 Discoverable + force adoption** | ✅ |
| + Subsystem (chooser/enroll) + admin overview | ✅ |

ครบทุก phase ของ plan v3 🎉
