# Plan — TOTP + Credential Lifecycle/Management + Recovery Ticket (four-eyes)

## Context

**ปัญหา:** เคส "เข้า Gmail เดิมไม่ได้ + ไม่มี/ทำ passkey หาย" = ตัน. Backup code UX แย่.
ระบบใช้ **Google OAuth = Primary Identity**; Passkey/TOTP = credential ยืนยันตัวตน; Recovery Ticket = ทางสุดท้าย.

**Scope (user เลือก "เต็มทุกข้อ — build logic ครบ"):** TOTP (enroll+recover+stepup) · Credential
**Lifecycle** (REGISTERED/ACTIVE/SUSPENDED/REVOKED จริง) · Credential Management (รายละเอียดเต็ม +
`credential_type ∈ {GOOGLE, PASSKEY, TOTP}`) · Recovery Ready = Passkey OR TOTP · Recovery Ticket +
Evidence/Remark + **Recovery Level NORMAL/HIGH (four-eyes จริง)** · Audit `changed_by SELF/RECOVERY` ·
Change-Google 24h cooldown · fix google_sub.

**2 จุดที่แก้จากรีวิว (ข้อเท็จจริง):**
- Email-OTP recovery เดิม (`recover/email-otp`) **คงไว้** — ใช้เคส "passkey หาย แต่ Gmail ยังเข้าได้ → reset passkey"
  (คนละ flow กับ Credential Recovery Policy ของการ re-link Google). แค่ **ตัด email ออกจาก ladder ของ re-link**
- Backup code **ยังมีในระบบ** (auto-gen ตอน enroll passkey) — ไม่นับใน Recovery Ready เพราะ **re-link Google ไม่ได้** (แค่ reset passkey)

**Reuse (คงไว้ตามข้อ 10):** `_apply_google_relink()` (account_link.py:138) · change-google redirect/callback ·
`change_google:{token}` Redis · approval-workflow pattern (`change_request_service.py` + pending-requests page) ·
ไม่เพิ่ม Google OAuth callback ใหม่ · ไม่แตะ Google Console

> ⚠️ งานใหญ่ — build เป็นเฟส: (1) TOTP+lifecycle (2) Credential Management (3) Recovery Ticket+four-eyes

---

## Part A — TOTP (Fallback Authentication Factor) + Credential Lifecycle

### A1. Credential Lifecycle (ใช้ร่วม Passkey + TOTP)
Enum **`credential_status ∈ {REGISTERED, ACTIVE, SUSPENDED, REVOKED}`** — เฉพาะ ACTIVE เท่านั้นที่ auth/step-up/recover ได้
- **`user_totp_credentials`** (ตารางใหม่): `id` · `user_id` FK · `secret_encrypted` Text (Fernet) · `status`
  (default REGISTERED) · `created_at` · `enabled_at` · `last_used_at`
- **`passkey_credentials`** (แก้): เพิ่ม `status` (server_default `ACTIVE`); data-migration set `REVOKED` ที่ `revoked_at IS NOT NULL`.
  auth query เดิม (`revoked_at IS NULL`) → เพิ่มเงื่อนไข `status='ACTIVE'` (SUSPENDED บล็อก auth ได้). revoke เดิม set ทั้ง `revoked_at`+`status='REVOKED'`
- **Migration** (down_revision `"5e31bcaf0cf4"`) — create `user_totp_credentials`, `recovery_tickets`, <!-- pragma: allowlist secret -->  (revision id ไม่ใช่ secret จริง)
  `recovery_ticket_approvals` (Part C) + add `passkey_credentials.status`

### A2. Service `app/services/totp_service.py`
`generate_secret` · `provisioning_uri(secret,email)` · `verify(secret,code,valid_window=1)` +
row helpers (encrypt/decrypt ผ่าน `secret_service.encrypt_secret/decrypt_secret` `secret_service.py:146,151`) +
`active_secret(user_id)` (คืน secret เฉพาะ status=ACTIVE) · `is_enabled(user_id)`

