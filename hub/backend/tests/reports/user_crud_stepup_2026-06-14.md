# Admin User CRUD + Step-up Gate — Test Report

| | |
|---|---|
| **วันที่** | 2026-06-14 |
| **ขอบเขต** | หน้าผู้ใช้งาน (admin) — เพิ่ม/แก้ไข/ลบ user + บังคับ step-up ทุก mutation |
| **ประเภท** | Manual integration test (HTTP endpoint จริง + step-up cache) |
| **ไฟล์ test** | `tests/manual_user_crud_stepup_driver.py` (เก็บถาวร) |
| **ผลรวม** | ✅ **21/21 PASS** |
| **Reproducible** | `docker compose exec hub-backend python -m tests.manual_user_crud_stepup_driver` |

---

## 1. เทสอะไร (Scope)

เพิ่มความสามารถ CRUD ผู้ใช้ในหน้า admin โดย **ทุก mutation (create/update/delete) ต้องผ่าน step-up** (Critical Action gate — กลไกเดิม `critical_action_policy.gate`)

**Endpoints ใหม่** (`routers/users.py`):
| Method | Path | Action | Gate |
|---|---|---|---|
| POST | `/admin/users/` | create_user | `gate("create_user")` |
| PATCH | `/admin/users/{id}` | update_user | `gate("update_user")` |
| DELETE | `/admin/users/{id}` | delete_user (soft) | `gate("delete_user")` |

3 actions ใหม่เพิ่มใน `CRITICAL_ACTIONS` frozenset

**Frontend** (`app/(console)/users/`):
- ปุ่ม "+ เพิ่มผู้ใช้" → `UserFormModal` (create)
- คอลัมน์ "จัดการ": ✏️ แก้ไข + 🗑️ ลบ ต่อ row
- 403 stepup_required → `lib/api.ts` interceptor พาไป `/auth/passkey/stepup` อัตโนมัติ (ไม่ต้องแก้)

---

## 2. เทสยังไง (Method)

Test driver ผสม HTTP จริง + step-up cache จริง:
1. mint admin JWT (`create_access_token`)
2. **ยิง mutation ก่อน set cache** → ตรวจ 403 stepup_required (gate ทำงาน)
3. `stepup_cache.set_granted(admin_id, jti, "passkey")` = จำลอง passkey verify ผ่าน
4. ยิง mutation อีกครั้ง → ผ่าน
5. ตรวจ validation / guards / soft delete / audit
6. cleanup test user + audit rows

---

## 3. ผลการทดสอบ (Results) — 21/21

### Group 1 — Step-up gate blocks ก่อน verify (3/3) ⭐
| Test | ผล |
|---|---|
| T1.1 CREATE ก่อน step-up → 403 stepup_required | ✅ |
| T1.2 PATCH ก่อน step-up → 403 | ✅ |
| T1.3 DELETE ก่อน step-up → 403 | ✅ |

→ ยืนยัน: **ทุก mutation ถูก gate** (response มี `{code: stepup_required, action, redirect}`)

### Group 2 — CREATE หลัง step-up (5/5)
| Test | ผล |
|---|---|
| T2.1 CREATE → 201 | ✅ |
| T2.2 response มี id + status=active | ✅ |
| T2.3 email ซ้ำ → 409 | ✅ |
| T2.4 identifier ซ้ำ → 409 | ✅ |
| T2.5 user_type ผิด → 422 | ✅ |

### Group 3 — UPDATE (3/3)
| Test | ผล |
|---|---|
| T3.1 PATCH → 200 + ค่าใหม่ | ✅ |
| T3.2 PATCH ว่าง → 422 | ✅ |
| T3.3 status ผิด → 422 | ✅ |

### Group 4 — Self-lockout guards (3/3) ⭐
| Test | ผล |
|---|---|
| T4.1 ถอด admin ตัวเอง → 400 | ✅ |
| T4.2 suspend ตัวเอง → 400 | ✅ |
| T4.3 ลบตัวเอง → 400 | ✅ |

### Group 5 — DELETE (soft) (4/4)
| Test | ผล |
|---|---|
| T5.1 DELETE → 200 + status=deleted | ✅ |
| T5.2 soft delete — row ยังอยู่ (ไม่ hard delete) | ✅ |
| T5.3 status = deleted ใน DB | ✅ |
| T5.4 ลบซ้ำ → 409 | ✅ |

### Group 6 — Audit log (3/3)
| Test | ผล |
|---|---|
| T6.1 audit มี create_user | ✅ |
| T6.2 audit มี update_user | ✅ |
| T6.3 audit มี delete_user | ✅ |

---

## 4. Security Checks

| Control | สถานะ | อ้างอิง |
|---|---|---|
| ทุก mutation ผ่าน step-up gate | ✅ | T1.1-1.3 |
| require_hub_admin (admin only) | ✅ | Depends เดิม |
| Soft delete (รักษา FK + history) | ✅ | T5.2, T5.3 — B11 |
| Self-lockout guards (ลบ/ถอดสิทธิ์ตัวเอง) | ✅ | T4.1-4.3 |
| email/identifier uniqueness | ✅ | T2.3, T2.4 |
| Input validation (user_type/status) → 422 | ✅ | T2.5, T3.3 |
| audit log → commit (B6 order) | ✅ | Group 6 |
| is_hub_admin sync ตาม user_type | ✅ | create/update logic |

---

## 5. ปัญหาที่เจอ + วิธีแก้

### ไม่มีปัญหาระหว่าง test
ผ่านครบ 21/21 รอบแรก

### Note — frontend pre-existing TS error (ไม่เกี่ยวงานนี้)
`subsystems/[id]/page.tsx:2024` มี TS2322 (`"warning"` tone ไม่อยู่ใน Badge type) — เป็น error เดิมที่มีอยู่ก่อน ไม่ใช่จากไฟล์ที่แก้ในงานนี้ (UserFormModal.tsx + users/page.tsx typecheck สะอาด)

### Design decisions
| ประเด็น | เลือก | เหตุผล |
|---|---|---|
| ลบ user | **Soft delete** (status=deleted) | B11 — hard delete พัง FK (login_sessions, audit_logs อ้าง user) |
| step-up reuse | กลไกเดิม `critical_action_policy` | ไม่สร้างใหม่ — flow + frontend interceptor พร้อมแล้ว |
| แก้ตัวเอง | อนุญาต ยกเว้นถอด admin/suspend/delete ตัวเอง | กัน self-lockout |

---

## 6. สรุป

หน้าผู้ใช้งาน admin มี **เพิ่ม/แก้ไข/ลบ** ครบ — ทุก mutation **บังคับ step-up** ผ่าน Critical Action gate เดิม

| องค์ประกอบ | สถานะ |
|---|---|
| Backend CRUD endpoints + gate | ✅ |
| Self-lockout guards | ✅ |
| Soft delete + audit | ✅ |
| Frontend UI (add/edit/delete modal) | ✅ |
| Step-up enforcement (21/21) | ✅ |

**ยังต้อง test ด้วย browser:**
- กดเพิ่ม/แก้/ลบ ในหน้า `/users` จริง → เด้งหน้า step-up → verify Passkey → กลับมาทำสำเร็จ
- Virtual Authenticator (F12 → WebAuthn) สำหรับ verify

---

*รัน reproducible: `docker compose exec hub-backend python -m tests.manual_user_crud_stepup_driver`*
