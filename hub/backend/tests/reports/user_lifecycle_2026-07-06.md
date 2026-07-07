# User Lifecycle Management — Test Report (2026-07-06)

## สรุป

เพิ่ม 2 สถานะผู้ใช้ใหม่ — **Graduated** (จบการศึกษา) และ **Resigned** (ลาออก) —
ต่อยอดจาก `active`/`suspended`/`deleted` เดิม ตาม mockup ที่ user เสนอ

**การตัดสินใจที่ยืนยันกับ user ก่อนเริ่มทำ:**
1. เข้าสถานะ Graduated/Resigned → **cascade revoke เหมือน delete** (revoke
   AccessList ทุก subsystem + kick session ที่ login ค้างอยู่ + revoke jti)
2. **เก็บ "Deleted" ไว้คู่กับ 4 สถานะใหม่** — ไม่แทนที่ soft-delete เดิม (รวมเป็น
   5 สถานะทั้งหมด: active/suspended/graduated/resigned/deleted)
3. ตั้งผ่าน **dropdown เดิม** ในฟอร์ม edit user (ไม่เพิ่มปุ่มเฉพาะ/bulk action)

## Test count: 287 passed (13 ใหม่ + 274 เดิม, no regression จากงานนี้)

```
docker compose exec hub-backend pytest . -q \
  --ignore=tests/test_e2e_full_stack.py \
  --ignore=tests/test_l1_oidc.py \
  --ignore=tests/test_l1_oidc_authlib.py
======================== 5 failed, 287 passed in 52.99s ========================
```

(5 failed = บั๊กเดิมก่อนงานนี้ `test_passkey_security.py::test_account_endpoints_reject_non_admin`,
ไม่เกี่ยวกับงานนี้ — ดู `tests/reports/refresh_token_2026-07-05.md` ที่ยืนยันด้วย git stash แล้ว)

## Design — extracted `_cascade_revoke_access()` helper

โค้ด revoke+kick เดิมอยู่แค่ใน `DELETE /admin/users/{id}` (dedicated delete
endpoint) เท่านั้น — `PATCH /admin/users/{id}` (แก้ status ทั่วไป) **ไม่เคยมี
cascade เลย** ก่อนงานนี้ (ช่องโหว่ที่เจอระหว่างสำรวจโค้ด): ถ้า admin PATCH
`status: "deleted"` ตรงๆ (ไม่ผ่านปุ่มลบ) จะไม่มีการ revoke access/kick session ใดๆ

แก้โดย extract logic ออกมาเป็น `app/routers/users.py::_cascade_revoke_access()`
ใช้ร่วมกันทั้ง `delete_user` (เดิม) และ `update_user` (ใหม่ — เมื่อ status
transition เข้า `_CASCADE_STATUSES = {"deleted", "graduated", "resigned"}`)

### Sections

**1. Validation** — `_VALID_STATUS` = `{active, suspended, deleted, graduated, resigned}`,
`_CASCADE_STATUSES` = `{deleted, graduated, resigned}`

**2. Cascade on status change ผ่าน PATCH** — เข้า graduated/resigned →
- `AccessList.revoked_at` ถูกตั้งทุก subsystem ที่มีสิทธิ์อยู่
- `LoginSession.logout_at` + jti revoke สำหรับ session ที่ active
- audit log (`action="update_user"`) มี `cascade_exit=True` + `subsystems_kicked`
  list ครบ (ใช้หา subsystem ตอน reactivate ทีหลัง)
- webhook `access_revoked` ยิงให้ subsystem เคลียร์ local session (fail-safe)

**3. Reactivation (graduated/resigned → active)** — restore `AccessList` ที่ถูก
kick กลับ (`revoked_at = NULL`) เฉพาะ subsystem ที่ตรงกับครั้งล่าสุดที่ถูก kick
(หาโดย `_find_kicked_subsystem_ids()` — broaden จากเดิมที่หาแค่ `action="delete_user"`
เป็นหาทั้ง `delete_user` และ `update_user` ที่มี `subsystems_kicked` ไม่ว่าง)

**4. ป้องกัน double-cascade** — เปลี่ยนระหว่าง cascade-status สองตัวโดยตรง
(เช่น graduated → resigned) ไม่ re-run revoke ซ้ำ (`is_cascade_exit` เช็ค
`user.status not in _CASCADE_STATUSES` ก่อน — ถ้าอยู่ใน cascade อยู่แล้วไม่ทำซ้ำ)
verify ด้วย `AccessList.revoked_at` ไม่เปลี่ยนเวลาตอน transition รอบสอง

**5. Self-lockout** — admin เปลี่ยน status ตัวเองเป็น graduated/resigned ไม่ได้
(ใช้ guard เดิม `data["status"] != "active"` ที่มีอยู่แล้ว ครอบคลุมอัตโนมัติ)

**6. Login-block message เฉพาะ status** — `deps.py::_status_block_message()`
ใหม่ — เดิม `f"บัญชีถูก {status}"` อ่านไม่เป็นธรรมชาติกับ graduated/resigned
(passive voice ผิดหลักไวยากรณ์ไทย เช่น "บัญชีถูก graduated") แก้เป็นข้อความ
เฉพาะต่อ status: suspended/deleted ยังเป็น passive ("ถูกระงับ"/"ถูกลบ"),
graduated/resigned เป็น active voice ("จบการศึกษาแล้ว"/"ลาออกจากระบบแล้ว")

## Frontend

- `UserFormModal.tsx` — dropdown เพิ่ม graduated/resigned พร้อม label ไทย
  ตรงกับ mockup, เตือน (⚠) ถ้าเลือก cascade-status ใหม่ + แจ้ง (✓) ถ้า reactivate
  กลับ active — เช็คด้วย `CASCADE_STATUSES` set ที่ต้องตรงกับ backend
  `_CASCADE_STATUSES` (คอมเมนต์ระบุไว้ชัด กันลืม sync กันคนละที่)
- `users/page.tsx` — badge สี per status (`STATUS_TONE`): active=good,
  suspended=warn, graduated=brand, resigned=default, deleted=danger

## Compliance / conventions

- B6/B7 (audit ก่อน commit ก่อน raise) — คงเดิม ไม่กระทบ
- Soft-delete pattern — ยังไม่ hard-delete ข้อมูล รักษา FK + history เหมือนเดิม
- Fail-safe webhook — `_cascade_revoke_access` ยิง webhook แบบ try/except เหมือน
  `delete_user` เดิม ไม่ block flow หลักถ้า subsystem ไม่ตอบ
