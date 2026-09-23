# Frontend Design Brief — Central Auth Hub

> เอกสารนี้คือ **north star** สำหรับ redesign frontend ทั้งหมด (~29 routes + ~11 shared components).
> ป้อนให้ `claude-design` / frontend-design skill ทีละหน้า โดยอ้าง **Design System** + section ของหน้านั้น.
> เป้าหมาย: ธีมใหม่ที่ **โดดเด่น เป็นเอกลักษณ์** แต่ยัง **อ่านง่าย ใช้งานจริงกับ data หนาแน่น** ได้.

โปรเจค: ระบบ Identity & Permission + Security Operations ของมหาวิทยาลัย
(OAuth/JWT/RBAC · 4-Layer ML risk scoring · audit hash-chain · realtime monitoring).
ผู้ใช้หลัก = **admin** (Hub Console) + **developer** (teacher/staff — Developer Portal).

---

## 1. Design Vision — "SIGNAL ROOM"

แนวคิด: **ห้องเฝ้าระวังสัญญาณ (Security Signal Room)** — รวมความรู้สึก *command deck*
(เฝ้าระวัง realtime, จริงจัง, แม่นยำ) เข้ากับ *editorial* (อ่านสบาย มีลำดับชั้นชัด).

**One memorable thing:** ทุกอย่างที่ "มีชีวิต" (online, risk, alert, login สด) เต้นเป็น **สัญญาณ (signal)** —
pulse dot, สัน hairline เรืองแสง, ตัวเลขขยับแบบ tabular mono. ระบบรู้สึก "กำลังหายใจ" ตลอดเวลา.

**Dual-surface (เอกลักษณ์หลัก):**
- **Command chrome (เข้ม)** — sidebar, control bar, live panel: พื้นหมึกเข้ม + accent สัญญาณ → "กำลังเฝ้าดู"
- **Document surface (สว่าง)** — ตาราง ฟอร์ม รายละเอียด: พื้นสว่าง อ่านนาน ๆ ได้ → "ทำงานจริง"

> หน้า `/activity` ที่มีอยู่ (control bar เข้ม + board สว่าง) = prototype ของทิศทางนี้ — ใช้เป็น reference.

**Tone:** precise · alive · trustworthy · ไม่เล่นเยอะจนรก. ความ "wow" มาจาก *การจัดลำดับชั้น + motion ที่ตรงจุด*
ไม่ใช่สีฉูดฉาด.

---

## 2. Design System

### 2.1 Color tokens
ใช้ CSS variables (เพิ่มใน `globals.css` / tailwind config). ตัวเลขเป็น HSL/HEX ปรับได้.

```
/* Canvas / surfaces */
--canvas-deep:   #0a0e17   /* command background (sidebar/control bar) */
--canvas-panel:  #111726   /* glass panel บนพื้นเข้ม */
--paper:         #f7f8fa   /* document background (เนื้อหา) */
--paper-card:    #ffffff   /* card */

/* Ink scale (เทา-น้ำเงิน) — ใช้ทั้ง text + border */
--ink-900..050  /* มีอยู่แล้วใน tailwind (ink-*) — คง scale เดิม */

/* Signature accent — "SIGNAL" (เลือก 1 ตัวเป็นพระเอก) */
--signal:        #34e8c4   /* mint-cyan เรืองแสง — live/active/primary action */
--signal-2:      #13b89a   /* deep mint — hover/border */

/* Risk gradient (สำคัญ — ใช้ทั่วระบบ ML/login) */
--risk-low:   #10b981  (<0.30)   emerald
--risk-mid:   #f59e0b  (0.30-0.60) amber
--risk-high:  #f97316  (0.60-0.85) orange
--risk-crit:  #e11d48  (>=0.85)   rose

/* Semantic */
--ok:#10b981  --warn:#f59e0b  --danger:#e11d48  --info:#0ea5e9  --violet:#8b5cf6
```
**กฎ:** accent `--signal` ใช้ **น้อยแต่เด็ด** (ปุ่มหลัก, live dot, active nav). อย่าเกลื่อน.
Risk ใช้ gradient ทุกที่ที่โชว์คะแนน (meter/score/decision) — สร้างภาษาภาพเดียวกันทั้งระบบ.

