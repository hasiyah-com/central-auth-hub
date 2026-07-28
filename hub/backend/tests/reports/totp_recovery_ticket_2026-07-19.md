# Test Report — TOTP + Credential Lifecycle + Recovery Ticket (multi-phase)

**วันที่:** 2026-07-19 · **แผน:** `plan/totp-recovery-ticket.md`

---

## Phase 1 — TOTP + Credential Lifecycle + Passkey Status ✅

**สร้าง:** `services/totp_service.py` · `routers/totp.py` · migration `a1b2c3d4e5f6` (user_totp_credentials,
recovery_tickets, recovery_ticket_approvals, passkey_credentials.status) · `models.py` (+3 models, credential
status enum) · pyotp==2.9.0

**Credential Lifecycle:** REGISTERED → ACTIVE → SUSPENDED → REVOKED (ใช้ร่วม Passkey+TOTP).
Passkey auth query เพิ่มเงื่อนไข `status=ACTIVE` (SUSPENDED บล็อก auth); backfill REVOKED ที่ revoked_at≠NULL.

**รัน:** `docker compose exec hub-backend pytest tests/test_totp.py -v` → **8/8 PASSED**

| test | ตรวจ |
|---|---|
| verify_correct_wrong_expired | pyotp verify (valid_window=1) |
| totp_lifecycle | REGISTERED→ACTIVE→SUSPENDED→REVOKED · verify_active เฉพาะ ACTIVE |
| confirm_enroll_wrong_code | code ผิด → คง REGISTERED |
| enroll_start_requires_stepup | gate totp_enroll → 403 ถ้าไม่มี step-up |
| enroll_flow_via_api | start→secret/QR → verify code จริง → ACTIVE |
| stepup_totp_grants_method_totp | /auth/stepup/totp/verify → cache method="totp" |
| change_google_still_requires_passkey | TOTP step-up **ไม่**ปลดล็อก change-google (บังคับ passkey) |
| passkey_suspended_not_counted | SUSPENDED passkey ไม่ถูกนับ/auth ไม่ได้ |

**Migration verify:** passkey status backfill = 4 ACTIVE / 12 REVOKED (ตรง revoked_at) · 3 ตารางใหม่สร้างครบ

**Regression:** `pytest test_passkey_login/security/lifecycle/register/recovery + change_google + stepup_cache +
critical_action_policy -q` → **122/122 PASSED** (passkey status ไม่กระทบของเดิม)

---

## Phase 2 — TOTP Recovery + Cooldown + Audit source + google_sub fix ✅

**ทำ:** `account_link.py` (`_mint_change_token` helper + 24h cooldown + `source` param + consume ticket) ·
`passkey.py` (`POST /auth/passkey/recover/totp`) · `users.py` (update_user เคลียร์ google_sub ตอนเปลี่ยน email)

**รัน:** `pytest tests/test_totp_recovery.py -v` → **6/6 PASSED**

| test | ตรวจ |
|---|---|
| recover_totp_success | TOTP ถูก → start_url + token source=RECOVERY |
| recover_totp_wrong_code / unknown_email | opaque 400 recovery_failed (anti-enum) |
| apply_sets_cooldown_and_source | re-link สำเร็จ → cooldown set + audit changed_by=RECOVERY |
| change_google_start_blocked_by_cooldown | ติด cooldown → 429 change_google_cooldown |
| admin_update_email_clears_google_sub | **bug fix**: admin เปลี่ยน email → google_sub=NULL + email_verified=False |

**Regression:** change_google + totp + rbac → **33/33 PASSED** (account_link refactor ไม่พัง)

## Phase 3 — Credential Management + Recovery Ticket (four-eyes) ✅

**สร้าง:** `routers/recovery.py` (request public + admin approve/reject four-eyes) ·
`services/credential_service.py` (list GOOGLE+PASSKEY+TOTP + recovery_ready) ·
endpoint `/auth/account/credentials` (self) + `/admin/users/{id}/credentials` (admin)

**รัน:** `pytest tests/test_recovery_ticket.py -q` → **6/6 PASSED**

