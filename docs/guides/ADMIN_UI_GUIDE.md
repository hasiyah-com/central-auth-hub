# คู่มือหน้าจอ Admin UI (Hub Frontend)

เอกสารนี้อธิบายทุกหน้าใน Hub Admin Console (`hub/frontend/app/(console)/*`) และ Developer Portal
(`hub/frontend/app/(developer)/*`) — แต่ละหน้าคืออะไร ทำอะไรได้บ้าง และปุ่ม/ส่วนประกอบสำคัญแต่ละอันใช้ทำอะไร เพื่ออะไร

โครงสร้างต่อหน้า:
- **คืออะไร** — หน้านี้มีไว้ทำอะไร
- **ทำอะไรได้บ้าง** — action หลักที่ทำได้ในหน้านี้
- **ปุ่ม/ส่วนประกอบสำคัญ** — รายละเอียดแต่ละปุ่ม/บล็อก
- **ข้อมูลที่แสดง** — field/สถิติที่ปรากฏ

> หมายเหตุ: การกระทำที่มีผลกระทบสูง (revoke, force-logout, ลบผู้ใช้, rotate secret, ระงับ subsystem ฯลฯ)
> ทุกอันต้องผ่าน **step-up ด้วย Passkey** (`mutateWithStepup`) — ถ้า backend ตอบ `403 stepup_required`
> จะเด้ง popup ให้ยืนยันตัวตนก่อน retry request เดิมอัตโนมัติ

---

## ภาพรวมเมนู (Admin Console)

| หน้า | Route | สรุป 1 บรรทัด |
|---|---|---|
| Dashboard | `/` | ศูนย์เฝ้าระวังรวม (SOC) — KPI + แผนที่ auth + สถานะระบบย่อย |
| ผู้ใช้งาน | `/users` | รายชื่อผู้ใช้ทั้งหมด + ค้นหา/กรอง/เพิ่ม |
| User 360° View | `/users/[id]` | รายละเอียดผู้ใช้ 1 คนแบบครบวงจร |
| ระบบย่อย | `/subsystems` | รายชื่อ subsystem ทั้งหมด + อนุมัติ/ปฏิเสธด่วน |
| รายละเอียดระบบย่อย | `/subsystems/[id]` | จัดการ subsystem 1 ระบบแบบเต็ม (admin มุมมอง) |
| คำขอรออนุมัติ | `/subsystems/pending` | หน้าอนุมัติ subsystem ใหม่แบบละเอียด |
| การเข้าใช้งาน (Realtime) | `/activity` | feed การ login สด ทุกระบบ |
| Audit Log | `/audit` | log ทุกการกระทำในระบบ (ค้นหา/กรองได้) |
| ML / ความผิดปกติ | `/ml` | ภาพรวมคะแนนความเสี่ยงจาก 4-Layer RBA |
| Threshold Tuning | `/ml/threshold` | จำลองผลถ้าเปลี่ยนค่า threshold block/mfa |
| ประวัติ ML ผู้ใช้ | `/ml/users/[id]` | ประวัติ session + score ของผู้ใช้ 1 คน |
| IP Blacklist | `/ip-blacklist` | จัดการ IP ที่ถูกขึ้นบัญชีดำ |
| API Alerts | `/api-alerts` | แจ้งเตือนพฤติกรรม API ผิดปกติ (rule-based) |
| Incidents | `/incidents` | triage เหตุการณ์เสี่ยง + one-click remediation |
| แจ้งเตือนทั้งหมด | `/notifications` | ศูนย์รวมแจ้งเตือนทุกประเภท + diagnostic |
| บัญชีของฉัน | `/account` | จัดการ Passkey / Backup codes ของ admin เอง |

Developer Portal (สำหรับ teacher/staff/admin ที่ลงทะเบียน subsystem เอง):

| หน้า | Route | สรุป 1 บรรทัด |
|---|---|---|
| บัญชีของฉัน | `/developer/account` | เหมือน `/account` (component เดียวกัน) |
| ระบบของฉัน | `/developer/subsystems` | รายชื่อ subsystem ที่ตัวเองเป็นเจ้าของ |
| ลงทะเบียนระบบย่อย | `/developer/subsystems/new` | ฟอร์มลงทะเบียน subsystem ใหม่ |
| รายละเอียดระบบย่อย | `/developer/subsystems/[id]` | จัดการ subsystem ของตัวเอง (มุมมอง developer) |

---

# 1. Dashboard — `/`

**คืออะไร:** หน้าแรกของ Admin Console ธีม "SOC" (navy/cyan) — ศูนย์เฝ้าระวังการยืนยันตัวตนทั้งระบบ รวม KPI, แผนที่ auth แบบ globe 3D, สถานะ subsystem, และการตั้งค่าวิธี login

**ทำอะไรได้บ้าง:**
- ดูภาพรวมผู้ใช้/subsystem/login/block ทั้งหมดแบบเรียลไทม์ (auto-poll ทุก 30 วินาที)
- สั่งตรวจสุขภาพระบบทั้งหมดทันที (Hub + ทุก subsystem)
- ดูแผนที่ geo ของ login 30 วันล่าสุด + สถานะ health ของแต่ละ subsystem
- ดูสัดส่วนผลตัดสิน RBA (allow/watch/block) 30 วัน
- เปิด/ปิดวิธี login ของทั้งระบบ (Google / Passkey)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **🩺 เช็คสุขภาพระบบ** — เรียก `POST /admin/subsystems/health/emit-summary-now` ยิง health check ไปทุก subsystem ทันที (ปกติมี cron รันเอง) ผลลัพธ์ขึ้นแบนเนอร์เขียว "✓ ตรวจเสร็จ" พร้อมลิงก์ไปหน้า notifications ดูรายละเอียด
- **sessions online (มุมขวาบน)** — ตัวเลข active session รวมทุกระบบ พร้อมจุดกะพริบ
- **แบนเนอร์แจ้งเตือน (amber)** — ปรากฏเมื่อมี unread notification > 0 พร้อม chip แยกตามหมวด (คำขอ approve / ML anomaly / API alert / subsystem ล่ม) คลิกไปหน้า `/notifications`
- **KPI strip 6 ช่อง** — ผู้ใช้ทั้งหมด, นักศึกษา, บุคลากร (teacher+staff+admin รวม), ระบบย่อย active, Login ทั้งหมด, ถูกบล็อก
- **แผนที่การยืนยันตัวตน (AuthTopologyMap)** — globe 3D (amCharts 5, orthographic projection) แสดงจุดเข้าใช้งานตามประเทศ (สีเขียว/เหลือง/แดงตามระดับความเสี่ยง) เส้นเชื่อม Hub↔subsystem (สีน้ำเงิน) ลากเมาส์เพื่อหมุนโลกได้ Thailand ไฮไลต์ด้วยขอบ cyan
- **การเชื่อมต่อระบบย่อย (side panel)** — รายชื่อ subsystem active ทุกตัว พร้อมจุดสี (เขียว=online/เหลือง=degraded/แดง=down) และ latency (ms) — คลิกแถวไปหน้ารายละเอียด subsystem นั้น
- **ผลตัดสิน RBA (side panel)** — stacked bar 3 สี (allow/watch/block) 30 วัน + ตัวเลข/เปอร์เซ็นต์แต่ละกลุ่ม พร้อมลิงก์ "ดูรายละเอียด ML →"
- **วิธีการเข้าสู่ระบบ (Login Methods card, ล่างสุด)** — สลับเปิด/ปิด **Passkey** และ **Google** เป็นวิธี login ที่ระบบอนุญาต ต้องเปิดอย่างน้อย 1 วิธี ปุ่ม **"บันทึก + ตัด session ทั้งหมด"** เป็น critical action (step-up) — เมื่อบันทึกจะ **ตัด session ที่เปิดอยู่ทุกอันในทุก subsystem ทันที** เพื่อบังคับให้ทุกคน login ใหม่ตามนโยบายล่าสุด ปุ่ม **"ยกเลิก"** ปรากฏเมื่อมีการแก้ไขค้างอยู่ (คืนค่าเดิม)

