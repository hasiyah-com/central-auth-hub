# Passkey Manual Test Checklist — Phase 0-7

คู่มือทดสอบ Passkey ครบทุก phase ด้วยมือ (browser). อัปเดต 2026-06-11.

---

## 🔧 Prerequisites

1. **Stack ขึ้นครบ:**
   ```bash
   docker compose ps     # hub-backend/frontend/ml/postgres/redis = Up
   curl localhost:8000/health && curl localhost:9000/health
   ```
2. **Browser:** Chrome/Edge ใหม่ (รองรับ WebAuthn)
3. **Virtual Authenticator** (สำหรับเทสหลาย account บนเครื่องเดียว):
   - F12 → ⋮ → More tools → **WebAuthn** → ✅ Enable virtual authenticator
   - Add: ctap2 / internal / ✅ resident keys / ✅ user verification
   - **เปิด DevTools ค้างไว้ตลอด** (ปิด = virtual หาย)
4. **SMTP** (เฉพาะเทส email OTP/reminder): ตั้ง `SMTP_USER`/`SMTP_PASSWORD` ใน `.env`

**Reset state (ถ้าต้องการเริ่มสะอาด):**
```bash
docker exec -i hub-postgres psql -U hub -d hub_db -c "TRUNCATE passkey_credentials, passkey_backup_codes CASCADE;"
```

---

## Phase 0 — Foundation (backend only, ไม่มี UI)

ตรวจผ่าน config + tests (ไม่ต้อง browser):
```bash
docker compose exec hub-backend python -c "from app.config import settings; print('rp_id:', settings.webauthn_rp_id, '| stepup_ttl:', settings.stepup_cache_ttl_sec, '| max_pk:', settings.webauthn_max_passkeys_per_user)"
# คาดหวัง: localhost / 900 / 10
docker compose exec hub-backend pytest tests/test_stepup_cache.py tests/test_critical_action_policy.py -q
```
- [ ] config โหลดถูก (localhost, 900, 10)
- [ ] step-up cache + critical gate tests ผ่าน

---

## Phase 1 — Register Passkey + Backup Codes (admin console)

> ⚠️ `/account/security` = **admin only**

1. Login Hub เป็น admin (Google) → http://localhost:3000
2. ไป http://localhost:3000/account/security
- [ ] เห็น banner "✅ เบราว์เซอร์รองรับ Passkey"
- [ ] กด "+ เพิ่ม Passkey" → ใส่ชื่อ "Test Device" → ลงทะเบียน → Windows Hello/Virtual
- [ ] **BackupCodesModal เด้ง** — codes 10 ตัว grid + เลข 01-10
- [ ] กด X / ESC → **ปิดไม่ได้** (mandatory)
- [ ] กด Copy หรือ Download → ปุ่มเขียว ✓
- [ ] ติ๊ก checkbox → ปุ่ม "ยืนยัน" enable → กด → modal ปิด

**Verify:**
```bash
docker exec -i hub-postgres psql -U hub -d hub_db -c "SELECT device_name, sign_count FROM passkey_credentials WHERE revoked_at IS NULL ORDER BY created_at DESC LIMIT 1;"
docker exec -i hub-postgres psql -U hub -d hub_db -c "SELECT action FROM audit_logs WHERE action LIKE 'passkey%' ORDER BY created_at DESC LIMIT 3;"
# คาดหวัง: passkey_registered + backup_codes_generated + acknowledged
```

---

## Phase 2 — Login ด้วย Passkey (Hub admin)

1. Logout → http://localhost:3000/auth/login
- [ ] เห็นปุ่ม emerald "🔑 Sign in with Passkey"
- [ ] กด → กรอก email admin → "ดำเนินการต่อ" → Windows Hello → เข้า /dashboard
- [ ] **Session detail** (`/audit` หรือ ml): browser/OS = "Chrome xxx · Windows 10" (ไม่ใช่ "?")
- [ ] กรอก email ผิด → "ไม่พบ Passkey ที่ใช้ได้" (opaque)