### 2.2 Typography
หลีกเลี่ยง Inter/Roboto/Arial. ใช้คู่ที่มีคาแรกเตอร์ + รองรับไทย:

| บทบาท | ฟอนต์ | ใช้กับ |
|---|---|---|
| **Display** | `Kanit` / `Anuphan` (700-800) | หัวข้อใหญ่, KPI number, hero |
| **Body** | `IBM Plex Sans Thai` (400-600) | เนื้อหา, label, ปุ่ม |
| **Mono** | `IBM Plex Mono` / `JetBrains Mono` | **ทุกค่าเทคนิค**: ID, IP, score, jti, timestamp, email-as-data, code |

**กฎเอกลักษณ์:** ค่าตัวเลข/ตัวระบุทุกตัว = mono + `tabular-nums`. ทำให้ระบบดู "เป็นเครื่องมือวิศวกร".
Type scale: 11/12/13/14 (body) · 17/20/22 (heading) · 28-44 (display/KPI). letter-spacing แน่นนิดในหัวข้อใหญ่.

### 2.3 Space · radius · elevation
- Spacing: ฐาน 4px. การ์ด padding 20-24. ช่องไฟ section 24-32.
- Radius: `lg`=12 (card) · `xl/2xl`=16-22 (panel/hero) · `full` (chip/dot). มุมคม 0-4 สำหรับ data cell.
- Border: hairline 1px `--ink-200` (สว่าง) / `rgba(148,178,224,.14)` (เข้ม). **ใช้ border มากกว่า shadow**.
- Elevation: เงา soft ต่ำ ๆ (`0 1px 2px`, card) — เงาแรงเฉพาะ modal/floating. บนพื้นเข้มใช้ glow accent แทนเงา.
- Glass (เฉพาะพื้นเข้ม): `backdrop-blur(14px)` + gradient panel + inset highlight 1px.

### 2.4 Motion
- **Page load:** staggered reveal (fade+translateY 8-16px, delay 60-120ms ต่อบล็อก). ครั้งเดียว ตอนเข้า.
- **Live:** pulse dot (2s) สำหรับสถานะสด · ตัวเลข tick (mono) · sweep highlight แถวใหม่ (เขียวจางหายใน 2.5s — มีใน /activity แล้ว).
- **Hover:** ปุ่มหลัก lift -2px + glow · row tint เบา · arrow slide.
- หลีกเลี่ยง animation ฟุ่มเฟือยทุกจุด — เน้น **high-impact moment** ตอนโหลด + ของที่สดจริง.

### 2.5 Signature elements (ใช้ซ้ำให้จำได้)
1. **Signal dot** — จุดเรืองแสง + ping ring สำหรับ live/online/alert.
2. **Hairline rule** — เส้น gradient จาง (`transparent→line→transparent`) คั่น section.
3. **Risk meter** — แท่งแนวนอน 0-1 ระบายสีตาม risk gradient + ตัวเลข mono (มีใน /activity).
4. **Mono data chips** — IP/ID/score เป็น chip mono พื้นจาง.
5. **Grain + corner glow** (พื้นเข้ม) — noise overlay opacity .05 + radial glow มุมจอ.
6. **Avatar token** — สี HSL จาก hash อีเมล (deterministic) — มีใน /activity แล้ว.

---

## 3. Core components (redesign ก่อน — ทุกหน้าใช้ร่วม)

