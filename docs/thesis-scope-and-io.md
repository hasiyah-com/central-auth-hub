# ขอบเขต + Dataset/Input/Output (ฉบับอ้างอิงระบบจริง)

> เอกสารนี้สรุป **ขอบเขตที่แก้ให้ตรงระบบที่พัฒนาจริง** (Google + Passkey) พร้อมตอบข้อเสนอแนะอาจารย์ 7 ข้อ
> โดยอ้างอิงโค้ดจริง: `hub/backend/app/models.py`, `ml-service/app/features.py`, `ml-service/app/model.py`,
> และรายงาน benchmark `hub/backend/tests/reports/benchmark_rba_model_comparison_2026-06-15.md`

**ชื่อโครงงาน:** การพัฒนาแบบจำลองการยืนยันตัวตนแบบรวมศูนย์เพื่อประเมินความเสี่ยงโดยใช้เทคนิคไอโซเลชันฟอเรสต์

---

## 1.3 ขอบเขตของโครงงาน (ฉบับแก้ — ตรงระบบจริง)

1. ผู้ใช้ยืนยันตัวตนด้วย **2 วิธี**: **บัญชี Google (OAuth 2.0)** และ **Passkey (WebAuthn/FIDO2)**
   โดยระบบรวมศูนย์ (Hub) ทำหน้าที่ authenticate + authorize ให้ระบบย่อย
   *(สถาปัตยกรรมไม่ใช่ SSO — แต่ละระบบย่อยมี session แยกของตัวเอง)*

2. ระบบบริหารจัดการสิทธิ์และแดชบอร์ดศูนย์กลาง มี 2 โมดูลหลัก
   1. **การจัดการสิทธิ์แบบรวมศูนย์ (RBAC)**
      - (a) บริหารจัดการบัญชี ค้นหา และกำหนดสิทธิ์การเข้าถึงระบบย่อย (whitelist ต่อระบบ)
      - (b) ควบคุมสถานะผู้ใช้ (active / suspended)
      - (c) จัดเก็บข้อมูลผู้ใช้: **ชื่อ-สกุล, รหัสนักศึกษา/รหัสพนักงาน, คณะ/สาขา, ชั้นปี/ตำแหน่ง, อีเมล, เบอร์โทรศัพท์, ที่อยู่**
   2. **การเฝ้าระวังและตรวจสอบ**
      - (a) บันทึกเหตุการณ์ (audit log) เพื่อตรวจสอบย้อนหลัง (append-only + hash chain)
      - (b) แสดงสถิติความเสี่ยง (เช่น การล็อกอินล้มเหลว, คะแนนความเสี่ยง, SHAP) บนแดชบอร์ด

3. ระบบใช้ **Machine Learning ตรวจจับความผิดปกติของการเข้าสู่ระบบและประเมินความเสี่ยง**
   ด้วยเทคนิค **Isolation Forest** และ **เปรียบเทียบประสิทธิภาพกับ One-Class SVM** (และ Local Outlier Factor)
   *(ML ใช้ประเมินความเสี่ยง ไม่ได้ตัดสินใจเรื่องสิทธิ์ — การจัดการสิทธิ์เป็น RBAC)*

4. ทดลองเชื่อมต่อกับระบบย่อย **2 ระบบ (หอพัก, ห้องสมุด)** เพื่อใช้ทดสอบระบบจำลอง

> **เปลี่ยนจากฉบับเดิมตรงไหน:** (1) Gmail → **Google + Passkey เท่านั้น (2 วิธี)** — ไม่ใช้ LINE,
> (2) ตัด PII ที่ระบบไม่มี (เลขบัตรประชาชน, วันเกิด, สัญชาติ) ออก เหลือ field จริง,
> (3) แก้ "ML จัดการสิทธิ์" → "ML ประเมินความเสี่ยง" (แยกจาก RBAC ให้ชัด)
>
> *(หมายเหตุ: โค้ด LINE Login ยังคงอยู่ในระบบแต่ไม่อยู่ในขอบเขตและไม่ตั้งค่าใช้งาน)*

### สถานะการพัฒนา (ตัวไหนเสร็จ / ยังไม่เสร็จ)