### A3. Enroll — router `app/routers/totp.py`
- `POST /auth/account/totp/enroll/start` — `get_current_user` + gate `totp_enroll` → สร้าง secret →
  **insert row status=REGISTERED** (encrypted; แทน Redis pending — ใช้ lifecycle จริง) → คืน `{otpauth_uri, secret}`
  (REGISTERED row เก่า >10 นาที ถูกแทนตอน start ใหม่)
- `POST /auth/account/totp/enroll/verify` — `{code}` → verify → `status=ACTIVE` + `enabled_at` + audit + alert email
- `POST /auth/account/totp/suspend` | `/reactivate` | `DELETE` (=REVOKE) — gate + audit + alert
- `GET /auth/account/totp/status` → `{status, enabled}`

### A4. Step-up
- `stepup_cache.set_granted` (`stepup_cache.py:52`) เพิ่ม method `"totp"` · `POST /auth/stepup/totp/verify` →
  verify (ACTIVE) → `_grant_stepup(...,"totp")` (reuse `passkey.py:1014`)
- generic `gate()` รับ auto (ยกเว้น `change_google_account` บังคับ passkey) · risk-stepup เพิ่มตัวเลือก TOTP ·
  frontend `runWithStepup` no_passkey → prompt TOTP; `/auth/passkey/stepup` เพิ่มช่อง TOTP

### A5. TOTP Recovery (re-link Google — fallback ไม่มี email/passkey)
`POST /auth/passkey/recover/totp` (public, 5/min, mirror `recover_backup_code` `passkey.py:518`) —
`{email, code}` → verify ACTIVE TOTP → mint `change_google:{token}` (`_mint_change_token`) → `{start_url}` ·
opaque 400 · audit `PASSKEY_RECOVERY_VIA_TOTP` → change_google_redirect+callback+`_apply_google_relink` เดิม

---

## Part B — Credential Management (+ credential_type GOOGLE)

**`credential_type ∈ {GOOGLE, PASSKEY, TOTP}`** (GOOGLE = virtual, derived จาก user.email/google_sub — ไม่มีตาราง)
- **Endpoint** `GET /admin/users/{id}/credentials` (admin) + `GET /account/credentials` (self) → list:
  - `GOOGLE`: `{email, status:(email_verified?verified:unverified), last_login (login_sessions), last_changed (audit account_google_changed)}`
  - `PASSKEY` ต่อ device: `{device, created_at, last_used, status}`
  - `TOTP`: `{enabled, created_at, last_used, status}`
  - + `backup_codes_remaining` (แจ้งว่ามี แต่ไม่นับ recovery-ready)
  - reuse `passkey_recovery.get_status` + passkey query + `totp_service`
- **`recovery_ready(user)`** = มี **ACTIVE Passkey OR ACTIVE TOTP** (backup code ไม่นับ — re-link Google ไม่ได้)
- **Frontend** section "Credential Management" — `/account` (self, จัดการ) + User 360 (admin, ดู) แสดงรายละเอียดเต็มด้านบน

---

## Part C — Recovery Ticket (request→ticket→approve→link) + Evidence + four-eyes

```
User (ไม่ login) → Recovery Request → Ticket(pending) → Admin Approve(×N ตาม level) → One-time Link → เชื่อม Gmail ใหม่
```
- **`recovery_tickets`**: `id` (=Ticket ID) · `user_id` · `email` · `credential_type` (factor ที่รายงานหาย) ·
  `reason` · `recovery_level` (NORMAL/HIGH) · `status` (pending/approved/rejected/consumed/expired) ·
  `requested_ip` · `link_token` (ออกตอน approve ครบ) · `token_expires_at` · `consumed_at` · `created_at`
- **`recovery_ticket_approvals`** (four-eyes): `id` · `ticket_id` FK · `admin_id` · `evidence_type`
  (student_card/citizen_id/other) · `evidence_note` · `remark` · `approved_at` — **1 row ต่อ 1 admin ที่ยืนยัน**
