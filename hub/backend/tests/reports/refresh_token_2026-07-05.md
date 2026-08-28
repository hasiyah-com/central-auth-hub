# Refresh Token — Test Report (2026-07-05)

## สรุป

เพิ่ม short-lived access token (60 → **15 นาที**) + rotating refresh token
(opaque, 30 วัน) สำหรับ Hub-direct login (Google OAuth + LINE (legacy) + Passkey
login/discoverable/risk-stepup) แทนการใช้ access token อายุยาวตัวเดียวแบบเดิม
ตามข้อเสนอแนะ "Short-lived Access Token + Refresh Token" — ลด window ความเสี่ยง
ถ้า access token หลุด โดยไม่ต้องให้ user login ใหม่ทุกครั้ง

**ต่อยอด (2026-07-05, รอบ 2):** `POST /auth/refresh` รัน **4-Layer RBA ซ้ำ**
ทุกครั้ง (ไม่ใช่แค่ตอน login ครั้งแรก) เพื่อจับ session-hijack — refresh token
ที่ถูกขโมยไปใช้จาก IP/ประเทศ/device อื่น จะโดนตรวจจับก่อนที่จะได้ access token
ใหม่ risk สูง → บังคับ Passkey step-up (ต่อยอด risk-stepup ที่มีอยู่แล้ว) หรือ
บล็อกเต็มถ้าเข้าเกณฑ์ hard-block/ไม่มี passkey

**ตัดออกจากแผน**: Session Downgrade (`docs/p2-session-downgrade-plan.md`, ลบแล้ว)
— Hub มองไม่เห็นกิจกรรมภายใน subsystem จึงลด scope session ได้ไม่แม่นยำ,
ซับซ้อนเกินความจำเป็นเทียบกับ Risk-Triggered Step-up ที่มีอยู่แล้ว

