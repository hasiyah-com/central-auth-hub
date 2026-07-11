# คู่มืออธิบายแผนภาพ — บทที่ 3 (18 รูป)

เอกสารนี้อธิบายรายละเอียดของแผนภาพทั้ง 18 รูปที่ใช้ใน [บทที่ 3](../บทที่%203.md) — สำหรับแต่ละรูปจะบอก **สิ่งที่รูปแสดง**, **องค์ประกอบสำคัญที่ควรอ่าน**, **แหล่งอ้างอิงในโค้ดจริง** (ไฟล์/ฟังก์ชันที่ยืนยันความถูกต้องแล้ว) และ **ตำแหน่งที่ถูกอ้างถึงในบทที่ 3.md**

ทุกรูปตรวจสอบแล้วว่าตรงกับโค้ดจริง ณ วันที่ปรับปรุงเอกสาร (ไม่ใช่แค่ตามแผนออกแบบ/เอกสารเก่า) — จุดที่พบว่าเอกสารเก่าไม่ตรงกับโค้ดจริงจะระบุไว้ในหมายเหตุของแต่ละรูป

---

## สารบัญ

| รูป | ชื่อ | หมวด |
|---|---|---|
| [3.1](#รูปที่-31--system-architecture-overview) | System Architecture Overview | สถาปัตยกรรม |
| [3.2](#รูปที่-32--business-architecture) | Business Architecture | สถาปัตยกรรม |
| [3.3](#รูปที่-33--logical-architecture) | Logical Architecture | สถาปัตยกรรม |
| [3.4](#รูปที่-34--component-diagram) | Component Diagram | สถาปัตยกรรม |
| [3.5](#รูปที่-35--subsystem-registration-flow) | Subsystem Registration Flow | Flow |
| [3.6](#รูปที่-36--access-policy-flow) | Access Policy Flow | Flow |
| [3.7](#รูปที่-37--deployment-diagram) | Deployment Diagram | สถาปัตยกรรม |
| [3.8](#รูปที่-38--database-er-diagram) | Database ER Diagram | ข้อมูล |
| [3.9](#รูปที่-39--authentication-flow) | Authentication Flow | Flow |
| [3.10](#รูปที่-310--oauthoidc-flow) | OAuth/OIDC Flow | Flow |
| [3.11](#รูปที่-311--jwt-verification-flow) | JWT Verification Flow | Flow |
| [3.12](#รูปที่-312--login-sequence-diagram) | Login Sequence Diagram | Flow |
| [3.13](#รูปที่-313--old-vs-new-risk-scoring) | Old vs New Risk Scoring | เปรียบเทียบ |
| [3.14](#รูปที่-314--hybrid-rba-flow) | Hybrid RBA Flow | Flow |
| [3.15](#รูปที่-315--machine-learning-pipeline) | Machine Learning Pipeline | Flow |
| [3.16](#รูปที่-316--feature-engineering-diagram) | Feature Engineering Diagram | ข้อมูล |
| [3.17](#รูปที่-317--passkey--risk-decision-flow) | Passkey + Risk Decision Flow | Flow |
| [3.18](#รูปที่-318--risk-detection--incident-response-flow) | Risk Detection & Incident Response Flow | Flow |

---

## รูปที่ 3.1 — System Architecture Overview

**ไฟล์:** `fig3-1_system_overview.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5 (intro)

**แสดงอะไร:** ภาพรวมทั้งระบบในระดับ system context — องค์ประกอบหลักทั้งหมดในภาพเดียว ไม่ลงรายละเอียดภายใน

**องค์ประกอบ:**
- **User / Admin** (แถวบน) — ผู้เรียกใช้งานสองกลุ่ม
- **Google OAuth** และ **Passkey** (สองฝั่ง) — ช่องทางยืนยันตัวตนภายนอกที่เชื่อมกับ Hub เพียงจุดเดียว
- **Hub** (ตรงกลาง) — ศูนย์กลาง
- **Database / Redis / ML Service** (แถวกลาง) — โครงสร้างพื้นฐานที่ Hub พึ่งพา
- **Subsystem A (หอพัก) / Subsystem B (ห้องสมุด)** (แถวล่าง) — ระบบย่อยทุกระบบที่ลงทะเบียน
- หมายเหตุสีแดงท้ายภาพ: "ไม่ใช่ SSO — แต่ละระบบย่อยมี session ของตนเองแยกจากกัน"

**หมายเหตุความถูกต้อง:** เดิมมีการเสนอ "LINE Login" เป็นอีกช่องทาง แต่ตรวจสอบแล้วว่าปุ่ม frontend ถูก comment out ตั้งแต่ 2026-06-10 (โค้ด backend ยังอยู่แต่ไม่ใช้งานจริง) — รูปนี้จึงแสดงเฉพาะ Google OAuth

---

## รูปที่ 3.2 — Business Architecture

**ไฟล์:** `fig3-2_business_architecture.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5

**แสดงอะไร:** มุมมองสถาปัตยกรรมเชิงธุรกิจ (business capability) — ระบบแบ่งความรับผิดชอบเป็น 4 กลุ่มเรียงตามลำดับกระบวนการหลัก พร้อมลูกศรวนกลับแสดง feedback loop

**องค์ประกอบ (4 กล่อง, วนตามเข็มนาฬิกา):**
1. **Identity & Onboarding** — อาจารย์/เจ้าหน้าที่/ผู้ดูแลระบบ ลงทะเบียน subsystem, ผู้ใช้ยืนยันตัวตน
2. **Access Governance** — ผู้ดูแลระบบ อนุมัติ subsystem + จัดการ whitelist/policy
3. **Risk & Trust Management** — ทำงานอัตโนมัติผ่าน Hybrid RBA
4. **Business Operations & Compliance** — ผู้ใช้ปลายทางจองห้อง/ยืมหนังสือ + audit log

**ใช้ยังไง:** เป็น "แผนที่" อธิบายว่าใครรับผิดชอบส่วนไหน ก่อนจะลงรายละเอียดทางเทคนิคในหัวข้อถัดๆ ไป

---

## รูปที่ 3.3 — Logical Architecture

**ไฟล์:** `fig3-3_logical_architecture.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5

**แสดงอะไร:** การแบ่งชั้นเชิงตรรกะของทั้งระบบ (ไม่ผูกกับรายละเอียดการ deploy จริง — ดูการ deploy จริงที่รูป 3.7)

**องค์ประกอบ (4 ชั้นหลัก + 1 แถบข้าง):**
- **Presentation Layer** — Admin Console (Next.js), Subsystem Web UI
- **API/Integration Layer** — OAuth2/OIDC Endpoints, REST API, WebAuthn API
- **Application Services Layer** — Identity & Auth Service, Hybrid RBA, Developer Portal, Business Logic
- **Data Layer** — hub_db, dorm_db/library_db, Redis, ML Model Store
- **Security** (แถบขวา, cross-cutting) — JWT/PKCE, Audit Log, Rate Limiting ครอบทุกชั้น

---

## รูปที่ 3.4 — Component Diagram

**ไฟล์:** `fig3-4_component_diagram.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5.1, 3.5.5

**แสดงอะไร:** แผนภาพคอมโพเนนต์ตาม UML รวม Hub และระบบย่อยไว้ในภาพเดียว แสดง interface ที่แต่ละฝั่งพึ่งพากัน

**องค์ประกอบ:**
- **Hub Backend** (กรอบซ้าย) — AuthController, OAuthController, AdminController, JWTService, RBAEngine, AuditService, PKCEService, DeveloperCtl, MLClient
- **ML Verifier Service** (กรอบขวาบน, «external system») — IsolationForest component, เชื่อมจาก MLClient ผ่าน «call» IScoreAPI
- **Subsystem App** (กรอบล่าง) — SubsystemRouter, HubClient, SessionService, AuditService
- วงกลมเล็ก (lollipop) = provided interface, เส้นประ = dependency

**อ่านยังไง:** `HubClient` ของระบบย่อยเรียกใช้ `IOAuthAPI` ที่ Hub เปิดให้ (เส้นประซ้าย) ส่วน `MLClient`/`RBAEngine` ใน Hub เรียก `IScoreAPI` ของ ML Verifier (เส้นประขวา) — แสดงว่า Hub เองก็เป็น "client" ของอีกระบบหนึ่งเช่นกัน

---

## รูปที่ 3.5 — Subsystem Registration Flow

**ไฟล์:** `fig3-5_subsystem_registration_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5.6

**แสดงอะไร:** ขั้นตอนตั้งแต่นักพัฒนาลงทะเบียนระบบย่อยจนถึงเริ่มใช้งานจริง — flowchart 7 ขั้น

**ขั้นตอน:**
1. นักพัฒนา submit คำขอ — **ต้องผ่าน step-up MFA ก่อน** (ไม่ใช่แค่ login ธรรมดา)
2. Hub ตรวจสอบ scope (ต้องอยู่ใน `ALLOWED_SCOPES`) + validate access policy config
3. สร้าง `client_id`/`client_secret` (Argon2id hash) + roster API key แยกต่างหาก
4. บันทึกด้วย `status=pending` + one-time secret retrieval token (HMAC, TTL 15 นาที)
5. ส่ง URL ดู secret กลับให้นักพัฒนา (ดูได้ครั้งเดียว)
6. ผู้ดูแลระบบอนุมัติ/ปฏิเสธ → แยกเป็น 2 กิ่ง (active / rejected)
7. Runtime — เมื่อ active แล้ว ใช้ OAuth flow จริง (รูป 3.10) + ดึง roster ผ่าน API

**แหล่งอ้างอิงโค้ด:** `hub/backend/app/routers/developer.py::register_subsystem()` (บรรทัด 227-320) — ยืนยันแล้วว่ามี step-up gate (`_stepup_gate("subsystem_register")`) จริง ไม่ใช่แค่ในเอกสาร

---

## รูปที่ 3.6 — Access Policy Flow

**ไฟล์:** `fig3-6_access_policy_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5.7

**แสดงอะไร:** กลไกควบคุมว่าใครเข้าระบบย่อยได้บ้าง — รองรับ 4 รูปแบบ ไม่ใช่แค่ whitelist อย่างเดียว

**องค์ประกอบ:**
- **4 กล่อง policy** (แถวบน): `explicit` (default, whitelist ใน access_list), `all` (ทุก active user), `role` (ตาม user_type ใน config), `attribute` (ABAC เทียบ faculty/major)
- **deny-list** (กล่องแดง) — ทับทุก policy เสมอ ใช้ ban รายคน
- **evaluate_access_policy()** (กล่องกลาง) — จุดตัดสินใจเดียวที่ทั้ง login-time และ roster sync เรียกใช้ร่วมกัน
- **① Runtime check** — ผ่าน/ไม่ผ่าน แยกกิ่ง allow/deny
- **② Roster Sync** — subsystem ดึงรายชื่อล่วงหน้าผ่าน `GET /api/v1/roster` (S2S)
- **③ เพิกถอนสิทธิ์** — soft delete, มีผลตั้งแต่ครั้งถัดไป

**แหล่งอ้างอิงโค้ด:** `hub/backend/app/services/access_policy.py` (ทั้งไฟล์ 147 บรรทัด) — ฟังก์ชัน `evaluate_access_policy()` และ `list_allowed_users()` คือ single source of truth ตามคอมเมนต์ในโค้ดเอง (บรรทัด 12)

**หมายเหตุความถูกต้อง:** นี่คือจุดที่ต่างจาก draft outline เดิมมากที่สุด — ของเดิมพูดถึงแค่ "Open Access" กับ "Restricted Access" (2 แบบ) แต่โค้ดจริงมี 4 แบบ (เพิ่ม role/attribute ในสัปดาห์ที่ 11)

---

## รูปที่ 3.7 — Deployment Diagram

**ไฟล์:** `fig3-7_deployment_diagram.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.5.8

**แสดงอะไร:** การติดตั้งระบบจริงบน infrastructure จริง (ไม่ใช่ logical view แบบรูป 3.3)

**องค์ประกอบ:**
- **Internet → Nginx** — reverse proxy รับ HTTPS (443), terminate TLS ด้วย Let's Encrypt, route ตาม subdomain (admin./auth./dorm./library.)
- **Docker network `cah-net`** (กรอบประใหญ่) — ไม่มีพอร์ตเปิดสู่ public โดยตรง
  - **Stack cah-hub** — hub-frontend, hub-backend, ml-service, PostgreSQL, Redis, volume `hub_jwt_keys`
  - **Stack cah-dorm** / **cah-library** — subsystem + PostgreSQL ของตัวเอง
- **Google OAuth** (กรอบประด้านล่าง, external) — เชื่อมจาก hub-backend เท่านั้น

**หมายเหตุความถูกต้อง:** ยืนยันจาก `docs/guides/DEPLOYMENT.md` แล้วว่าเป็น **VM เดียว** จริง ("VM เดียว + Let's Encrypt + nginx + 4 subdomains") — draft outline เดิมเสนอ 3 VM แยกกัน (Hub/Subsystem A/Subsystem B) ซึ่ง**ไม่ตรงกับการติดตั้งจริงปัจจุบัน** (เป็นแค่ทางเลือกสำหรับอนาคตถ้าจะแยก production จริง)

---

## รูปที่ 3.8 — Database ER Diagram

**ไฟล์:** `fig3-8_database_er_diagram.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.6.1, 3.6.2

**แสดงอะไร:** ความสัมพันธ์ของฐานข้อมูลทั้งหมดในระบบรวมกันภาพเดียว — ทั้ง Hub และระบบย่อย

**องค์ประกอบ:**
- **โซนบน (Hub Database — hub_db)** — 4 ตารางหลัก: `users`, `subsystems`, `access_list`, `login_sessions` พร้อมเส้นแสดง FK ที่ผูกกับ `users` เป็นศูนย์กลาง
- **โซนล่าง (Subsystem Databases)** — `dorm_db` (rooms, residents, reservations) และ `library_db` (books, members, borrowings)
- **เส้นประแดง** เชื่อมระหว่างสองโซน พร้อม label "hub_user_id (UUID) — ไม่มี FK ข้ามฐานข้อมูล" — แสดงว่าความสัมพันธ์นี้เป็นแค่ตรรกะ ไม่ใช่ FK จริงในระดับ DB

**ใช้คู่กับ:** ตาราง data dictionary เต็มในหัวข้อ 3.6.1-3.6.2 ของบทที่ 3.md (รูปนี้แสดงเฉพาะ field สำคัญ)

---

## รูปที่ 3.9 — Authentication Flow

**ไฟล์:** `fig3-9_authentication_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.7 (intro)

**แสดงอะไร:** flowchart ระดับสูงของการเลือกวิธียืนยันตัวตน จนถึงจุดที่ทุกวิธีมาบรรจบกัน

**เส้นทาง:** เริ่ม "กดเข้าสู่ระบบ" → เลือกวิธี (Google OAuth / Passkey) → "Hub ตรวจสอบสำเร็จ" → RBAC + access_list (รูป 3.6) → Risk Engine (รูป 3.14) → ตัดสินใจ 3 ทาง:
- **allow** (เขียว) → ออก JWT + session
- **mfa** (เหลือง) → Step-up (รูป 3.17)
- **block** (แดง) → บันทึก audit log

**ต่างจากรูป 3.12 ยังไง:** รูปนี้เป็น flowchart แนวคิด (ไม่มีลำดับเวลา/actor ชัดเจน) ส่วนรูป 3.12 เป็น sequence diagram แสดง actor และลำดับเวลาจริง

---

## รูปที่ 3.10 — OAuth/OIDC Flow

**ไฟล์:** `fig3-10_oauth_oidc_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.7.1

**แสดงอะไร:** sequence diagram ระดับโปรโตคอลของ OAuth 2.0 + PKCE เต็มรูปแบบ — 12 ขั้นตอน, 4 lifeline (ผู้ใช้, ระบบย่อย, Hub, Google)

**จุดสำคัญที่ควรสังเกต:**
- ขั้นที่ 2: ระบบย่อยสร้าง PKCE เอง (`code_verifier`/`code_challenge`) — ไม่ใช่ Hub สร้างให้
- ขั้นที่ 7-8: จุดที่ access_list/policy check (รูป 3.6) และ Risk Engine (รูป 3.14) ถูกเรียก — แทรกอยู่กลาง flow ไม่ใช่ท้าย flow
- ขั้นที่ 9: ใช้ Redis `getdel` แบบ atomic กัน race condition (auth_code ใช้ซ้ำไม่ได้)
- ขั้นที่ 12: การตรวจสอบ JWT ฝั่งระบบย่อย — รายละเอียดเต็มอยู่ในรูป 3.11

---

## รูปที่ 3.11 — JWT Verification Flow

**ไฟล์:** `fig3-11_jwt_verification_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.7.2

**แสดงอะไร:** ขยายความขั้นที่ 12 ของรูป 3.10 — Hub ออก JWT อย่างไร และระบบย่อยตรวจสอบอย่างไรก่อนเชื่อ

**องค์ประกอบ:**
- **Hub ออก JWT** — RS256, header `kid` (รองรับ key rotation), บันทึก `jti` ลง `login_sessions`
- **ระบบย่อยดึง JWKS** — `GET /.well-known/jwks.json`, cache 10 นาที, match ด้วย `kid`
- **pyjwt.decode(...)** — บังคับ `verify_aud/iss/exp = True` — กัน **audience confusion** (บั๊ก B4 ในเอกสารบั๊ก)
- **Hub ตรวจ jti blacklist** (ขนาน) — รองรับ force-revoke ก่อนหมดอายุจริง
- **Diamond ตัดสินใจ** → ผ่าน (สร้าง session) / ไม่ผ่าน (401)

**แหล่งอ้างอิงโค้ด:** `hub/subsystem-dorm/app/services/hub_client.py::verify_hub_jwt()` (บรรทัด 127-153) — ยืนยันตรงกับโค้ดจริงทุกขั้นตอน

---

## รูปที่ 3.12 — Login Sequence Diagram

**ไฟล์:** `fig3-12_login_sequence_diagram.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.7.5

**แสดงอะไร:** สรุปรวมทุกวิธียืนยันตัวตนเป็น sequence diagram เดียว พร้อม UML `alt` fragment แสดง 3 ทางออกที่เป็นไปได้

**องค์ประกอบ:**
- ขั้นที่ 1-6: เหมือนรูป 3.10 แต่ย่อให้กระชับ (ใช้ actor "Google" แทนรายละเอียด PKCE)
- **alt fragment** (กรอบล่าง) แบ่ง 3 กรณีตามผลการประเมิน:
  - `[allow]` risk < 0.50 — แลก JWT ทันที
  - `[mfa]` 0.50 ≤ risk < 0.85 — redirect ไป risk-stepup (รูป 3.17) แล้ววนกลับ allow
  - `[block]` risk ≥ 0.85 — ปฏิเสธ + audit log

**ใช้เป็น:** จุดปิดท้ายของหัวข้อ 3.7 ที่เชื่อมทุก sub-flow (OAuth, JWT verify, RBA, step-up) เข้าด้วยกันเป็นภาพเดียว

---

## รูปที่ 3.13 — Old vs New Risk Scoring

**ไฟล์:** `fig3-13_old_vs_new_comparison.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.8 (intro)

**แสดงอะไร:** เปรียบเทียบระบบประเมินความเสี่ยง **ก่อน** (single ML score) กับ **หลัง** (Hybrid RBA 4 ชั้น) — อธิบายเหตุผลว่าทำไมถึงเปลี่ยน

**คอลัมน์ซ้าย (ระบบเดิม, ก่อน Week 5):**
1. สกัด feature 12 ตัว
2. เรียก ml-service ครั้งเดียว (Isolation Forest ล้วน)
3. Threshold ตรงๆ บนคะแนนเดียว: ≥0.70→block, ≥0.40→mfa, else→pass
4. IP blacklist แยกอิสระ ไม่ผูกกับคะแนน
→ ผลลัพธ์: black box, false positive สูง

**คอลัมน์ขวา (ระบบใหม่, ปัจจุบัน):**
1. สกัด feature 23 ตัว (ขยายจาก 12)
2. Layer 1 Rule Engine → 3. Layer 2 Behavior Profiling → 4. Layer 3 Isolation Forest (cap 0.4) → 5. Layer 4 Risk Aggregator
→ ผลลัพธ์: explainable (SHAP), FPR ลดจาก 24% → 5.8%

**แหล่งอ้างอิงโค้ด:** เปรียบเทียบจาก commit ที่แนะนำ Hybrid RBA (`cf9da9d`) กับโค้ด `ml-service` ก่อนหน้านั้น — threshold เดิม (0.70/0.40) และ flow เดิม (เรียก ml-service ตรงๆ ไม่มี Rule Engine/Behavior Profiling) ยืนยันจากซอร์สโค้ด `oauth.py`/`ml_client.py` ก่อน commit ดังกล่าว

---

## รูปที่ 3.14 — Hybrid RBA Flow

**ไฟล์:** `fig3-14_hybrid_rba_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.8 (main)

**แสดงอะไร:** รายละเอียดการทำงานของ Hybrid RBA 4 ชั้นที่ใช้งานจริงปัจจุบัน

**องค์ประกอบ (แนวตั้ง):**
1. Login → สกัด Feature 23 ตัว
2. **Layer 1 — Rule Engine** → risk₁ (0.0-1.0), อาจ hard block ทันที
3. **Layer 2 — Behavior Profiling** → risk₂ (0.0-1.0), เทียบ baseline 30 วัน
4. **Layer 3 — Isolation Forest** → risk₃ (0.0-0.4, cap ไว้ไม่ให้ครอบงำ), เรียก ml-service
5. **Layer 4 — Risk Aggregator** → total = risk₁+risk₂+risk₃ (cap 1.0)
6. **4 กล่องผลลัพธ์:** allow (&lt;0.50) / warn (0.50-0.69) / challenge (0.70-0.84) / block (≥0.85)

**แหล่งอ้างอิงโค้ด:** `hub/backend/app/security/risk_aggregator.py::THRESHOLDS` (บรรทัด 19-23) ยืนยันค่า 0.85/0.70/0.50 ตรงกับที่ใช้ในการ calibrate จริง (ไม่ใช่ 0.30/0.70 ตามที่ draft บางฉบับเคยเข้าใจผิด — นั่นคือ threshold ตัวเก่าก่อน calibrate)

---

## รูปที่ 3.15 — Machine Learning Pipeline

**ไฟล์:** `fig3-15_ml_pipeline.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.9 (intro)

**แสดงอะไร:** ขั้นตอนการพัฒนาโมเดล ML ตั้งแต่สร้างข้อมูลจนถึงให้บริการจริง พร้อมวงจร retrain

**ขั้นตอน (7 ขั้น เรียงแนวตั้ง):**
1. Synthetic Data Generation — `generate_data.py` (seed=42), 6 รูปแบบ anomaly จำลอง
2. Preprocessing — ลบซ้ำ, จัดการค่าขาดหาย, แปลงข้อความเป็นตัวเลข
3. Feature Engineering — 23 features/12 หมวด (รูป 3.16)
4. Train — Isolation Forest → `iforest_v1.pkl`
5. Evaluate — ROC-AUC, confusion matrix (ผลจริง AUC=0.9946)
6. Explain — SHAP TreeExplainer
7. Serve — ml-service `/v1/score`
- เส้นประขวา วนกลับจาก step 7 ไป step 1: "Retrain เมื่อ feature เปลี่ยน / มีข้อมูลจริงสะสม"

**หมายเหตุความถูกต้อง:** จุดเริ่มต้นคือ **synthetic data** ไม่ใช่ raw log จริง (ระบบยังไม่มีข้อมูล login สะสมมากพอ) — สำคัญที่ต้องระบุชัด ไม่งั้นจะเข้าใจผิดว่าโมเดลเทรนจากข้อมูลจริง

---

## รูปที่ 3.16 — Feature Engineering Diagram

**ไฟล์:** `fig3-16_feature_engineering_diagram.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.9.3

**แสดงอะไร:** taxonomy ของ feature ทั้ง 23 ตัว จัดกลุ่มเป็น 12 หมวด (grid 4×3)

**12 หมวด:** Temporal(3), Geographic(3), Device(2), Velocity(2), Brute-force(1), Passkey/Device Trust(4), Session(2), Behavioral(1), OAuth scope(1), Privilege(2), History(1), GeoVelocity(1) = รวม 23

**แหล่งอ้างอิงโค้ด:** `ml-service/app/features.py::FEATURE_NAMES` ตรวจนับแล้วครบ 23 ตัวจริง — ตัวเลขนี้สำคัญเพราะ draft outline บางฉบับนับผิดเป็น 21 (ขาด `impossible_travel_score` กับ `ever_changed_permission`)

**ข้อควรระวังเวลาแก้ไข:** ลำดับ 23 ตัวนี้คือ "ข้อตกลงร่วม" ระหว่าง Hub (`rule_engine.py::FEAT`) กับ ML Verifier (`features.py::FEATURE_NAMES`) — สลับลำดับแม้ตัวเดียวทำให้คะแนนผิดทันที (บั๊ก B27/B49 ในเอกสารบั๊ก)

---

## รูปที่ 3.17 — Passkey + Risk Decision Flow

**ไฟล์:** `fig3-17_passkey_risk_decision_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.10 (main)

**แสดงอะไร:** เมื่อ Hybrid RBA ตัดสิน "mfa/challenge" จะเกิดอะไรขึ้นต่อ — ครอบคลุมทั้ง Passkey step-up และเส้นทาง block

**เส้นทางหลัก:**
1. ผลรวมคะแนนจาก Hybrid RBA → diamond "ระดับความเสี่ยง"
2. **allow** (&lt;0.50) → เข้าสู่ระบบสำเร็จ
3. **mfa** (0.50-0.84) → `risk_challenge.mint()` (Redis one-time token, atomic) → redirect `/auth/passkey/risk-stepup` → diamond เลือกวิธี → **Passkey** (challenge→biometric→เซ็น→verify signature+sign_count) หรือ **Email OTP** (fallback ถ้าอุปกรณ์ไม่รองรับ) → ยืนยันสำเร็จ → consume token → ออก JWT
4. **block** (≥0.85) → ปฏิเสธทันที ไม่ผ่าน step-up เลย → audit log

**จุดสังเกต:** มีคำอธิบาย "ตรวจ sign_count ย้อนกลับ → สัญญาณ credential ถูก clone" กำกับไว้ข้างกล่อง Passkey — เป็นกลไกความปลอดภัยเสริมที่มักถูกมองข้าม

---

## รูปที่ 3.18 — Risk Detection & Incident Response Flow

**ไฟล์:** `fig3-18_incident_response_flow.svg` · **อ้างถึงในบทที่ 3.md:** หัวข้อ 3.10.1

**แสดงอะไร:** วิธีที่ผู้ดูแลระบบสืบสวนและตอบสนองต่อ session ที่มีความเสี่ยง — จากผลของ RBA จนถึงการลงมือแก้ไข (ตรงกับหน้าจอ "Incident Detail" ใน Admin Console)

**3 เฟส:**

**เฟส 1 — Detection:** ทุก login ที่ผ่าน Hybrid RBA (รูป 3.14) บันทึก `risk_score`/`decision`/`risk_breakdown` (รวม SHAP) ลง `login_sessions` คู่กับ `audit_logs` ที่เกี่ยวข้อง — **ไม่มีตาราง incident แยก** ทุกอย่าง derive สด

**เฟส 2 — Triage:**
- `GET /admin/incidents` คัดกรอง session ที่ `decision ∈ {block, would_block, challenge, would_challenge, mfa, would_mfa}` หรือมาจาก IP โจมตี
- `GET /admin/incidents/{id}` ประกอบรายงาน: severity (จาก risk_score), incident ID (`INC-YYYY-MM-DD-seq`), สรุป WHY/WHAT/WHAT-TO-DO, Attack Path (Internet → ช่องทางเข้า → Central Auth Hub → เป้าหมาย → ผลลัพธ์)

**เฟส 3 — Remediation** (ต้องผ่าน step-up gate เดียวกับหัวข้อ 3.5.6):
- `revoke_session` — เพิกถอน jti (เชื่อมกับกลไกรูป 3.11)
- `block_ip` — เพิ่มเข้า blacklist
- `reset_passkey` — บังคับลงทะเบียนใหม่
- `notify_user` — แจ้งเตือนอีเมล
- ทุก action บันทึกกลับเข้า `audit_logs` (`incident_action_{action}`) → กลายเป็นข้อมูลสำหรับสืบสวนครั้งถัดไป

**แหล่งอ้างอิงโค้ด:**
- `hub/backend/app/services/incident_service.py` (663 บรรทัด — ทั้งฟีเจอร์)
- `hub/backend/app/routers/admin.py:2683-2753` (3 endpoints)
- `hub/frontend/app/(console)/incidents/` (list page + detail modal)

**หมายเหตุความถูกต้อง:** severity thresholds (critical≥0.85, high≥0.70, medium≥0.50) ตรงกับ `risk_aggregator.py` เป๊ะ — ยืนยันว่า UI ไม่ได้ใช้เกณฑ์แยกของตัวเอง

---

## ตารางสรุปการอ้างอิงโค้ดหลัก

| รูป | ไฟล์โค้ดหลักที่ยืนยันความถูกต้อง |
|---|---|
| 3.5 | `hub/backend/app/routers/developer.py::register_subsystem()` |
| 3.6 | `hub/backend/app/services/access_policy.py` |
| 3.7 | `docs/guides/DEPLOYMENT.md` |
| 3.10, 3.11 | `hub/subsystem-dorm/app/services/hub_client.py::verify_hub_jwt()` |
| 3.13, 3.14 | `hub/backend/app/security/risk_aggregator.py`, `rule_engine.py`, `risk_engine.py` |
| 3.15, 3.16 | `ml-service/app/features.py`, `ml-service/scripts/generate_data.py` |
| 3.17 | `hub/backend/app/routers/auth.py` (risk-stepup endpoints) |
| 3.18 | `hub/backend/app/services/incident_service.py`, `hub/backend/app/routers/admin.py` |
