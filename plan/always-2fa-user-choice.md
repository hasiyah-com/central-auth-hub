# Plan — Always-2FA (user choice) + Post-login Security Onboarding

## Context / เป้าหมาย

ผู้ใช้ต้องการ: หลัง login Google → ชวนตั้งค่ายืนยันตัวตน (passkey/TOTP/ทั้งสอง) และเปิดโหมด
"ขอ 2FA ทุก login" ได้เอง **โดยไม่ซ้ำซ้อนกับ Risk-Based MFA เดิม** (ไม่กลายเป็น 3 ชั้น)

**หลักการแก้ซ้ำซ้อน:** always-on กับ risk-mfa = ความต้องการเดียวกัน ("ขอ factor ที่สอง 1 ตัว")
→ ยุบเป็น **ด่านเดียว** ยืนยันครั้งเดียวจบ ไม่ว่าจะ trigger จากเหตุไหน

```
needs_2fa = (RBA decision = mfa)  OR  (user เปิด Always-2FA)  OR  (user เป็น admin)
```
`needs_2fa` จริง → risk-stepup เดียว รับ **passkey หรือ TOTP** → ผ่านจบ ไม่มีด่านสอง

**Decision locked (จาก user):**
- โหมด: **opt-in ต่อ user** + **admin ถูกบังคับ Always-2FA** (is_hub_admin → always)
- Factor ที่ด่าน: **passkey หรือ TOTP** (มี passkey→ใช้ passkey แข็งกว่า; ไม่มี→TOTP)
- Onboarding card: เลือก passkey / TOTP / ทั้งสอง — "ทั้งสอง" = **passkey ก่อน แล้ว TOTP**
- Card ขึ้นเฉพาะคนที่**ยังไม่มี factor เลย**; คนมี passkey แล้ว **ไม่ถูกกวน**

---

## Part A — Backend: รวม always-on เข้ากับ gate เดิม (ไม่เพิ่มด่าน)

### A1. Model (`models.py`, class User ~line 40)
เพิ่ม 3 คอลัมน์ (ใกล้ `is_hub_admin` line 68):
- `mfa_always` — `Boolean, server_default false` — user เปิด Always-2FA เอง
- `mfa_preferred_factor` — `String nullable` (`"passkey"` / `"totp"`) — factor ที่ชอบ (จัดลำดับที่ด่าน)
- `security_onboarding_dismissed` — `Boolean, server_default false` — กด "ไม่ต้องถามอีก" (per-account ไม่ใช่ per-device)

Helper property: `effective_mfa_always = mfa_always OR is_hub_admin` (admin บังคับ)

### A2. Migration
เพิ่ม 3 คอลัมน์ (down_revision = head ล่าสุด `a1b2c3d4e5f6`). ไม่มี data-backfill (default false)

### A3. `is_mfa_required` — แก้ 2 จุด (`auth.py:399` hub-direct + `auth.py:899` subsystem)
```python
effective_always = user.mfa_always or user.is_hub_admin
is_mfa_required = not is_hard_block and (
    (enforcing and actual_decision in ("block", "challenge"))  # risk-based (เดิม)
    or effective_always                                        # always-on (ใหม่)
)
```
> **หมายเหตุ shadow mode:** always-on เป็น "ตัวเลือกของ user" ไม่ใช่การ enforce ของ ML →
> ทำงาน**แม้ ML_SHADOW_MODE=true** (risk-based ยังเงียบตาม shadow เหมือนเดิม)
> ถ้า `oauth.py` มี callback ที่คำนวณ is_mfa_required แยก → แก้จุดนั้นด้วย (สม่ำเสมอทุก entry point)

### A4. Branch หลัง is_mfa_required — รับ TOTP ด้วย (auth.py ~439, ~939)
ปัจจุบัน: `has_passkey?` → risk-stepup ; ไม่มี → grace/force-enroll passkey
เปลี่ยนเงื่อน "มี second factor ไหม" ให้รวม TOTP:
```python
has_factor = webauthn_service.count_active(user.id, db) > 0 or totp_service.is_enabled(user.id, db)
if has_factor:
    → risk-stepup (จะรับ passkey/TOTP ตาม A5)
else:
    → grace / force-enroll passkey (เดิม)  # ไม่มีอะไรเลย = ต้องตั้งอย่างน้อย 1
```
กัน: always-on user ที่มี **TOTP อย่างเดียว** ไม่ถูกลากไป force-enroll passkey

