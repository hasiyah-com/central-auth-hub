# หน้า Incident Detail — อธิบายแต่ละส่วน (ก้อนข้อความคืออะไร ทำอะไร)

> เอกสารนี้อธิบายว่าหน้า **"เหตุการณ์เสี่ยง (Incidents)"** และหน้ารายละเอียด
> **Incident Detail** แต่ละก้อน/ส่วน คืออะไร แสดงข้อมูลอะไร ดึงมาจากไหน และปุ่มแต่ละอันทำอะไร
> — ใช้อ้างอิงตอนเขียนธีสิส / อธิบายให้กรรมการ
>
> **โค้ดที่เกี่ยวข้อง:**
> - Backend: `hub/backend/app/services/incident_service.py` (logic รวบข้อมูล + action)
> - Backend: `hub/backend/app/routers/admin.py` (endpoint `/admin/incidents*`)
> - Frontend: `hub/frontend/app/(console)/incidents/page.tsx` (หน้า list)
> - Frontend: `hub/frontend/app/(console)/incidents/_components/IncidentDetailModal.tsx` (หน้า detail)

---

## 0. ภาพรวม — Incident คืออะไร

**Incident (เหตุการณ์เสี่ยง)** = การ login ที่ระบบ **4-Layer RBA** (Risk-Based
Authentication) ประเมินแล้วว่า **เสี่ยง** — ไม่ใช่ทุก login แต่เฉพาะที่:

- `decision` ไม่ใช่ `allow` (เช่น `block`, `would_block`, `challenge`, `would_mfa`,
  `mfa_required`, `mfa_passed`) **หรือ**
- IP ถูก mark ว่าเป็น attack IP

**ไม่มีการสร้างตาราง incident แยก** — ระบบ derive (คำนวณสด) จากตาราง
`login_sessions` + `audit_logs` ที่มีอยู่แล้ว → ข้อมูลเป็น single source of truth
ไม่ต้อง sync

**จุดประสงค์:** ให้ admin เห็นภาพรวมแบบ **triage** ได้เร็ว — เกิดอะไรขึ้น เข้าทางไหน
ต้องปิดช่องโหว่ตรงไหน แล้วกดจัดการได้จากหน้าเดียว

**หลักการจัดหน้า — Admin ไม่ต้องไล่อ่านทั้งหมด:** เรียงรอบคำถาม 3 ข้อ
**Why? (ทำไมเสี่ยง) → What happened? (เกิดอะไร) → What should I do? (ควรทำอะไร)**
โดยส่วนบนสุด (Incident Summary + Attack Path) ตอบครบทั้ง 3 ข้อในพริบตา ส่วนที่เหลือ
เป็นรายละเอียดให้เจาะลึกถ้าต้องการ

---

## 1. หน้า List — "เหตุการณ์เสี่ยง"

ตาราง login เสี่ยงเรียงใหม่สุดก่อน + การ์ด KPI ด้านบน

| ก้อน | คืออะไร |
|---|---|
| **KPI: เหตุการณ์ทั้งหมด** | จำนวน incident ในช่วงเวลาที่เลือก (24 ชม./7 วัน/30 วัน) |
| **KPI: ถูกบล็อก** | จำนวนที่ decision = `block`/`would_block` |
| **KPI: ต้องยืนยันตัวตน** | จำนวนที่โดนบังคับ MFA/challenge |
| **KPI: Attack IP** | จำนวนที่มาจาก IP ในบัญชีดำ |
| **แถวในตาราง** | เวลา · ผู้ใช้ · เข้าทางไหน→เป้าหมาย · Risk · Decision · สถานะ session |

คลิกแถว → เปิดหน้า **Incident Detail** (modal เต็มจอ)

---

## 2. หน้า Incident Detail — Header (ส่วนหัว)

แถบบนสุด + แถบสรุปผู้ใช้

| ก้อน | คืออะไร / ดึงจากไหน |
|---|---|
| **Incident Detail + badge HIGH RISK** | ระดับความเสี่ยงรวม (คำนวณจาก risk_score: ≥0.85 = Critical) |
| **avatar + ชื่อ + email** | ข้อมูลผู้ใช้ (`users` table) |
| **badge ประเภท + สถานะบัญชี** | `user_type` (student/teacher/staff/admin) + `status` (active/graduated/…) |
| **Risk Score (เช่น 1.000 / 1.000)** | คะแนนความเสี่ยงรวมจาก 4-Layer RBA (`login_sessions.risk_score`) |
| **Decision** | ผลตัดสินของระบบ (`login_sessions.decision`) |
| **เวลา + Incident ID** | เวลาเกิด (UTC) + รหัสอ้างอิง `INC-YYYY-MM-DD-NNNNNN` (NNNNNN = ลำดับ incident ของวันนั้น) |