| ส่วน | สถานะ | หมายเหตุ |
|---|---|---|
| ข้อ 1 — Google OAuth | ✅ เสร็จ | วิธียืนยันตัวตนที่ 1 |
| ข้อ 1 — Passkey (WebAuthn) | ✅ เสร็จ | วิธีที่ 2 — register/login + backup code + recovery + risk step-up |
| ข้อ 2.1 — RBAC / whitelist / สถานะผู้ใช้ | ✅ เสร็จ | |
| ข้อ 2.2 — audit log + dashboard | ✅ เสร็จ | |
| ข้อ 3 — Isolation Forest + SHAP | ✅ เสร็จ | serve ใน production |
| ข้อ 3 — เปรียบเทียบ OCSVM / LOF | ✅ เสร็จ | offline benchmark (ดู §7) |
| ข้อ 3 — RBA 4 ชั้น | ✅ เสร็จ | Rule + Behavior + IForest + Aggregate |
| ข้อ 4 — 2 ระบบย่อย | ✅ เสร็จ | หอพัก + ห้องสมุด |
| ML **enforce** (block/MFA จริง) | 🔄 ยังไม่เสร็จ | ตอนนี้ **Shadow Mode** (`would_block`/`would_mfa`) — log แต่ยังไม่บล็อกจริง รอ calibrate |
| Session Downgrade (จำกัดสิทธิ์ตามความเสี่ยง) | ⏳ ยังไม่ทำ | ออกแบบเสร็จ ยังไม่ implement |
| Deploy ขึ้น Internet (production) | 🔄 กำลังทำ | nginx + TLS + 4 subdomains |
| ML Phase 2 (calibrate/feedback loop) | ⏳ ติด | ขาด real labeled attack data |
| Test suite (frontend Jest/RTL) + CI + pentest | ⏳ ยังไม่ทำ | |

---

## ข้อ 1 — Dataset ประกอบด้วยอะไร

มี **3 แหล่ง** แยกตามวัตถุประสงค์:

| แหล่ง | ใช้ทำอะไร | รายละเอียด |
|---|---|---|
| **RBA dataset จริง** (Wiefling et al. 2022) | benchmark / เปรียบเทียบโมเดล | ต้นฉบับ ~31,269,264 logins → sample **10,000 normal + 100 ATO จริง** |
| **Synthetic stealth attacks** | เติม attack ให้ครบ scenario | **40 ตัว** (8 scenario) → benchmark รวม **10,140 แถว, attack 1.38%** |
| **ข้อมูล production จริง** | เทรน/ใช้งานจริงในระบบ | ตาราง `login_sessions` — ทุก login ที่เกิดในระบบ + label `is_account_takeover`, `is_attack_ip` |

- โมเดลเป็น **unsupervised** (IForest/OCSVM/LOF) → เทรนจาก features เท่านั้น **ไม่เห็น label**;
  label ใช้แค่ "วัดผล" (Precision/Recall/F1/ROC-AUC/PR-AUC)
- ฟีเจอร์ที่ RBA dataset ไม่มี (passkey/session/scope/permission) ถูก **สังเคราะห์โดยระบุชัดในเอกสาร** — ไม่ปลอมเป็นข้อมูลจริง

---

## ข้อ 5 — ตัวอย่าง Input Log + 23 Features

**Raw log (1 แถว ใน `login_sessions`):**
```
created_at = 2026-06-22 10:15:32 (UTC)
ip         = 1.46.x.x          geo_country = TH
user_agent = Mozilla/5.0 ... Chrome/120  → os=Windows 10, browser=Chrome 120, device=desktop
user_id    = <uuid>            subsystem_id = <uuid หอพัก>
```

**Hub แปลงเป็น 23 features (ลำดับนี้คือ contract ที่ส่งเข้า ML):**

| หมวด | features |
|---|---|
| Temporal (3) | `hour_of_day`, `day_of_week`, `hours_from_typical_login_time` |
| Geographic (3) | `is_thailand`, `is_new_country`, `country_change_count_30d` |
| Device (2) | `is_new_device`, `is_new_user_agent_family` |
| Velocity (2) | `log_minutes_since_last_login`, `login_count_24h` |
| Brute-force (1) | `failed_logins_24h` |
| Passkey (4) | `passkey_count`, `passkey_age_days`, `new_passkey_recently_added`, `passkey_last_used_days` |
| Session (2) | `concurrent_session_count`, `active_subsystem_count` |
| Behavioral (1) | `weekday_usage_score` |
| OAuth (1) | `scope_sensitivity_score` |
| Privilege (2) | `ever_changed_permission`, `permission_change_age` |
| History (1) | `confirmed_incident_count` |
| Geo-velocity (1) | `impossible_travel_score` |

ตัวอย่างค่า (login ปกติด้านบน):
`hour=10, day=0(จันทร์), hours_from_typical=0.5, is_thailand=1, is_new_country=0, is_new_device=0, failed_logins_24h=0, login_count_24h=2, ...`

---

## ข้อ 2 — Output ของระบบมีลักษณะอย่างไร

ต่อ 1 login ระบบคืน (เก็บใน `login_sessions` + ส่งให้ dashboard):