| Component | ทิศทาง redesign |
|---|---|
| **Sidebar** | พื้น command เข้ม · โลโก้ + signal dot · nav active = แท่ง accent + glow · badge แจ้งเตือน pulse · กลุ่ม Admin/Developer คั่นด้วย hairline |
| **Topbar** | บางลง · title display font · breadcrumb mono เล็ก · user chip + avatar token · ปุ่ม logout ghost · sticky + hairline ล่าง |
| **StatsCard / Kpi** | แท่งสี accent ซ้าย · label mono uppercase · ตัวเลข display ใหญ่ tabular · sub mono · variant: live(pulse) / danger(สี) |
| **DataTable** | header mono uppercase พื้นจาง · row hairline · hover tint · zebra เบา ๆ optional · sticky header · empty/loading/error state สวย · cell ค่าเทคนิค = mono |
| **Badge** | shape chip · tone: ok/warn/danger/info/signal/violet/default · outline variant สำหรับ would_* · icon นำหน้าได้ |
| **SlidePanel / Modal** | glass บนพื้นมืด overlay · entrance spring · header + ปุ่มปิด · ใช้กับ detail/form/confirm |
| **Buttons** | primary = signal gradient + lift · secondary = ghost border · danger = rose · mono สำหรับปุ่มเทคนิค |
| **Inputs / Select** | hairline border · focus ring signal · mono สำหรับ field ค่าเทคนิค · file-drop แบบ dashed |
| **LineChart** | *(มีอยู่แล้ว — ใช้แทนกราฟแท่งทุกหน้า)* กราฟเส้นสไตล์สเปรดชีต (inline SVG) — hourly/trend ทุกที่ที่เคยเป็น bar chart |
| **Heartbeat** | pulse indicator แบบ live dot+ring สำหรับสถานะสด (online/active) — ใช้คู่กับ signal dot |
| **PasskeyNudgeBanner** | banner เตือนตั้ง Passkey — ใช้ใน `/auth/setup` + จุดอื่นที่ต้องกระตุ้นให้ตั้งค่า |
| **StepupTotpProvider** | context/provider สำหรับ TOTP fallback ของ step-up (ใช้คู่กับ SlidePanel confirm) |

---

## 4. Page-by-page briefs

> แต่ละหน้า: **Route · Title · ผู้ใช้ · หน้าที่ · Data/Endpoints · โมดูลหลัก · เป้า redesign · States**
> Priority: [หลัก] = หน้าหลัก redesign ก่อน · [รอง] = รอง · [utility] = utility

### 4.1 Hub Console (admin)

#### [หลัก] `/dashboard` — "ภาพรวมระบบ"
- **ผู้ใช้/หน้าที่:** admin landing — สรุปสุขภาพระบบ + ทางลัด
- **Data:** `/admin/overview`, `/admin/users/count`, `/admin/notifications/count`, `/admin/auth-policy`, `POST /admin/subsystems/health/emit-summary-now`
- **โมดูล:** action bar (เช็คสุขภาพ) · notification banner (action required) · KPI users/subsystems/logins · **LoginMethodsCard** (Google/Passkey toggle + step-up) · stat grids
- **เป้า:** ทำเป็น "command overview" — KPI สด, signal บนของที่ต้องสนใจ (blocked/unread), จัดลำดับชั้นให้ตาไปที่ของสำคัญก่อน. รวม cluster เป็น 3 โซน: สถานะ / งานค้าง / ตั้งค่า
- **States:** loading skeleton KPI · error banner · empty (ไม่มี unread = ซ่อน banner)

#### [หลัก] `/activity` — "การเข้าใช้งาน (Realtime)"  *(prototype ของธีม — ใช้เป็นต้นแบบ)*
- **หน้าที่:** feed login ทั้งระบบ pivot ด้วย email — ออนไลน์สด + ประวัติ
- **Data:** `/admin/activity` (active/items/kpis/channels/hourly), `/admin/subsystems`
- **โมดูล:** control bar เข้ม (LIVE pulse + window 1h/24h/7d/30d + refresh) · KPI strip (online/total/blocked/mfa/avg-risk) · panel "กำลังออนไลน์" (ticker เวลาสด) · hourly **LineChart** (เส้น SVG แทนแท่งเดิม) · filters · history feed (risk meter, channel chip, decision badge, geo, device, relative time, sweep แถวใหม่)
- **เป้า:** คงทิศทางนี้ ขัดเกลา polish เป็น **มาตรฐานของทั้งระบบ**
- **States:** loading · empty online · empty history

#### [หลัก] `/incidents` — "เหตุการณ์เสี่ยง" *(SOC — เพิ่มใหม่)*
- **หน้าที่:** ศูนย์ incident สำหรับ session ที่มีความเสี่ยง/ถูก block/mfa — forensic timeline ต่อ session
- **Data:** `/admin/incidents` (filter hours/decision/q), `/admin/incidents/{id}`
- **โมดูล:** filter bar (ช่วงเวลา/decision/ค้นหา) · list การ์ด (risk meter, decision badge, email, เวลา) · **detail modal — forensic 2-strand timeline** (สาย "account activity" คู่กับสาย "system/admin response" วางคู่กันตามเวลา) · เวลาแสดงเป็นไทย (parseUTC → Asia/Bangkok, พ.ศ.)
- **เป้า:** timeline 2 สายเป็นจุดขาย — ให้เห็นเหตุ-ผลชัด (user ทำอะไร → ระบบ/admin ตอบสนองอะไร) ในหน้าต่างเวลาเดียวกัน · risk gradient เด่นบนการ์ด
- **States:** loading · empty (ไม่มี incident ในช่วงที่เลือก) · modal loading

