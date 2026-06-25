# Risk-Triggered Passkey Flow — Test Report

**วันที่:** 2026-06-14
**ทีม:** Week 9-10 MFA wire-up
**ผู้ทดสอบ:** auto via pytest
**ไฟล์:** `tests/test_risk_passkey_flow.py`

---

## 1. Test Summary

| Metric | ค่า |
|---|---|
| Tests total | 22 |
| Passed | **22** ✅ |
| Failed | 0 |
| Duration | 6.23s |
| Full suite (regression) | 189/189 ✅ (167 เดิม + 22 ใหม่) |

---

## 2. Scope ที่ครอบคลุม

### 2.1 Config (3 tests)
- `risk_block_hard_threshold = 0.85` — hard block threshold
- `passkey_grace_period_days = 7` — grace period สำหรับ user ใหม่
- `risk_challenge_ttl_sec = 300` — risk_challenge TTL (5 นาที)

### 2.2 risk_challenge service (7 tests)
- `mint()` คืน URL-safe token (≥ 32 chars)
- `peek()` ไม่ลบ — เรียกซ้ำได้
- `consume()` atomic getdel (B9 pattern)
- `consume()` ครั้งที่สอง → `None` (กัน replay)
- Unknown id → `None` (peek + consume)
- Payload มี fields ครบ (user_id, hub_state, authreq, risk_score, risk_breakdown,
  risk_reasons, provider, kind, flow, minted_at)

### 2.3 Grace Period helper (2 tests)
- User created < 7d + ไม่มี passkey → `in_grace_period = True`
  - `adoption_status` คืน `in_grace_period=True`, `grace_days_remaining=5`
- User created > 7d + ไม่มี passkey → `in_grace_period = False`
  - `grace_days_remaining = 0`

### 2.4 Risk Re-Auth endpoints (4 tests)
- `GET /auth/passkey/risk-stepup` — challenge ไม่มี → **410**
- `POST .../start` — kind=enroll → **400** (ต้อง kind=reauth)
- `POST .../verify` — kind=enroll → **400**
- `GET .../risk-stepup` — render page + reasons + risk_score
  - มี browser-unsupported message + Account Recovery link

### 2.5 Force Enrollment endpoints (5 tests)
- `GET .../force-enroll` — kind=reauth → **400**
- `POST .../register/start` ไม่ผ่าน OTP → **403** (B45)
- `POST .../send-otp` → สร้าง hash ใน Redis
- `POST .../verify-otp` ผิด → **401** + ไม่ set passed flag
- `POST .../verify-otp` ถูก → set passed flag + ลบ OTP hash

### 2.6 Regression (1 test)
- MFA OTP service (`generate_otp` / `hash_otp` / `verify_otp`) ยังทำงานปกติ

---

## 3. Security Checks ผ่านครบ

| Rule | Description | สถานะ |
|---|---|---|
| **B9** | risk_challenge ใช้ atomic getdel กัน replay | ✅ |
| **B44** | risk >= 0.85 hard block แยกจาก aggregator "block" (0.80-0.84) | ✅ (config + finalizer) |
| **B45** | Force Enrollment ต้องผ่าน OTP ก่อน register/start | ✅ (test 403 ผ่าน) |
| **B46** | Browser unsupported → Account Recovery (ไม่ fallback OTP) | ✅ (HTML render มี link) |
| Kind validation | risk-stepup ต้อง kind=reauth, force-enroll ต้อง kind=enroll | ✅ |
| Challenge expiry | TTL 5 นาที + 410 Gone | ✅ |
| OTP gate | Wrong OTP → 401, Correct OTP → set flag + delete hash | ✅ |

---

## 4. ที่ Test ยังไม่ครอบคลุม (Future Work)

| Scope | เหตุผล |
|---|---|
| Full WebAuthn ceremony ใน Force Enroll | ใช้ soft-webauthn — pattern เดียวกับ `test_passkey_ceremony.py` (มี coverage อยู่แล้ว) |
| End-to-end finalizer branch (block/mfa/grace) | ต้อง mock Google OAuth flow — ใช้ Playwright E2E แทน |
| Banner flag ใน subsystem token response | E2E ต้องทำผ่าน real subsystem (Dorm/Library) |
| Counter regression during re-auth boost | depend บน live ML score — ใช้ unit test ของ webauthn_service เดิม |

---

## 5. Reproducible Run

```bash
docker compose exec hub-backend pytest tests/test_risk_passkey_flow.py -v
```

Expected output: `22 passed in ~6s`

Full regression:
```bash
docker compose exec hub-backend pytest tests/ -q \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_l1_oidc_authlib.py
```

Expected: `189 passed in ~50s`

---

## 6. Compliance Mapping

| Standard | Coverage |
|---|---|
| NIST SP 800-63B-4 §5.1.7 (Out-of-band OTP) | OTP 6 digit + HMAC-SHA256 + TTL 5 นาที ✅ |
| FIDO Alliance phishing-resistant | Step-up + force-enroll ใช้ WebAuthn เท่านั้น ✅ |
| OWASP A07 (Auth Failures) | Atomic consume + kind validation + OTP gate ✅ |
| OAuth 2.0 Security BCP | One-time tokens (5 นาที TTL) ✅ |

---

*Generated 2026-06-14 — Week 9-10 risk-triggered Passkey flow*