- **Recovery Level logic:** NORMAL = 1 approval พอ · **HIGH = ต้อง 2 approvals จาก admin ต่างคน** (four-eyes) ·
  default: target `is_hub_admin` → HIGH, อื่น → NORMAL (admin ปรับได้)
- **Endpoints:**
  - `POST /auth/recovery/request` (public, rate-limit) — `{email, credential_type, reason}` → ถ้ามี user สร้าง
    ticket pending → **opaque** `{submitted:True}` + audit
  - `GET /admin/recovery-tickets?status=pending` (require_hub_admin)
  - `POST /admin/recovery-tickets/{id}/approve` (gate `recovery_ticket_review`) — body `{evidence_type, evidence_note, remark}`
    → insert approval row (กัน admin คนเดิม approve ซ้ำ) → ถ้า approvals ครบตาม level: mint `change_google:{token}`
    (user_id, TTL 1800, **bypass cooldown**) → `link_token`/status=approved → คืน `{relink_url}` ให้ admin ส่ง user ·
    ถ้ายังไม่ครบ (HIGH เหลืออีกคน) → status=pending, คืน `{awaiting_second_approval:True}` · audit `recovery_ticket_approved`
  - `POST /admin/recovery-tickets/{id}/reject` — status=rejected + audit
- user เปิด relink_url → callback → `_apply_google_relink` (source=RECOVERY) → mark ticket consumed
- **Admin UI** หน้าใหม่ `/recovery-tickets` (mirror `/subsystems/pending`) — โชว์ evidence form + สถานะ approval
  (เช่น "1/2 four-eyes") + badge count ใน sidebar

---

## Part D — Cooldown + Audit source
- **24h cooldown:** Redis `change_google_cooldown:{user_id}` set หลัง `_apply_google_relink` สำเร็จ (TTL 86400);
  เช็คตอน mint self-service (passkey change-google + TOTP recover) → reject `{code:"change_google_cooldown"}`;
  Recovery Ticket approve **bypass**
- **Audit `changed_by`:** `_apply_google_relink` เพิ่ม param `source ∈ {SELF, RECOVERY}` → ใส่ใน audit
  `account_google_changed` metadata (SELF=passkey change-google; RECOVERY=TOTP recover + ticket)

## Part E — Bug fix `google_sub`
`users.py:update_user` — `"email"` เปลี่ยน → set `google_sub=None` + `email_verified=False` (re-bind TOFU `auth.py:307`;
เดิมทิ้ง sub เก่า → mismatch guard `auth.py:280` บล็อกถาวร)

## Part F — Credential Recovery Policy (ladder)
เอกสาร/UI ระบุ ladder ของ **re-link Google**: `Passkey → TOTP → Recovery Ticket` (ไม่มี email — Gmail ตายในเคสนี้).
email-OTP-reset-passkey เดิมเป็น flow แยก (คงไว้)

---

## Security analysis

| Threat | Mitigation |
|---|---|
| Session hijack วาง TOTP | enroll gate step-up + alert email |
| TOTP secret หลุด | `secret_encrypted` Fernet |
| Brute TOTP | valid_window=1 + rate-limit |
| Credential ถูกใช้หลัง suspend/revoke | auth/step-up/recover เช็ค `status=ACTIVE` เท่านั้น |
| Re-link abuse/bounce | 24h cooldown + single-use token (B9) + OAuth proof + guards + alert + force-logout |
| Recovery Ticket ปลอม | admin approve (ยืนยัน evidence นอกระบบ) + **four-eyes สำหรับ HIGH** + audit ทุกขั้น + opaque request |
| Admin ยึดบัญชี | admin approve แค่ออก link — user พิสูจน์ครอง Gmail เอง; HIGH=2 admin |
| แยกแยะการเปลี่ยนบัญชี | audit `changed_by SELF/RECOVERY` |
| แก้ email→ล็อกเอาต์ | E เคลียร์ google_sub |

**Recovery ladder:** passkey → TOTP → Recovery Ticket (four-eyes ถ้า HIGH) — ตันโดยตั้งใจถ้าไม่มีเลย