#### [หลัก] `/users` — "ผู้ใช้งาน"
- **หน้าที่:** CRUD ผู้ใช้ (100+ คน) — student/teacher/staff/admin
- **Data:** `/admin/users` (filter type/faculty), `/admin/users/count`, `POST/PATCH/DELETE /admin/users/{id}` (step-up)
- **โมดูล:** filter bar (type/faculty/search) · count chips ต่อ type · ตาราง (avatar, email mono, type badge, status, identifier) · UserFormModal (create/edit) · delete confirm + step-up
- **เป้า:** ตารางอ่านง่ายระดับ data-dense · type เป็นภาษาภาพเดียว (สี/ไอคอนต่อ role) · modal เป็น SlidePanel glass · เน้น scan เร็ว
- **States:** loading rows · empty filter · row busy (step-up verifying overlay)

#### [หลัก] `/users/[id]` — "User 360" *(เพิ่มใหม่ — หน้าหนัก)*
- **หน้าที่:** มุมมองรวมของ user 1 คน — access + login history + passkeys + summary
- **Data:** access list, login sessions, passkeys, summary ของ user (endpoint กลุ่ม `/admin/users/{id}/...`)
- **โมดูล:** profile header · **Access Overview เป็น donut** (แบ่งตาม scope/หมวด — scope เป็นชื่อฟิลด์ PII จริง จัดกลุ่มก่อนแสดง) · login history table (risk meter, decision, device, geo, relative time — ใช้ `parseUTC`/`relTime` จาก `lib/format.ts` เป็น canonical กัน B53) · passkey list · summary card
- **เป้า:** เป็นหน้า "สืบสวน user เดียว" ที่อ่านครบไม่ต้องสลับหน้า · donut + timeline ให้เห็น pattern เร็ว · ใช้ mono กับค่าเทคนิคทุกจุดตาม design system
- **States:** loading section ต่อ section (access/history/passkeys โหลดแยกกันได้) · empty history/passkeys

#### [หลัก] `/subsystems` — "ระบบย่อย" *(redesign แล้ว — ทำ KPI + การ์ดแล้ว 2026-08)*
- **หน้าที่:** list subsystem ทุกตัว — filter all/pending/active/suspended
- **Data:** `/admin/subsystems?status=`
- **โมดูล:** ~~ตาราง~~ → **KPI strip + การ์ดต่อ subsystem** (ชื่อ, client_id mono, status badge, whitelist count, owner) — ข้อมูลเดิมครบทุก field แค่เปลี่ยน layout · tab filter · ลิงก์ไป detail
- **เป้า:** status เป็น signal (active=pulse เขียว, suspended=rose, pending=amber) · client_id mono chip · count เป็น KPI เล็ก — **ใช้เป็น reference สำหรับหน้าอื่นที่จะทำ card-based list ต่อ** (เช่น `/developer/subsystems`)

#### [หลัก] `/subsystems/[id]` — "Subsystem detail" *(หน้าหนักสุด)*
- **หน้าที่:** จัดการ subsystem 1 ตัว (admin override)
- **Data:** `/admin/subsystems/{id}/stats|active-sessions|audit|suspend|resume|sessions/{id}/revoke`, `/developer/subsystems/{id}/...` (whitelist/CSV/role/edit/rotate/transfer)
- **โมดูล:** status hero + ปุ่ม suspend/resume · stats (login/decision/active) · edit modal (scope/redirect/roles/webhook → change request) · rotate secret · **whitelist** (เพิ่มทีละคน + **CSV upload** + bulk role) · **active sessions panel** (+ revoke 3 ระดับ) · audit feed · transfer owner
- **เป้า:** แบ่ง tab/section ชัด (Overview · Whitelist · Sessions · Audit · Settings) · active sessions = live panel เข้ม · งานอันตราย (suspend/rotate/revoke) มี visual weight + step-up ชัด
- **States:** เยอะ — ทุก mutation มี loading/verifying/result; empty whitelist; empty sessions

