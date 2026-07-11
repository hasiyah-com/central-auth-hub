

```markdown
# Terms of Reference (TOR)
**โครงการ:** Central Auth Hub — ระบบการจัดการสิทธิ์ผู้ใช้แบบศูนย์กลางและการจัดการระบบย่อย (Centralized Identity, Permission & Subsystem Management Platform)  
**ประเภทโครงการ:** โครงงานคอมพิวเตอร์ (Senior Project)  
**ระยะเวลาดำเนินการ:** 16 สัปดาห์  

---

## 1. ที่มาและความสำคัญ (Background and Rationale)
ในสถาบันการศึกษาหรือองค์กรขนาดใหญ่ มักมีระบบสารสนเทศย่อยเป็นจำนวนมาก (เช่น ระบบหอพัก, ระบบห้องสมุด) ซึ่งแต่ละระบบมักจะมีระบบจัดการผู้ใช้และการเข้าสู่ระบบแยกกัน (Silos) ส่งผลให้เกิดปัญหาด้านความปลอดภัย ความซ้ำซ้อนของข้อมูล และความยากในการจัดการสิทธิ์ข้ามระบบ 

โครงการ **Central Auth Hub** จึงถูกพัฒนาขึ้นเพื่อเป็นศูนย์กลางการยืนยันตัวตนและจัดการสิทธิ์ (Identity & Access Management: IAM) โดยใช้มาตรฐาน OAuth 2.0 + PKCE พร้อมผสานเทคโนโลยี Machine Learning (Risk-Based Authentication) เพื่อตรวจจับพฤติกรรมการเข้าสู่ระบบที่ผิดปกติ ทั้งนี้ระบบมุ่งเน้นการให้ความสำคัญกับ **การบริหารจัดการวงจรชีวิตของระบบย่อย (Subsystem Lifecycle Management)** และ **การควบคุมสิทธิ์การเข้าถึงอย่างละเอียด (Granular Permission Management)**

## 2. วัตถุประสงค์ของโครงการ (Objectives)
1. เพื่อพัฒนาระบบศูนย์กลางการยืนยันตัวตน (Identity Provider - IdP) ที่รองรับมาตรฐาน OAuth 2.0, OIDC และ PKCE
2. เพื่อพัฒนาระบบจัดการระบบย่อย (Subsystem Management) ที่รองรับการลงทะเบียน การแจกจ่าย Secret แบบปลอดภัย และการหมุนเวียน Secret (Secret Rotation)
3. เพื่อพัฒนาระบบจัดการสิทธิ์ผู้ใช้ (Permission Management) แบบ Fine-grained ผ่าน OAuth Scopes และระบบ Workflow การขอสิทธิ์เข้าใช้งานระบบย่อย (Self-Service Access Request)
4. เพื่อเพิ่มความมั่นคงปลอดภัยด้วยระบบ Risk-Based Authentication (RBA) ด้วย Machine Learning (Isolation Forest) และการประยุกต์ใช้ SHAP เพื่ออธิบายผลการตัดสินใจ
5. เพื่อออกแบบสถาปัตยกรรมแบบไมโครเซอร์วิส (Microservices) ที่แยกส่วนฐานข้อมูลของ Hub และ Subsystems อย่างเป็นอิสระ

## 3. ขอบเขตของระบบ (Project Scope)

### 3.1 ขอบเขตที่อยู่ในความรับผิดชอบ (In-Scope)
*   **Central Auth Hub (Hub):** ระบบหลักที่ทำหน้าที่จัดการผู้ใช้, จัดการระบบย่อย, ตรวจสอบสิทธิ์, และบันทึก Audit Log
*   **Subsystem Management Module:** ระบบสำหรับ Developer ลงทะเบียนระบบย่อย ขอควบคุม Redirect URI, และจัดการ Secret Rotation
*   **Permission & Access Management Module:** ระบบควบคุมสิทธิ์ RBAC ร่วมกับ OAuth Scopes, ระบบ Triage สำหรับคำขอเข้าใช้ระบบย่อย และการเพิกถอนสิทธิ์แบบ Real-time
*   **ML Verifier Module:** ระบบประมวลผลคะแนนความเสี่ยง (4-Layer RBA) แบบ Shadow Mode
*   **Admin Dashboard:** หน้า UI สำหรับ Admin บริหารจัดการระบบทั้งหมด (Next.js)
*   **Subsystem A (ระบบหอพัก) และ Subsystem B (ระบบห้องสมุด):** ระบบย่อยตัวอย่าง (Reference Implementation) เพื่อจำลองการเชื่อมต่อกับ Hub

### 3.2 ขอบเขตที่ไม่อยู่ในความรับผิดชอบ (Out-of-Scope)
*   ไม่รวมการพัฒนาระบบ SSO (Single Sign-On) แบบเซสชั่นรวมศูนย์ (ระบบแต่ละระบบย่อยมี Session ของตนเองแยกกัน)
*   ไม่รวมการใช้งาน Identity Provider อื่นๆ นอกจาก Google OAuth (LINE Login ถูกปิดการใช้งานชั่วคราว)
*   ไม่รวมการ Deploy ขึ้น Production บน Cloud สาธารณะ (ใช้ Docker Compose จำลองบนเครื่อง Local/Server ภายในเท่านั้น)

## 4. รายละเอียดความต้องการของระบบ (Functional Requirements)

### 4.1 การจัดการระบบย่อย (Subsystem Management)
*   **Registration:** นักพัฒนาสามารถลงทะเบียนระบบย่อยได้ พร้อมระบุ `client_id` และ `redirect_uris` (บังคับ Exact-match)
*   **Secret Delivery:** ระบบต้องแจกจ่าย `client_secret` ผ่าน One-time link ที่มีอายุ 15 นาที และเก็บ Hash ด้วย Argon2id
*   **Secret Rotation:** นักพัฒนาและ Admin สามารถสั่งเปลี่ยน Secret ได้ทันที (Invalidate ตัวเก่าทันที)
*   **Health Monitoring:** ระบบ Hub ต้องมี Cron job ตรวจสอบสถานะ (Health Check) ของระบบย่อยทุก 5 นาที และแสดงสถานะ Offline/Online บน Dashboard

### 4.2 การจัดการสิทธิ์ผู้ใช้ (Permission & Access Management)
*   **Whitelist Management:** นักพัฒนาสามารถอัปโหลดรายชื่อผู้ใช้ที่อนุญาต (Whitelist) ผ่าน CSV หรือเพิ่มทีละคนได้
*   **Self-Service Access Request:** ผู้ใช้สามารถกดขอสิทธิ์เข้าใช้ระบบย่อย (Status: Pending) ได้เอง และรอการอนุมัติจากเจ้าของระบบย่อย
*   **Triage Workflow:** หน้าจอสำหรับเจ้าของระบบ/Admin เพื่อพิจารณาคำขอ (Approve/Reject) พร้อมระบุเหตุผล
*   **Granular Scopes:** ระบบรองรับการขอและอนุญาตสิทธิ์แบบเฉพาะเจาะจง (เช่น `dorm:read`, `library:borrow`) และฝังใน JWT Token
*   **Real-time Revocation:** เมื่อ Admin เพิกถอนสิทธิ์ของผู้ใช้ ระบบต้องบล็อกการเข้าถึงทันทีผ่าน Redis Token Blacklist แม้ JWT ยังไม่หมดอายุ

### 4.3 ระบบยืนยันตัวตนและความปลอดภัย (Authentication & Security)
*   **OAuth 2.0 Flow:** รองรับ Authorization Code Flow พร้อม PKCE (บังคับใช้ hmac.compare_digest ป้องกัน Timing Attack)
*   **JWT Security:** ใช้ RS256 (Asymmetric), มีการแยก `aud` (Audience) ระหว่าง Hub และ Subsystem อย่างเคร่งครัด
*   **Risk-Based Authentication (RBA):** 
    *   ประมวลผล 12 Features (Temporal, Geographic, Device, Velocity)
    *   ใช้ Isolation Forest ทำนายความผิดปกติ (ทำงานใน Shadow Mode)
    *   แสดงผล SHAP values เพื่ออธิบายว่า Feature ใดมีผลต่อการตัดสินใจ
*   **Audit Logging:** บันทึก Log แบบ Append-only ทุกการเปลี่ยนแปลงสถานะ ปฏิบัติตามกฎ "Log -> Commit -> Raise"

## 5. ข้อกำหนดทางเทคนิค (Technical Specifications)
*   **Backend:** Python 3.11, FastAPI, SQLAlchemy, Authlib
*   **Frontend (Admin):** Next.js 14 (App Router), TypeScript, Tailwind CSS
*   **Frontend (Subsystem):** Jinja2, Tailwind CSS
*   **Machine Learning:** scikit-learn (Isolation Forest), SHAP (TreeExplainer)
*   **Database & Cache:** PostgreSQL 15, Redis 7
*   **Infrastructure:** Docker Compose (แยกเป็น 3 Stacks: cah-hub, cah-dorm, cah-library)
*   **Security Standards:** OWASP Top 10, NIST SP 800-63B-4, RFC 6749, RFC 7636, RFC 7519

## 6. ผลงานที่คาดว่าจะได้รับ (Deliverables)
1. ซอร์สโค้ดระบบ (Source Code) บน GitHub Repository พร้อม CI/CD และ Pre-commit hooks
2. ชุดติดตั้งระบบผ่าน Docker Compose ที่สามารถรันได้บนเครื่อง Local ด้วยคำสั่งเดียว
3. เอกสาร Database Schema (DBML) และ API Documentation (Swagger/OpenAPI)
4. เอกสารวิทยานิพนธ์ (Thesis Document) ครอบคลุมการวิเคราะห์, การออกแบบสถาปัตยกรรม, ผลการทดสอบระบบ ML และการประเมินความปลอดภัย
5. ชุดข้อมูลจำลอง (Seed Data) สำหรับ ผู้ใช้ 100 คน, ห้องพัก 24 ห้อง, และหนังสือ 30 เล่ม

## 7. แผนการดำเนินงาน (Timeline & Milestones)

| ช่วงเวลา | กิจกรรมหลัก (Milestones) |
| :--- | :--- |
| **สัปดาห์ที่ 1-4** | ออกแบบฐานข้อมูล, สร้าง Hub Backend, เชื่อมต่อ Google OAuth, สร้างระบบลงทะเบียนระบบย่อย |
| **สัปดาห์ที่ 5-8** | พัฒนา OAuth Flow + PKCE, พัฒนา ML Verifier (Shadow mode), พัฒนา Subsystem A & B, สร้าง Admin Dashboard |
| **สัปดาห์ที่ 9-10** | **(Focus)** พัฒนาระบบ Self-Service Access Request, Secret Rotation, ปรับปรุง Granular Scopes, ทำ Real-time Revocation |
| **สัปดาห์ที่ 11-12** | เสริมความปลอดภัย (CSRF, CSP, Rate Limit), ทำ Threat Model, เก็บข้อมูล ML จำลองการโจมตี |
| **สัปดาห์ที่ 13-14** | เขียน Integration Test, ตั้งค่า GitHub Actions CI, ทำ User Acceptance Test (UAT) |
| **สัปดาห์ที่ 15-16** | เขียนเอกสารวิทยานิพนธ์, ทำสไลด์นำเสนอ, ซ้อมสอบ Defend |

## 8. เกณฑ์การประเมินผลความสำเร็จ (Success Criteria)
1. ระบบย่อย A และ B สามารถเข้าสู่ระบบผ่าน Hub ด้วย OAuth 2.0 + PKCE ได้สำเร็จโดยไม่เกิด Error
2. ระบบสามารถตรวจจับพฤติกรรมการ Login ที่ผิดปกติ (เช่น เข้าจาก IP ต่างประเทศในเวลาดึก) และแสดงค่า Anomaly Score และ SHAP ได้ถูกต้อง
3. กระบวนการขอสิทธิ์ (Access Request) และการเพิกถอนสิทธิ์ (Revocation) ทำงานได้แบบ Real-time
4. ผ่านการตรวจสอบช่องโหว่พื้นฐานตาม OWASP Top 10 (เช่น ไม่มี Broken Access Control, ไม่มี Timing Attack)
5. ระบบทดสอบ (Unit Test / Integration Test) ทำงานผ่าน 100% ของฟังก์ชันหลัก
```