---

## 2.5 ส่วนบนสุด — Incident Summary + Attack Path (ตอบ Why→What→What-to-do)

### Incident Summary (สรุปเหตุการณ์)
3 คอลัมน์ตอบ 3 คำถามในบรรทัดเดียว + แถบ impact:

| คอลัมน์ | ความหมาย | ที่มา |
|---|---|---|
| **WHY · ทำไมเสี่ยง** | เหตุผลอันดับ 1 ที่จับได้ (แปลเป็นภาษาคน) | risk_reasons[0] |
| **WHAT · เกิดอะไรขึ้น** | ระบบทำอะไร (บล็อก/บังคับ MFA/log เฉยๆ) | decision |
| **WHAT TO DO · ควรทำอะไร** | action สำคัญสุดที่แนะนำ | action แรกที่กดได้ |

**แถบ impact (statements):** เช่น "✓ ปิดกั้นสำเร็จ", "✓ ไม่ออก Token", "✓ ไม่มีข้อมูลรั่วไหล"

> **⚠️ ยึดความจริง (สำคัญตอน defend):** ถ้าเป็น **Shadow Mode** (would_block) ระบบ
> **ไม่ได้บล็อกจริง** → token ออกแล้ว → impact จะแสดง "⚠ ออก Token แล้ว — ถ้าเปิด
> enforce จะถูกบล็อก" ไม่ใช่ "No Data Exposure" — เฉพาะ enforce block จริงเท่านั้น
> ที่ขึ้น "ไม่มีข้อมูลรั่วไหล"

### Attack Path (เส้นทางการโจมตี)
ไดอะแกรมแนวนอนให้เห็นทันทีว่าการโจมตีมาทางไหน → จบที่ไหน:

```
Internet → Google OAuth → Central Auth Hub → [เป้าหมาย] → BLOCK/CHALLENGE/ALLOW
(IP+geo)   (endpoint)      (4-Layer RBA)      (subsystem)   (ผลลัพธ์)
```

- node สี **แดง** = ต้นทางน่าสงสัย (attack IP) / จุดที่ถูกกั้น
- ถ้า decision = block → เป้าหมาย (subsystem) ขึ้น "ยังไม่ถึง (ถูกกั้นที่ Hub)" —
  สะท้อนว่าการโจมตี**ไม่ถึง**ระบบย่อยจริง

---

## 3. ส่วนที่ 1 — ช่องทางการเข้า (Authentication Entry Point)

**ตอบคำถาม: "attacker/ผู้ใช้ เข้ามาทางช่องไหน?"**

| ฟิลด์ | ความหมาย | แหล่งข้อมูล |
|---|---|---|
| **Entry Type / ช่องทาง** | Google OAuth / Passkey / discoverable / LINE | `login_sessions.login_method` |
| **Source / เป้าหมาย** | เข้า Hub Console หรือระบบย่อยตัวไหน | `subsystem_id` → ชื่อ subsystem (NULL = Hub-direct) |
| **Endpoint** | URL จริงที่รับ login (เช่น `GET /auth/google/callback`) | map จาก login_method |
| **Auth Method** | วิธียืนยันตัวตน (Google OAuth / Passkey WebAuthn) | map จาก login_method |
| **Client / App** | แอปที่ขอ login (`hub-console` หรือ client_id ของ subsystem) | `subsystems.client_id` |
| **Scopes / สิทธิ์** | สิทธิ์ที่ login นี้มี | subsystem = **OAuth scope จริง** / Hub-direct = **สิทธิ์ตามบทบาท (RBAC) จริง**\* |
| **Role** | บทบาทผู้ใช้ | `users.user_type` |
| **First / Last Seen** | ช่วงเวลาของเหตุการณ์ (จาก timeline) | `login_sessions.created_at` + audit events |
| **IP / ประเทศ / เมือง** | ที่มาทางภูมิศาสตร์ | `ip`, `geo_country`, `geo_city` |
| **Device / Browser / OS / User Agent** | อุปกรณ์ที่ใช้ | parse จาก `user_agent` |
| **Network** | Private (LAN/Docker) หรือ Public + subnet | คำนวณจาก IP (RFC1918 check) |