**ข้อมูลที่แสดง:** จำนวนผู้ใช้แยกประเภท, สถานะ/latency ของแต่ละ subsystem, จำนวน session online, สัดส่วน decision (allow/watch/block), แหล่งที่มา login ตามประเทศ

---

# 2. ผู้ใช้งาน — `/users`

**คืออะไร:** ตารางรายชื่อผู้ใช้ทั้งหมดในระบบ (100+ คน seed จาก Google OAuth) จุดเริ่มต้นค้นหา/จัดการผู้ใช้

**ทำอะไรได้บ้าง:**
- ค้นหา/กรองผู้ใช้ตามประเภท (student/teacher/staff/admin) และคณะ
- เพิ่มผู้ใช้ใหม่ด้วยมือ (ไม่ผ่าน Google OAuth)
- คลิกแถวเพื่อไปหน้า User 360° View ของคนนั้น

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **ตัวกรอง "ทุกประเภท"** — dropdown เลือก student/teacher/staff/admin
- **ช่อง "กรองตามคณะ…"** — พิมพ์ค้นหา faculty แบบ text
- **+ เพิ่มผู้ใช้** — เปิด `UserFormModal` โหมด create กรอกอีเมล/ชื่อ/ประเภท/คณะ ฯลฯ ด้วยมือ (ไม่ใช่ flow login ปกติ)
- **แถวในตาราง** — คลิกทั้งแถวเพื่อไปหน้า `/users/[id]` (User 360° View) ของผู้ใช้นั้น

**ข้อมูลที่แสดง:** ชื่อ+อีเมล, ประเภทผู้ใช้ (badge สี), รหัส (student_id/employee_id), คณะ, สาขา/ตำแหน่ง, สถานะบัญชี (active/suspended/graduated/resigned/deleted — badge สี)

---

# 3. User 360° View — `/users/[id]`

**คืออะไร:** หน้ารายละเอียดผู้ใช้ 1 คนแบบครบวงจร — โปรไฟล์, ความเสี่ยง, สิทธิ์เข้าระบบย่อย, ประวัติ login, Passkey, session ที่ออนไลน์ รวมทุกอย่างที่แต่ก่อนกระจายอยู่หลาย modal ไว้ในหน้าเดียว

**ทำอะไรได้บ้าง:**
- ดูโปรไฟล์เต็ม + risk score ปัจจุบัน + กราฟความเสี่ยงย้อนหลัง (sparkline)
- ให้/ถอนสิทธิ์เข้า subsystem ทีละระบบ
- บังคับ logout ทุกอุปกรณ์, reset passkey, ลบผู้ใช้ (soft delete), แก้ไขข้อมูล/สถานะ
- ดู audit log เฉพาะของผู้ใช้คนนี้ (สิ่งที่เขาทำเอง)
- ดู session ที่ออนไลน์อยู่ตอนนี้ + สรุปสัดส่วน scope ที่มอบให้แต่ละระบบ + ปัจจัยเสี่ยงของ login ล่าสุด

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **🚪 Force Logout ทั้งหมด** (title bar + Quick Actions) — เรียก `POST /admin/users/{id}/force-logout` step-up gate ปิด LoginSession ทุกอันของผู้ใช้นี้ (ทุก subsystem + Hub-direct) และ revoke jti ใน Redis blacklist ปิดใช้งานถ้าไม่มี session ออนไลน์
- **🗑️ ลบผู้ใช้** (title bar + Quick Actions) — soft delete (`status = deleted`) cascade revoke สิทธิ์ subsystem ทั้งหมด + ตัด session ปิดใช้งานถ้าสถานะเป็น deleted อยู่แล้ว
- **✏️ แก้ไขผู้ใช้** — เปิด `UserFormModal` โหมด edit แก้ชื่อ/ประเภท/คณะ/สถานะได้
- **Risk card** — badge ระดับความเสี่ยง (Low/Warn/High/Block) + ตัวเลข score + sparkline SVG ของ 12 session ล่าสุด (เก่า→ใหม่)
- **ที่อยู่ (address field)** — ดับเบิลคลิกเพื่อขยาย/ย่อ (ค่า default truncate เพราะอาจยาว)
- **6 stat cards** — สิทธิ์ระบบย่อย (active), บทบาท (unique roles), Scopes (unique), Session ออนไลน์ตอนนี้, Failed Logins 7 วัน (แดงถ้า >0), Risk Event ล่าสุด
- **สิทธิ์เข้าถึงระบบย่อย section**
  - dropdown **"+ เพิ่มสิทธิ์เข้าระบบ…"** + ปุ่ม **เพิ่ม** — เฉพาะ subsystem ที่ยังไม่มีสิทธิ์ (grantable list) เพิ่ม whitelist entry ให้ทันที
  - แต่ละแถว subsystem แสดง role + badge "นโยบาย" ถ้าได้สิทธิ์ผ่าน access policy (ไม่ใช่ whitelist ตรงๆ) + เหตุผลที่เข้าได้ (เช่น "ตามนโยบาย: ทุกคน")
  - ปุ่ม **ถอนสิทธิ์** (แดง) — เฉพาะแถวที่เป็น whitelist entry จริง (`can_revoke=true`) ปิด session ที่เปิดอยู่ในระบบนั้นด้วย ถ้าเข้าได้จาก policy (all/role/attribute) จะขึ้นข้อความ "ถอนรายคนไม่ได้" แทนปุ่ม เพราะต้องไปแก้ policy ที่ตัว subsystem
  - ถ้าบัญชีไม่ใช่ `active` จะมีแบนเนอร์เตือนว่าถูกบล็อกทุกระบบย่อยโดยอัตโนมัติ
