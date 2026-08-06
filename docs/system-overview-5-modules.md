# Central Auth Hub — ภาพรวม 5 ระบบหลัก

> ระบบการจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง (Centralized Identity & Permission Management Platform) สำหรับมหาวิทยาลัย
>
> เอกสารนี้อธิบายแต่ละระบบว่า **ทำอะไร / ทำยังไง / เพื่ออะไร**

---

## สารบัญ

1. [ระบบยืนยันตัวตน (Authentication)](#1-ระบบยืนยันตัวตน-authentication)
2. [ระบบจัดการผู้ใช้งานและสิทธิ์ (User & Permission Management)](#2-ระบบจัดการผู้ใช้งานและสิทธิ์-user--permission-management)
3. [ระบบจัดการระบบย่อย (Subsystem Management)](#3-ระบบจัดการระบบย่อย-subsystem-management)
4. [ระบบประเมินความเสี่ยง (Risk Assessment — RBA)](#4-ระบบประเมินความเสี่ยง-risk-assessment--rba)
5. [ระบบติดตามและตรวจสอบ (Monitoring & Audit)](#5-ระบบติดตามและตรวจสอบ-monitoring--audit)
6. [ภาพรวมการทำงานร่วมกัน](#ภาพรวมการทำงานร่วมกัน)

---

## เทคโนโลยีที่ใช้

| Layer | Technology |
|-------|-----------|
| Backend (Hub) | Python 3.11 + FastAPI + SQLAlchemy + Authlib |
| Backend (ML) | Python 3.11 + FastAPI + scikit-learn + SHAP |
| Database | PostgreSQL 15 |
| Cache / Session | Redis 7 |
| Auth Protocol | OAuth 2.0 + PKCE + JWT (RS256) + JWKS |
| Frontend (Admin) | Next.js 14 (App Router) + TypeScript + Tailwind CSS |
| Containers | Docker Compose (3 stacks: cah-hub / cah-dorm / cah-library) |

---

## 1. ระบบยืนยันตัวตน (Authentication)

### ทำอะไร
ยืนยันว่า "คุณคือใคร" ก่อนให้เข้าใช้งาน — รองรับ 3 ช่องทาง: **Google OAuth** (หลัก), **Passkey** (WebAuthn/FIDO2), และ **TOTP** (Authenticator app) เป็นปัจจัยเสริม/กู้บัญชี

### ทำยังไง
- **Google OAuth 2.0 + PKCE** — ผู้ใช้ล็อกอินผ่าน Google, Hub รับ identity ผ่าน OIDC discovery (Authlib) แล้วผูก `google_sub` กับบัญชีในระบบ (TOFU — Trust On First Use)
- **JWT (RS256)** — หลังยืนยันสำเร็จ Hub ออก token เซ็นด้วย private key; ทุก token มี `aud` claim บังคับ (Hub-direct = `hub.internal`, subsystem = `client_id`) เพื่อกัน token ข้ามระบบ (audience confusion)
- **JWKS discovery** — subsystem ตรวจ JWT ด้วย public key ของ Hub (cache 10 นาที)
- **Passkey (WebAuthn/FIDO2)** — ล็อกอินแบบไม่ใช้รหัสผ่าน, ตรวจ signature ด้วย public key ที่ลงทะเบียนไว้ — กัน phishing ได้
- **TOTP (RFC 6238)** — รหัส 6 หลักจากแอป Authenticator เป็น Fallback Factor + ใช้กู้บัญชี; secret เก็บ Fernet-encrypted
- **Refresh Token** — access token อายุสั้น (15 นาที) + rotating refresh token (30 วัน) หมุนคู่ใหม่ทุกครั้ง กัน replay
- **Token Revocation** — Redis jti blacklist, ยกเลิก token ได้ทันที (logout, admin force-logout, subsystem back-channel)

### เพื่ออะไร
รวมการยืนยันตัวตนไว้ที่จุดเดียว (centralized) — แต่ละระบบย่อยไม่ต้องจัดการรหัสผ่านเอง ลดจุดที่ credential รั่วได้ และบังคับมาตรฐานความปลอดภัยเดียวกันทั้งระบบ

> ⚠️ **สถาปัตยกรรมไม่ใช่ SSO** — Hub ทำหน้าที่ authenticate + authorize เท่านั้น แต่ละ subsystem มี session แยกของตัวเอง

---

## 2. ระบบจัดการผู้ใช้งานและสิทธิ์ (User & Permission Management)

### ทำอะไร
เก็บข้อมูลผู้ใช้และควบคุมว่า "ใครทำอะไรได้บ้าง" — ทั้งระดับบทบาท (role) และระดับสิทธิ์เข้าระบบย่อยแต่ละตัว

### ทำยังไง
- **RBAC (Role-Based Access Control)** — 4 บทบาท: `student` / `teacher` / `staff` / `admin`

  | Route | student | teacher | staff | admin |
  |-------|---------|---------|-------|-------|
  | `/auth/google/*` (Hub console) | ❌ | ✅ | ✅ | ✅ |
  | `/developer/*` (ลงทะเบียน subsystem) | ❌ | ✅ | ✅ | ✅ |
  | `/admin/*` | ❌ | ❌ | ❌ | ✅ |
  | `/oauth/*` (เข้าระบบย่อย) | ✅ (ถ้า whitelist) | ✅ | ✅ | ✅ |

- **Access List (whitelist)** — ตารางระบุว่า user คนไหนเข้า subsystem ไหนได้ + role ในระบบนั้น; ใช้ **soft delete** (`revoked_at`) เพื่อเก็บประวัติ
- **Defense in Depth** — ตรวจสิทธิ์ 2 ชั้น: ที่ callback (ชั้น 1) + ที่ endpoint ผ่าน `Depends(require_hub_admin / require_developer)` (ชั้น 2)
- **Credential Management** — จัดการ credential ต่อ user แยกตามประเภท (GOOGLE / PASSKEY / TOTP) พร้อม lifecycle (REGISTERED → ACTIVE → SUSPENDED → REVOKED)
- **User Lifecycle** — จัดการสถานะเมื่อ user พ้นสภาพ (graduated / resigned) → ตัดสิทธิ์แบบ cascade เหมือนการลบ

### เพื่ออะไร
คุมสิทธิ์แบบละเอียดตามหลัก **least privilege** — ให้แต่ละคนเข้าถึงเฉพาะสิ่งที่ควรเข้าถึง และเพิกถอนสิทธิ์ได้ทันทีเมื่อจำเป็น

---

## 3. ระบบจัดการระบบย่อย (Subsystem Management)

### ทำอะไร
ให้ระบบย่อย (หอพัก, ห้องสมุด ฯลฯ) มาลงทะเบียนเป็น **OAuth client** แล้วเชื่อมต่อกับ Hub เพื่อยืม identity

### ทำยังไง
- **Developer Portal** — teacher/staff ลงทะเบียน subsystem → ได้ `client_id` + `client_secret` (แสดงครั้งเดียวผ่าน one-time link 15 นาที)
- **Secret Delivery ปลอดภัย**
  - `client_secret` เก็บเป็น **Argon2id hash** (ไม่เก็บ plaintext)
  - ตัว secret encrypted ด้วย **Fernet**
  - token ของลิงก์เก็บเป็น **HMAC-SHA256** (ไม่ใช่ plaintext)
  - ลิงก์ใช้ครั้งเดียว + JS `history.replaceState()` ลบ token ออกจาก URL
- **OAuth Flow (subsystem)**
  ```
  /oauth/authorize → Google → /oauth/callback (เช็ค access_list + risk)
      → ออก authorization code → /oauth/token (server-to-server แลก JWT)
  ```
- **Atomic auth code** — ใช้ Redis `getdel` (atomic) กัน race condition — code ใช้ซ้ำไม่ได้
- **PKCE บังคับ** — ทุก OAuth flow ต้องมี code_challenge กัน auth code interception
- **Admin Approval** — subsystem ใหม่ต้องรอ admin อนุมัติ (pending → active → suspended)
- **Back-channel Notification** — action ที่ Hub ทำ (revoke, force-logout) ยิง webhook แจ้ง subsystem ข้าม trust domain (fail-safe)

### เพื่ออะไร
ให้ทีมที่เป็นเจ้าของแต่ละระบบย่อย (คนละทีม) เชื่อมต่อได้อย่างปลอดภัยและเป็นมาตรฐาน — จำลองการใช้งานจริงที่ subsystem deploy แยกกันโดยทีมอิสระ

---

## 4. ระบบประเมินความเสี่ยง (Risk Assessment — RBA)

### ทำอะไร
วิเคราะห์ทุกครั้งที่ล็อกอินว่า "เสี่ยงแค่ไหน" แล้วตัดสินใจ: **ผ่าน / ขอยืนยันเพิ่ม (MFA) / บล็อก**

### ทำยังไง — 4 ชั้น (4-Layer RBA)

| ชั้น | ทำอะไร | อ้างอิง |
|------|--------|---------|
| **1. Rule Engine** | กฎตรงๆ เช่น impossible travel (ข้ามประเทศเร็วผิดปกติ), login เยอะเกินไป | — |
| **2. Behavior Profiling** | เทียบกับพฤติกรรมปกติของ user (เวลาที่ชอบล็อกอิน, อุปกรณ์เดิม) | Wiefling 2022 |
| **3. Isolation Forest** | โมเดล ML (unsupervised) จับ anomaly จาก 23 features | Liu et al. 2008 |
| **4. Aggregation** | รวมคะแนน 3 ชั้น → คะแนน 0.00–1.00 | Freeman 2016 / F-RBA 2024 |

- **23 Features** — 4 หมวด: Temporal (เวลา), Geographic (ภูมิศาสตร์), Device (อุปกรณ์), Velocity (ความเร็ว)
- **SHAP TreeExplainer** — อธิบายว่า feature ไหนดันคะแนนขึ้น (per-feature contribution) แสดงเป็น bar ใน UI
- **Threshold ตัดสินใจ**
  - `< 0.50` → ผ่าน (allow)
  - `0.50 – 0.85` → challenge (ขอ MFA ด้วย Passkey/TOTP)
  - `≥ 0.85` → บล็อก (block)
- **Risk-Triggered MFA** — คะแนนกลาง → เด้งให้ยืนยันด้วย Passkey หรือ TOTP ก่อนเข้า
- **Always-2FA (user choice)** — ผู้ใช้เลือกเปิด "ขอยืนยันทุกครั้ง" ได้เอง (รวมเข้ากับ gate เดียวกับ risk-based — ไม่ซ้ำซ้อน)
- **Shadow Mode** — โหมด log อย่างเดียวไม่บล็อกจริง (`would_block` / `would_mfa`) สำหรับเก็บข้อมูลปรับ threshold
- **Fail-safe** — ML service ล่ม → default เป็น "ผ่าน" (Hub ไม่ล่มตาม)

### เพื่ออะไร
สมดุลระหว่าง **ความปลอดภัย** กับ **UX** — ไม่รบกวนผู้ใช้ปกติ แต่จับพฤติกรรมผิดปกติ (บัญชีถูกขโมย) ได้แบบ adaptive ตามงานวิจัยด้าน Risk-Based Authentication

---

## 5. ระบบติดตามและตรวจสอบ (Monitoring & Audit)

### ทำอะไร
บันทึกทุกเหตุการณ์สำคัญไว้ตรวจสอบย้อนหลัง + เฝ้าระวังภัยแบบ real-time

### ทำยังไง
- **Audit Log** — ทุก action ที่เปลี่ยนสถานะบันทึก `actor / action / target / ip / metadata` แบบ **append-only + hash chain** (แก้ย้อนหลังไม่ได้)
  - บังคับลำดับ `log_action() → commit → raise` เพื่อไม่ให้ audit หายเมื่อ transaction rollback
  - บันทึกทั้ง **success และ failure path** (ล็อกอินผิดก็ต้องบันทึก — เพื่อตามหา attacker)
- **Request Logger** — middleware จับทุก HTTP request (method, path, status, duration, ip)
- **Login Sessions** — เก็บทุกครั้งที่ล็อกอิน พร้อม `risk_score`, `decision`, ประเทศ, อุปกรณ์, browser
- **SOC Dashboard / User 360** — admin ดู timeline ของ user, สถิติ decision distribution, แผนที่ login
- **Alert System** — แจ้งเตือน admin เมื่อ risk สูง หรือ failed login เยอะผิดปกติต่อ IP (5 ครั้ง/5 นาที)
- **IP Blacklist** — บล็อก IP ที่เป็นภัย (import จาก threat intelligence feed)
- **GeoIP** — resolve ประเทศจาก IP (MaxMind GeoLite2)
- **Event Bus (Hooks)** — pluggable extension points รอบ event สำคัญ (login, token, oauth, ml) แบบ fail-safe

### เพื่ออะไร
- **Accountability** — ตอบได้ว่า "ใครทำอะไร เมื่อไหร่" (compliance)
- **Forensics** — สืบสวนย้อนหลังเมื่อเกิดเหตุ
- **Detection & Response** — เฝ้าระวังและตอบสนองภัยแบบ proactive

---

## ภาพรวมการทำงานร่วมกัน

```
ผู้ใช้ล็อกอิน
   ↓
[1] ยืนยันตัวตน (Google / Passkey / TOTP)
   ↓
[2] ตรวจสิทธิ์ (RBAC + access_list)
   ↓
[4] ประเมินความเสี่ยง (4-Layer RBA) → ผ่าน / MFA / บล็อก
   ↓
[3] ออก token ให้ระบบย่อย (ถ้าเป็น OAuth flow)
   ↓
[5] บันทึกทุกขั้น (audit + login session + alert)
```

ทั้ง 5 ระบบทำงานเป็น **Defense in Depth — 10 ชั้นความปลอดภัย** ถ้าชั้นใดถูกเจาะ ยังมีชั้นอื่นป้องกันต่อ:

| # | ชั้น | กลไก |
|---|------|------|
| 1 | Data at Rest | Argon2id hash + pgcrypto |
| 2 | Data in Transit | HTTPS/TLS |
| 3 | Auth Flow | OAuth 2.0 + PKCE |
| 4 | Token Security | JWT RS256 + jti |
| 5 | Subsystem Key | One-time link + AES/Fernet |
| 6 | Session Security | HttpOnly + SameSite cookies |
| 7 | Audit Log | Append-only + hash chain |
| 8 | Rate Limiting | ต่อ IP / ต่อ client_id |
| 9 | ML Anomaly Detection | Isolation Forest |
| 10 | Secret Management | `.env` แยกจาก git + key rotation |

---

## สถาปัตยกรรมระบบ

```
┌──────────┐   redirect     ┌──────────┐   OAuth    ┌──────────┐
│ Subsystem│──────────────▶│   Hub    │──────────▶│  Google  │
│  (หอพัก, │◀──Token (S2S)─│ (Central)│            │  OAuth   │
│ ห้องสมุด) │                └────┬─────┘             └──────────┘
└──────────┘                    │
                                ▼
                         ┌──────────────┐
                         │  ML Verifier │ (Isolation Forest + SHAP)
                         └──────────────┘
                                │
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
            ┌──────────┐                 ┌─────────┐
            │ Postgres │                 │  Redis  │
            └──────────┘                 └─────────┘
```

| Service | หน้าที่ | Port |
|---------|--------|------|
| Hub | Central Auth Server (identity, permission, audit, risk) | 8000 |
| Hub Admin Frontend | Next.js admin console | 3000 |
| Subsystem A — ระบบหอพัก | OAuth client + จองห้อง | 8001 |
| Subsystem B — ระบบห้องสมุด | OAuth client + ยืม/คืนหนังสือ | 8002 |
| ML Verifier | Isolation Forest + SHAP risk scoring | 9000 |
