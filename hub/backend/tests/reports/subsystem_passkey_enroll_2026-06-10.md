# Subsystem Passkey Enrollment (E) — Test Report

**Date**: 2026-06-10
**Feature**: ให้ subsystem users (รวมนักศึกษา) ลงทะเบียน Passkey ได้ ผ่าน interstitial หลัง Google login
**Decision**: Option 1 — Interstitial หลัง Google login (user เลือก 2026-06-10)
**Status**: ✅ ALL PASS (101/101 รวม regression)

---

## ปัญหาที่แก้

`/account/security` (register passkey เดิม) ต้องมี Hub JWT (`aud=hub.internal`) แต่
**นักศึกษาถูกบล็อกจาก hub-direct login** ([auth.py:198](../../app/routers/auth.py#L198))
→ เข้า console ไม่ได้ → ลง passkey ไม่ได้เลย ทั้งที่เป็นผู้ใช้หลักของหอพัก/ห้องสมุด

**แก้:** enrollment ใน OAuth flow ของ subsystem (ไม่ต้อง console) — pattern เดียวกับ Google/GitHub

---

## Flow

```
subsystem → /oauth/authorize → chooser → Continue with Google
   → Google verify identity (oauth_callback)
   → ถ้า user ยังไม่มี passkey (count_active==0):
        commit google_sub + store enroll:{hub_state} → render interstitial
        ┌─────────────────────────────────────────┐
        │  หน้า "ตั้งค่า Passkey"                   │
        │  [ตั้งค่า Passkey]  → WebAuthn register   │
        │       → backup codes modal (must save)   │
        │  [ข้ามไปก่อน]                            │
        └─────────────────────────────────────────┘
        → ทั้งสองทาง → GET /oauth/continue?hub_state
   → ถ้ามี passkey แล้ว: _finalize ตามปกติ (ข้าม interstitial)
   → /oauth/continue → _finalize_subsystem_login → authcode → กลับ subsystem
```

นักศึกษาผ่าน flow นี้ได้ — subsystem callback (`/oauth/callback`) **ไม่บล็อก student**
(ต่างจาก hub-direct `/auth/google/callback`)

---

## Endpoints ใหม่

```
POST /oauth/passkey/enroll/start   {hub_state}                      → registration options
POST /oauth/passkey/enroll/finish  {hub_state, device_name, credential} → {passkey_id, backup_codes?}
GET  /oauth/continue               ?hub_state                        → authcode + redirect subsystem
```

**Security:** identity มาจาก `enroll:{hub_state}` ที่ server สร้างหลัง Google verify แล้ว
(client ปลอม user_id ไม่ได้). ไม่ต้องใช้ Hub JWT — แต่ผูกกับ flow context ที่ผ่าน Google มา

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_oauth_passkey.py -v
```

### Result — 20 tests (B 12 + E 8)

```
test_enroll_start_without_context_returns_400 PASSED
test_enroll_finish_without_context_returns_400 PASSED
test_enroll_start_short_hub_state_returns_422 PASSED
test_enroll_finish_missing_device_name_returns_422 PASSED
test_enroll_start_valid_context_returns_options PASSED   (student user!)
test_continue_without_authreq_returns_400 PASSED
test_continue_without_enroll_context_returns_400 PASSED
test_enroll_endpoints_registered PASSED
... + 12 B tests

============================== 20 passed in 1.29s ==============================
```

### Full regression

```
============================= 101 passed in 17.63s =============================
```

---

## Test coverage — E (8 tests)

| Test | ตรวจ |
|---|---|
| `enroll_start_without_context_returns_400` | flow guard — ต้องมี enroll context |
| `enroll_finish_without_context_returns_400` | flow guard (finish) |
| `enroll_start_short_hub_state_returns_422` | input validation |
| `enroll_finish_missing_device_name_returns_422` | device_name required |
| `enroll_start_valid_context_returns_options` | **student user** ได้ options (พิสูจน์นักศึกษา enroll ได้) |
| `continue_without_authreq_returns_400` | continue guard |
| `continue_without_enroll_context_returns_400` | continue ต้องมี enroll context |
| `enroll_endpoints_registered` | endpoints มีจริง |

---

## Security checks

- ✅ **Identity จาก server context** — `enroll:{hub_state}` สร้างหลัง Google verify, client ปลอม user ไม่ได้
- ✅ **Flow guard** — ทุก enroll/continue endpoint ต้องมี context (400 ถ้าเรียกนอก flow)
- ✅ **Student support** — subsystem callback ไม่บล็อก student → นักศึกษา enroll passkey ได้
- ✅ **Opt-in** — ปุ่ม "ข้ามไปก่อน" เสมอ (ไม่บังคับ — ตรงกับ Decision Q5)
- ✅ **Backup codes** — passkey แรก → generate 10 codes + modal must-save (copy/download + checkbox)
- ✅ **_finalize ตัวเดียวกัน** — /oauth/continue ผ่าน access_list + RBA + block เหมือน flow ปกติ
- ✅ **authcode timing** — สร้าง authcode ที่ /oauth/continue (หลัง interstitial) → ไม่หมดอายุระหว่างตั้งค่า
- ✅ **register_begin exclude_credentials** — กันลง passkey ซ้ำ device เดิม
- ✅ **CSP nonce** — interstitial inline style+script ใช้ nonce (กัน XSS)
- ✅ **B6/B9/B20** — audit order, atomic challenge, get_client_ip ครบ

---

## Manual test (operator, browser + Chrome virtual authenticator)

```
1. ลบ passkey เดิมของ test user ออกจาก DB (ถ้ามี)
2. ไป subsystem → login → chooser → Continue with Google → เลือก account
3. หลัง Google → เห็นหน้า "ตั้งค่า Passkey" (เพราะยังไม่มี passkey)
4a. กด "ตั้งค่า Passkey" → ใส่ชื่อ → WebAuthn → backup codes modal → save → เข้าต่อ
4b. หรือกด "ข้ามไปก่อน" → เข้า subsystem เลย
5. login ครั้งหน้า: chooser → Passkey → กรอก email → ผ่าน (ไม่ต้อง Google)
```

verify:
```sql
SELECT u.email, pc.device_name, pc.created_at,
       (SELECT COUNT(*) FROM passkey_backup_codes WHERE user_id=u.id) AS codes
FROM passkey_credentials pc JOIN users u ON u.id=pc.user_id
WHERE pc.revoked_at IS NULL;
-- audit: action='passkey_registered' metadata.via='subsystem_enroll'
```

---

## Files changed

- `app/routers/oauth.py`:
  - + `ENROLL_TTL` + `passkey_recovery` import
  - oauth_callback: interstitial branch (count_active==0 → render enroll page)
  - + `/oauth/passkey/enroll/start` + `/finish` (register via enroll context)
  - + `/oauth/continue` (authcode + redirect หลัง interstitial)
  - + `_passkey_enroll_html()` (Secure Vault interstitial + backup codes modal)
- `app/routers/auth.py`: google_login + `prompt=select_account` (บังคับเลือก account — multi-account/testing)
- `tests/test_oauth_passkey.py`: + 8 enroll tests (รวม 20)

---

## ครบ flow Passkey ตอนนี้

| ทาง | ใคร | ผ่าน |
|---|---|---|
| Hub console `/account/security` | teacher/staff/admin | Phase 1-2 |
| Subsystem chooser login | ทุกคนที่มี passkey | B |
| **Subsystem enroll interstitial** | **ทุกคนรวมนักศึกษา** | **E (นี่)** |