**Discoverable (Phase 7 — ในหน้าเดียวกัน):**
- [ ] กด Passkey → ปุ่ม "🔓 เข้าโดยไม่กรอก email" → browser โชว์ passkey → เลือก → เข้าได้ (ไม่กรอก email)

---

## Phase 3 — Lifecycle (list/rename/delete)

ที่ /account/security (admin):
- [ ] เห็น list passkey: device name, last used, country
- [ ] กด ✏️ → แก้ชื่อ → Enter → ชื่อเปลี่ยน
- [ ] register 2nd passkey → เห็น 2 รายการ
- [ ] กด 🗑️ ตัวหนึ่ง → "แน่ใจ?" → ลบ → เหลือ 1
- [ ] เหลือ passkey ตัวเดียว → ปุ่ม 🗑️ **disabled** (last-passkey guard)

**Admin overview (หน้า Users):**
1. ไป http://localhost:3000/users
- [ ] คอลัมน์ "🔑 ดู" → กด → modal โชว์ passkey ของ user คนนั้น + ปุ่ม Reset

---

## Phase 4 — Recovery + Backup Codes Lifecycle

### Backup code recovery
1. mint code ใหม่ (เพราะ codes hash):
   ```bash
   docker compose exec hub-backend python -c "
   from app.database import SessionLocal; from app.models import User
   from app.services import passkey_recovery as pr
   db=SessionLocal(); u=db.query(User).filter(User.email=='<U08>').first()
   print('CODE:', pr.generate_backup_codes(u.id, db, rotate=True)[0]); db.commit()"
   ```
2. ไป http://localhost:3000/auth/passkey/recover → tab "Backup Code"
- [ ] กรอก email + code → "กู้บัญชี" → ✓ สำเร็จ
- [ ] code เดิมซ้ำ → "ไม่ถูกต้อง" (one-time)
- [ ] email มั่ว → "ไม่ถูกต้อง" (anti-enum เหมือนกัน)

### Regenerate (admin) — Phase 5 gate จะเด้ง step-up
- [ ] /account/security → "🔄 สร้างใหม่" → **ถูกพาไปหน้า step-up** (Phase 5) → ยืนยัน → codes ใหม่

### OTP recovery / regen (ต้อง SMTP)
- [ ] recover page → "กู้ OTP" → email → OTP → revoke passkey + codes ใหม่
- [ ] recover page → "ขอ codes ใหม่" → OTP → codes ใหม่ (**passkey ยังอยู่**)
- [ ] codes display = grid + copy/download/ack (UI เหมือน admin modal)

### Subsystem recovery
- [ ] subsystem chooser → ลิงก์ "ทำ Passkey หาย? กู้บัญชี" → หน้า Hub recover (dark)

---

## Phase 5 — Step-up + Critical Action Gate

1. Login admin (ต้องมี passkey)
2. /account/security → กด "🔄 สร้างใหม่" (backup codes)
- [ ] **ถูกพาไปหน้า "🔐 ยืนยันตัวตนอีกครั้ง"** (ไม่ทำสำเร็จเลย)
- [ ] ปุ่ม "🔑 ยืนยันด้วย Passkey" เป็น **สีเขียว** (ไม่ disabled)
- [ ] กด → Windows Hello → กลับมาหน้าเดิม
- [ ] กดสร้างใหม่อีกครั้ง → **สำเร็จเลย** (ใน 15 นาที, cache hit)
- [ ] ลบ passkey ภายใน 15 นาที → ไม่ถูกถาม step-up ซ้ำ
- [ ] "ใช้ OTP ทาง email แทน" → ส่ง OTP → กรอก → ผ่าน (ต้อง SMTP)