### A5. risk-stepup page รับ TOTP (`passkey.py:_risk_stepup_html` :2001 + GET handler)
- GET handler ส่ง `has_totp` + `preferred_factor` เข้า HTML
- HTML เพิ่ม section TOTP (แสดงถ้า `has_totp`): ช่องกรอก 6 หลัก + ปุ่มยืนยัน
  - จัดลำดับตาม `preferred_factor` (ชอบ TOTP → โชว์ TOTP ก่อน; else passkey ก่อน)
  - passkey ไม่รองรับ/ไม่มี → โชว์ TOTP เป็นหลัก (แทน "unsupported → recovery" อย่างเดียว)
- **Endpoint ใหม่** `POST /auth/passkey/risk-stepup/verify-totp` — `{challenge_id, code}`:
  verify_active TOTP → **consume challenge (atomic, B9)** → issue JWT + refresh (mirror
  `/risk-stepup/verify` ของ passkey เป๊ะ) → คืน `redirect_url` · audit `risk_mfa_totp_success`
  · fail → opaque + audit fail (B7)

---

## Part B — Frontend: Onboarding card + Account settings

### B1. Post-login onboarding card (เฉพาะ no-factor user)
Component ใหม่ `components/SecurityOnboarding.tsx` — เช็คหลัง login:
- เงื่อนไขแสดง: `!security_onboarding_dismissed` **และ** `count(passkey)=0 && !totp.enabled`
  (มี passkey หรือ TOTP แล้ว → ไม่ขึ้น)
- การ์ดเลือก 3 ทาง (ดู ASCII ในแชท): **Passkey [แนะนำ]** / **TOTP** / **ทั้งสอง [ปลอดภัยสุด]**
  + `[ไว้ทีหลัง]` (ปิดชั่วคราว) + `[ไม่ต้องถามอีก]` (→ PATCH `security_onboarding_dismissed=true`)
- เลือกแล้ว (reuse ของเดิมหมด):
  | เลือก | flow |
  |---|---|
  | Passkey | passkey ceremony เดิม (+ backup codes) |
  | TOTP | TotpCard wizard (QR) เดิม |
  | ทั้งสอง | **passkey ก่อน → ต่อ TOTP** |
- ตั้งเสร็จ → ถามต่อ "ให้ขอยืนยันทุก login ไหม?" → เปิด `mfa_always`
- Endpoint: `GET /auth/account/security-status` (has_passkey/has_totp/mfa_always/dismissed/is_admin)
  + `POST /auth/account/security/dismiss-onboarding`

### B2. /account — Always-2FA toggle + preferred factor
- ใน `AccountView.tsx`: การ์ด "ความปลอดภัยการเข้าสู่ระบบ"
  - Toggle **"ขอยืนยันตัวตนทุกครั้งที่ล็อกอิน (Always-2FA)"** → PATCH `mfa_always`
  - เลือก **factor ที่ต้องการใช้ก่อน** (passkey/TOTP) → PATCH `mfa_preferred_factor`
  - **admin:** toggle ล็อกเป็น ON + ข้อความ "บังคับสำหรับผู้ดูแลระบบ" (แก้ไม่ได้)
- Endpoint: `PATCH /auth/account/security` `{mfa_always?, mfa_preferred_factor?}`
  (admin ตั้ง mfa_always=false ไม่ได้ — server ปฏิเสธ/ignore)

### B3. Guard ไม่ให้เด้ง 2 อัน
Onboarding card (no-factor) กับ passkey force-enroll (risk) ห้ามซ้อน — no-factor + login เสี่ยง
ควรไหลไป force-enroll (backend) ก่อน; card เป็น non-risk path เท่านั้น → เช็ค state ให้ card
ไม่โผล่ทับหน้า force-enroll

---

## Part C — Recovery / Edge cases

