# Revoke ทุกนโยบาย + สถานะบัญชี + แก้เวลา (User 360) — 2026-07-11

## บริบท / ที่มา

ในหน้า **User 360° View** (`/users/[id]`) มี 3 ปัญหาที่ผู้ใช้ขอแก้ (จาก screenshot):

1. **ถอนสิทธิ์ได้แค่บาง subsystem** — subsystem ที่ใช้ policy `all/role/attribute`
   (เช่น "ระบบเกรด" = role: student) โชว์ **"ถอนรายคนไม่ได้"** เพราะเดิม revoke
   soft-delete ได้เฉพาะ explicit whitelist (allow entry). ต้องการ: ถอนรายคนได้
   **ทุกนโยบาย**.
2. **ไม่โชว์สถานะบัญชี** ในการ์ดสิทธิ์เข้าถึงระบบย่อย.
3. **เวลาเพี้ยน** — login ที่พึ่งเกิดขึ้นโชว์ "7 ชม.ที่แล้ว" (bug timezone UTC vs
   Asia/Bangkok +7).

## วิธีแก้

### 1. ถอนสิทธิ์ทุกนโยบาย — ผ่าน deny-list

`evaluate_access_policy` เช็ค **deny entry** (`AccessList.entry_type='deny'`,
`revoked_at` NULL) **ก่อน** ทุก policy อยู่แล้ว → ใช้กลไกนี้:

- `revoke_user_access` (`DELETE /admin/users/{uid}/access/{sid}`): เปลี่ยนจาก
  "soft-delete allow entry" เป็น **upsert deny entry** (flip allow→deny หรือสร้าง
  deny ใหม่สำหรับ policy-based ที่ไม่มี allow row) → บล็อกได้ทุกนโยบาย + ตัดออกจาก
  roster sync (`list_allowed_users`) + ปิด active sessions + ยิง webhook
  `access_revoked` (ถาวร) ให้ subsystem ตัด local cookie ทันที.
- `grant_user_access` (`POST .../access/{sid}`): เป็น inverse — flip deny→allow =
  **คืนสิทธิ์** + ยิง `access_restored` ถ้าเดิมเป็น deny (ยกเลิก re-auth marker
  ฝั่ง subsystem → session เดิมกลับมาใช้ได้).
- `user_access_list`: `can_revoke: True` ทุก subsystem + เพิ่ม `revoke_method`
  (`allow_entry` | `deny_list`).

ไฟล์: `hub/backend/app/routers/admin.py`

### 2. สถานะบัญชี

`hub/frontend/app/(console)/users/[id]/page.tsx`:
- เพิ่ม Badge สถานะบัญชีใน header การ์ด "สิทธิ์เข้าถึงระบบย่อย".
- แถบเตือนสีเหลืองเมื่อ `status != active` (นโยบายทุกแบบต้องการ active → ถูกบล็อก
  ทุกระบบอัตโนมัติ).

### 3. แก้เวลา (timezone)

Backend ส่ง timestamp เป็น **naive UTC** (`datetime.isoformat()` ไม่มี `Z`/offset).
`new Date("2026-07-11T13:42:15")` ถูก JS ตีความเป็น **local time** → ที่ไทย (UTC+7)
เวลาที่พึ่งเกิดเพี้ยนเป็น 7 ชม.ก่อน. เพิ่ม helper `parseUTC()` เติม `Z` ถ้ายังไม่มี
tz designator → parse เป็น UTC ก่อนแปลงเป็น local ตอนแสดง. ใช้ใน `relTime()`
(ครอบทุกจุดที่โชว์เวลา: created_at, last_login, session, passkey).

## ผลการทดสอบ

### Backend — `tests/test_revoke_all_policies.py` (pytest, rollback-safe)

```
$ docker compose exec hub-backend pytest tests/test_revoke_all_policies.py -v

tests/test_revoke_all_policies.py::test_revoke_role_policy_via_deny        PASSED [ 20%]
tests/test_revoke_all_policies.py::test_revoke_all_policy_via_deny         PASSED [ 40%]
tests/test_revoke_all_policies.py::test_revoke_attribute_policy_via_deny   PASSED [ 60%]
tests/test_revoke_all_policies.py::test_denied_user_excluded_from_roster   PASSED [ 80%]
tests/test_revoke_all_policies.py::test_grant_restores_after_deny          PASSED [100%]

============================== 5 passed in 4.06s ===============================
```

| Test | ยืนยัน |
|------|--------|
| `test_revoke_role_policy_via_deny` | subsystem role:student → deny บล็อก student รายคน (reason `denied`) |
| `test_revoke_all_policy_via_deny` | subsystem all → deny บล็อกรายคน |
| `test_revoke_attribute_policy_via_deny` | subsystem attribute (คณะ) → deny บล็อกรายคน |
| `test_denied_user_excluded_from_roster` | user ที่โดน deny หลุดจาก `list_allowed_users` (roster ไม่ sync) |
| `test_grant_restores_after_deny` | grant (flip allow) → กลับเข้าได้ + กลับเข้า roster |

Regression: `tests/test_access_policy.py` → **14 passed** (ไม่กระทบของเดิม).

### Frontend — timezone logic (node)

```
naive-UTC-now diff minutes: 0    (want ~0 → "เมื่อครู่")   ✅ แก้แล้ว
OLD new Date() diff minutes: 420  (= 7 ชม. = bug เดิมที่ TZ+7)
```

`parseUTC` ไม่ double-append `Z`: string ที่มี `Z`/`+07:00` อยู่แล้ว parse ถูกต้อง.

TypeScript: `npx tsc --noEmit` → ไม่มี error.

## Security notes

- deny-list เก็บ audit เต็ม (`admin_revoke_user_access` metadata: policy, method,
  closed_sessions). revoke → `log_action` → `commit` → webhook (ลำดับ B6).
- webhook fail-safe (B21): ยิงไม่สำเร็จ = log ไม่ raise; Hub บล็อกตอน login ใหม่อยู่ดี.
- step-up gate เดิม (`whitelist_remove` / `whitelist_add`) ยังครอบ revoke/grant.

## ไฟล์ที่แก้

- `hub/backend/app/routers/admin.py` — revoke (deny upsert + webhook), grant
  (restore webhook), user_access_list (`can_revoke: True`), import
  `send_access_restored`.
- `hub/frontend/app/(console)/users/[id]/page.tsx` — `parseUTC`/`relTime`,
  status badge + warning, revoke confirm wording.
- `hub/backend/tests/test_revoke_all_policies.py` — ใหม่ (5 tests).