| field | ความหมาย | ตัวอย่าง |
|---|---|---|
| `anomaly_score` | 0.00–1.00 จาก Isolation Forest | 0.12 |
| `risk_score` | 0.000–1.000 รวม 4 ชั้น (RBA) | 0.180 |
| `risk_breakdown` | คะแนนแยกแต่ละชั้น | `{"rule":0.0,"behavior":0.1,"iforest":0.08}` |
| `risk_reasons` | เหตุผล (อ่านเข้าใจง่าย) | `["is_new_device (+0.30)", "hours_diff=12 (+0.40)"]` |
| **SHAP** | feature ไหนดันคะแนน (per-feature) | `is_new_country +0.18 (anomaly)` |
| `decision` | **allow / warn / challenge(MFA) / block** | allow *(Shadow: `would_block`/`would_mfa`)* |

---

## ข้อ 6 — Normal Case vs Anomaly Case

| | **Normal Case** | **Anomaly Case** |
|---|---|---|
| เวลา | 10:15 จันทร์ (เวลางาน) | 03:40 (ดึกผิดปกติ) |
| ประเทศ | TH (`is_thailand=1`) | ประเทศใหม่ RU (`is_new_country=1`) |
| อุปกรณ์ | เครื่องเดิม (`is_new_device=0`) | เครื่องใหม่ (`is_new_device=1`) |
| `failed_logins_24h` | 0 | 5 |
| IP | ปกติ | อยู่ใน threat feed (`is_attack_ip=1`) |
| **anomaly_score** | ~0.10 | ~0.85 |
| **decision** | allow | block / MFA |

**กรณี "stealth" (จับยาก — ใช้ใน benchmark):** raw ดูปกติทุกอย่าง (อยู่ TH, เครื่องคุ้น, เวลางาน, login สำเร็จ)
แต่ซ่อนสัญญาณ เช่น `new_passkey_recently_added=1` + เครื่องใหม่ (passkey abuse), หรือ
`concurrent_session_count` 4–10 (account sharing/ATO), หรือ `permission_change_age` 0–2 วัน + scope สูง (privilege abuse)

---

## ข้อ 3 — ภาพรวมระบบ (System Overview)

```
ผู้ใช้ → login (Google / Passkey) ที่ Hub
      → Hub สกัด 23 features (จาก session + ประวัติผู้ใช้)
      → ประเมินความเสี่ยง 4 ชั้น: (1) Rule (2) Behavior (3) IsolationForest+SHAP (4) รวมคะแนน
      → ตัดสินใจ: allow / MFA step-up / block
      → บันทึก audit + login_sessions → แสดงบน Dashboard (สถิติเสี่ยง + SHAP)
      → ถ้า allow: Hub ออก JWT (RS256) ให้ระบบย่อย (หอพัก/ห้องสมุด)
```
*(ดูแผนภาพประกอบในแชต — central_auth_hub_rba_overview)*

---

## §7 — เหตุผลเลือก Isolation Forest deploy (ทั้งที่ OCSVM ได้คะแนนสูงกว่า)

ผลเปรียบเทียบบน benchmark (10,140 แถว, attack 1.38%):

| Feature set | Model | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|
| C (23) | **OneClassSVM** | 0.705 | **0.963** | **0.844** |
| C (23) | IsolationForest | 0.707 | 0.928 | 0.734 |
| C (23) | LocalOutlierFactor | 0.500 | 0.751 | 0.536 |

**OCSVM ได้ PR-AUC สูงสุด** แต่ระบบ deploy ใช้ **Isolation Forest** เพราะ:
1. **อธิบายผลได้ (Explainability):** SHAP **TreeExplainer** ทำงาน native กับ tree-based model → บอกได้ทันทีว่า feature ใดดันคะแนน (OCSVM ไม่มี tree → อธิบายยาก)
2. **เร็ว เหมาะ real-time:** scoring ระดับ ms ต่อ login
3. **ตรงชื่อโครงงาน** ที่เน้น Isolation Forest โดยใช้ OCSVM/LOF เป็น baseline เปรียบเทียบ

> ในเล่ม ควรเขียน justify จุดนี้ให้ชัด (กรรมการมักถามว่าทำไมไม่ใช้ตัวที่ score สูงสุด) — คำตอบคือ trade-off ระหว่าง accuracy กับ explainability + speed

---

## ภาคผนวก: ตรวจสอบเอกสารบทที่ 3 กับระบบจริง

> ตรวจร่างหัวข้อ 3.5–3.8 ของผู้ใช้กับโค้ดจริง (models.py, routers, services) — สรุปสิ่งที่ถูก/ผิด/ควรแก้

### 3.5 การออกแบบสถาปัตยกรรม — ✅ ถูกแล้ว
แบ่ง 5 ส่วน (Authentication Hub / OAuth/OIDC / Passkey / Risk Engine / Subsystem) เป็น logical grouping ที่ดี ตรงกับ codebase

