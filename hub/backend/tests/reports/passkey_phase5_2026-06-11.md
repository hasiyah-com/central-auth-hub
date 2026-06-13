# Passkey Phase 5 — Step-up Auth + ML Integration + Critical Action Gate

**Date**: 2026-06-11
**Plan**: `docs/passkey-implementation-plan.md` v3
**Phase**: 5 — Step-up (Improvement #2) + Critical Action Gate (Improvement #8) + ML Device Trust (Improvement #5)
**Decision**: TOTP ตัดออก — ใช้ email OTP เดิมเป็น fallback (user 2026-06-11)
**Status**: ✅ ALL PASS (151/151 regression)

---

## 1. Step-up re-auth (Improvement #2)

### Endpoints
```
POST /auth/passkey/stepup/start    → assertion options (400 no_passkey → fallback OTP)
POST /auth/passkey/stepup/finish   → verify → grant trusted session 15 นาที
POST /auth/stepup/otp/start        → email OTP fallback (3/min)
POST /auth/stepup/otp/verify       → verify OTP → grant (5/min, lockout 5 ครั้ง)
```

ทั้ง 2 ทาง → `stepup_cache.set_granted(user_id, jti, method)` — Redis TTL 900s (Q7).
Grant ผูกกับ **jti ของ token ปัจจุบัน** — logout/token ใหม่ = ต้อง step-up ใหม่.

### Service
- `webauthn_service.stepup_begin/stepup_complete` — assertion ceremony keyed by user_id
  (challenge: `passkey:stepup:challenge:{user_id}`, atomic getdel B9, UV required,
  counter regression tracking เหมือน login)
- OTP fallback: `stepup:otp:{user_id}` Redis, mfa_service (HMAC constant-time), 5 attempts

---

## 2. Critical Action Gate wired (Improvement #8)

| Endpoint | Action |
|---|---|
| DELETE /account/passkeys/{id} | `gate("delete_passkey")` |
| POST /account/passkeys/backup-codes/regenerate | `gate("regenerate_backup_codes")` |
| POST /admin/users/{id}/reset-passkeys | `gate("admin_reset")` |

Gate (Phase 0) ตอนนี้ active จริง: ไม่มี step-up grant → **403 stepup_required** →
frontend redirect ไป step-up → กลับมาทำต่อ.

### Verified cycle (functional test)
```
1. admin token (no stepup) → regenerate → 403 stepup_required
2. grant stepup cache      → regenerate → 200 (10 codes)
3. clear cache             → regenerate → 403 อีกครั้ง
```

---

## 3. Frontend

- `auth/passkey/stepup/page.tsx` — ยืนยันด้วย Passkey → no_passkey/ปฏิเสธ → สลับ email OTP
  → สำเร็จ → กลับ `return_to`
- `lib/passkey.ts` — stepUpWithPasskey / stepupOtpStart / stepupOtpVerify
- `lib/api.ts` (clientFetch) — **central handler**: 403 `stepup_required` →
  redirect `/auth/passkey/stepup?return_to=<หน้าปัจจุบัน>` อัตโนมัติทุก console page

---

## 4. ML Device Trust features (Improvement #5) — 12 → 17

| Feature | Range | Risk implication |
|---|---|---|
| has_passkey | 0/1 | มี = trusted |
| passkey_count | 0-10 | มาก = mature account |
| passkey_age_days | 0-3650 | ใหม่ = น่าสงสัย |
| new_passkey_recently_added | 0/1 | เพิ่ม < 1 ชม. = **takeover sign** |
| passkey_last_used_days | 0-3650 | นานไม่ใช้ = device อาจเปลี่ยน |

### Files (B27/B28 — feature order contract)
- `ml-service/app/features.py` — FEATURE_NAMES + RANGES (17)
- `ml-service/scripts/generate_data.py` — + passkey features ทุก generator
  + anomaly pattern ใหม่ **passkey_takeover** (เพิ่ม passkey เมื่อกี้ + login จากที่แปลก)
- `hub/backend/app/services/feature_extraction.py` — extract 5 features จาก
  passkey_credentials (cold start: ไม่มี passkey → 0 ทุกตัว, neutral)

### Retrain result
```
dataset: 10,000 normal + 500 anomaly (17 features)
AUC-ROC: 0.9946
best threshold (Youden's J): TPR 0.9900, FPR 0.0445
```

### End-to-end scoring verification
```
normal + established passkey (age 200d)       → 0.34 pass
takeover (new passkey 0.1d + foreign + new dev) → 0.69 mfa
  → SHAP top: country_change_count_30d (1.42), new_passkey_recently_added (1.41)
```
→ model จับ takeover pattern ได้ + SHAP อธิบายว่า passkey ใหม่เป็นปัจจัยหลัก

---

## Test result

```
================== 151 passed in 63.50s ==================
```

อัปเดต: `test_regenerate_endpoint_admin_only` — สะท้อน gate ใหม่
(admin no-stepup → 403 stepup_required; + grant → 200; clear → 403)

---

## Security checks

- ✅ **Grant ผูก jti** — token ใหม่/logout = step-up ใหม่ (ไม่ carry ข้าม session)
- ✅ **TTL 900s** (Q7) — env-configurable
- ✅ **Challenge atomic getdel** (B9) + UV required (Decision #2)
- ✅ **OTP fallback**: HMAC constant-time + lockout 5 + rate limit — ตามที่ user สั่ง (ไม่ใช้ TOTP)
- ✅ **Gate fail-closed** — ไม่มี jti/ไม่มี grant → 403 เสมอ
- ✅ **Audit**: passkey_stepup_success/failed + stepup_otp_success
- ✅ **B27** — retrain หลังเพิ่ม features (ไม่งั้น feature-count mismatch crash)
- ✅ **Cold start neutral** — user ไม่มี passkey → features 0 (ไม่ penalize)

---

## Manual test (operator)

```
1. Login admin (Google/passkey) → /account/security
2. กด "🔄 สร้างใหม่" (backup codes)
   → ถูกพาไปหน้า "ยืนยันตัวตนอีกครั้ง" (step-up)
3. ยืนยันด้วย Passkey (หรือ OTP ถ้าไม่มี)
   → กลับมาหน้า security อัตโนมัติ → กดสร้างใหม่อีกครั้ง → สำเร็จ
4. ภายใน 15 นาที: ลบ passkey / reset ของ user อื่น → ไม่ถูกถามซ้ำ (cache hit)
5. หลัง 15 นาที → ถูกถาม step-up ใหม่
```

---

## Phase 5 — Acceptance criteria

- [x] stepup_begin/complete (passkey ceremony, keyed by user)
- [x] OTP fallback (email OTP เดิม — TOTP ตัดตาม user)
- [x] grant → stepup_cache (jti-bound, TTL 900s)
- [x] gate wired: delete_passkey, regenerate_backup_codes, admin_reset
- [x] frontend stepup page + clientFetch auto-redirect + return_to
- [x] ML 17 features + passkey_takeover pattern + retrain (AUC 0.9946)
- [x] feature extraction end-to-end verified (17 features, SHAP จับ takeover)
- [x] 151/151 regression

---

## Passkey roadmap

| Phase | สถานะ |
|---|---|
| 0-4 + subsystem (B/A/E) + backup lifecycle | ✅ |
| **5 Step-up + ML + critical gate** | ✅ **(นี่)** |
| 6 Integration tests (soft-webauthn, full ceremony) | ⏳ next |
| 7 Discoverable + force adoption | ⏳ deferred |
