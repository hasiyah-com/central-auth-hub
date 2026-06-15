# access_updated Webhook — role/scope change → user re-auth

| | |
|---|---|
| **วันที่** | 2026-06-15 |
| **ขอบเขต** | admin แก้ role/scope subsystem → ยิง webhook → user ที่ active ถูกบังคับ re-auth |
| **ประเภท** | Manual integration test (Hub dispatcher + subsystem receiver + PHP store) |
| **ไฟล์ test** | `tests/manual_access_updated_driver.py` (Hub) + `sdk/php-client/tests/RevocationStoreTest_manual.php` (PHP) |
| **ผลรวม** | ✅ **Hub 14/14 + PHP 8/8 = 22/22** |

---

## 1. เทสอะไร

ทำให้ action บน subsystem (เปลี่ยน role / แก้ scope) **แตะ user ที่ login อยู่** — เหมือนหอพัก:
- เปลี่ยน role → user เฉพาะคนถูกบังคับ re-login (ได้ role ใหม่)
- แก้ scope/config → kick ทุกคน (ได้ scope ใหม่)

**สถาปัตยกรรม:** webhook event ใหม่ `access_updated` (แยกจาก `access_revoked`)
```
admin approve/auto-apply → notify_subsystem_after_apply → send_access_updated
   → subsystem mark "ต้อง re-auth" → request ถัดไปเด้ง login → re-login → ค่าใหม่
```

---

## 2. ผลการทดสอบ

### Hub (manual_access_updated_driver.py) — 14/14
- role change → ยิง user เฉพาะคน (hub_user_id) + reason=role_changed
- bulk role → ยิงทุกคนที่เปลี่ยน
- edit_scope → hub_user_id=None (kick ALL) + reason=config_changed:edit_scope
- rotate_secret → ไม่ยิง (ไม่กระทบ session)
- dispatcher payload: event=access_updated + X-Hub-Event + HMAC signature

### PHP RevocationStore (RevocationStoreTest_manual.php) — 8/8
- markUser/markAll + isRevokedSince (revoked > logged_in_at)
- WebhookReceiver verify OK + bad-signature/replay → throw

### End-to-end (จริง)
- dorm: `send_access_updated(hub_user_id=None)` → delivered=True → residents 2 คน hub_access_revoked_at ถูก set ✅
- library: delivered=True ✅
- ทั้ง 3 subsystem `/internal/access-updated` → 401 (route + verify signature)

---

## 3. ปัญหาที่เจอ + วิธีแก้

### ⚠️ B-new-1: admin auto-apply ข้าม webhook hook
**อาการ:** admin แก้ scope หอพัก → user ไม่เด้ง
**สาเหตุ:** admin auto-apply ผ่าน `create_request` (apply ทันที) ไม่ผ่าน `approve_change_request` endpoint ที่ hook ไว้
**แก้:** เติม `notify_subsystem_after_apply` ใน `create_request` (admin override path) ด้วย — ครอบทั้ง 2 path (admin auto-apply + developer pending→approve)

### ⚠️ B-new-2: webhook override path ตายตัวบล็อก event ใหม่
**อาการ:** access_updated ถูกส่งไป `/internal/access-revoked` → 400 "missing event/hub_user_id"
**สาเหตุ:** subsystem ตั้ง `access_revoke_webhook_url = .../internal/access-revoked` (path เต็ม) → `_resolve_webhook_url` ใช้ path เดิมกับทุก event
**แก้:** resolver strip known webhook path (`/internal/access-revoked|access-updated`) ออกก่อน แล้วต่อ path ของ event ปัจจุบัน → `access-updated` ไป endpoint ถูก

### ⚠️ Environment: subsystem start ก่อน DB
**อาการ:** dorm/library 🔴 down (could not translate host name postgres-dorm/library)
**สาเหตุ:** subsystem container start ตอน postgres ของ stack ยังไม่ขึ้น (Strategy A single-stack)
**แก้:** `docker compose -f docker-compose.<sub>.yml up -d` (ยก postgres) → restart subsystem (ไม่ใช่ code bug)

---

## 4. สรุป — 3 subsystem พฤติกรรมเท่ากัน

| Action | dorm | library | PHP myapp |
|---|---|---|---|
| ถอด whitelist (access_revoked) | ✅ | ✅ | ✅ |
| เปลี่ยน role (access_updated, คนเดียว) | ✅ | ✅ | ✅ |
| แก้ scope/config (access_updated, kick all) | ✅ | ✅ | ✅ |

**ต้องตั้งค่า:** WEBHOOK_SHARED_KEY (Hub+subsystem ตรงกัน) + subsystem `access_revoke_webhook_url`

---

*รัน: `docker compose exec hub-backend python -m tests.manual_access_updated_driver`*
*PHP: `E:\xampp\php\php.exe hub/sdk/php-client/tests/RevocationStoreTest_manual.php`*