> *\*ช่องนี้แยก 2 กรณีตามความจริงของระบบ (`scopes_kind`):*
> - *`oauth` — **subsystem login**: แสดง OAuth scope จริงจาก `subsystems.scope`
>   ที่ subsystem ขอตอนลงทะเบียน (badge เขียว)*
> - *`role` — **Hub-direct login**: ระบบ**ไม่มี OAuth scope ต่อ session** (JWT มีแค่
>   sub/email/user_type/faculty) จึงแสดง **สิทธิ์จริงตาม RBAC** ที่บทบาทนั้นเข้าถึงได้
>   (admin → Admin Console `/admin/*` + Developer Portal `/developer/*`) — เป็นสิทธิ์
>   ที่ระบบใช้ตัดสินจริงผ่าน `is_hub_admin`/`user_type` ไม่ใช่ค่าปั้น (badge ม่วง)*

---

## 4. ส่วนที่ 2 — การวิเคราะห์ความเสี่ยง (Risk Analysis)

**ตอบคำถาม: "เสี่ยงแค่ไหน เพราะอะไร?"**

**แบบย่อ (เห็นทันที):** Risk Score + Decision + Top 3 Reasons — พอให้ตัดสินใจได้เร็ว

**ปุ่ม "View ML Explanation"** — กดเพื่อกาง **3 ชั้น** ของ RBA + **SHAP** (per-feature
ของ Layer 3) สำหรับคนที่อยากเจาะลึกว่า ML คิดยังไง — ถ้า ML service ไม่ได้ส่ง SHAP มา
จะแสดงแค่ 3 ชั้น + หมายเหตุ

รายละเอียด 3 ชั้น (กางจากปุ่ม):

| ชั้น | คืออะไร | เพดานคะแนน |
|---|---|---|
| **Layer 1 — Rule Engine** | กฎตายตัว: IP blacklist, impossible travel, failed logins เกินเกณฑ์ (hard block ได้) | ≤ 1.0 |
| **Layer 2 — Behavior Profiling** | เทียบพฤติกรรมกับ profile เดิม: เวลา/ประเทศ/อุปกรณ์ใหม่ | ≤ 1.0 |
| **Layer 3 — Isolation Forest (ML)** | unsupervised anomaly detection | cap 0.4 |

> **⚠️ หมายเหตุสำคัญ (เพื่อการ defend):** การรวมคะแนนเป็นแบบ **บวกกัน (additive)**
> `total = rule + behavior + iforest` (cap ที่ 1.0) — **ไม่ใช่** weighted average
> 40/30/20/10% และ **ไม่มีชั้น "Context"** — มีแค่ 3 ชั้น + Layer 4 (Aggregation)
> ที่รวมคะแนนแล้วตัดสิน decision ตาม threshold (block ≥0.85, challenge ≥0.7,
> warn ≥0.5) ตาม Freeman 2016 / F-RBA 2024

---

## 5. ส่วนที่ 3 — เหตุผลที่ทำให้เกิดความเสี่ยง (Evidence · Risk Reasons)

**ตอบคำถาม: "ทำไมถึงเสี่ยง? มีหลักฐานอะไร?"**

list เหตุผลที่แต่ละชั้นจับได้ แบบ structured (feature + รายละเอียด) เช่น:

- `failed_logins_24h = 11 >= 10 (hard block)` — login ผิด 11 ครั้งใน 24 ชม.
- `is_new_country` — login จากประเทศที่ไม่เคยมา
- `is_new_device` — อุปกรณ์ใหม่
- `impossible_travel: TH → US in 0.5h` — เดินทางเร็วเกินจริง

ดึงจาก `login_sessions.risk_reasons` (list ที่ rule_engine + behavior_profiling เขียนไว้)

---

## 6. ส่วนที่ 4 — ไทม์ไลน์เหตุการณ์ (Timeline)

**ตอบคำถาม: "เกิดอะไรขึ้นบ้างตามลำดับเวลา?"**

เหตุการณ์ด้านความปลอดภัยของผู้ใช้คนนี้ รอบเวลา login (±10–30 นาที) เช่น
บล็อกโดย ML → บังคับ MFA → ยืนยันผ่าน — ดึงจาก `audit_logs` (append-only)
cap 20 เหตุการณ์กัน list ยาวเกิน

---

## 7. ส่วนที่ 5 — การตอบสนองของระบบ (System Response)

**ตอบคำถาม: "แล้วระบบทำอะไรต่อ? ออก token ไหม?"**