---

## Files

**ใหม่:** `services/totp_service.py` · `routers/totp.py` · `routers/recovery.py` (request+admin review) ·
`alembic/versions/xxxx_totp_recovery_lifecycle.py` · `components/account/TotpCard.tsx` ·
`components/account/CredentialManagement.tsx` · `app/(console)/recovery-tickets/page.tsx` ·
`tests/test_totp.py` · `tests/test_credential_lifecycle.py` · `tests/test_recovery_ticket.py` ·
`tests/reports/totp_recovery_ticket_<date>.md`

**แก้:** `models.py` (+`UserTotpCredential`,`RecoveryTicket`,`RecoveryTicketApproval`, passkey `status`) ·
`requirements.txt` (pyotp) · `frontend/package.json` (qrcode.react) · `main.py` · `stepup_cache.py` ·
`critical_action_policy.py` (+`totp_enroll`,`recovery_ticket_review`) · `account_link.py` (`_mint_change_token`+cooldown+source) ·
`passkey.py` (recover/totp + risk-stepup + stepup page + passkey status checks) · `services/passkey_recovery.py` (status) ·
`users.py` (E) · `admin.py` (credentials summary) · `AccountView.tsx` · `recover/page.tsx` ·
`users/[id]/page.tsx` (Credential Mgmt + Recovery Ready + Auth Methods) · `lib/passkey.ts` · sidebar nav ·
`.env.example`/`VM_PENDING_CHANGES.md`

---

## Verification (TDD — RED → GREEN)

**pytest:**
1. `totp_service.verify` ถูก/ผิด/หมดเวลา
2. enroll start→row REGISTERED / verify→ACTIVE+enabled_at / verify ผิด→400 คง REGISTERED
3. **lifecycle:** suspend→SUSPENDED (auth/step-up/recover ใช้ไม่ได้) · reactivate→ACTIVE · revoke→REVOKED · passkey SUSPENDED บล็อก login
4. stepup/totp/verify (ACTIVE) → cache method="totp" → critical action ผ่าน · `change_google_account` ยังบังคับ passkey
5. recover/totp (ACTIVE) → start_url+token · ผิด/ไม่มี user/REGISTERED→opaque 400 · → `_apply_google_relink` re-link (user.id เดิม, source=RECOVERY ใน audit)
6. **cooldown:** re-link แล้ว mint ครั้ง 2 ใน 24h→reject · ticket approve bypass
7. **Credential Mgmt:** `/credentials` คืน GOOGLE+PASSKEY+TOTP + `recovery_ready`=Passkey OR TOTP (ACTIVE)
8. **Recovery Ticket:** request→pending (opaque) · approve NORMAL (1 admin)→link+approved · **HIGH ต้อง 2 admin ต่างคน** (admin เดิม approve ซ้ำ→ปฏิเสธ, 1/2→awaiting, 2/2→link) · approval บันทึก evidence/remark · reject→rejected · non-admin เข้าไม่ได้
9. **audit changed_by:** SELF (passkey change) vs RECOVERY (totp/ticket) แยกกัน
10. **E:** admin PATCH email → google_sub NULL + email_verified False
11. regression: `pytest tests/test_change_google.py tests/test_passkey_login.py tests/test_passkey_security.py tests/test_critical_action_policy.py tests/test_stepup_cache.py tests/test_passkey_recovery.py -q` (passkey status ต้องไม่พังของเดิม)

**Frontend:** `tsc --noEmit` exit 0

**Manual E2E:** enroll (สแกน QR) · lifecycle (suspend→login ไม่ได้→reactivate) · TOTP recovery (recover→re-link) ·
Recovery Ticket NORMAL + HIGH (2 admin) ผ่าน `/recovery-tickets` · User360 Credential Mgmt + Recovery Ready

**Prereq:** `alembic upgrade head` + rebuild (pyotp) + `npm i` (qrcode.react) + `--force-recreate` (B36).
ไม่ต้องเพิ่ม Google Console URI (reuse change-google callback)
