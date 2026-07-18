# Plan — ข้อ 3: เปลี่ยนบัญชี Google (Self-service Re-link) + Security

## Context

**ปัญหา:** ระบบ login แบบ Hub-direct ใช้ **email เป็น key ในการหา User** (`auth.py:177`) และ
`google_sub` เป็นเพียง guard กัน hijack (TOFU-bound ครั้งแรกที่ `auth.py:308`, เช็ค mismatch ที่
`auth.py:280`). ผลคือถ้าผู้ใช้ **ลืมรหัส Gmail / บัญชี Google ถูกปิด / ต้องเปลี่ยนอีเมล** →
เข้าระบบไม่ได้ถาวร ทั้งที่ข้อมูล/สิทธิ์/audit/subsystem ทั้งหมดผูกกับ `user.id` (UUID PK) ไม่ใช่ email/sub

**เป้าหมาย:** ให้ผู้ใช้ที่ยัง**ยืนยันตัวตนเดิมได้ (Passkey)** เชื่อมบัญชี Google ใหม่ (email + sub ใหม่)
เข้ากับ Hub user เดิม โดยข้อมูลเดิมอยู่ครบ — และออกแบบให้ **กัน account takeover** เพราะนี่คือ
primitive ที่อันตรายที่สุด (ผูก Google ของ attacker เข้ากับ user เหยื่อ = ยึดบัญชี)

**การตัดสินใจ (จาก user):**
1. **Full re-link** — เปลี่ยนทั้ง `user.email` + `user.google_sub`
2. **บังคับ Passkey เท่านั้น** สำหรับ step-up ของ action นี้ (ไม่รับ email-OTP — เพราะ scenario คือ email เดิมอาจเสียไปแล้ว + phishing-resistant)

**ไม่ต้องมี Alembic migration** — ใช้ column เดิมทั้งหมด (`google_sub`, `email`, `email_verified`,
`email_verified_at` — 2 ตัวหลังประกาศไว้แล้วแต่ยังไม่เคยเขียน `models.py:61-64`)

---

## สถาปัตยกรรม Flow (3 endpoints — bridging token)

เหตุผลที่ต้อง 3 ขา: prod แยก subdomain (`admin.` vs `auth.`) → Authlib session-state cookie
round-trip ได้เฉพาะตอน **browser navigate ตรง** (เหมือน `/auth/google/login` ที่เป็น `<a href>`).
XHR ผ่าน `/api/proxy` เซ็ต cookie ให้ browser ไม่ได้ → ต้องใช้ **Redis single-use token** เป็นตัว
เชื่อม "initiation ที่ผ่าน passkey step-up (XHR)" → "OAuth legs (browser nav)" — mirror pattern
`authreq:{hub_state}` ของ subsystem flow (`oauth.py:64,207,272`)

```
[Account page] ── mutateWithStepup (XHR, passkey ceremony inline) ──▶
  (1) POST /auth/account/change-google/start        [gated: passkey step-up]
        → mint Redis change_google:{token} = {user_id, jti, ip, at}, TTL 600s
        → return { start_url: "{HUB}/auth/account/change-google/redirect?t={token}" }
        ← frontend: window.location.href = start_url   (full-page nav)

  (2) GET /auth/account/change-google/redirect?t={token}   [browser nav]
        → peek token (ยังไม่ consume) → 400 ถ้าไม่มี/หมดอายุ
        → oauth.google.authorize_redirect(request, GOOGLE_CHANGE_REDIRECT_URI,
             state=token, prompt="select_account")   ← Authlib session cookie ถึง browser ที่นี่

  (3) GET /auth/account/change-google/callback?code&state={token}   [browser nav จาก Google]
        → Authlib validate session-state (CSRF) + Redis getdel token (single-use, B9)
        → verify state == token.key, resolve user_id จาก token payload
        → exchange code → new_email, new_sub, email_verified จาก Google userinfo
        → GUARDS (ดูล่าง) → APPLY → FORCE RE-LOGIN → ALERT emails → AUDIT
        → redirect {admin_frontend_url}/auth/login?google_changed=1
```

---

## Backend — รายละเอียด

**ไฟล์ใหม่:** `hub/backend/app/routers/account_link.py` (router prefix `/auth/account`,
register ใน `main.py`) — แยกจาก `auth.py` ที่ใหญ่แล้ว

### (1) `POST /change-google/start` — passkey-step-up gated
- Auth: `Depends(get_current_user)` (ผ่าน proxy → bearer)
- **Passkey-only gate (custom, ไม่ใช่ `gate()` ตรงๆ เพราะ `gate()` รับ OTP ด้วย):**
  reuse `_extract_jti` + `stepup_cache.check_cached(user.id, jti)` (`critical_action_policy.py:80`,
  `stepup_cache.py:65`) → payload ต้องมี **`method == "passkey"`**; ไม่งั้น raise
  `403 {code:"stepup_required", action:"change_google_account", ...}` (ให้ frontend re-drive passkey)
  → เพิ่มชื่อ `change_google_account` ใน `CRITICAL_ACTIONS` (`critical_action_policy.py:43`) ด้วย เพื่อความสม่ำเสมอ
