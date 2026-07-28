# หน้า Activity / Subsystem — นิยาม "Session Active" แบบรวม logic 2 หน้า (2026-07-22)

> ต่อยอดจาก `activity_online_heartbeat_2026-07-22.md` — รอบนี้เปลี่ยนกรอบคิดจาก
> "เดาว่าใครกำลังคลิก" → "session ที่ Hub รู้ว่ายัง valid" และรวม logic ให้ 2 หน้า
> (`/activity` + subsystem detail) ใช้เกณฑ์เดียวกัน

## ที่มา

หน้า `/activity` (heartbeat) กับ subsystem detail (`/active-sessions`) เดิม **ใช้เกณฑ์ต่างกัน**:
- `/activity` → heartbeat 5 นาที (หลังแก้รอบก่อน)
- subsystem detail → `created_at` ภายใน 15 นาที (JWT window เดิม) — เดามั่ว ไม่ตรง cookie จริง (60 นาที)

ปัญหาเชิงนิยาม: Hub เป็น IdP มองไม่เห็นการคลิกใน subsystem (ไม่ใช่ SSO) → "เดาว่าคลิกอยู่"
ทำไม่ได้แม่น. เปลี่ยนเป็นแสดง **"session validity"** ซึ่ง Hub รู้แม่น (authoritative)

## แนวคิดใหม่ — แยกเกณฑ์ตามสิ่งที่ Hub เห็นจริง

| ชนิด session | Hub เห็นอะไร | เกณฑ์ active |
|---|---|---|
| **hub-direct** | ทุก request (console) | **presence heartbeat** — `last_seen_at` ภายใน 5 นาที = อยู่จริง |
| **subsystem** | แค่ตอน login (ไม่เห็นการคลิก) | **session validity** — `created_at + อายุ cookie subsystem (60น)` หรือจน logout/revoke |

ทั้งคู่ต้อง: `logout_at NULL` + `jti NOT NULL` (กัน ghost) + ไม่ block

## Implementation — single source of truth

`admin.py::_active_session_condition(now)` — SQLAlchemy condition เดียว ใช้ทั้ง 2 endpoint:

```python
or_(
    and_(subsystem_id IS NULL,     COALESCE(last_seen, created) >= now-5นาที),   # hub: heartbeat
    and_(subsystem_id IS NOT NULL, created_at >= now-60นาที),                    # subsystem: validity
)
+ logout_at NULL + jti NOT NULL + decision ไม่ block
```

- `access_activity` (/activity) → ใช้ helper
- `list_active_sessions` (subsystem detail) → ใช้ helper (filter subsystem_id เพิ่ม)
- เพิ่ม response: `session_kind` (hub/subsystem) + `session_expires_at` (subsystem = login+TTL)

Constants: `_HUB_ONLINE_WINDOW_MIN=5`, `_SUBSYSTEM_SESSION_TTL_MIN=60`
(ตรงกับ `subsystem-*/config.py:session_max_age_seconds=3600`)

## Frontend

- **`/activity`**: header "Session ที่ใช้งานอยู่" + คำอธิบาย 🟢 Hub=ออนไลน์จริง · 🔵 ระบบย่อย=session valid
  · per-row: จุดสี hub/subsystem + hub โชว์ "ออนไลน์จริง" (pulse) / subsystem โชว์ "session · ถึง HH:MM"
- **subsystem detail**: "Session ที่ยังใช้งานได้" + หมายเหตุ "ค่าประมาณจากอายุ session (~60น)"
  · คอลัมน์ระยะเวลาเพิ่ม "valid ถึง ~HH:MM" · จุดสีฟ้า (ไม่ pulse — ไม่ใช่ real-time)

## ผลการทดสอบ

### `tests/test_activity_online.py` — 13 tests (เพิ่มจาก 9)

```
tests/test_activity_online.py .............   13 passed
```

เพิ่มจากรอบก่อน:
| Test | ยืนยัน |
|---|---|
| `test_subsystem_session_within_ttl_is_active` | subsystem 30น (ไม่ heartbeat) → active (< 60 TTL) |
| `test_subsystem_session_past_ttl_not_active` | subsystem 90น → ตัด (> 60 TTL) |
| `test_hub_direct_stale_beyond_5min_but_subsystem_same_age_active` | อายุ 20น เท่ากัน: hub หลุด / subsystem ยัง (คนละเกณฑ์) |
| `test_subsystem_detail_endpoint_uses_same_logic` | 2 หน้าใช้ helper เดียวกัน + กัน ghost ทั้งคู่ |

### Regression
```
test_activity_online (13) · test_incidents (36) · test_refresh_token (18) · test_token_revocation (5)
============================== 72 passed ===============================
```
TypeScript `tsc --noEmit` — ไม่มี error

### ทดสอบข้อมูลจริง (E2E)
```
=== /activity ===
subsystem session (30น, ไม่ heartbeat): ACTIVE  kind=subsystem  expires=+60น  ✓
hub session (30น, ไม่ heartbeat):        not active (ถูกต้อง — เกิน 5น)          ✓
=== subsystem detail (คนละหน้า เกณฑ์เดียวกัน) ===
subsystem session อยู่ในลิสต์: True  expires ตรงกัน  ✓
```

## ไฟล์ที่แก้

- `hub/backend/app/routers/admin.py` — `_active_session_condition` helper + constants + 2 endpoint ใช้ร่วม + `session_kind`/`session_expires_at`
- `hub/frontend/app/(console)/activity/page.tsx` — label/badge hub vs subsystem
- `hub/frontend/app/(console)/subsystems/[id]/page.tsx` — "session validity" framing + valid-until
- `hub/backend/tests/test_activity_online.py` — +4 tests (subsystem branch + cross-page)

## ข้อจำกัดที่ยอมรับ (documented)

subsystem "active" = **session ยัง valid** ไม่ใช่ "กำลังคลิกอยู่" — user อาจ walk away
แต่ session ยังไม่หมด (ก็ยังนับ active เพราะยังเป็น attack surface จริง). Hub มองไม่เห็น
การคลิกใน subsystem (ไม่ใช่ SSO) → ถ้าต้องการ real-time presence ของ subsystem ต้องให้
subsystem ยิง heartbeat มา (presence-ping) ซึ่ง**ไม่ทำ** เพื่อรักษาความอิสระของ subsystem
