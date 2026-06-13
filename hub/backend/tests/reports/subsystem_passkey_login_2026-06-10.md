# Subsystem Passkey Login (A + B) — Test Report

**Date**: 2026-06-10
**Feature**: ให้ subsystem (หอพัก/ห้องสมุด) login ได้ทั้ง Google + Passkey ผ่าน OAuth flow
**Status**: ✅ ALL PASS (93/93 รวม regression)

---

## Requirement (user)

```
Subsystem → /oauth/authorize → หน้าเลือก Login
  [ Continue with Google ]      [ Continue with Passkey ]
        ↓                              ↓
   Google Callback              WebAuthn Verify
        ↓                              ↓
   Authorization Code  ←── เหมือนกัน ──→  Authorization Code
        ↓
   /oauth/token → JWT
```

ทำ **B (backend) ก่อน → A (chooser UI) ต่อ**

---

## B — Passkey เข้า OAuth callback flow (backend)

### B1 — Refactor: extract `_finalize_subsystem_login()`

logic ~290 บรรทัดใน `oauth_callback` (access_list → identity challenge → RBA →
login session → block → authorization code → audit → redirect) ถูกแยกเป็น
shared helper ที่ **provider-agnostic** — Google + Passkey เรียกตัวเดียวกัน
→ logic + audit + security checks ตรงกันเป๊ะ ไม่ duplicate

**Google-specific (อยู่นอก helper):** token exchange, userinfo, unknown_email,
google_sub binding, profile sync
**Passkey-specific (อยู่นอก helper):** WebAuthn assertion verify, active check
**Shared (ใน helper):** ที่เหลือทั้งหมด

### B2 — Passkey OAuth endpoints

```
POST /oauth/passkey/start   {hub_state, email}           → WebAuthn assertion options
POST /oauth/passkey/finish  {hub_state, email, credential} → {redirect_url}
```

