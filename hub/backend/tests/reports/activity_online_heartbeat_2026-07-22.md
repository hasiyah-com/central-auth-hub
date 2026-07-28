# แก้บั๊กหน้า "การเข้าใช้งาน" — Online detection ด้วย Presence Heartbeat (2026-07-22)

## ปัญหาที่พบ (หน้า `/activity`)

ผู้ใช้รายงาน: "มีผู้ใช้ออนไลน์แต่ไม่มีข้อมูล และชอบค้างข้อมูลเดิม"

ตรวจสอบจากโค้ด + ข้อมูลจริงใน DB พบ 4 สาเหตุ:

| # | อาการ | สาเหตุ (หลักฐาน) |
|---|------|------|
| 1 | "ค้างข้อมูลเดิม" — คนออกไปแล้วยังโชว์ online | `logout_at` แทบไม่เคยถูกเซ็ต (ปิดแท็บไม่ยิง `/auth/logout`) → **271 session ค้าง `logout_at NULL`**. ตัวเดียวที่ดึงออกจาก online คือหน้าต่าง 15 นาที |
| 2 | คน active จริงเกิน 15 นาที "หายไป" | `/auth/refresh` อัปเดตแค่ `jti`/`refresh_id` **ไม่อัปเดต `created_at`** → คนทำงานต่อเนื่อง `created_at` เก่า → หลุด online |
| 3 | "มีออนไลน์แต่ไม่มีข้อมูล" — ghost | `active_cond` กรองแค่ block → session challenge/mfa ที่ไม่ผ่าน step-up (**jti IS NULL = ไม่เคยได้ token**) ถูกนับ online. หลักฐาน: would_mfa 7 ตัว jti NULL ทั้งหมด |
| 4 | หน้าค้าง data เก่าเงียบ ๆ | frontend เมื่อ fetch error → `setError()` แต่ไม่ล้าง `data` → ลิสต์เดิม + pulse เขียวค้าง (ดูเหมือน realtime) |

> **ยืนยันว่า count กับ list ไม่มีทางไม่ตรงกัน** — backend คืน `active_count = len(active)`
> จาก query เดียวกัน (มี test กันไว้)

## วิธีแก้ — Presence Heartbeat (`last_seen_at`)

เปลี่ยนนิยาม online จาก "created_at ภายใน 15 นาที" (proxy) → "เห็น activity จริงภายใน 5 นาที"

### 1. Schema — migration `d4e5f6a7b8c9`
เพิ่ม `login_sessions.last_seen_at` (nullable, index) + backfill = `created_at` (session เดิมไม่หลุด online ทันที)

### 2. bump `last_seen_at` ตอน Hub เห็น activity จริง
- **`POST /auth/heartbeat`** (ใหม่) — console ยิงทุก 60 วิระหว่างเปิดหน้าอยู่ (throttle: เขียนเฉพาะเมื่อ last_seen เก่ากว่า 20 วิ). token เสีย = 200 `{ok:false}` (idempotent, ไม่เด้ง)
- **`/auth/refresh`** — bump `last_seen_at` (refresh = presence จริง)
- session ใหม่: `last_seen_at` NULL ตอนสร้าง → query ใช้ `COALESCE(last_seen_at, created_at)` เป็น fallback

### 3. `active_cond` ใหม่ (`admin.py`)
```python
online_cutoff = now - timedelta(minutes=_ONLINE_WINDOW_MIN)   # 5 นาที
last_activity = func.coalesce(LoginSession.last_seen_at, LoginSession.created_at)
active_cond = and_(
    LoginSession.logout_at.is_(None),
    LoginSession.jti.isnot(None),          # กัน ghost (challenge/mfa ที่ไม่ผ่าน = jti NULL)
    last_activity >= online_cutoff,        # presence heartbeat แทน created_at
    LoginSession.decision.notin_(_BLOCKED_DECISIONS),
)
```