#### [รอง] `/subsystems/pending` — pending subsystem approvals
- **หน้าที่:** อนุมัติ/ปฏิเสธ subsystem ที่รอ (status=pending)
- **Data:** `/admin/subsystems?status=pending`, approve/reject
- **โมดูล:** การ์ดต่อ subsystem (ข้อมูล + ปุ่ม approve/reject) · ว่าง = empty state
- **เป้า:** การ์ด review อ่านครบในใบเดียว · ปุ่มตัดสินใจชัด (approve=signal, reject=ghost danger)

#### [รอง] `/pending-requests` — "คำขอ Approve · Developer Change Requests"
- **หน้าที่:** triage คำขอแก้ของ developer (edit_scope/roles/redirect/rotate_secret/whitelist) → approve/reject
- **Data:** `/admin/change-requests`, `/admin/change-requests/{id}/approve|reject`
- **โมดูล:** list คำขอ (type chip, subsystem, diff old→new, ผู้ขอ, เวลา) · approve/reject + note · admin override
- **เป้า:** แสดง **diff old→new** ชัด (สำคัญ) · type เป็น icon+สี · เรียงตามความเร่งด่วน

#### [รอง] `/recovery-tickets` — "คำขอกู้บัญชี" *(เพิ่มใหม่)*
- **หน้าที่:** admin triage คำขอกู้บัญชีจาก user ที่ทำ passkey หาย/เข้า email ไม่ได้ (ต่อจาก recovery ticket flow ที่ user ยื่นเอง)
- **Data:** recovery ticket list + approve (มี `recovery_level`, ต้อง step-up ก่อน action) → gen recovery link
- **โมดูล:** list ticket (email, เหตุผล, เวลา, recovery_level badge) · approve → แสดง one-time recovery link (คล้าย secret retrieval — copy ครั้งเดียว) · step-up gate ก่อน approve
- **เป้า:** ระดับความเสี่ยง (recovery_level) เป็น signal ชัด · approve flow ต้องรู้สึกหนักแน่น (step-up + confirm) เพราะเป็นทางเลี่ยง passkey · link ที่ gen ออกมาเน้น "one-time" เหมือน secret retrieval pattern
- **States:** loading · empty (ไม่มีคำขอค้าง) · busy ตอน approve/verifying

#### [หลัก] `/ml` — "ML / ความผิดปกติ"
- **หน้าที่:** ศูนย์ ML — session ผิดปกติ, decision distribution, feedback ground-truth
- **Data:** `/admin/ml/overview`, `/admin/ml/sessions/...`, feedback label
- **โมดูล:** KPI (anomaly rate, decision breakdown) · session list (risk meter, SHAP top features, decision) · ปุ่ม label false/true positive · ลิงก์ไป user profile
- **เป้า:** risk gradient เด่น · SHAP เป็น bar contribution (per-feature) · "เฝ้าระวัง" feel — ของเสี่ยงเด้งขึ้นบน
- **States:** loading · empty (ไม่มี anomaly)

#### [รอง] `/ml/threshold` — "Threshold Tuning"
- **หน้าที่:** ปรับ threshold risk (challenge/block) + preview ผลกระทบ + SHAP
- **Data:** `/admin/ml/threshold/preview`
- **โมดูล:** sliders (challenge/block threshold) · preview histogram ของ session ที่ค่าจะเปลี่ยน decision · SHAP explainer
- **เป้า:** slider + histogram interactive · เห็นผลกระทบ realtime ก่อน apply · เส้น threshold ลากบน distribution

#### [รอง] `/ml/users/[id]` — per-user ML profile
- **หน้าที่:** ประวัติ risk + behavior ของ user 1 คน
- **Data:** `/admin/ml/users/{id}`
- **โมดูล:** timeline login + risk · behavior profile (typical hour/geo/device) · session ล่าสุด
- **เป้า:** timeline เป็น sparkline risk · baseline vs anomaly เปรียบเทียบเห็นชัด