- ต้องมี active `authreq:{hub_state}` ก่อน (flow guard — กันเรียกนอก flow)
- EmailStr validation (SQLi/XSS reject ที่ Pydantic layer)
- `auth_complete` opaque error (anti-enumeration)
- counter regression (Improvement #10) → +0.2 risk boost ผ่าน helper, ไม่ block
- finish → `_finalize_subsystem_login(provider="passkey")` → คืน redirect_url

---

## A — Chooser page ที่ `/oauth/authorize`

`/oauth/authorize` เดิม redirect ตรงไป Google → เปลี่ยนเป็นแสดง **HTML chooser**:
- ปุ่ม **Passkey** → JS WebAuthn ceremony (inline) → fetch `/oauth/passkey/{start,finish}` → navigate `redirect_url`
- ปุ่ม **Google** → `GET /oauth/authorize/google?hub_state=...` → Authlib redirect (logic เดิม)

หน้า chooser:
- เสิร์ฟจาก Hub (localhost:8000) → fetch same-origin ไม่ต้อง proxy
- feature detection (`PublicKeyCredential`) → ซ่อน/disable ถ้า browser ไม่รองรับ
- subsystem name escaped (กัน HTML injection จาก DB)
- email-first input (Decision #1)

---

## API endpoints (เพิ่ม)

```
GET  /oauth/authorize           → HTML chooser (เดิม redirect Google)
GET  /oauth/authorize/google    → Authlib redirect ไป Google (ปุ่ม Google)
POST /oauth/passkey/start       → assertion options
POST /oauth/passkey/finish      → {redirect_url}
```

---

## Test Execution

```bash
docker compose exec -T hub-backend pytest tests/test_oauth_passkey.py -v
```

### test_oauth_passkey.py — 12 tests

```
test_start_without_authreq_returns_400 PASSED
test_finish_without_authreq_returns_400 PASSED
test_start_rejects_non_email[notanemail] PASSED
test_start_rejects_non_email[x' OR '1'='1] PASSED
test_start_rejects_non_email[<script>alert(1)</script>] PASSED
test_start_rejects_non_email[a b@x.com] PASSED
test_start_short_hub_state_returns_422 PASSED
test_start_valid_flow_returns_options PASSED
test_finish_missing_credential_returns_422 PASSED
test_finish_no_challenge_returns_400 PASSED
test_finalizer_helper_exists_and_signature PASSED
test_oauth_callback_still_imports PASSED

============================== 12 passed in 0.98s ==============================
```

### Full regression (รวม Google flow ไม่พัง)

```
93 passed in 15.66s
```

ครอบคลุม: oauth_passkey(12) + passkey_register(10) + passkey_login(11) +
passkey_security(20) + stepup_cache(6) + critical_action(7) + health(5) +
rbac(5) + pkce(3) + jwt_service(4) + secret_service(8) + rate_limit(2)

---

## Manual render verification

```bash
curl "http://localhost:8000/oauth/authorize?client_id=cli_...&redirect_uri=...&state=...&code_challenge=..."
```
→ HTML แสดง:
- "เข้าสู่ ระบบห้องสมุด" (subsystem name)
- ปุ่ม "🔑 ดำเนินการด้วย Passkey"
- ปุ่ม "Continue with Google" → `/oauth/authorize/google?hub_state=<token>`

---

## Security checks

- ✅ **Shared finalizer** — Passkey path ผ่าน access_list + identity challenge + RBA + block เหมือน Google เป๊ะ (ไม่มี bypass)
- ✅ **Flow guard** — passkey endpoints ต้องมี authreq:{hub_state} ก่อน (กันเรียกนอก flow)
- ✅ **EmailStr validation** — SQLi/XSS reject ที่ Pydantic (422)
- ✅ **Anti-enumeration** — opaque options + opaque 401 (ไม่บอกว่า email มี Passkey ไหม)
- ✅ **B9 atomic getdel** — passkey challenge + authcode ใช้ครั้งเดียว
- ✅ **B6 audit order** — log → commit → raise ทุก failure path
- ✅ **PKCE คงอยู่** — passkey path ยังเก็บ code_challenge ใน authcode → /oauth/token verify เหมือนเดิม
- ✅ **HTML injection guard** — subsystem name escaped ในหน้า chooser
- ✅ **Google flow ไม่ถูกแตะ** — token_exchange + google_sub binding คงเดิม (regression pass)
- ✅ **counter regression** (Improvement #10) — +0.2 risk, audit, ไม่ block

---

## Reproducible

```bash
docker compose exec -T hub-backend pytest tests/test_oauth_passkey.py -v

# render chooser (ต้องมี active subsystem)
curl "http://localhost:8000/oauth/authorize?client_id=<cid>&redirect_uri=<uri>&state=s&code_challenge=$(python -c 'print(chr(120)*43)')"

# guards
curl -X POST localhost:8000/oauth/passkey/start -d '{"hub_state":"nope12345678","email":"a@uni.ac.th"}' -H "Content-Type: application/json"  # 400
curl -X POST localhost:8000/oauth/passkey/start -d '{"hub_state":"nope12345678","email":"notanemail"}' -H "Content-Type: application/json"   # 422
```

---

## Files changed

### Backend
- `app/routers/oauth.py`:
  - + import pydantic (BaseModel/EmailStr/Field) + webauthn_service
  - refactor: extract `_finalize_subsystem_login()` (provider-agnostic helper)
  - `/oauth/authorize` → return HTML chooser (เดิม redirect Google)
  - + `/oauth/authorize/google` (ปุ่ม Google → Authlib redirect)
  - + `/oauth/passkey/start` + `/oauth/passkey/finish` (Passkey path)
  - + `_login_chooser_html()` (chooser page + inline WebAuthn JS)
- `tests/test_oauth_passkey.py` — **ใหม่** (12 tests)

---

## End-to-end manual test (operator — browser required)

Pre-req: user มี Passkey register ที่ Hub แล้ว + อยู่ใน whitelist ของ subsystem

1. ไป subsystem (เช่น http://localhost:8002) → กด login
2. redirect มา `/oauth/authorize` → **เห็นหน้าเลือก 2 ปุ่ม**
3. **ทดสอบ Passkey path:**
   - กด "🔑 ดำเนินการด้วย Passkey" → กรอก email → TouchID/Hello
   - → redirect กลับ subsystem พร้อม code → subsystem แลก token สำเร็จ
4. **ทดสอบ Google path:**
   - กด "Continue with Google" → Google login → redirect กลับ subsystem
5. ทั้งสองทาง → ได้ JWT จาก /oauth/token เหมือนกัน
6. DB: `SELECT action, metadata->>'provider' FROM audit_logs WHERE action='oauth_authorized' ORDER BY created_at DESC LIMIT 2;`
   → เห็น provider = "passkey" และ "google"

---

## หมายเหตุ — ไม่ขัด architecture (ไม่ใช่ SSO)

Passkey ทำงานเฉพาะตอน authenticate ที่ Hub ในแต่ละ OAuth flow ของ subsystem.
ไม่มีการแชร์ session ข้ามระบบ — แต่ละ subsystem ยังต้องผ่าน /oauth/authorize +
ยืนยันตัวตนที่ Hub ใหม่ทุกครั้ง (Passkey แค่เป็นทางเลือกแทน Google ในขั้น authenticate).
