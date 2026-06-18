# Repeated Failed Mutation — api_guard rule 5

| | |
|---|---|
| **วันที่** | 2026-06-15 |
| **ขอบเขต** | backlog #21 — alert เมื่อ actor พยายามทำ action ที่ fail ซ้ำเกิน threshold |
| **ไฟล์ test** | tests/manual_repeated_failure_alert_driver.py |
| **ผลรวม** | 11/11 PASS |

## 1. เทสอะไร

เติม rule ที่ 5 ใน `api_guard.RULES` — scan `audit_logs` หา action ที่ลงท้ายด้วย
`_failed` / `_denied` / `_blocked%` (ครอบ failure-path logging ทุกอันที่ทำใน session ก่อน)
ถ้า actor เดียวกัน fail > 10 ครั้ง / 5 นาที → fire alert (severity=warning) +
persist เป็น ApiAlert + dedup 10 นาที

ต่างจาก rule เดิม:
- excessive_requests / high_error_rate / unauthorized_probing / bot_pattern = สแกน `request_logs` (HTTP level — per IP)
- **repeated_failed_mutation** = สแกน `audit_logs` (business level — per actor)
  → จับ IDOR/enumeration/probe ที่ HTTP-level อาจมองเป็น 404 ปกติ

## 2. ผลทดสอบ — 11/11

| Group | Test | ผล |
|---|---|---|
| 1 | 5 fail < threshold(10) → ไม่ alert | ✅ |
| 2 | 12 fail > threshold → 1 alert | ✅ |
| 2 | alert มี actor_email + top_actions + count + severity=warning | ✅ ครบ 4 |
| 3 | persist สร้าง ApiAlert | ✅ |
| 3 | dedup 10 นาที → ไม่ persist ซ้ำ | ✅ |
| 4 | _FAILED_ACTION_LIKE ครอบคลุม _failed / _denied / _blocked | ✅ ครบ 3 |

## 3. เปลี่ยนแปลงในโค้ด

- `api_guard.RULES["repeated_failed_mutation"]` — threshold 10/5min, severity=warning
- `_FAILED_ACTION_LIKE = ("%_failed", "%_denied", "%_blocked%")` — pattern จับ failure
- `scan_request_logs()` เพิ่ม rule 5 — group by `actor_id`, dump `top_actions` 5 อันแรก
  + actor_email + latest IP ของ actor ใน window
- `scan_and_persist()` dedup รวม user_id (เพราะ actor-based rule อาจ ip=None)

## 4. ปัญหาที่เจอ + แก้

- ใส่ใน RULES แล้วต้องเพิ่ม Rule 5 ใน scan function ด้วย (ไม่งั้น declare แต่ไม่รัน)
- dedup เดิม `(rule + ip)` ไม่ครอบ ip=None → เพิ่ม `user_id` ใน dedup logic
- cleanup test row ต้องใช้ ip pattern (ตั้งให้พิเศษ `10.0.0.1/2`) แทน JSON metadata
  path (psycopg2 ไม่รู้จัก `.astext`)

## 5. การใช้งานจริง

scan รันโดย:
- `api_guard_scheduler` (cron-based ใน background)
- `POST /admin/api-alerts/scan` (manual trigger)

→ alert ใหม่จะโผล่ในหน้า API Alerts dashboard ทันที + fire ผ่าน webhook/email
ตาม alert_service config

## 6. สถานะ backlog

- **#21 alert repeat-failure** → ✅ **เสร็จ** (commit ต่อไป)
- ที่เหลือใน backlog-traceability.md: IP-in-dev (3 วิธี), failure-log endpoint ที่เหลือ (เสร็จไปแล้ว rounds ก่อน)