- mint `secrets.token_urlsafe(32)` → `redis_client.setex("change_google:{token}", 600, json{user_id, jti, ip, at})`
- return `{ start_url }`

### (2) `GET /change-google/redirect?t=` — browser nav
- peek `change_google:{t}` (get, ไม่ลบ) → 400 ถ้าไม่มี
- `return await oauth.google.authorize_redirect(request, settings.google_change_redirect_uri, state=t, prompt="select_account")`
  (reuse shared client `auth.py:51-58`, pattern `auth.py:106`)

### (3) `GET /change-google/callback` — apply
- `token = await oauth.google.authorize_access_token(request)` (Authlib session-state = CSRF, `auth.py:162`)
- `payload = redis_client.getdel("change_google:{state}")` → 410 ถ้า None (single-use/replay guard, B9)
- `userinfo = token["userinfo"]` → `new_sub`, `new_email`, `email_verified`
- **GUARDS (ทุกอันfail → audit `account_google_change_failed_*` → commit → redirect login?error):**
  1. `email_verified is True` (Google userinfo) — ไม่งั้น reject
  2. `new_sub` ไม่ตรงกับ user อื่น: `User.google_sub == new_sub AND id != uid` → reject (`google_sub` UNIQUE `models.py:34`)
  3. `new_email` ไม่ตรงกับ user อื่น: `User.email == new_email AND id != uid` → reject (`email` UNIQUE `models.py:36`)
  4. same account (`new_sub == user.google_sub`) → no-op message (ไม่ error)
  5. user.status == active
- **APPLY:** `user.email = new_email; user.google_sub = new_sub; user.email_verified = True;
  user.email_verified_at = utcnow()`
- **FORCE RE-LOGIN (identity binding เปลี่ยน → session เดิมต้องตาย):** reuse logic force-logout
  ที่มีอยู่ (`admin.py` force-logout / `session_revoke`) — close ทุก `LoginSession` ของ user +
  `jwt_service.revoke_jti(jti)` แต่ละ session + `refresh_token_service` revoke +
  `stepup_cache.clear_all_for_user(user.id)` (`stepup_cache.py:89`)
- **ALERT emails (anti-takeover control สำคัญสุด):** `email_service._send_html_email` ไปทั้ง
  **old_email + new_email** — "บัญชี Google ที่ใช้ login ถูกเปลี่ยน" + เวลา/IP → เหยื่อรู้ตัวถ้าโดนยึด
- **AUDIT:** `log_action(db, actor_id=user.id, action="account_google_changed", target_type="user",
  target_id=user.id, ip=get_client_ip(request), metadata={old_email, new_email, old_sub_prefix,
  new_sub_prefix})` → `db.commit()` (B6 order)
- redirect `{admin_frontend_url}/auth/login?google_changed=1`

### Reused building blocks (ไม่เขียนใหม่)
| ต้องใช้ | มีอยู่แล้วที่ |
|---|---|
| step-up cache check/method | `stepup_cache.check_cached/clear_all_for_user` (`stepup_cache.py:65,89`) |
| jti จาก bearer | `critical_action_policy._extract_jti` (`critical_action_policy.py:80`) |
| Google OAuth client + redirect/exchange | `oauth.google.*` (`auth.py:51-58,106,162`) |
| single-use Redis token | pattern `authreq` (`oauth.py:64,207,272`) + `redis_client.getdel` |
| revoke sessions | force-logout logic ใน `admin.py` (`session_revoke`) + `jwt_service.revoke_jti` + `refresh_token_service` |
| audit | `audit_service.log_action` (`audit_service.py:13`) |
| email | `email_service._send_html_email` (ใช้ใน `mfa_service.py`) |
| client IP | `get_client_ip` (`deps.py`) |

### Config (`config.py`) + manual step
- เพิ่ม `google_change_redirect_uri` (default `http://localhost:8000/auth/account/change-google/callback`)
- **Manual (B17):** เพิ่ม redirect URI นี้ใน Google Cloud Console → Credentials → Authorized redirect URIs
  (dev: `http://localhost:8000/...`; prod: `https://auth.<domain>/auth/account/change-google/callback`)
- บันทึกใน `docs/VM_PENDING_CHANGES.md` (env + Google Console step)

---

## Frontend — รายละเอียด

**ไฟล์:** `hub/frontend/components/AccountView.tsx` (+ helper ใน `hub/frontend/lib/passkey.ts`)

- เพิ่ม card **"บัญชี Google"** ใต้ Profile: แสดง email ที่เชื่อมอยู่ (`me.email` จาก `/api/me` ที่มีอยู่แล้ว)
  + ปุ่ม **"เปลี่ยนบัญชี Google"**
- helper ใหม่ใน `passkey.ts`:
  `changeGoogleStart(setVerifying) = mutateWithStepup<{start_url}>("/auth/account/change-google/start",
  {method:"POST"}, setVerifying)` → on success `window.location.href = res.start_url`
  (mutateWithStepup ขับ passkey ceremony inline อยู่แล้ว — `passkey.ts:522,464`)
