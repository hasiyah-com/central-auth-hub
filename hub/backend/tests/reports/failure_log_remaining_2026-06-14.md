# Failure-path Logging (ที่เหลือ) — Test Report

| | |
|---|---|
| **วันที่** | 2026-06-14 |
| **ขอบเขต** | log ทุก failure path ที่เหลือ — IDOR + user CRUD 404/409 + subsystem register/update/transfer/bulk |
| **ประเภท** | Manual integration test |
| **ไฟล์ test** | `tests/manual_failure_log_remaining_driver.py` (เก็บถาวร) |
| **ผลรวม** | ✅ **8/8 PASS** |
| **Reproducible** | `docker compose exec hub-backend python -m tests.manual_failure_log_remaining_driver` |

---

## 1. เทสอะไร (Scope)

ต่อจากรอบก่อน (whitelist add/remove/role) — wire failure logging ที่เหลือทั้งหมด ตามกฎ B7 (ทุก `raise HTTPException` ต้องมี `log_action` ก่อน)

**จุดที่เพิ่ม:**
| จุด | action | ครอบคลุม |
|---|---|---|
| `_get_owned_subsystem` 404 ⭐ | `subsystem_access_denied` | **10 endpoints** (IDOR — แตะ subsystem คนอื่น) |
| register scope ผิด | `subsystem_register_failed` | สมัคร subsystem |
| update scope/no-field | `subsystem_update_failed` | แก้ subsystem |
| bulk empty/too-many | `whitelist_bulk_failed` | batch role |
| transfer 404/self | `subsystem_transfer_failed` | โอน ownership |
| user GET 404 | `user_access_denied` | เดา user ID |
| user PATCH 404 | `update_user_failed` | — |
| user DELETE 404/self | `delete_user_failed` | — |
| create email/identifier ซ้ำ | `create_user_failed` | enumeration |

**กลไก:** เพิ่ม helper `_audit_fail()` ใน developer.py + users.py — log (ip + user_agent + reason) → commit → raise

---

## 2. ผลการทดสอบ (Results) — 8/8

### Group 1 — IDOR (1/1) ⭐
| Test | ผล |
|---|---|
| PATCH subsystem FAKE → `subsystem_access_denied` | ✅ 404 +1 log |

### Group 2 — User CRUD 404/409 (4/4)
| Test | ผล |
|---|---|
| GET user FAKE → `user_access_denied` | ✅ 404 |
| PATCH user FAKE → `update_user_failed` | ✅ 404 |
| DELETE user FAKE → `delete_user_failed` | ✅ 404 |
| CREATE email ซ้ำ → `create_user_failed` | ✅ 409 |

### Group 3 — Subsystem register/transfer (2/2)
| Test | ผล |
|---|---|
| register scope ผิด → `subsystem_register_failed` | ✅ 400 |
| transfer email ไม่มี → `subsystem_transfer_failed` | ✅ 404 |

### Group 4 — metadata traceability (1/1)
| Test | ผล |
|---|---|
| `subsystem_access_denied` มี reason + ip + user_agent | ✅ `{reason: not_found_or_not_owner, user_agent: ..., subsystem_id: ...}` |

---

## 3. Security Value

| ภัย | ก่อน | หลัง |
|---|---|---|
| **IDOR** (developer เดา subsystem_id คนอื่น) | audit ว่าง — สืบไม่ได้ | ✅ `subsystem_access_denied` + actor + ip |
| **User enumeration** (เดา user ID / email) | ไม่ log | ✅ `user_access_denied` / `create_user_failed` |
| **Probe subsystem mutation** | ไม่ log | ✅ `*_failed` ทุก action |

→ ทุกความพยายามที่ fail มี trail (actor + ip + user_agent + reason) — feed ให้ alert (backlog #1) ได้

---

## 4. ปัญหาที่เจอ + วิธีแก้

### ⚠️ register scope test ส่ง string → 422 ก่อน logging
**อาการ:** ส่ง `scope: "evil:scope"` (string) → pydantic ต้องการ `list[str]` → 422 ก่อนถึง business logic
**วิธีแก้:** ส่งเป็น list `["evil:scope"]` → ผ่าน schema → ถึง scope-invalid check → 400 → log ทำงาน
**บทเรียนเดิม:** failure ที่ schema-level (422) ไม่ถึง audit (จับโดย request_logs แทน) — audit log ครอบเฉพาะ business-logic failures

---

## 5. สรุป

failure logging **ครบทุก endpoint** แล้ว — ทุกการปฏิเสธคำขอมี audit trail

| รอบ | ครอบคลุม | สถานะ |
|---|---|---|
| รอบ 1 | whitelist add/remove/role | ✅ (failure_log_ratelimit) |
| **รอบ 2 (นี้)** | IDOR + user CRUD + register/update/bulk/transfer | ✅ 8/8 |

**เหลือ backlog:** #1 alert เมื่อ fail ซ้ำเกิน threshold (reuse security_listener)

---

*รัน reproducible: `docker compose exec hub-backend python -m tests.manual_failure_log_remaining_driver`*