#### [รอง] `/api-alerts` — "API Alerts"
- **หน้าที่:** rule-based API anomaly (excessive req, high error, probing, bot)
- **Data:** `/admin/api-alerts`, `/scan`, `/{id}/resolve`
- **โมดูล:** alert list (rule chip, severity, IP mono, detail JSON, เวลา) · resolve · ปุ่ม scan ตอนนี้ · filter severity
- **เป้า:** severity เป็น signal (critical=rose pulse) · detail expandable · IP ลิงก์ไป blacklist

#### [รอง] `/ip-blacklist` — "IP Blacklist"
- **หน้าที่:** จัดการ IP ที่ block
- **Data:** `/admin/ip-blacklist`, `/{id}` (delete), `POST .../upload`, `.../refresh-ipsum`
- **โมดูล:** ตาราง IP (ip mono, reason, ผู้เพิ่ม, เวลา) · เพิ่มเดี่ยว · upload list · refresh จาก ipsum feed · ลบ
- **เป้า:** IP mono เด่น · source (manual/ipsum) เป็น chip · จำนวนเป็น KPI

#### [รอง] `/audit` — "Audit Log"
- **หน้าที่:** viewer audit ทั้งระบบ (hash-chain, append-only)
- **Data:** `/admin/audit` (filter action/actor/target, paginate)
- **โมดูล:** filter bar · ตาราง (เวลา, actor email, action chip tone, target, IP) · row detail (metadata JSON) · pagination
- **เป้า:** action tone ตามกลุ่ม (login/approve/revoke/fail) · timeline feel · detail panel อ่าน metadata ง่าย · เวลาเป็น Asia/Bangkok
- **States:** loading · empty filter · pagination

#### [รอง] `/notifications` — "แจ้งเตือนทั้งหมด"
- **หน้าที่:** ศูนย์แจ้งเตือน (approval/ml/api/health) · read state per admin
- **Data:** `/admin/notifications`, `/count`, `/mark-read`, `/mark-unread`, `/clear-all`
- **โมดูล:** category filter chips · list การ์ด (icon ต่อ category, unread เด่น, เวลา, ลิงก์ไปต้นทาง) · mark read/unread · clear all
- **เป้า:** unread มี signal · category สีเดียวกับ sidebar badge · จัดกลุ่มตามวัน

#### [utility] `/account` — "บัญชีของฉัน" *(เพิ่งทำใหม่)*
- **หน้าที่:** profile admin + จัดการ Passkey + backup codes
- **Data:** `/api/me`, `/account/passkeys/*`, backup-codes
- **โมดูล:** profile card (avatar, role, faculty, badge) · passkey list (เพิ่ม/ลบ/เปลี่ยนชื่อ) · backup codes status + regenerate · BackupCodesModal
- **เป้า:** profile hero สวย · passkey card เป็น device chip (platform/cross-platform icon) · งานปลอดภัยมี weight
- **หมายเหตุ:** `/account/security` = redirect → `/account` (ไม่ต้อง design)

#### [utility] `/auth/setup` — Passkey nudge หลัง login *(เพิ่มใหม่)*
- **หน้าที่:** โผล่หลัง login ครั้งแรก/ยังไม่มี passkey — ชวนตั้ง Passkey ก่อนเข้าใช้งานจริง (later/never → redirect ไปหน้าแรกตาม role: admin→`/dashboard`, developer→`/developer/subsystems`)
- **โมดูล:** `PasskeyNudgeBanner` component · ปุ่ม ตั้งตอนนี้ / ทีหลัง / ไม่ต้องถามอีก
- **เป้า:** friendly ไม่บังคับจนรำคาญ แต่สื่อประโยชน์ชัด (ความปลอดภัย + เร็วกว่า) — ใช้ Signal Room โทนอบอุ่นกว่าหน้า login

### 4.2 Auth (public/pre-login)

