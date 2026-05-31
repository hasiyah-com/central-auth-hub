# ML Admin Dashboard UI — 4 หน้า (Week 8)

## Context

P1 (backend endpoints) เสร็จแล้วทั้ง 4 ตัว + เพิ่ม 5 columns ใหม่ (os_name, browser, device_type, is_attack_ip, is_account_takeover) ให้ตรง RBA dataset ของ Wiefling 2022
ตอนนี้หน้า ML (`/ml`) เป็นไฟล์เดียว 489 บรรทัด (KPI + histogram + threshold tuning + anomaly table) รวมกันหมด

เป้าหมาย: แยกออกเป็น 4 หน้า/view + เพิ่ม session detail panel + feedback form

---

## ฐานข้อมูลที่เก็บข้อมูลตามฟีเจอร์

**ฐานข้อมูล:** `hub_db` (PostgreSQL, port 5432)
**ตาราง:** `login_sessions`

| Column | Type | หมายเหตุ |
|--------|------|---------|
| id | UUID | Primary key |
| user_id | UUID | FK → users |
| subsystem_id | UUID | FK → subsystems |
| ip | INET | IP address |
| user_agent | Text | Raw UA string |
| geo_country | VARCHAR(50) | รหัสประเทศ (TH, US, ...) |
| geo_city | VARCHAR(100) | ชื่อเมือง |
| os_name | VARCHAR(100) | "Windows 10", "iOS 16.0" (ตรงกับ RBA dataset) |
| browser | VARCHAR(100) | "Chrome 120.0.3538" (ตรงกับ RBA dataset) |
| device_type | VARCHAR(20) | "mobile", "desktop", "tablet", "bot" (ตรงกับ RBA dataset) |
| anomaly_score | NUMERIC(3,2) | 0.00–1.00 |
| decision | VARCHAR(20) | pass/mfa/block/would_mfa/would_block |
| is_attack_ip | BOOLEAN | IP อยู่ใน blacklist (ตรงกับ RBA dataset) |
| is_account_takeover | BOOLEAN | admin ยืนยันว่าเป็น attacker จริง (ตรงกับ RBA dataset) |
| created_at | TIMESTAMP | UTC, indexed |

**ตาราง ground truth:** `ml_feedback`

| Column | Type | หมายเหตุ |
|--------|------|---------|
| id | UUID | Primary key |
| session_id | UUID | FK → login_sessions (unique) |
| label | VARCHAR(20) | false_positive / true_positive / normal_confirmed |
| note | TEXT | หมายเหตุจาก admin |
| marked_by | UUID | FK → users (admin ที่ mark) |
| created_at | TIMESTAMP | UTC |

---

## โครงสร้างไฟล์

```
hub/frontend/
├── components/
│   └── SlidePanel.tsx                          ← ใหม่: reusable slide-in panel
│
├── app/(console)/ml/
│   ├── page.tsx                                ← แก้: refactor เหลือ overview + panel
│   ├── _types.ts                               ← ใหม่: shared types ทุกหน้า ML
│   ├── _components/
│   │   ├── ScoreHistogram.tsx                  ← ใหม่: extract histogram section
│   │   ├── SessionDetailPanel.tsx              ← ใหม่: session detail + feedback form
│   │   └── AnomalyTable.tsx                    ← ใหม่: clickable row table
│   ├── threshold/
│   │   └── page.tsx                            ← ใหม่: threshold tuning (extract จาก ml/page)
│   └── users/
│       └── [id]/
│           └── page.tsx                        ← ใหม่: user timeline

hub/backend/app/routers/
│   └── ml_admin.py                             ← แก้: เพิ่ม user_id ใน top_anomalies
```

**ไฟล์ใหม่ 7 ไฟล์ / แก้ 2 ไฟล์ / ไม่แก้ Sidebar (active detection ทำงานอัตโนมัติ)**

---

## หน้า 1: ML Overview (`/ml`) — refactor page.tsx ที่มีอยู่

**ย้ายออก:** threshold tuning section ทั้งหมด (~140 บรรทัด + SimCell + states)
**เพิ่ม:** row click → slide panel, link card ไป `/ml/threshold`