- **Recent Login & Risk Events** — 8 รายการล่าสุด (เวลา, subsystem, ช่องทาง login, IP/ประเทศ/browser, risk score, decision badge)
- **Quick Actions (sidebar)** — ปุ่มลัด 5 อัน: บังคับ Logout, Reset Passkey (ลบ passkey ทั้งหมด — ต้อง confirm), เปลี่ยนสถานะ/แก้ไข (เปิด edit modal เดียวกับปุ่มบนสุด), **ดู Audit Log** (ไปหน้า `/audit?actor_id=...` กรองเฉพาะสิ่งที่ผู้ใช้นี้ทำเอง), ลบผู้ใช้
- **Passkeys & MFA card** — รายการ passkey ที่ลงทะเบียนไว้ (ชื่ออุปกรณ์ + ใช้ล่าสุดเมื่อไหร่) + สถานะ backup codes เหลือกี่ชุด
- **Active Sessions card** — session ที่ online จริงตอนนี้ (สูงสุด 5 รายการ) พร้อม device/IP/ประเทศ/subsystem
- **Access Overview (donut chart)** — สัดส่วน scope ที่มอบให้ แบ่งหมวด: ระบุตัวตน (name/student_id/employee_id), ติดต่อ (email/phone/address), วิชาการ (faculty/major/year/position), อื่นๆ
- **Risk Factors card** — เหตุผลความเสี่ยงของ login ล่าสุด (จาก RBA `risk_reasons`) สูงสุด 5 ข้อ

**ข้อมูลที่แสดง:** โปรไฟล์เต็ม (email/user_type/identifier/faculty/major-หรือ-position/phone/address/created_at), current risk + ประวัติ, สิทธิ์เข้าระบบย่อยทั้งหมด (พร้อมแหล่งที่มา), ประวัติ login, passkey/backup code, session online

---

# 4. ระบบย่อย — `/subsystems`

**คืออะไร:** ตารางรายชื่อ subsystem (OAuth client) ทั้งหมดที่เคยลงทะเบียนกับ Hub — มุมมอง admin

**ทำอะไรได้บ้าง:**
- กรองตามสถานะ (ทั้งหมด/รออนุมัติ/active/suspended)
- อนุมัติ/ปฏิเสธ subsystem ที่ status = pending ได้ทันทีจากตาราง (ไม่ต้อง confirm)
- คลิกแถวไปหน้ารายละเอียด subsystem

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **filter chips** — ทั้งหมด / รออนุมัติ / active / suspended
- **หน้าอนุมัติแบบละเอียด →** — ลิงก์ไปหน้า `/subsystems/pending` (มุมมองที่มี confirm step + แสดง redirect_uris/scope ครบ)
- **ปุ่ม "อนุมัติ" / "ปฏิเสธ"** (เฉพาะแถว pending) — เรียก `POST /admin/subsystems/{id}/approve|reject` ทันที ไม่มี step-up (เพราะมีหน้า pending แบบละเอียดกว่าให้ใช้แทนถ้าต้องการความรอบคอบ)
- **badge นโยบาย** — แสดง access policy ของแต่ละระบบ: 📋 รายชื่อ (explicit whitelist) / 🌐 ทุกคน (all) / 👥 บทบาท (role) / 🎯 คุณสมบัติ (attribute)

**ข้อมูลที่แสดง:** ชื่อ+client_id+คำอธิบาย, สถานะ, นโยบายการเข้าถึง, จำนวน whitelist, เจ้าของ (owner_email)

---

# 5. รายละเอียดระบบย่อย (Admin) — `/subsystems/[id]`

**คืออะไร:** หน้าจัดการ subsystem 1 ระบบแบบเต็มรูปแบบ จากมุมมอง **admin** (ต่างจาก developer ตรงที่ admin ควบคุมได้ทุกอย่างรวมถึงระงับ/เปิดใช้งาน/revoke session ผู้ใช้)

**ทำอะไรได้บ้าง:**
- ดู KPI 7 วันล่าสุด (login, unique users, active now, block count) + กราฟ login รายวัน
- แก้ไขข้อมูล subsystem (คำอธิบาย/redirect URI/scope/allowed roles/webhook URL)
- Rotate client_secret, โอน ownership ให้ developer คนอื่น, ระงับ/เปิดใช้งาน subsystem
- ดูและ revoke session ที่ผู้ใช้กำลัง active อยู่ (3 ระดับ)
- จัดการ Access Policy (whitelist/all/role/attribute) ผ่าน `AccessPolicyCard`
- จัดการ whitelist: เพิ่มทีละคน, อัปโหลด CSV bulk, แก้ role ทีละคนหรือ bulk, ลบ
- ดู audit log เฉพาะของ subsystem นี้ (แบ่งหน้า)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **✎ แก้ไข** — เปิด modal แก้ description/redirect URIs/scope/allowed roles/webhook URL ทั้งหมด apply ทันที (ไม่ต้องรอ approve เพราะเป็น admin เอง)
- **🔑 Rotate Secret** — สร้าง `client_secret` ใหม่ทันที secret เก่ายังใช้ได้อีก 24 ชม. (grace period) ผลลัพธ์ส่งทาง email หรือแสดง one-time link ถ้า SMTP ใช้ไม่ได้
- **↦ โอนเจ้าของ** — เปิด modal กรอกอีเมลเจ้าของใหม่ (ต้องเป็น teacher/staff/admin ที่เคย login แล้ว) เตือนว่าหลังโอน admin จะเข้าหน้านี้แทนเจ้าของเดิมไม่ได้ (เจ้าของใหม่จะเห็นแทนใน developer portal)
- **⏸ ระงับ / ▶ เปิดใช้งาน** — toggle `status` เป็น `suspended`/`active` — subsystem ที่ถูกระงับจะปฏิเสธ login ใหม่ทั้งหมดทันที
- **KPI 7 วัน (4 การ์ด)** — Login total, Unique users, Active ตอนนี้, Block/would_block รวม + กราฟแท่ง login ต่อวัน
- **ผู้ใช้กำลัง active (auto-refresh 10s)** — ตารางรายชื่อ session online จริง พร้อมปุ่ม **⛔ Revoke ▾** เปิดเมนู 3 ระดับ:
  - **📧 Notify only** — เตะออก + ส่ง email แจ้ง, login ใหม่ได้ทันที
  - **🔒 Require email confirm** — เตะออก + ต้องคลิกลิงก์ยืนยันใน email ก่อน login ใหม่ (15 นาที)
  - **🛑 Revoke + Ban** — เตะออก + ลบออกจาก whitelist ถาวร (login ใหม่ไม่ได้จนกว่าจะเพิ่มกลับ)
