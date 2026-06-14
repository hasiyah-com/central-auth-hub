# Subsystem Mutations + Step-up Gate — Test Report

| | |
|---|---|
| **วันที่** | 2026-06-14 |
| **ขอบเขต** | ทุกการกระทำในส่วนระบบย่อย (subsystem) ต้องผ่าน step-up |
| **ประเภท** | Manual integration test (HTTP จริง + step-up cache) |
| **ไฟล์ test** | `tests/manual_subsystem_stepup_driver.py` (เก็บถาวร) |
| **ผลรวม** | ✅ **28/28 PASS** (14 endpoints × 2 phase) |
| **Reproducible** | `docker compose exec hub-backend python -m tests.manual_subsystem_stepup_driver` |

---

## 1. เทสอะไร (Scope)

บังคับ step-up (Critical Action gate) ให้ **ทุก mutation ในส่วนระบบย่อย** — เหมือน user CRUD

**14 endpoints** ที่ gate (developer.py 9 + admin.py 5):

| Endpoint | Action | Router |
|---|---|---|
| POST `/developer/subsystems` | subsystem_register | developer |
| POST `.../whitelist` (CSV) | whitelist_add | developer |
| POST `.../whitelist/user` | whitelist_add | developer |
| DELETE `.../whitelist/{uid}` | whitelist_remove | developer |
| PATCH `.../whitelist/{uid}` | whitelist_role_change | developer |
| POST `.../whitelist/bulk-update` | whitelist_role_change | developer |
| PATCH `/developer/subsystems/{id}` | subsystem_update | developer |
| POST `.../transfer-owner` | subsystem_transfer_owner | developer |
| POST `.../rotate-secret` | rotate_oauth_secret | developer |
| POST `/admin/subsystems/{id}/approve` | subsystem_approve | admin |
| POST `.../reject` | subsystem_reject | admin |
| POST `.../suspend` | subsystem_suspend | admin |
| POST `.../resume` | subsystem_resume | admin |
| POST `.../sessions/{sid}/revoke` | session_revoke | admin |

11 actions ใหม่เพิ่มใน `CRITICAL_ACTIONS` (rotate_oauth_secret มีอยู่แล้ว — wire เพิ่ม)

**Frontend** (`subsystems/[id]/page.tsx`): 10 mutation call sites เปลี่ยนเป็น `mutateWithStepup()` → inline step-up (verify Passkey ในหน้า ไม่ redirect — Option C)

---

## 2. เทสยังไง (Method)

2-phase driver:
- **Phase 1** — clear step-up cache → ยิงทุก endpoint → ตรวจ 403 + `code=stepup_required` + `action` ตรงกับที่ gate กำหนด
- **Phase 2** — `set_granted(passkey)` → ยิงซ้ำ → ตรวจ **ไม่ใช่** 403 stepup_required (gate ผ่าน → ติดแค่ business logic 404/422 = ถูกต้อง เพราะใช้ UUID ปลอม)

ใช้ UUID ปลอม — gate ทำงาน**ก่อน** business logic เสมอ → ไม่สร้าง state ถาวร

---

## 3. ผลการทดสอบ (Results) — 28/28

### Phase 1 — ก่อน step-up: ทุก mutation → 403 stepup_required (14/14)
ทุก endpoint คืน `{code: stepup_required, action: <ตรงตามที่กำหนด>, redirect}` ✅

ตรวจ `action` ตรงเป๊ะทุกตัว: subsystem_register, whitelist_add (×2), whitelist_remove, whitelist_role_change (×2), subsystem_update, subsystem_transfer_owner, rotate_oauth_secret, subsystem_approve/reject/suspend/resume, session_revoke

### Phase 2 — หลัง step-up: ผ่าน gate (14/14)
หลัง set cache ทุก endpoint **ไม่ติด** stepup_required อีก → ผ่าน gate → ติด business logic (404 user/subsystem ไม่พบ, 422 validation) = พฤติกรรมถูกต้อง ✅

---

## 4. Security Checks

| Control | สถานะ |
|---|---|
| ทุก subsystem mutation ผ่าน step-up gate | ✅ 14/14 |
| action name ตรงกับ endpoint (audit/redirect ชัด) | ✅ Phase 1 |
| gate ทำงานก่อน business logic (fail-closed) | ✅ Phase 2 |
| require_developer / require_hub_admin ยังคงอยู่ | ✅ (Depends เดิม) |
| import order — admin.py `_stepup_gate` ย้ายขึ้น top (กัน NameError) | ✅ fixed |

---

## 5. ปัญหาที่เจอ + วิธีแก้

### ⚠️ admin.py — import gate อยู่กลางไฟล์ (line 284) แต่ใช้ที่ line 200
**อาการ:** approve endpoint (line 200) อยู่ **ก่อน** `from ... import gate as _stepup_gate` (line 284) → decorator eval ตอน import = NameError
**วิธีแก้:** ย้าย import ขึ้น top-level imports (หลัง `audit_service`) + ลบตัวกลางไฟล์
**ยืนยัน:** `py_compile` + import OK

### Frontend — pre-existing TS error (ไม่เกี่ยวงานนี้)
`subsystems/[id]/page.tsx` มี Badge tone `"warning"` ที่ไม่อยู่ใน Badge type (line ~2062) — เป็น error เดิมก่อนแก้ → flag เป็น background task แยก (ไฟล์ที่แก้ส่วน step-up typecheck สะอาด)

### Inline step-up reuse
ใช้ helper `mutateWithStepup()` ใหม่ (= `runWithStepup` + `clientFetch stepupMode:"throw"`) → verify Passkey ในหน้า ไม่ redirect ไม่เสีย form state (เหมือน user CRUD)

---

## 6. สรุป

ทุกการกระทำในส่วนระบบย่อย (14 endpoints) **บังคับ step-up ครบ** — เหมือนการเพิ่ม user

| องค์ประกอบ | สถานะ |
|---|---|
| Backend gate 14 endpoints | ✅ 28/28 |
| action names ตรง + audit ชัด | ✅ |
| Frontend inline step-up (10 call sites) | ✅ |
| verifying overlay | ✅ |

**ยังต้อง test ด้วย browser:**
- หน้า subsystem detail → กด whitelist add / role / revoke / suspend
- → overlay "กำลังยืนยัน Passkey" เด้ง → Virtual Authenticator → สำเร็จในหน้า (ไม่ redirect)

---

*รัน reproducible: `docker compose exec hub-backend python -m tests.manual_subsystem_stepup_driver`*