#### [หลัก] `/auth/login` — admin login
- **หน้าที่:** login admin — Passkey + Google ตาม **auth-policy** (ซ่อนปุ่มที่ปิด)
- **Data:** `/api/hub/auth/policy`
- **โมดูล:** brand hero · ปุ่ม Passkey (email-first + discoverable) · ปุ่ม Google · recover link · เคารพ policy
- **เป้า:** **first impression** — ใช้ Signal Room เต็มที่ (พื้นเข้ม, gradient mesh, grain, staggered reveal). มี backend `_login_chooser_html` (subsystem) ที่ทำธีมนี้แล้ว → ใช้ภาษาเดียวกัน
- **States:** policy loading · passkey unsupported · error (anti-enumeration generic)

#### [utility] `/auth/callback` — OAuth token handoff
- **หน้าที่:** รับ token หลัง OAuth → set cookie → redirect. แทบไม่มี UI
- **เป้า:** loading state สวย (spinner + brand) + error fallback

#### [รอง] `/auth/passkey/recover` — กู้บัญชี Passkey
- **หน้าที่:** backup code / email OTP / regen codes → ลบ passkey เก่า
- **โมดูล:** tab (backup/otp/regen) · email + code · success + return_to (กลับ subsystem login) · CodesAck (copy/download/ack)
- **เป้า:** มี backend dark version (`/oauth/passkey/recover`) ที่สวยแล้ว → frontend ให้ตรงภาษาเดียวกัน
- **States:** sending · success card (มี animation แล้ว) · error

#### [รอง] `/auth/passkey/stepup` — step-up re-auth
- **หน้าที่:** ยืนยันตัวตนก่อน critical action (passkey → fallback OTP) → trusted 15 นาที → กลับ return_to
- **โมดูล:** passkey prompt · OTP fallback · return_to
- **เป้า:** focus เดียว, มี weight ของ "ด่านความปลอดภัย" · ใช้ Signal Room

### 4.3 Developer Portal (teacher/staff)

#### [หลัก] `/developer/subsystems` — "ระบบของฉัน"
- **หน้าที่:** list subsystem ที่ตัวเองเป็น owner
- **โมดูล:** การ์ด/ตาราง subsystem (status, whitelist count, client_id) · ปุ่มลงทะเบียนใหม่ · ลิงก์ไป detail
- **เป้า:** ภาษาเดียวกับ admin /subsystems แต่ scope แค่ของตัวเอง · empty = CTA ลงทะเบียน

#### [รอง] `/developer/subsystems/new` — ลงทะเบียนใหม่
- **หน้าที่:** ฟอร์มสร้าง subsystem → ได้ one-time secret retrieval URL
- **โมดูล:** ฟอร์ม (ชื่อ, redirect_uris, scope checkboxes, allowed_roles, webhook) · ผลลัพธ์ + secret URL (one-time) + ลิงก์ไป detail
- **เป้า:** ฟอร์ม multi-section อ่านง่าย · scope เป็น checkbox card มีคำอธิบาย · success state เน้น "เก็บ secret เดี๋ยวนี้"

#### [หลัก] `/developer/subsystems/[id]` — จัดการ subsystem ของฉัน
- **หน้าที่:** เหมือน admin detail แต่ owner — แก้ → สร้าง change request (รอ admin approve)
- **Data:** `/developer/subsystems/{id}/whitelist|whitelist/user|rotate-secret|transfer-owner|...`
- **โมดูล:** status · whitelist (เพิ่ม/**CSV**/bulk role) · edit (→ change request) · rotate secret (→ request) · pending requests ของตัวเอง
- **เป้า:** ให้รู้ชัดว่าอะไร "apply ทันที" vs "ต้องรอ approve" · CSV upload เด่น · ภาษาเดียวกับ admin detail

#### [utility] `/developer/account` — "บัญชีของฉัน" (developer) *(เพิ่มใหม่)*
- **หน้าที่:** คู่ขนานกับ admin `/account` — profile ของ developer (teacher/staff) เท่านั้น (ไม่มี passkey/backup-codes management เต็มแบบ admin — ดู scope จริงในโค้ดก่อน implement)
- **เป้า:** ใช้ `AccountView` component เดียวกับ `/account` ถ้า scope ตรงกัน — ต่างกันแค่ nav context (Developer Portal ไม่ใช่ Hub Console)

---

### 4.4 Utility / Mockup