### 3.5.2 OAuth/OIDC Server — ⚠️ ต้องแก้
ลบ "ออก ID Token" และ "Refresh Token" ออก:
- ระบบใช้ **JWT (RS256)** ตัวเดียวเป็น access token (มี `aud=client_id`) — ไม่ได้ออก ID token แยก
- **ไม่มี Refresh Token** ใน implementation จริง (OIDC discovery ประกาศ `grant_types_supported = ["authorization_code"]` เท่านั้น)
- มี **Token Revocation** (Redis jti blacklist) — ควรเขียนเพิ่ม

**หน้าที่ฉบับแก้:**
- ออก Authorization Code (PKCE)
- ออก Access Token (JWT RS256 + aud claim)
- ตรวจสอบ Token (Introspection endpoint)
- เพิกถอน Token (Revocation via jti blacklist)

### 3.6 การออกแบบฐานข้อมูล — ❌ ต้องแก้ใหญ่ (ชื่อตารางไม่ตรง)

ตารางจริงในระบบ (15 ตาราง, ตามลำดับใน `models.py`):

| ตาราง | คำอธิบาย |
|---|---|
| `users` | ผู้ใช้: google_sub, email, full_name, user_type (student/teacher/staff/admin), identifier, faculty, major, phone, address |
| `subsystems` | ระบบย่อยที่ลงทะเบียน (= "OAuth Clients"): client_id, client_secret_hash, redirect_uris, scope, allowed_roles |
| `access_list` | Whitelist + RBAC: ผู้ใช้คนใดเข้าระบบย่อยใดได้ + role_in_sub (soft-delete ผ่าน revoked_at) |
| `login_sessions` | ทุก login + 23 features + risk_score + risk_breakdown + decision + SHAP (= ข้อมูลความเสี่ยงทั้งหมด) |
| `audit_logs` | กิจกรรมทั้งหมด: actor_id, action, target, ip, metadata |
| `request_logs` | HTTP request log (ทุก method/path/status_code/duration) |
| `passkey_credentials` | WebAuthn credential: credential_id, public_key, sign_count, device_name, transports |
| `passkey_backup_codes` | Recovery code (Argon2id hash, 10 รหัสต่อ user, generation-tracked) |
| `secret_retrieval_tokens` | One-time link สำหรับดู client_secret (HMAC + Fernet) |
| `subsystem_change_requests` | คำขอเปลี่ยน scope/role/redirect ของ subsystem (รอ admin approve) |
| `ml_feedback` | Label ที่ admin ใส่ให้ session (false_positive / true_positive / normal_confirmed) |
| `api_alerts` | Rule-based API anomaly alerts |
| `ip_blacklist` | IP ที่ admin/threat-feed ยืนยันว่าเป็น attacker |
| `app_settings` | runtime configurable settings |

**สำคัญ — ไม่มีตารางเหล่านี้ในเอกสารแต่ระบบจริงมี:** `access_list` (RBAC), `login_sessions` (= risk_events), `passkey_backup_codes`, `request_logs`, `ip_blacklist`, `ml_feedback`

**สำคัญ — มีในเอกสารแต่ระบบจริงไม่มี:** `refresh_tokens` (ตัดทิ้ง), `risk_events` (เปลี่ยนเป็น `login_sessions`)

ดู ER diagram ที่ [diagrams/er-diagram.svg](diagrams/er-diagram.svg)

### 3.7.1 Google OAuth Login — ⚠️ ลำดับใน flow ผิด
เอกสารเขียน `User → Google → Hub → JWT → Subsystem` ทำให้เข้าใจผิดว่า user ไป Google ก่อน

**ลำดับจริง** (user ไม่เคยติดต่อ Google ตรง — Hub redirect ให้):
```
User → Subsystem (กดเข้า)
     → Hub /oauth/authorize (เช็ค PKCE + state)
     → Google OAuth (redirect)
     → Hub /oauth/callback (verify code, รับ email)
     → ตรวจ access_list + RBAC + Risk Engine
     → ออก JWT (aud=client_id)
     → Subsystem (verify JWT ผ่าน JWKS)
```

### 3.7.3 Account Recovery — ✅ ถูกแล้ว
มีจริงทั้ง 3 ช่องทาง: Backup Code (10 รหัส, Argon2id), Email OTP, Passkey Recovery

### 3.8 RBA — ✅ ถูกเกือบหมด เพิ่มแค่:
**3.8.4 Decision** ในระบบจริงมี 4 ระดับ (ไม่ใช่ 3): **allow / warn / challenge(MFA) / block**
- allow: score < 0.40
- warn: 0.40–0.49 (แจ้งเตือนแต่ผ่าน)
- challenge (MFA): 0.50–0.84
- block: ≥ 0.85

หมายเหตุ: ปัจจุบันยังเป็น **Shadow Mode** (decision = `would_*`) ยังไม่ enforce จริง