โครงสร้าง:
```
<Topbar title="ML / ความผิดปกติ" />
<main>
  Header + days selector + shadow mode badge        (เดิม)
  KPI cards x4 (total, anomaly rate, MFA, block)    (เดิม)
  <ScoreHistogram />                                 (extract)
  Link card → "/ml/threshold" แสดง current B/M       (ใหม่)
  <AnomalyTable onRowClick={setSelected} />          (ใหม่)
</main>
<SlidePanel open={!!selected}>
  <SessionDetailPanel session={selected} />          (ใหม่)
</SlidePanel>
```

**AnomalyTable** — render `<table>` เองด้วย class เดียวกับ DataTable แต่เพิ่ม `onClick` + `cursor-pointer` บน `<tr>` (ไม่แก้ shared DataTable เพราะใช้ที่อื่น)

คอลัมน์: User, Score (bar), Decision (badge), Device (icon + browser + OS), IP/Country, Labels (attack_ip / takeover badges), Time

---

## หน้า 2: Session Detail (SlidePanel — popup จากขวา)

**`components/SlidePanel.tsx`** — reusable, pure CSS transition

```tsx
Props: { open: boolean; onClose: () => void; title: string; children: ReactNode }
```

- Width `w-[500px] max-w-full`, z-50, backdrop `bg-ink-900/30`
- ปิดด้วย: X button / คลิก backdrop / ปุ่ม Escape
- Body: `overflow-y-auto` scroll ได้

**`SessionDetailPanel.tsx`** — content ภายใน panel

layout:
1. **Score header** — ตัวเลขใหญ่ + progress bar + decision badge
2. **Detail grid** (2 col) — email, IP, country, OS, browser, device_type, is_attack_ip, is_account_takeover, timestamp
3. **Feedback form** — 3 radio buttons (true_positive / false_positive / normal_confirmed) + textarea note + ปุ่มบันทึก (two-step confirm ตาม pattern เดิม)
4. **Actions** — link "ดูประวัติ user →" ไปที่ `/ml/users/[user_id]`

Data flow feedback:
```
click บันทึก → confirm → POST /admin/ml/sessions/{id}/feedback
  → สำเร็จ: แสดง success message + เรียก onFeedbackSaved() refresh parent
  → ล้มเหลว: แสดง error inline
```

---

## หน้า 3: User Timeline (`/ml/users/[id]`)

**API:** `GET /admin/ml/users/{id}/sessions?days={days}&limit=100`

layout ตาม pattern ของ `subsystems/[id]/page.tsx`:
```
<Topbar title="ประวัติ ML · {user.full_name}" />
<main>
  Breadcrumb: "← ML Overview"
  Hero: ชื่อ, email, user_type badge, days selector

  KPI mini x3: total sessions | avg score | flagged sessions (score >= 0.4)

  Session table (เหมือน AnomalyTable pattern):
    Time, Score (bar), Decision, Device, IP/Country, Labels, Feedback badge
    คลิกแถว → SlidePanel (SessionDetailPanel เดียวกัน แต่ซ่อนปุ่ม "ดูประวัติ user")
</main>
<SlidePanel> ... </SlidePanel>
```

---

## หน้า 4: Threshold Tuning (`/ml/threshold`)

**API:** `GET /admin/ml/threshold/preview?block={b}&mfa={m}&days=30`

layout:
```
<Topbar title="Threshold Tuning" />
<main>
  Breadcrumb: "← ML Overview"
  Header + คำอธิบาย

  2-column layout (เดิม แต่มีพื้นที่มากขึ้น):
    Left: Block slider + MFA slider + current .env values
    Right: Simulated breakdown (pass/mfa/block cards) + Feedback section (TP/FP/precision)

  เพิ่ม: Current vs Proposed comparison แสดง delta
</main>
```

- เอา code จาก threshold section เดิมของ ml/page.tsx มาเต็มๆ (รวม SimCell helper)
- fetch `/admin/ml/overview?days=1` ครั้งเดียวตอน mount เพื่ออ่าน `meta.thresholds` (init slider)
- debounce 300ms เรียก preview API เมื่อ slider เปลี่ยน (pattern เดิม)

---

## Backend Change (1 บรรทัด)

**ไฟล์:** `hub/backend/app/routers/ml_admin.py` — function `ml_overview`, ใน loop top_anomalies

