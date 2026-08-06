# E2E Test — ครบทุกขอบเขต (ข้อ 1-5) Positive + Negative · 2026-07-26

## ภาพรวม

ชุดเทส **End-to-End** ที่ไล่ flow จริงหลายขั้นตอน (ไม่ใช่ unit เดี่ยว) แมปตรงกับขอบเขต
โครงงาน 5 ข้อ — **61 test cases** ครบทั้ง positive + negative รันซ้ำ **3 รอบไม่ flaky**

| ไฟล์ | ขอบเขต | เทส | ครอบคลุม E2E |
|---|---|---|---|
| `test_e2e_auth.py` | ข้อ 1 ยืนยันตัวตน | 13 | passkey ceremony เต็ม (crypto จริง) + TOTP + recovery |
| `test_e2e_permission.py` | ข้อ 2.1 จัดการสิทธิ์ | 13 | สร้างบัญชี→สิทธิ์→session→ถอน→บล็อก (HTTP+DB) |
| `test_e2e_subsystem.py` | ข้อ 2.2 บริหารระบบย่อย | 17 | ลงทะเบียน→อนุมัติ→rotate→transfer |
| `test_e2e_oauth_flow.py` | ข้อ 5 เชื่อมต่อระบบย่อย | 7 | OAuth+PKCE→JWT→verify JWKS |
| `test_e2e_rba.py` | ข้อ 4+3 RBA 4 ชั้น + SHAP | 11 | features→4 ชั้น→decision (ML จริง) |
| **รวม** | | **61** | |

## รายละเอียด flow ที่ทดสอบ (E2E จริง)

### ข้อ 1 — ยืนยันตัวตน (13)
- **Passkey ceremony เต็ม** (software authenticator สร้าง attestation/assertion จริง verify ด้วย py_webauthn):
  register → login (positive) · login อุปกรณ์แปลก (negative) · step-up · duplicate excludeCredentials
- **TOTP:** enroll→confirm ด้วย code จริง (pyotp)→verify_active (positive) · code ผิด (negative) · verify ก่อน enroll · revoke→disabled
- **Recovery:** ออก backup code→กู้คืน (positive) · code ผิด · ใช้ซ้ำ (single-use)
- has_second_factor สะท้อนจริงหลัง register passkey/TOTP

### ข้อ 2.1 — จัดการสิทธิ์ (13)
- **สร้างบัญชี** (endpoint+step-up)→ปรากฏใน list+search (positive) · email ซ้ำ (negative) · ไม่มี step-up→403
- **เปลี่ยนบทบาท+สถานะ**→GET สะท้อน (positive) · สถานะผิด→422
- **ให้/ถอนสิทธิ์ flow:** grant→เข้าได้→revoke(deny)→เข้าไม่ได้ · ถอนไม่มี step-up→403
- **สถานะกระทบการเข้าถึง:** suspended→บล็อก→reactivate→เข้าได้
- **Force Logout:** สร้าง session→force logout→logout_at ถูก set จริง · reset passkey ไม่มี step-up→403

### ข้อ 2.2 — บริหารระบบย่อย (17)
- **ลงทะเบียน**→client_id+api_key+pending · admin อนุมัติ→active
- **Redirect URI validation** (5 negative: javascript:/ftp:/http-real/…) · **Scope** (3 negative)
- ไม่ใช่ developer→403 · ไม่มี step-up→403
- **Rotate secret** (positive+step-up negative) · **Transfer owner** (โอนเจ้าของสำเร็จ) · สถิติ (admin only)

### ข้อ 5 — OAuth flow (7)
- **Full flow:** auth_code→/oauth/token (secret+PKCE verifier)→JWT (RS256, aud=client_id)→verify ผ่าน JWKS
- Negative: secret ผิด→401 · PKCE verifier ไม่ตรง→ปฏิเสธ · **code ใช้ซ้ำ→ปฏิเสธ (atomic getdel)** · code ปลอม · **audience confusion (B4)**

### ข้อ 4 — RBA 4 ชั้น (11)
- login ปกติ→breakdown ครบ 4 ชั้น (rule/behavior/iforest+raw)
- เครื่องใหม่→rule +0.30 · ประเทศใหม่ต่างชาติ→คะแนนขึ้น · anomaly ≥ normal (ทิศทางถูก)
- **hard block** (failed≥10 / login_count≥50)→block ทันที score 1.0
- shadow mode→prefix would_ · SHAP: iforest_raw + reasons อ่านได้ · score cap 1.0

## ผลรัน + เสถียรภาพ

```
รัน 1 ครั้ง: 61 passed in 36.35s
รอบ 1: 61 passed    รอบ 2: 61 passed    รอบ 3: 61 passed
```
**ไม่มี flaky test**

## ข้อจำกัด (สิ่งที่ E2E อัตโนมัติไม่ครอบ — ต้อง manual)
- **Google OAuth consent screen จริง** — ต้องมี Google account จริง (E2E นี้จำลองหลัง callback)
- **Passkey ด้วยฮาร์ดแวร์จริง** (Windows Hello/Touch ID) — E2E ใช้ software authenticator (crypto เหมือนจริง)
- **Frontend UI (Next.js)** — E2E นี้เป็น backend flow; UI ทดสอบผ่าน Playwright (workflow มีแล้ว)

## วิธีรัน
```bash
docker compose exec hub-backend pytest tests/test_e2e_*.py -v
```