**ML Device Trust (curl):**
```bash
# takeover (passkey เพิ่งเพิ่ม + ต่างประเทศ) → score สูง
curl -s -X POST localhost:9000/v1/score -H "Content-Type: application/json" \
  -d '{"features":[3,2,0,8,0,1,2,1,1,0.5,2,1,1,1,0.1,1,0.1]}' | python -m json.tool | head -8
```
- [ ] score ~0.69 "mfa" + SHAP ชี้ new_passkey_recently_added

---

## Phase 6 — Integration tests + CI (ไม่ใช่ browser)

```bash
docker compose exec hub-backend pytest tests/test_passkey_ceremony.py -v
```
- [ ] 13/13 ผ่าน (full ceremony: register/login/stepup/discoverable/counter regression)
- [ ] `.github/workflows/backend-ci.yml` มีอยู่

---

## Phase 7 — Discoverable + Force Adoption

### Discoverable (ทดสอบใน Phase 2 แล้ว)
- [ ] ปุ่ม "เข้าโดยไม่กรอก email" ทำงาน

### Force adoption (config + endpoint)
```bash
# default opt-in → nudge=false
curl -s -X POST localhost:8000/auth/passkey/login/start ...  # (ต้องมี token)
docker compose exec hub-backend python -c "
from app.database import SessionLocal; from app.models import User
from app.services import webauthn_service as ws
db=SessionLocal(); u=db.query(User).filter(User.is_hub_admin==True).first()
print(ws.adoption_status(u, db))"
```
- [ ] adoption_status คืน {has_passkey, nudge: false (opt-in default), ...}

---

## ✅ Subsystem flow (B/A/E — เทสรวม)

1. ไป subsystem (http://localhost:8002 ห้องสมุด หรือ 8001 หอพัก) → กด login
- [ ] redirect มา **หน้า chooser** (dark) — 2 ปุ่ม Google/Passkey + ลิงก์กู้บัญชี
- [ ] "Continue with Google" → เลือก account → ถ้าไม่มี passkey → **หน้า "ตั้งค่า Passkey"** (enroll interstitial)
- [ ] enroll → backup codes → เข้า subsystem
- [ ] login ครั้งหน้า → chooser → Passkey → กรอก email → เข้า subsystem (ไม่ผ่าน Google)
- [ ] **นักศึกษา enroll ได้** (ไม่ถูกบล็อก)

**Verify provider:**
```bash
docker exec -i hub-postgres psql -U hub -d hub_db -c "SELECT metadata->>'provider', metadata->>'method' FROM audit_logs WHERE action='oauth_authorized' ORDER BY created_at DESC LIMIT 3;"
```

---

## 🔒 Security spot-checks (curl)

```bash
# non-email / SQLi → 422
curl -s -X POST localhost:8000/auth/passkey/login/start -H "Content-Type: application/json" -d '{"email":"x OR 1=1"}' -w " [%{http_code}]\n" | tail -c 20
# /account/passkeys ไม่มี token → 403
curl -s localhost:8000/account/passkeys -w " [%{http_code}]\n" | tail -c 10
# discoverable malformed X-Forwarded-For → ไม่ 500
curl -s -X POST localhost:8000/auth/passkey/login/discoverable/start -H "X-Forwarded-For: garbage" -d '{}' -H "Content-Type: application/json" -w " [%{http_code}]\n" | tail -c 20
```
- [ ] non-email → 422 · no-token → 403 · garbage XFF → 200 (ไม่ 500)

---

## สรุป — ครบ 7 phase + subsystem ✅

| Phase | จุดเทสหลัก |
|---|---|
| 0 | config + service tests |
| 1 | register + mandatory backup modal |
| 2 | login (email-first) + session device |
| 3 | list/rename/delete + admin overview |
| 4 | recovery (backup/OTP) + regen + ack UX |
| 5 | step-up gate + ML 17 features |
| 6 | ceremony integration tests + CI |
| 7 | discoverable + adoption |
| B/A/E | subsystem chooser/enroll/recover |