| เคส | ผลลัพธ์ |
|---|---|
| always-on user ทำ factor หายหมด | → Recovery Ticket ladder (มีแล้ว) |
| always-on + มี TOTP อย่างเดียว | ด่านรับ TOTP (A4/A5) ไม่ลาก force-enroll passkey |
| admin ยังไม่มี factor | force-enroll ตอน login (บังคับตั้ง) — สม่ำเสมอกับ always |
| user ใหม่ (grace period) + ไม่ opt-in | grace/force-enroll passkey เดิม ไม่เปลี่ยน |
| เสี่ยงกลาง + always-on | **ยืนยันครั้งเดียว** (ด่านเดียว satisfy ทั้งคู่) |

---

## Security review

| Threat | Mitigation |
|---|---|
| ซ้ำซ้อน 2-3 ด่าน | ยุบเป็น gate เดียว (OR logic) — max 1 step-up/login |
| downgrade passkey→TOTP | ด่านรับทั้งคู่; preferred=passkey ให้ passkey ก่อน |
| admin ปิด 2FA เอง | server บังคับ effective_always ผ่าน is_hub_admin (ปิดไม่ได้) |
| challenge replay | verify-totp consume challenge atomic (B9) เหมือน passkey |
| TOTP brute ที่ด่าน | valid_window=1 + verify_active (ACTIVE only) + rate-limit |
| always-on ถูก bypass shadow mode | always-on ทำงานอิสระจาก shadow (เป็น user pref) |
| audit | risk_mfa_totp_success/fail + mfa_always_changed + onboarding events |

---

## Files

**แก้ (backend):** `models.py` (+3 cols +property) · migration ใหม่ · `auth.py` (is_mfa_required ×2
+ has_factor branch ×2) · `passkey.py` (_risk_stepup_html + GET handler + verify-totp endpoint) ·
`oauth.py` (is_mfa_required ถ้ามีจุดคำนวณแยก) · `routers/account_*` (security-status / security PATCH /
dismiss-onboarding)

**แก้/ใหม่ (frontend):** `components/SecurityOnboarding.tsx` (ใหม่) · `AccountView.tsx` (Always-2FA
card) · `lib/passkey.ts` (helpers: securityStatus, setMfaAlways, setPreferredFactor, dismissOnboarding) ·
mount SecurityOnboarding หลัง login (console layout / dashboard)

**ไม่แตะ:** RBA scoring, risk_challenge core, recovery ladder, Google Console, StepupTotpProvider (inline
step-up คนละเรื่อง)

---

## Verification (TDD RED→GREEN)

**pytest (`tests/test_always_2fa.py`):**
1. `mfa_always=true` + risk ต่ำ → is_mfa_required true → redirect risk-stepup
2. admin (is_hub_admin) + mfa_always=false → ยัง required (บังคับ)
3. non-admin + mfa_always=false + risk ต่ำ → **ไม่** required (regression: flow เดิมไม่เปลี่ยน)
4. always-on ทำงานแม้ shadow mode
5. always-on + มี TOTP อย่างเดียว → risk-stepup (ไม่ force-enroll)
6. always-on + ไม่มี factor → force-enroll (ตั้งอย่างน้อย 1)
7. `POST /risk-stepup/verify-totp` ถูก → JWT + redirect + challenge consumed · ผิด → opaque + audit
8. verify-totp ซ้ำ challenge เดิม → 410 (replay guard)
9. `PATCH /auth/account/security` admin ตั้ง mfa_always=false → ปฏิเสธ/ignore
10. preferred_factor ordering (มีผลต่อ has_totp/preferred ที่ส่งเข้า HTML)
11. regression: `test_risk_passkey_flow` + `test_auth` + `test_refresh_token` ไม่พัง

**Frontend:** `tsc --noEmit` exit 0 · browser: onboarding card (no-factor) เลือกได้ 3 ทาง ·
Always-2FA toggle · admin เห็น toggle ล็อก · risk-stepup แสดง TOTP เมื่อมี

**Prereq:** `alembic upgrade head` + `--force-recreate` (B36). ไม่แตะ Google Console