## Test count: 274 passed (18 ใหม่ + 256 เดิม, no regression จากงานนี้)

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_l1_oidc_authlib.py
======================== 5 failed, 274 passed in 51.42s ========================
```

(3 ไฟล์ที่ ignore เป็น standalone script ที่มี `sys.exit()` ระดับ module — ไม่ผ่าน
pytest collection มาก่อนหน้านี้แล้ว ไม่เกี่ยวกับงานนี้)

**5 failed ที่เหลือ (`test_passkey_security.py::test_account_endpoints_reject_non_admin`)
เป็นบั๊กเดิมที่มีอยู่ก่อนงานนี้ — ยืนยันด้วย `git stash` แล้วรันซ้ำ fail เหมือนเดิมทั้งที่
revert โค้ด refresh token ออกหมด** สาเหตุคือ commit ก่อนหน้า
`fix(passkey): allow developer role to manage own passkeys (not admin-only)`
เปลี่ยน RBAC แล้วแต่ test ไม่ได้อัปเดตตาม ไม่เกี่ยวกับ refresh token/risk gate

## Sections

### 1. Service layer — `app/services/refresh_token_service.py` (`tests/test_refresh_token.py`)

- `issue()` คืน opaque token รูปแบบ `{refresh_id}.{secret}`, secret ≥32 chars
- `rotate()` round-trip: คืน user_id/session_id/refresh_id/raw_token ใหม่
- `rotate()` single-use — reuse (replay) token เดิมหลัง rotate แล้ว → `None`
- `rotate()` reject refresh_id ที่ไม่มีอยู่จริง
- `rotate()` reject secret ที่ tamper — **และ token จริงต้องยังใช้ได้อยู่**
  (กัน DoS: attacker รู้ refresh_id แต่เดา secret ผิด ไม่ควรทำให้ token เจ้าของ
  ตัวจริงใช้ไม่ได้ — แก้จาก draft แรกที่ delete-then-check ทำให้ทดสอบนี้ fail)
- `rotate()` reject malformed token (ไม่มี `.`, string ว่าง)
- `revoke()` by id → กัน rotate ต่อทันที

### 2. HTTP — `POST /auth/refresh`

- Happy path: ออก access+refresh คู่ใหม่, access token verify ผ่านด้วย `sub` ถูกต้อง,
  refresh token เดิม (raw) rotate ไปแล้วใช้ซ้ำไม่ได้ (401), token ใหม่ยังใช้ต่อได้
- Invalid/garbage token → 401
- User status != active (เช่น suspended) → 401 (แม้ refresh token valid — consumed ไปด้วย)

### 3. `POST /auth/logout` revoke ทั้ง access + refresh

- ส่ง `refresh_token` มาใน body → revoke ทันที (ไม่ต้องรอ 30 วัน TTL)
- `sess.refresh_id` ที่ผูกไว้ก็ revoke ด้วย (เผื่อ client ไม่ได้ส่ง raw token มา)

### 4. Risk re-evaluation on refresh — `_refresh_risk_gate` (session-hijack detection)

RBA รันซ้ำทุกครั้งที่ refresh (สกัด features จาก IP/device/geo **ปัจจุบัน**
ไม่ใช่ตอน login) — ก่อนหน้านี้ refresh ไม่มีการตรวจเลย ทำให้ refresh token ที่
อายุยาว (30 วัน) กลายเป็นช่องโหว่ถ้าหลุดไปใช้จากที่อื่น

| เคส | ผลลัพธ์ |
|---|---|
| risk ปกติ | ออก token คู่ใหม่ตามปกติ, ไม่ log audit (ไม่ใช่ทุก refresh ควรมี entry) |
| enforce + risk สูง (challenge) + มี passkey | **200** `{stepup_required, stepup_url}` — ไม่ออก token จนกว่าจะยืนยัน Passkey ผ่าน (revoke refresh token คู่ที่เพิ่ง rotate ทิ้งก่อน) |
| enforce + risk สูง + ไม่มี passkey | **401** — บังคับ login ใหม่เต็ม (login flow จัดการ force-enroll เอง) |
| enforce + score ≥ hard-block threshold | **401** — ตัด session (`logout_at` + revoke jti) |
| **shadow mode (default)** + risk สูง | ไม่ enforce, ออก token ปกติ **แต่ log `risk_refresh_would_stepup` เข้า audit_logs** |
| shadow mode + risk ปกติ | ไม่ log อะไรเลย |

**Design decision (ยืนยันกับ user แล้ว):** `audit_logs` เป็น **append-only** เก็บ
ทุกเหตุการณ์ความปลอดภัย (ต่างจาก `LoginSession.risk_*` ที่เป็นแค่ current-state
เขียนทับได้ทุกครั้ง) — ดังนั้น shadow-mode "would_stepup" ก็ต้อง log เข้า
audit_logs ด้วย ไม่ใช่แค่อัปเดต session snapshot เฉยๆ (draft แรกเคยตัดออกเพราะ
กลัว noise แต่กลับเข้ามาใหม่หลัง review กับ user — เหตุการณ์ elevated-risk ไม่ได้
เกิดบ่อยพอจะเป็นปัญหา volume จริง)

Tests (`tests/test_refresh_token.py`):
- `test_refresh_low_risk_issues_normally` — enforce mode, risk ต่ำ → 200 ปกติ
- `test_refresh_high_risk_with_passkey_requires_stepup` — enforce + challenge + passkey → 200 stepup_required, ไม่มี access_token ใน body
- `test_refresh_hard_block_forces_relogin` — enforce + hard-block → 401 + session.logout_at ถูก set
- `test_refresh_high_risk_no_passkey_forces_relogin` — enforce + challenge + ไม่มี passkey → 401
- `test_refresh_shadow_mode_high_risk_still_issues` — shadow + risk สูง → ยังออก token
- `test_refresh_shadow_mode_high_risk_logs_audit_entry` — shadow + risk สูง → มี `AuditLog(action="risk_refresh_would_stepup")` metadata ถูกต้อง
- `test_refresh_low_risk_shadow_mode_no_audit_entry` — shadow + risk ปกติ → ไม่มี audit entry เพิ่ม

## Manual E2E verification (ผ่าน real running stack — ไม่ mock)

รันกับ hub-stack ที่ localhost:3000 (Next.js) + localhost:8000 (Hub backend) จริง
โดย mint token pair ให้ user จริง (`<U01>`, admin) ตรงจาก
`create_access_token` + `refresh_token_service.issue` (แทนการ login ผ่าน Google
OAuth ที่ automate ไม่ได้ในสภาพแวดล้อมนี้ — ไม่มีเบราว์เซอร์จริงให้กรอก credentials):

| # | Test | Result |
|---|------|--------|
| 1 | `POST /api/set-token` เก็บ access+refresh ใน httpOnly cookie ทั้งคู่ | ✅ |
| 2 | `GET /api/proxy/auth/me` ด้วย access token valid | ✅ 200 + profile ถูกต้อง |
| 3 | Revoke access token (`revoke_jti`) จำลอง token หมดอายุ | ✅ |
| 4 | `GET /api/proxy/auth/me` อีกครั้ง — proxy เจอ 401 → refresh อัตโนมัติ (RBA รันซ้ำจริง) → retry → คืน 200 พร้อม cookie ใหม่ (transparent ต่อ caller ทั้งหมด) | ✅ |
| 5 | Refresh token **เดิม** (ก่อน rotate ใน step 4) ใช้ซ้ำ → fail | ✅ 401 |
| 6 | `POST /api/refresh` ตรงๆ ด้วย refresh token ที่ rotate แล้ว (จาก step 4) → ได้คู่ใหม่อีกรอบ | ✅ |
| 7 | `DELETE /api/set-token` (logout) พร้อม refresh token ล่าสุด → เรียก Hub `/auth/logout` revoke ทั้งคู่ | ✅ |
| 8 | `POST /api/refresh` หลัง logout ด้วย token เดิม → fail | ✅ 401 |
| 9 | หลัง refresh สำเร็จ (step 4) — `LoginSession.risk_score`/`risk_breakdown`/`risk_reasons` ของ session ถูกอัปเดตจริง (พิสูจน์ว่า RBA รันซ้ำ ไม่ใช่แค่ skip ผ่าน) — เห็นค่า `risk_score=0.200, breakdown={rule,behavior,iforest,iforest_raw}` | ✅ |
| 10 | `jti` ของ session เปลี่ยนหลัง refresh (= token ใหม่จริง ไม่ใช่ token เดิม) | ✅ |
| 11 | Query `audit_logs` ตรงๆ หลังรัน pytest suite — เจอ entry `risk_refresh_would_stepup` จริงพร้อม metadata `{risk_score, decision, reasons, shadow:true}` ถูกต้องตามที่โค้ด log | ✅ |

Cleanup: ลบ cookie files ชั่วคราว + synthetic `LoginSession` rows
(`user_agent` ∈ `{manual-test, manual-test-refresh, diag}`) ที่สร้างไว้ทดสอบออก
จาก DB แล้ว (ไม่ปนกับ Activity feed จริง)

**Config note:** dev `.env` เคย pin `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60` ทับ
โค้ด default (15) อยู่ — user แก้ `.env` เป็น 15 เอง + `docker compose up -d
--force-recreate hub-backend` (B36 — restart เฉยๆ ไม่ re-read .env) ยืนยันแล้วว่า
running app เห็นค่า 15 ถูกต้อง

## Security properties covered

- Access token อายุสั้น (15 นาที) — ลด window ถ้าหลุด (URL log, referrer leak, XSS
  ขโมยจาก memory ฯลฯ)
- Refresh token **single-use rotation** — ใช้ซ้ำ (replay) ไม่ได้ ป้องกันด้วย atomic
  GET→compare→DELETE (Redis DEL คืนจำนวนจริง กัน race ระหว่าง concurrent request)
- Secret ไม่เก็บ plaintext — HMAC-SHA256 (เหมือน `secret_service.hash_retrieval_token`)
  + `hmac.compare_digest` กัน timing attack (B3)
- Tampered secret ไม่ consume entry จริง (กัน DoS ต่อ session ของเจ้าของตัวจริง)
- Logout revoke ทั้ง access (jti blacklist, ของเดิม) + refresh (ใหม่) — ปิดช่องที่
  attacker ขโมย refresh cookie ไปมิ้นท์ access token ใหม่ได้หลัง user "logout" แล้ว
- Refresh/access token คู่ใหม่ผูกกลับ `LoginSession.jti`/`refresh_id` เดิมเสมอ —
  admin/self force-revoke ยังตามทัน session ล่าสุดแม้ผ่านการ refresh มาแล้วหลายรอบ
- **RBA รันซ้ำทุกครั้งที่ refresh** — ปิดช่องโหว่ที่ refresh token อายุยาว (30 วัน)
  กลายเป็น attack surface ใหม่ถ้าไม่มีการตรวจสอบต่อเนื่อง (เดิมมีแค่ตอน login
  ครั้งเดียว) — risk สูงจาก IP/ประเทศ/device ที่เปลี่ยนไประหว่างทาง จะโดน step-up
  หรือบล็อกก่อนได้ access token ใหม่

## Compliance / conventions

- B3 (compare_digest สำหรับ secret) ✅
- B9 pattern (atomic single-use ผ่าน Redis) ✅ — ใช้ GET+compare+DELETE แทน blind
  getdel เพราะต้องกันกรณี secret ผิดไม่ให้ consume entry (ต่างจาก auth-code เดิมที่
  ไม่ต้องกันกรณีนี้)
- Feature/config เปลี่ยน (`jwt_access_token_expire_minutes` 60→15) ไม่กระทบ
  4-Layer RBA features (ไม่ใช่ ML feature)
- Audit log convention: `audit_logs` = append-only ทุกเหตุการณ์ความปลอดภัย
  (ไม่ว่า shadow/enforce), `LoginSession.risk_*` = current-state snapshot
  เขียนทับได้ — ยึดหลักนี้ตอนตัดสินใจ scope ของ `_refresh_risk_gate` logging