เพิ่ม `"user_id": str(u.id),` หลัง `"session_id": str(sess.id),`

จำเป็นเพราะ: Session Detail Panel ต้องมี link "ดูประวัติ user →" ไปที่ `/ml/users/[user_id]`

---

## Shared Types (`_types.ts`)

```ts
export type Anomaly = {
  session_id: string; user_id: string; user_email: string;
  score: number; decision: string | null;
  ip: string | null; geo_country: string | null;
  os_name: string | null; browser: string | null; device_type: string | null;
  is_attack_ip: boolean; is_account_takeover: boolean;
  created_at: string;
};

export type UserSession = {
  id: string; score: number | null; decision: string | null;
  ip: string | null; geo_country: string | null;
  os_name: string | null; browser: string | null; device_type: string | null;
  is_attack_ip: boolean; is_account_takeover: boolean;
  created_at: string; feedback_label: string | null;
};

// + Overview, ThresholdPreview, UserTimeline, FeedbackResponse types
// + DECISION_TONE map, FEEDBACK_LABELS array
```

---

## Reuse ที่มีอยู่

| ใช้ซ้ำ | จาก | ใช้ที่ |
|--------|-----|------|
| `clientFetch<T>()` | `lib/api.ts` | ทุกหน้า — GET + POST feedback |
| `<Badge tone={...}>` | `components/Badge.tsx` | decision badge, labels, feedback |
| `<StatsCard>` | `components/StatsCard.tsx` | KPI cards (overview + user timeline) |
| `<Topbar>` | `components/Topbar.tsx` | ทุกหน้า |
| `clsx()` | dependency | SlidePanel transition classes |
| Two-step confirm pattern | `subsystems/pending/page.tsx` | feedback submit button |
| Breadcrumb pattern | `subsystems/[id]/page.tsx` | threshold + user timeline |

**ไม่ต้องเพิ่ม dependency ใหม่** — ใช้แค่ React + clsx + Tailwind

---

## ลำดับ Implementation

| Phase | ไฟล์ | หมายเหตุ |
|-------|------|---------|
| 1 | `_types.ts` | shared types ต้องมีก่อน |
| 1 | `components/SlidePanel.tsx` | reusable component |
| 1 | `ml_admin.py` — เพิ่ม user_id | backend 1 บรรทัด |
| 2 | `_components/ScoreHistogram.tsx` | extract จาก page เดิม |
| 2 | `_components/SessionDetailPanel.tsx` | feedback form + detail |
| 2 | `_components/AnomalyTable.tsx` | clickable table |
| 3 | `ml/threshold/page.tsx` | extract threshold section |
| 3 | `ml/users/[id]/page.tsx` | user timeline page |
| 4 | `ml/page.tsx` — refactor | ลบ threshold, ใช้ components ใหม่ |

Phase 4 ทำสุดท้ายเพราะ: ถ้าแก้ page.tsx ก่อนที่ components จะพร้อม หน้าจะพัง

---

## Verification

```bash
# 1. restart backend (เพิ่ม user_id)
docker compose restart hub-backend

# 2. เปิด browser → http://localhost:3000/ml
#    - เห็น KPI + histogram + link card ไป threshold + anomaly table
#    - คลิกแถว → slide panel เปิดจากขวา แสดง detail + feedback form
#    - กดบันทึก feedback → panel แสดง success, ตาราง refresh

# 3. http://localhost:3000/ml/threshold
#    - เลื่อน slider → simulated breakdown อัปเดต (debounce 300ms)
#    - breadcrumb "← ML Overview" กลับหน้าหลัก

# 4. จาก session panel → คลิก "ดูประวัติ user →"
#    - ไปที่ /ml/users/{id}
#    - เห็น user info + session table + คลิกแถวเปิด panel ได้

# 5. ตรวจ Sidebar: ทุก sub-route (/ml, /ml/threshold, /ml/users/xxx)
#    ML nav item ต้อง active (highlight) ทั้งหมด

# 6. responsive: ย่อ browser width → table scroll horizontal, panel full-width
```

---

## หมายเหตุ

- P1 (ML admin endpoints) — เสร็จแล้ว, merged เข้า main
- P2 (Session Downgrade) — plan บันทึกที่ `docs/p2-session-downgrade-plan.md`, รอ Week 9-10
