# Failure-path Logging + Rate Limit + Traceability — Test Report

| | |
|---|---|
| **วันที่** | 2026-06-14 |
| **ขอบเขต** | เก็บ log ทุก attempt (รวม failure) + rate limit + ตรวจ traceability (ต้นทาง/อุปกรณ์/action) |
| **ประเภท** | Manual integration test |
| **ไฟล์ test** | `tests/manual_failure_log_ratelimit_driver.py` (เก็บถาวร) |
| **ผลรวม** | ✅ **11/11 PASS** |
| **Reproducible** | `docker compose exec hub-backend python -m tests.manual_failure_log_ratelimit_driver` (เว้น ≥1 นาทีระหว่างรันเพราะ rate limit) |

---

## 1. เทสอะไร (Scope)

ตอบโจทย์ผู้ใช้: "กดอะไรเก็บอันนั้นทั้งหมด + รู้ต้นทาง/อุปกรณ์/สิ่งที่ทำ + ยิงซ้ำควรมี action"

**3 เรื่อง:**
1. **Failure-path audit logging** — ทุก attempt (รวมที่ล้มเหลว) ถูก log (เดิม fail ไม่ log → audit ดูเหมือนเก็บครั้งเดียว)
2. **Traceability** — `request_logs` (middleware) + `audit_logs` เก็บ ต้นทาง IP / user-agent / method / path / status / user
3. **Rate limit** — spam เกิน 30/min → 429

---

## 2. สิ่งที่แก้ (Implementation)

### Failure-path logging — `developer.py` whitelist
| Endpoint | failure | action ใหม่ |
|---|---|---|
| add | email ไม่มีใน Hub (404) | `whitelist_add_failed` (reason=email_not_found) |
| add | กดซ้ำ มีอยู่แล้ว (400) | `whitelist_add_blocked_duplicate` |
| remove | ไม่อยู่ใน whitelist (404) | `whitelist_remove_failed` |
| role | ไม่อยู่ใน whitelist (404) | `whitelist_role_change_failed` |

ทุก log เก็บ `email/user_id + reason + ip + user_agent` (B7 — log → commit → raise)

### Rate limit — `@limiter.limit(rate_limit_admin_mutation)` = 30/min
- whitelist add/remove/role (developer.py)
- user CRUD POST/PATCH/DELETE (users.py)
- setting ใหม่ `rate_limit_admin_mutation: str = "30/minute"`

---

## 3. ผลการทดสอบ (Results) — 11/11

### Group 1 — Failure log ทุก attempt (4/4) ⭐
| Test | ผล |
|---|---|
| T1.1 ยิง 3 ครั้ง (email ไม่มี) → 404 | ✅ |
| T1.2 audit เพิ่ม **3 row** (ทุก attempt ไม่ใช่ครั้งเดียว) | ✅ +3 |
| T1.3 audit เก็บ reason + email + **user_agent** | ✅ |
| T1.4 audit เก็บ **ip** (ต้นทาง) | ✅ 127.0.0.1 |

### Group 2 — request_logs traceability (6/6) ⭐
ตอบ "เข้าทางไหน ใช้อะไร ทำอะไร":
| Test | เก็บอะไร | ผล |
|---|---|---|
| T2.1 | request ถูกเก็บ | ✅ |
| T2.2 | method + path (ทำอะไร ที่ไหน) | ✅ POST /...whitelist |
| T2.3 | user_agent (ใช้อะไรเข้ามา) | ✅ |
| T2.4 | user_id (ใครทำ) | ✅ |
| T2.5 | status_code (ผลลัพธ์) | ✅ 404 |
| T2.6 | ip (ต้นทาง) | ✅ 127.0.0.1 |

### Group 3 — Rate limit (1/1)
| Test | ผล |
|---|---|
| T3.1 ยิงรัว → 429 ที่ request #28 | ✅ (30/min ทำงาน) |

---

## 4. การมองเห็นที่ได้ (Forensic Trail)

หลังแก้ — ไล่เหตุการณ์ได้ครบจาก 2 ตาราง:

```
request_logs : POST /developer/subsystems/X/whitelist/user · 404 · 127.0.0.1 · FailLogDriver/1.0 · user=admin   ← ทุก click
audit_logs   : admin · whitelist_add_failed · email=ghost@uni.ac.th · reason=email_not_found · ip=127.0.0.1 · UA=...   ← ทุก attempt
```

**รู้ครบ:** ใคร (user_id/actor) · จาก IP ไหน · อุปกรณ์อะไร (UA) · ทำ action อะไร · endpoint ไหน · ผลเป็นยังไง · กี่ครั้ง

---

## 5. ปัญหาที่เจอ + วิธีแก้ (ระหว่าง test)

### ⚠️ ใช้ email `.invalid` TLD → 422 ก่อนถึง logging
**อาการ:** รอบแรก driver ใช้ `@nowhere.invalid` → pydantic `EmailStr` reject (validation 422) **ก่อน** เข้า endpoint → logging code ไม่รัน + rate limiter ไม่นับ
**สาเหตุ:** FastAPI validate body (422) ก่อน dependency + limiter decorator → failure ที่ schema level ไม่ถึง business logic
**วิธีแก้:** เปลี่ยนเป็น `@uni.ac.th` (format ถูก แต่ไม่มีใน Hub) → ผ่าน pydantic → ถึง 404 path → log ทำงาน
**บทเรียน:** rate limit + failure log ครอบเฉพาะ request ที่ผ่าน schema validation; ส่วน 422 (malformed) จับโดย request_logs middleware แทน

---

## 6. สรุป

| โจทย์ผู้ใช้ | สถานะ |
|---|---|
| กดอะไรเก็บทั้งหมด (รวม fail) | ✅ failure path log แล้ว |
| รู้ต้นทาง (IP) | ✅ request_logs + audit |
| รู้อุปกรณ์ (ใช้อะไรเข้ามา) | ✅ user_agent ทั้ง 2 ชั้น |
| รู้ทำอะไรไปบ้าง | ✅ method/path/action |
| ยิงซ้ำมี action | ✅ log ทุกครั้ง + rate limit 429 |
| **Alert เมื่อ fail ซ้ำ (option 3)** | ⏳ backlog (task #21) |

---

*รัน reproducible: `docker compose exec hub-backend python -m tests.manual_failure_log_ratelimit_driver` (เว้น ≥1 นาที/รัน)*