#### [utility] `/ui-mockup/[screen]` — gallery mockup *(เพิ่มใหม่ — ไม่ใช่หน้า console จริง)*
- **หน้าที่:** เก็บ mockup 2 ภาษา (TH/EN) ของหน้าจอต่าง ๆ รวมถึง live-auth login mockup — ใช้ทดลอง direction ก่อนทำจริง ไม่ผูก data จริงเสมอไป
- **เป้า:** ไม่ต้อง redesign ตาม brief นี้โดยตรง — เป็นพื้นที่ prototype/reference ที่มีอยู่แล้ว ใช้ดูไอเดียประกอบตอนทำหน้าอื่น ๆ

---

## 5. Cross-cutting

- **States บังคับทุกหน้า:** loading (skeleton ไม่ใช่แค่ spinner) · empty (มี icon + ข้อความ + CTA) · error (banner กู้ได้) · busy/verifying (overlay ตอน step-up).
- **Responsive:** sidebar ยุบเป็น drawer < lg · ตาราง overflow-x หรือ stack เป็น card บน mobile · KPI grid 2→5 cols.
- **Thai-first:** ฟอนต์ไทยต้องคม · บรรทัด/line-height เผื่อสระบน-ล่าง · ตัวเลข/เทคนิคใช้ mono (อ่านง่ายข้ามภาษา).
- **A11y:** contrast ผ่าน AA (โดยเฉพาะ accent บนเข้ม) · focus ring ชัด · ปุ่ม/ลิงก์มี label · ไม่สื่อด้วยสีอย่างเดียว (มี icon/ข้อความ).
- **Dark/light:** ใช้ dual-surface ตามนิยาม — **อย่าทำมืดทั้งหน้าที่เป็นตารางยาว ๆ** (ล้าตา). เข้ม = chrome/live, สว่าง = เนื้อหา.
- **Performance:** chart เป็น inline SVG (ไม่มี lib หนัก) — ตอนนี้ทุกหน้าใช้ **LineChart** (เส้นสไตล์สเปรดชีต แทนกราฟแท่งเดิม, e890b9c) ให้ใช้ component นี้ต่อเป็นมาตรฐาน · motion เป็น CSS · poll realtime เฉพาะหน้าที่ต้อง (activity/dashboard/incidents).
- **Single-domain mode:** frontend + backend ให้บริการจาก origin เดียวกัน (Next.js rewrites proxy backend paths ตรง — จำเป็นสำหรับ WebAuthn RP ID). หน้าที่เป็น Hub-served HTML ล้วน (เช่น dark passkey recover page ที่ backend เสิร์ฟเอง) ใช้ภาษาภาพเดียวกับ Signal Room แต่ไม่ใช่ Next.js component — ถ้า redesign หน้าเหล่านั้นต้องแก้ที่ backend template ไม่ใช่ frontend.

---

## 6. Rollout order (แนะนำ)

1. **Design system + core components** (Sidebar, Topbar, StatsCard, DataTable, Badge, buttons/inputs, tokens) — ทุกหน้าได้ประโยชน์ทันที
2. **`/auth/login`** — first impression + พิสูจน์ธีม
3. **`/activity`** polish → ตั้งเป็นมาตรฐาน (LineChart เป็น pattern มาตรฐานแล้ว)
4. **`/dashboard`** → **`/users`** + **`/users/[id]`** → **`/subsystems`** *(ทำ KPI+การ์ดแล้ว — ใช้เป็น reference)* **+ `/subsystems/[id]`**
5. **`/incidents`** (forensic timeline — SOC priority สูง) → **`/ml` + `/ml/threshold`** (risk gradient เด่น)
6. หน้ารอง: audit · notifications · api-alerts · ip-blacklist · pending-requests · recovery-tickets
7. Developer Portal (4 หน้า: subsystems, subsystems/new, subsystems/[id], account)
8. Utility: account · auth/callback · auth/setup · recover · stepup

---

## วิธีใช้เอกสารกับ claude-design
> ป้อนทีละหน้า เช่น:
> "ใช้ **Design System** (section 2-3) ของ `docs/frontend-design-brief.md` ออกแบบหน้า `/users` (section 4.1)
> ให้ตรงทิศทาง **Signal Room** — dual-surface, mono สำหรับค่าเทคนิค, risk gradient, signature elements.
> โค้ดจริง Next.js 14 + Tailwind, เข้ากับ component ที่มี (Topbar/DataTable/Badge)."