| ฟิลด์ | ความหมาย |
|---|---|
| **Decision** | ผลตัดสิน (block/challenge/would_*) |
| **Action Taken** | สิ่งที่ระบบทำ (ปฏิเสธ token / บังคับ MFA / บันทึกเฉยๆ ถ้า shadow) |
| **Token Issued** | ออก Access Token ไหม (จาก `jti` มีค่าไหม) |
| **Session Created** | สร้าง session ไหม |
| **Refresh Token** | ออก refresh token ไหม (จาก `refresh_id`) |
| **สถานะ session** | ยังเปิด / ถูกตัด / หมดอายุ |
| **Log Saved** | บันทึกใน Audit Log แล้ว (เสมอ) |
| **Shadow Mode note** | ⚠️ ถ้าเป็น would_* = RBA จับได้แต่ยังไม่ enforce จริง (token ออกปกติ) |

---

## 8. ส่วนที่ 6 — แนวทางการจัดการ (Recommended Actions)

**ตอบคำถาม: "admin ต้องทำอะไร? ปิดช่องโหว่ตรงไหน?"**

ปุ่ม action **จัดกลุ่มตามหมวด** ให้เห็นว่าต้องปิดช่องโหว่ที่ layer ไหน:

| หมวด | action | ทำอะไรจริง | ชนิด |
|---|---|---|---|
| **🎯 Root Cause** | บล็อกการเข้าถึงทันที | เพิกถอน Token + ปิด session | execute `revoke_session` |
| **🔑 Authentication** | บังคับตั้ง Passkey ใหม่ | revoke passkey ทั้งหมด → enroll ใหม่ | execute `reset_passkey` |
| **🌐 Network** | บล็อก IP นี้ | เพิ่ม IP เข้า blacklist ถาวร | execute `block_ip` |
| **👤 Account** | ตรวจสอบบัญชีผู้ใช้ / แจ้งเตือน | ดูโปรไฟล์ / ส่งอีเมลแจ้ง | navigate / execute `notify_user` |
| **🧩 Subsystem** | ทบทวน Access Policy | ไปหน้าตั้งค่าระบบย่อยเป้าหมาย | navigate |
| **⚙️ Configuration** | ทบทวนการตั้งค่าระบบ | ไป ML threshold / auth policy | navigate |

> ทุก action ที่ mutate ต้องผ่าน **step-up gate** (`incident_action`) — 403 ถ้ายัง
> ไม่ยืนยัน Passkey → frontend เปิด popup ยืนยันในหน้า แล้ว retry อัตโนมัติ

---

## 9. ส่วนที่ 7 — ข้อมูลเพิ่มเติม (Additional Information · 7 วัน)

**ตอบคำถาม: "ผู้ใช้คนนี้มีประวัติเสี่ยงบ่อยไหม?"**

สถิติ 7 วันของผู้ใช้ — คำนวณสดจาก `login_sessions`:

| ฟิลด์ | ความหมาย |
|---|---|
| **Incidents (7d)** | จำนวน incident ใน 7 วัน |
| **Avg Risk (7d)** | ค่าเฉลี่ย risk_score |
| **Blocked (7d)** | จำนวนที่ถูก block |
| **Passkey Success** | % passkey login ที่สำเร็จ |

> **Last Password Login** = "—" เสมอ เพราะระบบนี้**ไม่มี password login** (Google
> OAuth + Passkey เท่านั้น) — เก็บไว้เพื่อความครบของ template

---

## 10. ส่วนที่ 8 — ลิงก์ที่เกี่ยวข้อง (Related Links)

ทางลัดไปหน้าที่เกี่ยวข้อง:
- **ดูประวัติการเข้าถึงของผู้ใช้** → เข้าหน้าผู้ใช้คนนั้น **ตรงๆ** (`/users/{user_id}`)
  ไม่ใช่ list กรอง — เห็นสิทธิ์ระบบย่อย + ประวัติ login ทันที
- **ดู Audit Log** → `/audit`
- **ดู ML / Risk Dashboard** → `/ml`

> ปุ่ม "ตรวจสอบบัญชีผู้ใช้" ในส่วนที่ 6 ก็ลิงก์ไปหน้าเดียวกัน (`/users/{user_id}`)

---

## สรุป flow การใช้งาน

```
login เสี่ยง (RBA flag)
   → โผล่ในหน้า "เหตุการณ์เสี่ยง" (list)
   → admin คลิกดู Incident Detail
   → อ่าน: เข้าทางไหน (1) · เสี่ยงเพราะอะไร (2,3) · เกิดอะไรตามลำดับ (4)
           · ระบบทำอะไร (5) · ผู้ใช้เสี่ยงบ่อยไหม (7)
   → ตัดสินใจ + กดปุ่มจัดการ (6) — ยืนยัน Passkey → ทำจริง
```