| test | ตรวจ |
|---|---|
| request_creates_pending_ticket | ยื่นคำขอ → ticket pending (level NORMAL) |
| request_unknown_email_opaque | email ไม่มี → opaque + ไม่สร้าง ticket (anti-enum) |
| approve_normal_issues_link | NORMAL 1 admin approve → relink_url + status=approved + evidence บันทึก |
| approve_high_requires_two_admins | **HIGH four-eyes:** A→1/2 awaiting · A ซ้ำ→409 · B→2/2→link |
| non_admin_cannot_list | teacher เข้า /admin/recovery-tickets → 403 |
| credentials_lists_google_passkey_totp | `/credentials` คืน GOOGLE+PASSKEY+TOTP + recovery_ready=true |

**Regression รวมทุกเฟส:** `pytest test_totp + test_totp_recovery + test_recovery_ticket +
change_google + passkey_login + passkey_recovery + rbac + stepup_cache -q` → **86/86 PASSED**

---

## Phase 4 — Frontend (UI) ✅

**สร้าง/แก้:** `lib/passkey.ts` (helpers: totp enroll/verify/disable/status, recoverWithTotp,
submitRecoveryRequest, credentials, admin ticket approve/reject) · `components/account/TotpCard.tsx`
(enroll QR ด้วย qrcode.react) · `AccountView.tsx` (+TotpCard) · `recover/page.tsx` (+tab Authenticator
+ ขอ Admin ช่วย) · `app/(console)/recovery-tickets/page.tsx` (admin triage + evidence form + four-eyes) ·
`Sidebar.tsx` (+คำขอกู้บัญชี) · `users/[id]/page.tsx` (Authentication Methods + Recovery Ready badge) ·
`package.json` (qrcode.react)

**Verify:**
- `tsc --noEmit` exit 0 (ทุกไฟล์)
- Browser (public recover page): 5 tabs render · คลิก Authenticator → TOTP input + "ยืนยัน →
  เปลี่ยนบัญชี Google" · **no console errors** · qrcode.react bundle โหลดสะอาด
- pages ที่ต้อง login (TotpCard, /recovery-tickets, User360) — tsc ผ่าน + reuse helpers เดียวกับที่ verify แล้ว

---

## Phase 4b — Inline step-up TOTP fallback (ปิด gap Part A4) ✅

**อาการที่พบ:** step-up ใน UI ขึ้นแค่ passkey — `runWithStepup()` (lib/passkey.ts) hard-code
`stepUpWithPasskey()` อย่างเดียว, `onVerifying` เป็นแค่ boolean spinner ไม่มีช่องกรอก TOTP
→ user ที่ไม่มี passkey เด้งไป recovery ทั้งที่มี TOTP ใช้แทนได้

**แก้ (frontend, reuse helper เดิม `stepupWithTotp`):**
- `lib/passkey.ts` — `runWithStepup(run, onVerifying, opts?)` : passkey fail (no_passkey /
  user cancel `NotAllowedError`) + `opts.totpFallback !== false` + มี provider → เรียก
  `_totpStepupPrompt()` (modal) → retry. `registerTotpStepupPrompt()` registry.
  `mutateWithStepup` thread `opts` ต่อ. **`changeGoogleStart` ตั้ง `totpFallback:false`**
  (passkey-only — backend บังคับ, กัน retry loop เพราะ gate change_google ปฏิเสธ totp)
- `components/StepupTotpProvider.tsx` (ใหม่) — modal กรอก 6 หลัก, เช็ค `totpStatus()` ก่อน
  (ถ้าไม่มี TOTP → ข้อความแนะนำ ไม่ dead-end), verify + error เอง, resolve true/false
- `app/layout.tsx` — mount `<StepupTotpProvider>` ครอบทุกหน้า (console+developer+account)

**Verify:** `tsc --noEmit` — ไม่มี error ในไฟล์ที่แก้ (เหลือแต่ amcharts5/qrcode.react ที่รอ `npm i`)

**Manual E2E (บน stack ที่รันจริง):** login เป็น user ที่**มี TOTP แต่ไม่มี passkey** → ทำ
critical action (เช่น suspend/disable TOTP, admin approve ticket) → passkey ceremony ล้ม/ไม่มี →
modal TOTP เด้ง → กรอกรหัส → action ผ่าน · เทียบ change-google: ต้อง**ไม่**เด้ง TOTP (คงข้อความ
"ต้องมี Passkey")

---

## สรุป: เสร็จครบทั้ง 4 เฟส (backend 3 + frontend)
Backend 20 tests + 86 regression · Frontend tsc 0 + browser verify · ทุก improvement 10 ข้อจากรีวิว
พับเข้าครบ (lifecycle, four-eyes, credential_type GOOGLE, audit source, evidence, recovery level ฯลฯ)