### 4. Frontend
- **`components/Heartbeat.tsx`** — ยิง heartbeat 60 วิ, หยุดเมื่อแท็บซ่อน, ยิงทันทีเมื่อกลับมาโฟกัส (mount ใน console layout)
- **`activity/page.tsx`** — เพิ่ม `stale = error && data` → เมื่อโหลดพลาด: การ์ด online dim + grayscale + timestamp เปลี่ยนเป็น "⚠ ค้าง" สีเหลือง (กันเข้าใจผิดว่า pulse เขียว = realtime)

## ข้อจำกัดสถาปัตยกรรม (สำคัญ — บันทึกไว้)

Hub **มองไม่เห็น activity ภายใน subsystem** (ไม่ใช่ SSO) — heartbeat จึงแม่นเฉพาะ
**hub-direct session** (admin console ที่ยิง heartbeat ได้). subsystem session ได้แค่
`last_seen_at = created_at` (bump ตอน login เท่านั้น เพราะ subsystem ไม่ได้ refresh token กับ Hub)
→ subsystem login โชว์ online 5 นาทีจาก login แล้วหลุด (ยอมรับได้ — ปัจจุบันมี subsystem
session เปิดค้างแค่ 1 ตัว). นี่คือข้อจำกัดเดียวกับที่ทำให้ Session Downgrade ถูกตัดออกจากแผน

## ผลการทดสอบ (TDD)

### `tests/test_activity_online.py` — 9 tests

```
tests/test_activity_online.py .........                                  [100%]
============================== 9 passed in 2.96s ===============================
```

| Test | ยืนยัน |
|---|---|
| `test_fresh_session_is_online` | session สด (last_seen now) → online |
| `test_stale_session_not_online` | last_seen เกิน 5 นาที → หลุด online |
| `test_ghost_session_no_jti_not_online` | jti NULL (challenge ไม่ผ่าน) → ไม่ online |
| `test_logged_out_session_not_online` | logout_at set → ไม่ online |
| `test_blocked_session_not_online` | decision=block → ไม่ online |
| `test_null_last_seen_falls_back_to_created_at` | session เก่า (last_seen NULL) ใช้ created_at |
| `test_active_count_equals_active_len` | KPI count == len(list) เสมอ |
| `test_heartbeat_bumps_last_seen` | POST /auth/heartbeat → last_seen bump จริง |
| `test_heartbeat_bad_token_is_ok_false` | token เสีย → 200 ok:false (idempotent) |

### Regression
```
test_activity_online.py .........  test_refresh_token.py ..................  test_token_revocation.py .....
============================== 32 passed ===============================
```
TypeScript `tsc --noEmit` — ไม่มี error

### ทดสอบกับข้อมูลจริง
```
online ตอนนี้ (หลังแก้): active_count=6, len(active)=6   (ตรงกัน)
ghost sessions (jti NULL) ที่ตอนนี้ไม่ถูกนับ online แล้ว: 28
heartbeat ตัวเอง: {'ok': True}
```
(6 ที่ online = session admin อายุ < 1 นาที จากการรันเทสต์ — แสดง online ถูกต้อง จะหลุดเองใน 5 นาทีถ้าไม่ heartbeat)

## ไฟล์ที่แก้

- `hub/backend/alembic/versions/d4e5f6a7b8c9_login_session_last_seen_at.py` — ใหม่ (migration)
- `hub/backend/app/models.py` — เพิ่ม `LoginSession.last_seen_at`
- `hub/backend/app/routers/auth.py` — `/auth/heartbeat` ใหม่ + bump ใน `/auth/refresh` + import `or_`
- `hub/backend/app/routers/admin.py` — `active_cond` ใหม่ + `_ONLINE_WINDOW_MIN`
- `hub/frontend/components/Heartbeat.tsx` — ใหม่
- `hub/frontend/app/(console)/layout.tsx` — mount `<Heartbeat/>`
- `hub/frontend/app/(console)/activity/page.tsx` — stale indicator
- `hub/backend/tests/test_activity_online.py` — ใหม่ (9 tests)