- error `no_passkey` → แสดง "ต้องมี Passkey เพื่อเปลี่ยนบัญชี — ไป Account Recovery" + ลิงก์ `/auth/passkey/recover`
- login page (`app/auth/login/page.tsx`): อ่าน `?google_changed=1` → banner เขียว "เปลี่ยนบัญชี Google
  สำเร็จ — เข้าสู่ระบบด้วยบัญชีใหม่" (หน้านี้ใช้ `useSearchParams` อยู่แล้ว)

---

## Security analysis

| Threat | Mitigation |
|---|---|
| Attacker ผูก Google ตัวเองเข้ากับ user เหยื่อ | ต้องผ่าน **passkey step-up** (phishing-resistant, ครองอุปกรณ์เหยื่อจริง) + OAuth พิสูจน์ครอง Google ใหม่ — 2 proof สดพร้อมกัน |
| Replay / race บน token | Redis single-use `getdel` (B9) + TTL 600s + bind `{user_id, jti, ip}` |
| CSRF บน OAuth leg | Authlib session-state (`authorize_access_token` validate) |
| ยึด email คนอื่น / sub ชน | UNIQUE guards (new_email/new_sub ไม่ตรง user อื่น) ก่อน apply |
| Google email ปลอม/ยังไม่ verify | require `userinfo.email_verified == true` |
| เหยื่อไม่รู้ตัวว่าโดนเปลี่ยน | **Alert email ไป old + new** + audit `account_google_changed` |
| session เก่ายังใช้ได้หลังเปลี่ยน identity | force revoke ทุก session + jti + refresh + stepup cache |
| brute/abuse initiate | rate-limit `/change-google/start` (`@limiter.limit` เหมือน `auth.py:84`) |

**Residual risk (เขียนใน thesis):** ถ้า attacker ครอง Passkey ของเหยื่อได้จริง (เช่นอุปกรณ์ถูกขโมย
พร้อม unlock) จะทำได้ — แต่นั่นคือ full device compromise ซึ่งเกินขอบเขต IAM; alert email ยังเป็น
detective control ชั้นสุดท้าย **จุดขาย thesis:** การ re-link ทำได้เพราะออกแบบ identity แยกจาก IdP
(UUID PK ≠ google_sub) — เปลี่ยน 2 column ข้อมูลอยู่ครบ

---

## Files

**สร้างใหม่:**
- `hub/backend/app/routers/account_link.py` — 3 endpoints
- `hub/backend/tests/test_change_google.py` — TDD
- `hub/backend/tests/reports/change_google_<date>.md` — รายงานผล (กฎ test-artifact)

**แก้:**
- `hub/backend/app/main.py` — register router
- `hub/backend/app/services/critical_action_policy.py:43` — เพิ่ม `change_google_account`
- `hub/backend/app/config.py` — เพิ่ม `google_change_redirect_uri`
- `hub/frontend/components/AccountView.tsx` — card ใหม่
- `hub/frontend/lib/passkey.ts` — `changeGoogleStart` helper
- `hub/frontend/app/auth/login/page.tsx` — success banner
- `docs/VM_PENDING_CHANGES.md`, `.env.example`, `docs/bugs-encountered.md` (ถ้าเจอ bug)

---

## Verification (TDD — RED → GREEN → REFACTOR ตามกฎโปรเจค)

**pytest** `hub/backend/tests/test_change_google.py` (รัน `docker compose exec hub-backend pytest tests/test_change_google.py -v`):
1. `start` ไม่มี passkey-stepup grant → 403 `stepup_required`
2. `start` มี **otp** grant เท่านั้น → ยัง 403 (บังคับ passkey)
3. `start` มี **passkey** grant → 200 + `start_url` + Redis token ถูก mint
4. `redirect` token หมดอายุ/ไม่มี → 400
5. `callback` happy: re-link → `user.email`+`user.google_sub` เปลี่ยน, **`user.id` เดิม**, `access_list`/`audit` ของ user ยังอยู่ครบ
6. `callback` guard: new_email เป็นของ user อื่น → reject ; new_sub ชน → reject ; `email_verified=false` → reject
7. `callback` replay (getdel แล้ว) → 410
8. หลัง callback: ทุก `LoginSession.jti` ถูก `is_revoked`, stepup cache ว่าง
9. audit row `account_google_changed` มี old/new ; alert email ถูกเรียก 2 ครั้ง (mock `_send_html_email`)

**Manual E2E (dev, ผ่าน Browser MCP):** login Hub → /account → "เปลี่ยนบัญชี Google" → passkey
ceremony → เลือก Google account ที่ 2 (ต้องเป็น test user ใน Console) → กลับมาที่ login?google_changed=1
→ login ด้วยบัญชีใหม่ได้ + ข้อมูลเดิมอยู่ ; ตรวจ `/audit` เห็น `account_google_changed`

**Prereq manual:** เพิ่ม redirect URI ใน Google Console + `google_change_redirect_uri` ใน `.env` +
`--force-recreate hub-backend` (B36) ; Google OAuth app ต้องมี test user ≥ 2 บัญชี (B15)