- **AccessPolicyCard** — จัดการ policy การเข้าถึง (explicit/all/role/attribute) + แสดง API key prefix (สำหรับ Roster Sync)
- **Whitelist section**
  - ฟอร์ม **เพิ่มเข้า whitelist** — กรอกอีเมล + เลือก role ที่ subsystem รองรับ
  - **📄 อัปโหลด CSV** — bulk add จากไฟล์ (header `email,role,note`) ระบบ skip คนที่ไม่อยู่ใน Hub หรือ role ไม่ตรง
  - **checkbox เลือกหลายแถว + toolbar bulk** — เลือกหลายคนแล้วเปลี่ยน role พร้อมกันทีเดียว ("ใช้กับทั้งหมด") มีปุ่ม "เลือกทั้งหมด"
  - **role in sub (คลิกเพื่อแก้)** — แก้ role ของ user ทีละคนแบบ inline (dropdown + ✓/✕)
  - **ปุ่ม "ลบ"** ต่อแถว — soft-remove ออกจาก whitelist
  - แถวที่ user ถูกลบที่ Hub (`status=deleted`) จะขีดฆ่า + badge "🚫 deleted"
- **Audit section** — ตาราง audit log เฉพาะ subsystem นี้ พร้อมปุ่ม **ก่อนหน้า/ถัดไป** (แบ่งหน้า 50 รายการ) และปุ่ม **ดูรายละเอียด** ต่อแถวเปิด modal metadata ดิบ

**ข้อมูลที่แสดง:** client_id, เจ้าของ, scope OAuth, จำนวน whitelist, redirect URIs, health status (online/degraded/down + latency), grace period ของ secret เก่า (ถ้ามี), audit trail แบบเต็ม

---

# 6. คำขอรออนุมัติ — `/subsystems/pending`

**คืออะไร:** หน้า triage เฉพาะสำหรับ subsystem ที่รอการอนุมัติ — แยกจาก `/subsystems` เพราะ subsystem ใหม่คือการสร้าง OAuth client ที่มีผลระยะยาว ต้องดูรายละเอียดครบก่อนตัดสินใจ (ไม่ใช่แค่ตารางกดผ่านๆ)

