# Always-2FA — passkey login = strong factor (แนวทาง 3, ทำให้เป็นทางการ) 2026-07-26

## บริบท

ผู้ใช้รายงาน: admin ตั้ง Always-2FA แต่ login ด้วย passkey (risk 0.6) **ไม่เด้งให้ยืนยันอีกครั้ง**

### สอบสวน (จาก DB จริง)
```
login 07-26 07:39:33 : login_method=passkey · risk_score=0.6 · decision=would_warn
ml_shadow_mode=True (enforcing=False) → risk ไม่ enforce
admin U01: is_hub_admin=True, effective_mfa_always=True, มี passkey+TOTP
```

**ต้นตอ:** gate Always-2FA (`is_second_factor_required`) อยู่เฉพาะ flow federated
(Google callback `auth.py`). flow **passkey login** (`passkey.py`) ออก JWT ตรง ๆ ไม่เช็ค gate
→ admin login ด้วย passkey ข้าม Always-2FA

### วินิจฉัย: ไม่ใช่บั๊ก — เป็นดีไซน์ที่ถูก แต่ "ไม่ได้ประกาศ"
Passkey (WebAuthn + user verification) = possession (อุปกรณ์) + inherence/knowledge
(biometric/PIN) = **MFA-grade ในตัวเดียว** (NIST SP 800-63B AAL2+, phishing-resistant).
ขอ factor ที่สองซ้ำ = ซ้ำซ้อน (3 ชั้น). Google OAuth เดี่ยว = primary อ่อน → ต้อง step-up.

พฤติกรรมเดิมจึง**ให้ผลลัพธ์ถูกอยู่แล้ว** (passkey ผ่าน / Google ต้อง step-up) แต่เกิดจาก
"โค้ดไม่ได้เช็ค" (โดยบังเอิญ) → ดูเหมือนบั๊ก + เสี่ยงมีคนมา "แก้" ผิดทีหลัง

## สิ่งที่ทำ (แนวทาง 3 — ทำให้เป็นทางการ ไม่เปลี่ยน behavior)

Always-2FA นับ **ตามความแข็งแรงของ factor ไม่ใช่จำนวนหน้าจอ**:

**1. `mfa_policy.py`**
- `STRONG_LOGIN_METHODS = ("passkey", "discoverable")` — source of truth
- `login_method_satisfies_2fa(method)` — passkey ผ่าน / federated ต้อง step-up
- docstring module + `is_second_factor_required` ระบุกฎชัด (passkey flow ไม่ต้องเรียก gate)

**2. `passkey.py`** (login_finish + login_discoverable_finish)
- comment "โดยตั้งใจ": passkey = strong factor → ผ่าน Always-2FA
- audit metadata: `effective_mfa_always` + `mfa_satisfied_by="passkey"` →
  **auditable ว่า 2FA ถูก satisfy ด้วย passkey ไม่ใช่ถูกข้าม**

**ไม่แตะ logic การ login** — behavior เหมือนเดิมทุกอย่าง แค่ประกาศเจตนา + audit trail

## สรุปกฎ (ชัดเจนแล้ว)

| Login method | Always-2FA | เหตุผล |
|---|---|---|
| passkey / discoverable | ✅ ผ่านในตัว (ไม่ step-up ซ้ำ) | strong factor MFA-grade |
| Google OAuth | ต้อง step-up passkey/TOTP | federated primary เดี่ยว (อ่อนกว่า) |

## ผลการทดสอบ

```
tests/test_mfa_policy_passkey_2fa.py .......  (7 tests)
tests/test_passkey_login.py ...............   (15)
tests/test_passkey_security.py .............. (36)
============================== 58 passed ===============================
```

| Test | ยืนยัน |
|---|---|
| `test_passkey_login_satisfies_2fa` | passkey → ผ่าน 2FA |
| `test_discoverable_passkey_login_satisfies_2fa` | discoverable → ผ่าน |
| `test_google_login_does_not_satisfy_2fa` | Google → ไม่ผ่าน (ต้อง step-up) |
| `test_federated_gate_still_requires_2fa_for_always_user` | Google flow: admin ยังต้อง step-up |
| `test_federated_gate_hard_block_wins` | hard block ชนะ mfa |

## ไฟล์ที่แก้
- `hub/backend/app/services/mfa_policy.py` — helper + constant + docstring
- `hub/backend/app/routers/passkey.py` — comment เจตนา + audit `mfa_satisfied_by` + import mfa_policy
- `hub/backend/tests/test_mfa_policy_passkey_2fa.py` — ใหม่ (7 tests)

## สำหรับ thesis
"Always-2FA บังคับ factor ที่สองตามความแข็งแรง — passkey login (phishing-resistant,
NIST AAL2+) ถือว่า satisfy 2FA ในตัว ไม่ต้องยืนยันซ้ำ; federated login (Google) ต้อง
step-up passkey/TOTP เสริม" — auditable ผ่าน `mfa_satisfied_by` ใน audit log