**ทำอะไรได้บ้าง:**
- ดูรายละเอียดคำขอลงทะเบียนแต่ละใบแบบเต็ม (redirect URIs, scope, เจ้าของ, จำนวน whitelist เริ่มต้น)
- อนุมัติหรือปฏิเสธ พร้อม step ยืนยันซ้ำก่อนกดจริง (ผ่าน step-up Passkey)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- แต่ละ card แสดง: ชื่อระบบ, คำอธิบาย, client_id, เวลาที่ลงทะเบียน, เจ้าของ, จำนวน whitelist, scope, redirect URIs ครบ
- **อนุมัติ / ปฏิเสธ** — กดครั้งแรกเปลี่ยนเป็นแถบยืนยัน ("ยืนยันอนุมัติ?"/"ยืนยันปฏิเสธ?") + ปุ่ม **ยืนยัน**/**ยกเลิก** กันการกดพลาด เรียก step-up ผ่าน Passkey ก่อนยิง `POST /admin/subsystems/{id}/approve|reject` จริง

**ข้อมูลที่แสดง:** เหมือนบนแต่จัดเป็น card ต่อคำขอแทนตาราง เพื่ออ่านง่ายก่อนตัดสินใจ

---

# 7. การเข้าใช้งาน (Realtime) — `/activity`

**คืออะไร:** ฟีดการ login สดของทั้งระบบ (ทุก subsystem + Hub-direct) ธีม "Mission Control" มี live pulse + auto-refresh ทุก 8 วินาที

**ทำอะไรได้บ้าง:**
- ดูว่าใครกำลัง online อยู่ตอนนี้ (ทุกระบบรวมกัน) พร้อมระยะเวลาที่ online เดินสดแบบเรียลไทม์
- ดูกราฟปริมาณ login รายชั่วโมง (แยกสำเร็จ/ถูกบล็อก)
- ค้นหา/กรองประวัติ login ตามอีเมล, decision, ช่องทาง login, subsystem
- หยุด/เล่น live feed และปรับช่วงเวลาที่ดู (1ชม./24ชม./7วัน/30วัน)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **⏸ หยุด / ▶ เล่น** — toggle auto-refresh (ปกติ poll ทุก 8 วินาที)
- **window selector** — 1 ชม. / 24 ชม. / 7 วัน / 30 วัน
- **↻ รีเฟรช** — โหลดใหม่ทันทีนอกรอบ auto
- **KPI strip 5 ช่อง** — ออนไลน์ตอนนี้ (ทุกระบบรวม, มี pulse), เข้าใช้งานในช่วงเวลา, ถูกบล็อก, ต้อง MFA, ความเสี่ยงเฉลี่ย
- **กำลังออนไลน์ (การ์ดเขียว)** — รายชื่อ session online จริง พร้อม avatar สี, ช่องทาง login, risk bar, ตำแหน่งภูมิศาสตร์, ระยะเวลาที่ online (นับสดทุกวินาที)
- **กราฟรายชั่วโมง (SVG bar chart)** — สีน้ำเงิน=สำเร็จ, สีแดง=ถูกบล็อก hover ดูตัวเลขต่อชั่วโมง
- **ตัวกรอง** — ค้นหาอีเมล/ชื่อ, decision, ช่องทาง (google/passkey/line/hub_direct), subsystem + ปุ่ม **ล้างตัวกรอง**
- **ตารางประวัติ** — ผู้ใช้, ระบบ, ช่องทาง, risk bar, decision badge, ที่ไหน (IP/ประเทศ + เตือนถ้าเป็น attack IP), อุปกรณ์, เวลา — แถวใหม่ที่เพิ่งเข้ามาไฮไลต์เขียวชั่วครู่ (fade animation)

**ข้อมูลที่แสดง:** session online real-time, ประวัติ 80 รายการล่าสุดตามตัวกรอง, สถิติรวม, การกระจายตามชั่วโมง

---

# 8. Audit Log — `/audit`

**คืออะไร:** log ทุกการกระทำที่มีผลต่อ state ของระบบ (append-only, ตาม defense-in-depth layer 7) ใช้สืบสวนย้อนหลังว่าใครทำอะไร เมื่อไหร่ จากที่ไหน

**ทำอะไรได้บ้าง:**
- ค้นหา/กรอง log ตาม action (text match), target type
- ดูรายละเอียด metadata ของแต่ละรายการ (highlight field สำคัญก่อน raw JSON)
- เปิดจากหน้าอื่นแบบ scoped (เช่นจาก User 360° View) — ล็อกเฉพาะ log ของ user คนเดียว แยกเป็น "เป้าหมาย" (target_id — สิ่งที่ถูกกระทำต่อเขา) หรือ "กระทำเอง" (actor_id — สิ่งที่เขาทำเอง)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **แบนเนอร์ scope (ถ้ามาจากลิงก์ scoped)** — บอกว่ากำลังดู log ของใคร + ปุ่ม **ดูทั้งหมด ✕** ล้าง scope กลับไปดูทุกคน
- **ช่องค้นหา action** — พิมพ์ตรงกับ action string (เช่น `subsystem_approved`)
- **dropdown target type** — user / subsystem / access_list / login_session
- **คอลัมน์ "รายละเอียด"** — `<details>` แบบ 2 ชั้น: ชั้นแรกไฮไลต์ field สำคัญ (อีเมล, เหตุผล, role, provider, อุปกรณ์จาก user-agent) ชั้นสองเป็น raw JSON metadata ทั้งหมด
- **pagination** — ก่อนหน้า/ถัดไป 50 รายการต่อหน้า

**ข้อมูลที่แสดง:** เวลา (Bangkok TZ), ผู้กระทำ (หรือ "system" ถ้าไม่มี actor), action (badge สีตามหมวด), target type/id, IP + อุปกรณ์ที่ใช้, metadata

---

# 9. ML / ความผิดปกติ — `/ml`

**คืออะไร:** ภาพรวมผลการให้คะแนนความเสี่ยงของ 4-Layer RBA (Rule Engine + Behavior Profiling + Isolation Forest + Aggregation) ทุก login session ที่ผ่านมา

**ทำอะไรได้บ้าง:**
- ดูอัตรา anomaly, จำนวน MFA/Block (แยก live กับ shadow mode)
- ดู histogram การกระจายของ score ทั้งหมด
- สลับดู session ล่าสุด หรือ top anomalies (score สูงสุด)
- คลิก session เพื่อดูรายละเอียด + ให้ feedback (ground truth) สำหรับ tuning ภายหลัง
- ไปหน้า Threshold Tuning เพื่อจำลองผลถ้าปรับ threshold

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **badge SHADOW MODE / ENFORCING** — บอกว่าตอนนี้ ML แค่บันทึกคะแนน (shadow) หรือ block จริง (enforcing) ตาม `ML_SHADOW_MODE` ใน .env
- **window selector** — 1/7/30/90 วันล่าสุด
- **KPI 4 ช่อง** — Login ทั้งหมด, Anomaly Rate %, MFA/would_mfa รวม, Block/would_block รวม
- **ScoreHistogram** — กราฟกระจายคะแนน anomaly
- **การ์ด "Threshold Tuning"** — แสดงค่า threshold ปัจจุบัน (Block/MFA) คลิกไปหน้า `/ml/threshold`
- **toggle 🕒 Recent / 🔥 Top Score** — สลับเรียง session ตามเวลาล่าสุด หรือ score สูงสุด
- **ตาราง session** — คลิกแถวเปิด slide panel รายละเอียด (feature breakdown, SHAP, ปุ่มให้ feedback ว่า true/false positive)

**ข้อมูลที่แสดง:** decision breakdown, score histogram, รายชื่อ session พร้อมคะแนนและปัจจัยเสี่ยง

---

# 10. Threshold Tuning — `/ml/threshold`

**คืออะไร:** เครื่องมือจำลอง (what-if) ว่าถ้าเปลี่ยนค่า threshold ของ block/mfa จะกระทบผลตัดสินของ session ย้อนหลัง 30 วันอย่างไร โดย**ไม่ retrain model จริง** — แค่ apply threshold ใหม่กับ score ที่บันทึกไว้แล้ว

**ทำอะไรได้บ้าง:**
- ลาก slider ปรับ Block threshold และ MFA threshold แล้วดูผลจำลองทันที (debounce 300ms)
- เทียบ current vs proposed breakdown (pass/mfa/block) แบบ delta
- ดู precision estimate จาก feedback ที่ admin เคยให้ไว้ (true positive / false positive)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **Slider Block threshold** (แดง) — ค่า score ที่ >= จะถูก block
- **Slider MFA threshold** (เหลือง) — ค่า score ที่ >= จะขึ้น MFA (ต้องน้อยกว่า Block เสมอ มีเตือนถ้าตั้งผิด)
- **Simulated breakdown (Pass/MFA/Block)** — จำนวน session ที่จะตกแต่ละกลุ่มถ้าใช้ threshold ที่ตั้งไว้
- **Current → Proposed** — ตารางเทียบค่าปัจจุบันกับค่าที่กำลังทดลอง พร้อมตัวเลข delta (+/-) สีแดง/เขียว
- **Feedback (ground truth)** — TP/FP/Precision estimate จาก feedback ที่ admin เคยกดไว้ในหน้า ML

**ข้อมูลที่แสดง:** ค่าปัจจุบันใน `.env`, ผลจำลอง 30 วัน, precision estimate — หน้านี้ไม่มีปุ่ม "บันทึก" จริง (ใช้เพื่อประกอบการตัดสินใจก่อนไปแก้ `.env` เอง)

---

# 11. ประวัติ ML ผู้ใช้ — `/ml/users/[id]`

**คืออะไร:** timeline คะแนนความเสี่ยงของผู้ใช้ 1 คนโดยเฉพาะ (เข้าถึงจากลิงก์ในหน้า ML หรือ User 360°)

**ทำอะไรได้บ้าง:**
- ดูสถิติสรุปของผู้ใช้คนนี้ (จำนวน session, avg score, จำนวนที่ถูก flag)
- ปรับช่วงเวลาดู (7/30/90/365 วัน)
- คลิก session เพื่อดูรายละเอียด + ให้ feedback

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **← ML Overview** — breadcrumb กลับไปหน้ารวม
- **dropdown ช่วงเวลา** — 7/30/90 วัน/1 ปี
- **KPI mini 3 ช่อง** — Total Sessions, Avg Score, Flagged (score >= 0.4)
- **ตาราง session** — เหมือนหน้า ML overview แต่ไม่แสดงคอลัมน์ user (รู้อยู่แล้วว่าเป็นใคร) คลิกแถวเปิด slide panel รายละเอียด

**ข้อมูลที่แสดง:** โปรไฟล์ผู้ใช้ (ชื่อ/email/user_type), สถิติ, รายการ session พร้อม score

---

# 12. IP Blacklist — `/ip-blacklist`

**คืออะไร:** จัดการรายชื่อ IP ที่ถูกขึ้นบัญชีดำ — login จาก IP ในลิสต์นี้จะถูกตั้ง `is_attack_ip=true` อัตโนมัติ (ป้อนเป็น feature หนึ่งใน RBA ตาม Wiefling 2022)

**ทำอะไรได้บ้าง:**
- เพิ่ม/ลบ IP ทีละรายการ พร้อมเหตุผล
- อัปโหลด CSV เพิ่มหลาย IP พร้อมกัน
- ดึง threat-intel feed สาธารณะ (ipsum L5 บน GitHub) มา upsert เข้า DB อัตโนมัติ
- ค้นหา IP/เหตุผลในลิสต์ที่มี พร้อม pagination

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **🔄 Refresh ipsum** — ดาวน์โหลด threat-intel list ล่าสุดจาก GitHub มา insert เฉพาะ IP ใหม่ (ข้ามที่ซ้ำ) ต้อง confirm ก่อน แสดงผลลัพธ์ (fetched/เพิ่มใหม่/ซ้ำ/เวลาที่ใช้)
- **ฟอร์มเพิ่ม IP** — กรอก IP + เหตุผล (optional) แล้วกด **เพิ่ม**
- **อัปโหลด CSV** — format `ip,reason` บรรทัดละ 1 IP
- **ช่องค้นหา + ปุ่มค้นหา/✕** — ค้นหา IP หรือ reason
- **ปุ่ม "ลบ"** ต่อแถว — เอา IP ออกจาก blacklist
- **pagination** (⏮ ← หน้า X/Y → ⏭) — เมื่อมีมากกว่า 50 รายการ

**ข้อมูลที่แสดง:** จำนวน IP ทั้งหมดใน blacklist, รายการ IP + เหตุผล + วันที่เพิ่ม

---

# 13. API Alerts — `/api-alerts`

**คืออะไร:** ระบบตรวจจับพฤติกรรม API ผิดปกติแบบ rule-based (วิเคราะห์จาก `request_logs`) ตาม OWASP API4:2023 + NIST SP 800-228 — คนละชั้นกับ ML/RBA ที่ดูเฉพาะตอน login

**ทำอะไรได้บ้าง:**
- สแกนหา alert ใหม่ทันที (นอกรอบ cron ปกติ) จาก request 5 นาทีล่าสุด
- ดูรายการ alert ทั้งหมด กรองตามกฎ/สถานะตรวจสอบ
- Mark alert ว่าตรวจสอบแล้ว (resolve)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **สแกนตอนนี้** — เรียก `POST /admin/api-alerts/scan?minutes=5` สแกนย้อนหลัง 5 นาที รายงานจำนวน alert ใหม่ที่พบ
- **dropdown ช่วงเวลา** — 1/7/30 วัน
- **KPI 3 ช่อง** — Critical (ยังไม่ตรวจ), Warning (ยังไม่ตรวจ), Resolved
- **ตัวกรอง** — ตามกฎ (4 กฎ: excessive_requests 🔥, high_error_rate ⚠️, unauthorized_probing 🚨, bot_pattern 🤖) และสถานะตรวจสอบ
- **Alert card แต่ละใบ** — แสดง rule/severity badge, รายละเอียด (count/threshold, CV, interval, path ที่โดนยิง), IP, เวลา + ปุ่ม **Resolve** (เฉพาะที่ยังไม่ตรวจ)
- **กฎที่ตรวจจับ (reference grid)** — อธิบาย 4 กฎที่ระบบใช้ตรวจจับ

**ข้อมูลที่แสดง:** alert list พร้อมรายละเอียดเชิงลึกต่อกฎ (เช่น coefficient of variation, mean interval, sample paths ที่ถูกยิง)

---

# 14. Incidents — `/incidents`

**คืออะไร:** หน้า triage เหตุการณ์เสี่ยงที่ RBA ตัดสิน (block/challenge/mfa) — เวอร์ชันเจาะลึกกว่า `/activity` เพราะโฟกัสเฉพาะ login ที่ "มีปัญหา" พร้อมเครื่องมือแก้ไขทันที (one-click remediation)

**ทำอะไรได้บ้าง:**
- ดูรายการ incident พร้อมกรองตามช่วงเวลา/decision/ค้นหาอีเมล
- คลิกแถวเปิด modal เต็มจอ ดูรายละเอียดเชิงลึกทุกมิติของเหตุการณ์นั้น
- สั่ง remediation action ได้ตรงจาก modal (เช่น block IP, reset passkey, revoke session) โดยไม่ต้องสลับหน้า

**ปุ่ม/ส่วนประกอบสำคัญ (หน้ารายการ):**
- **KPI 4 ช่อง** — เหตุการณ์ทั้งหมด, ถูกบล็อก, ต้องยืนยันตัวตน, Attack IP
- **window chips** — 24 ชม./7 วัน/30 วัน
- **dropdown decision** — block/would_block/challenge/would_mfa/mfa_passed
- **ช่องค้นหา** — email/ชื่อ (กด Enter)
- **ตาราง** — เวลา, ผู้ใช้, ช่องทางเข้า→เป้าหมาย, risk score, decision badge, สถานะ session — คลิกแถวเปิด modal รายละเอียด

**ปุ่ม/ส่วนประกอบสำคัญ (Incident Detail Modal):**
- **หัวข้อ + badge ระดับความเสี่ยง**
- **🧭 สรุปเหตุการณ์ (Incident Summary)** — 3 คอลัมน์ WHY (ทำไมเสี่ยง) / WHAT (เกิดอะไรขึ้น) / WHAT TO DO (ควรทำอะไร) + impact statement chips (✓/⚠)
- **🛤️ เส้นทางการโจมตี (Attack Path)** — diagram ขั้นตอน node-by-node ของ flow การเข้าระบบครั้งนี้
- **1. ช่องทางการเข้า (Entry)** — endpoint, auth method, client/app, scope ที่ขอ (OAuth) หรือ role (RBAC), IP/ประเทศ/อุปกรณ์/network
- **2. การวิเคราะห์ความเสี่ยง (Risk Analysis)** — score, decision, top reasons + ปุ่ม **🔬 View ML Explanation (4-Layer + SHAP)** ขยายดู breakdown แต่ละ layer (Rule/Behavior/IForest) เป็น additive model และค่า SHAP ต่อ feature (ถ้า ML service ส่งมา)
- **3. หลักฐานความเสี่ยง (Evidence)** — เหตุผลเป็นรายการ (feature + detail)
- **4. ไทม์ไลน์เหตุการณ์** — audit action ที่เกี่ยวข้องเรียงเวลา
- **5. การตอบสนองของระบบ** — decision, action ที่ระบบทำจริง, ออก token/session/refresh token หรือไม่, สถานะ session, บันทึก log แล้วหรือยัง, เตือนถ้าเป็น Shadow Mode
- **6. แนวทางการจัดการ (Recommended Actions)** — ปุ่ม action จริงจัดกลุ่มตามหมวด (root_cause/authentication/network/account/subsystem/configuration) ปุ่มที่ทำได้ทันทีเรียก step-up ก่อนสั่งจริง (เช่น reset_passkey, block_ip ต้อง confirm ก่อน) ส่วนที่ทำไม่ได้ตรงนี้จะเป็นลิงก์พาไปหน้าที่เกี่ยวข้องแทน
- **7. ข้อมูลเพิ่มเติม (7 วัน)** — สถิติของผู้ใช้คนนี้ 7 วันล่าสุด (จำนวน incident, avg risk, blocked attempts, passkey success rate)
- **8. ลิงก์ที่เกี่ยวข้อง** — ทางลัดไปหน้าอื่นที่เกี่ยวกับ incident นี้ (เช่น User 360°, subsystem)

**ข้อมูลที่แสดง:** ทุกมิติของ 1 login event ที่มีความเสี่ยง ตั้งแต่ต้นทางจนถึงผลลัพธ์ พร้อมเครื่องมือแก้ไขในหน้าเดียว

---

# 15. แจ้งเตือนทั้งหมด — `/notifications`

**คืออะไร:** ศูนย์รวมแจ้งเตือนทุกประเภทในระบบ (คำขอ approve, ML anomaly, API alert, subsystem ล่ม ฯลฯ) — auto-refresh ทุก 30 วินาที

**ทำอะไรได้บ้าง:**
- ดูแจ้งเตือนทั้งหมดแบบ flat list เรียงเวลาล่าสุด, กรองตามหมวด/อ่านแล้วหรือยัง
- Mark อ่านแล้ว/ยังไม่อ่าน ทีละรายการหรือทั้งหมดพร้อมกัน
- คลิกดูรายละเอียดเชิงลึก — ระบบมี **diagnostic panel อัตโนมัติ** ที่วิเคราะห์อาการ/สาเหตุที่เป็นไปได้/วิธีแก้ ให้ตามประเภทแจ้งเตือน (เช่น subsystem down เพราะ redirect_uri ตั้ง localhost ผิด)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **badge "🔔 N ยังไม่อ่าน" / "✓ อ่านครบแล้ว"** — สรุปสถานะรวม
- **✓ Mark ทั้งหมดว่าอ่าน** — เคลียร์ unread ทั้งหมดในคราวเดียว (มี confirm)
- **⟳ รีเฟรช** — โหลดใหม่นอกรอบ auto
- **แท็บ ยังไม่อ่าน / อ่านแล้ว / ทั้งหมด** — พร้อมตัวเลขนับ
- **Featured card** — แจ้งเตือนสำคัญที่สุด (critical ก่อน ถ้าไม่มีก็ล่าสุด) เด่นด้านบนสุด คลิกไปหน้าที่เกี่ยวข้องตรง (แสดงเฉพาะเมื่อยังมี unread)
- **dropdown กรองตามประเภท** — คำขอ Approve / คำขอ Admin Override / คำขอที่ตัดสินแล้ว / ML Anomaly / API Alerts / Subsystem ล่ม
- **ตารางแจ้งเตือน** — เวลา (จุดกะพริบถ้ายังไม่อ่าน), severity badge, ประเภท, หัวข้อ+รายละเอียดย่อ, ปุ่ม ✓/↺ (toggle อ่าน) และปุ่ม **ดู →** เปิด slide panel รายละเอียดเต็ม (auto mark-read เมื่อเปิด)
- **Slide panel รายละเอียด**
  - **🩺 วิเคราะห์ + วิธีแก้ (diagnostic panel)** — เฉพาะบางประเภท (subsystem down/degraded, ML anomaly, API alert, approval request) วิเคราะห์อาการ→สาเหตุที่เป็นไปได้→ขั้นตอนแก้ไขเป็นข้อๆ
  - **Health/API summary พิเศษ** — ถ้าเป็นสรุปรวม (health check ทั้งระบบ หรือสรุป API alerts) จะแสดง breakdown สถานะ online/degraded/down ของแต่ละ service หรือ top rules/top IPs
  - **Raw metadata** — `<details>` เปิดดู JSON ดิบทั้งหมด
  - ปุ่ม **ปิด** และ **ไปยังหน้าที่เกี่ยวข้อง →** (ลิงก์ตรงไปหน้า subsystem/pending-requests/ml/api-alerts ตามประเภท)

**ข้อมูลที่แสดง:** แจ้งเตือนทุกหมวดพร้อม severity, เวลา, สถานะอ่าน, คำแนะนำการแก้ไขอัตโนมัติ

---

# 16. บัญชีของฉัน — `/account` (และ `/account/security` → redirect ไปที่นี่)

**คืออะไร:** หน้าจัดการโปรไฟล์และความปลอดภัยของบัญชีตัวเอง (ทั้ง admin และ developer ใช้ component เดียวกัน `AccountView`) — Passkey เป็นกลไกหลักสำหรับ step-up authentication ของ critical actions ทั้งระบบ

**ทำอะไรได้บ้าง:**
- ดูข้อมูลโปรไฟล์ตัวเอง (ชื่อ/อีเมล/ประเภท/คณะ/สิทธิ์)
- เพิ่ม/ลบ Passkey ของตัวเอง (สูงสุดตามค่า `max`, ปกติ 10)
- สร้าง/ดู backup codes ใหม่ (ใช้กรณี Passkey ใช้ไม่ได้)

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **Profile card** — avatar ตัวอักษรแรกของชื่อ, badge ADMIN หรือ user_type, ข้อมูล ประเภทผู้ใช้/คณะ/สิทธิ์
- **+ เพิ่ม Passkey** — เปิดฟอร์มตั้งชื่ออุปกรณ์ (เช่น "MacBook Air") แล้วกด **ลงทะเบียน** เริ่ม WebAuthn ceremony ของเบราว์เซอร์ ปิดปุ่มถ้าถึงจำนวนสูงสุดแล้ว
- **PasskeyCard ต่อรายการ** — แต่ละ passkey ที่ลงทะเบียนไว้ (แก้ชื่อ/ลบได้ ป้องกันลบตัวสุดท้ายถ้าไม่มี backup)
- **🔄 สร้างใหม่ (backup codes)** — regenerate ชุด backup codes ใหม่ (โค้ดเก่าทั้งหมดใช้ไม่ได้ทันที) ต้อง confirm ก่อน แสดงเตือนสีเหลืองถ้าเหลือน้อย
- **BackupCodesModal** — เด้งขึ้นหลังสร้าง/regenerate โชว์โค้ดครั้งเดียวให้ก็อปปี้เก็บไว้

**ข้อมูลที่แสดง:** โปรไฟล์, จำนวน passkey/สูงสุด, backup codes เหลือ/ทั้งหมด

---

# Developer Portal

หน้าเหล่านี้ใช้โดย **teacher/staff/admin** ที่ลงทะเบียน subsystem ของตัวเอง (เจ้าของ subsystem) — คนละสิทธิ์กับ Hub Admin แม้ admin จะเข้าถึงได้ทั้งสองฝั่ง

---

## 17. บัญชีของฉัน (Developer) — `/developer/account`

**คืออะไร:** หน้าเดียวกับ `/account` (ใช้ `AccountView` component ร่วมกัน) เข้าถึงผ่าน sidebar ฝั่ง developer

**ทำอะไรได้บ้าง / ปุ่ม:** เหมือนข้อ 16 ทุกประการ

---

## 18. ระบบของฉัน — `/developer/subsystems`

**คืออะไร:** รายชื่อ subsystem ที่ตัวเอง**เป็นเจ้าของ**เท่านั้น (ต่างจาก `/subsystems` ฝั่ง admin ที่เห็นทุกระบบ)

**ทำอะไรได้บ้าง:**
- ดูรายชื่อ subsystem ของตัวเอง พร้อมสถานะและ scope ที่ขอ
- ลงทะเบียนระบบใหม่
- คลิกไปหน้ารายละเอียดของแต่ละระบบ

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **+ ลงทะเบียนระบบใหม่** — ไปหน้า `/developer/subsystems/new`
- **empty state** — ถ้ายังไม่มี subsystem จะโชว์คำอธิบาย + ปุ่ม "เริ่มลงทะเบียน →"
- **แถวในตาราง** — ชื่อ+client_id+คำอธิบาย, สถานะ (พร้อมใช้งาน/รออนุมัติ/ถูกระงับ), scope ที่ขอ (chip แสดงสูงสุด 4 อัน), วันที่ลงทะเบียน

**ข้อมูลที่แสดง:** subsystem ของตัวเองทั้งหมด

---

## 19. ลงทะเบียนระบบย่อย — `/developer/subsystems/new`

**คืออะไร:** ฟอร์มลงทะเบียน subsystem ใหม่เข้ากับ Hub เป็น OAuth client

**ทำอะไรได้บ้าง:**
- กรอกข้อมูลระบบ, redirect URIs, เลือก scope ที่ต้องการ (data minimization), เลือก access policy, ตั้ง webhook URL (optional)
- ยืนยันด้วย Passkey (step-up) แล้วได้ client_secret + (ถ้ามี) Roster API key กลับมาแสดงครั้งเดียว

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **ชื่อระบบ / คำอธิบาย** — free text
- **Redirect URIs** — เพิ่มได้หลายอัน (**+ เพิ่ม URI** / **✕** ลบทีละอัน) ต้องตรงกับที่ subsystem ใช้จริงกัน open redirect
- **Scope ที่ต้องการ** — checkbox 10 ตัวเลือก (email, name, student_id, employee_id, faculty, major, year, position, phone, address) เลือกเฉพาะที่จำเป็นจริง
- **นโยบายการเข้าถึง (Access Policy)** — เลือก 1 ใน 4: 📋 Whitelist (รายชื่อ CSV), 🌐 All Users (ทุกคน active เข้าได้), 👥 Role (เฉพาะบทบาทที่เลือก — ปรากฏ chip เลือก role เพิ่ม), 🎯 Attribute (เฉพาะคณะ/สาขา — กรอก text คั่นด้วย comma)
- **Access-revoke Webhook URL (optional)** — ปล่อยว่างได้ ระบบจะ derive อัตโนมัติจาก redirect_uri แรก
- **ปุ่ม "ลงทะเบียน →"** — ส่งฟอร์ม ยืนยันด้วย Passkey แบบ inline (ถ้ายกเลิกหรือไม่มี passkey ข้อมูลในฟอร์มยังอยู่ไม่หาย)
- **หน้าสำเร็จ** — แสดง client_id/subsystem_id, Roster API key (ถ้ามี, แสดงครั้งเดียว), client_secret ผ่านลิงก์ email (หรือ URL ตรงถ้า SMTP ใช้ไม่ได้ ใช้ครั้งเดียวหมดอายุ 15 นาที), webhook endpoint ที่ต้องไปสร้างฝั่ง subsystem เอง, ปุ่ม **ไปยังหน้าระบบ →** / **กลับรายการ**

**ข้อมูลที่แสดง:** N/A (เป็นฟอร์ม) — ผลลัพธ์หลังส่งแสดง credential ที่ได้

---

## 20. รายละเอียดระบบย่อย (Developer) — `/developer/subsystems/[id]`

**คืออะไร:** หน้าจัดการ subsystem ของตัวเอง มุมมอง developer (เบากว่าเวอร์ชัน admin ตรงที่ไม่มี active sessions/revoke/suspend — การเปลี่ยนแปลงบางอย่างต้องรอ admin approve)

**ทำอะไรได้บ้าง:**
- ดูข้อมูล OAuth client (client_id, scope) — client_secret ไม่แสดงซ้ำ (ดูได้ครั้งเดียวตอนลงทะเบียน/rotate)
- แก้ไข description ได้ทันที ส่วน redirect URIs/scope/allowed roles ต้องรอ admin review
- ขอ rotate client_secret (สร้าง pending request ให้ admin approve ก่อน)
- จัดการ whitelist: เพิ่ม/ลบ/แก้ role ทีละคน, อัปโหลด CSV

**ปุ่ม/ส่วนประกอบสำคัญ:**
- **✎ แก้ไข** — เปิด modal: คำอธิบาย apply ทันที ส่วน redirect URIs/scope/allowed roles ต้องรอ admin approve (ขึ้นเตือนสีเหลืองในฟอร์ม)
- **🔑 ขอ Rotate Secret** — ต่างจากฝั่ง admin ตรงที่**ไม่ apply ทันที** สร้างเป็น pending request ให้ admin approve ก่อน แล้วค่อยได้ email แจ้ง secret ใหม่
- **Pending Approval banner** — แสดงคำขอที่ยังรอ admin review (เช่น rotate secret, แก้ scope, เปลี่ยน role) พร้อมประเภทคำขอและเวลา
- **Whitelist section** — ฟอร์มเพิ่ม user + role, อัปโหลด CSV, แก้ role แบบ inline, ปุ่มลบต่อแถว (เหมือนฝั่ง admin แต่ scope เฉพาะ subsystem ตัวเอง)

**ข้อมูลที่แสดง:** ข้อมูล OAuth client, whitelist, คำขอที่รอ approve

---

## Component ที่ใช้ร่วมกันหลายหน้า (อ้างอิง)

- **`Topbar`** — แถบหัวข้อบนสุดของทุกหน้า แสดงชื่อหน้า + เมนู user
- **`DataTable`** — ตารางมาตรฐาน รองรับ `onRowClick` ให้คลิกทั้งแถวนำทางได้ (ใช้ในหน้า users, subsystems, developer/subsystems, audit, subsystems/[id] whitelist)
- **`Badge`** — ป้ายสถานะสีตาม tone (good/warn/danger/brand/default)
- **`UserFormModal`** — ฟอร์ม create/edit ผู้ใช้ ใช้ร่วมทั้งหน้า `/users` และ `/users/[id]`
- **`SlidePanel`** — แผงเลื่อนจากขวาสำหรับดูรายละเอียดโดยไม่ออกจากหน้า (ML session detail, notification detail)
- **`mutateWithStepup` / `runWithStepup`** (`lib/passkey.ts`) — wrapper สำหรับ critical action ทุกอัน ดัก 403 `stepup_required` แล้วเปิด popup ยืนยัน Passkey อัตโนมัติก่อน retry
