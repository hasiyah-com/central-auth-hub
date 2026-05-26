# P2 — Step-Up Authentication: Session Downgrade (Week 9-10)

## ทำไมถึงเลือก Session Downgrade

เปรียบเทียบ 4 ตัวเลือกตามหลัก CIA (ดูรายละเอียด `docs/mfa-options-analysis.md`):

| ตัวเลือก | Confidentiality | Integrity | Availability | สรุป |
|----------|:-:|:-:|:-:|---|
| Student ID Challenge | 🟡 | 🟡 | 🟢 | รหัสนักศึกษาไม่ใช่ความลับ |
| Email OTP | 🟢 | 🟢 | 🔴 | SMTP ล่ม = เข้าไม่ได้เลย |
| **Session Downgrade** | 🟡 | 🟢 | 🟢 | **เหมาะที่สุดในบริบทมหาวิทยาลัย** |
| Trusted Device | 🟢 | 🟢 | 🟡 | นักศึกษาใช้ Lab/คอมหลายเครื่อง — friction สูง |

ML model เก็บ `is_new_device` + `is_new_user_agent_family` เป็น feature อยู่แล้ว
→ Trusted Device ซ้ำซ้อน โมเดลจัดการสัญญาณ "device ใหม่" แทนแล้ว

---

## พฤติกรรมที่ต้องการ

```
score < 0.40   →  PASS (เดิม — ไม่เปลี่ยน)
0.40 – 0.70    →  PASS + banner เตือนเล็กน้อย
score ≥ 0.70   →  READ-ONLY session
                   JWT มี claim "restricted": true
                   subsystems block POST/PUT/DELETE
                   แสดง banner: "สิทธิ์ถูกจำกัดชั่วคราว กรุณา login ใหม่"
                   บันทึก audit log + แจ้ง admin
```

---

## ไฟล์ที่ต้องแก้

### Hub Backend

**1. `hub/backend/app/routers/oauth.py`** (line ~222-232)
- เพิ่ม `restricted = bool(float(anomaly_score) >= 0.70)` หลัง actual_decision logic
- ส่ง `"restricted": restricted` เข้า Redis auth code dict

**2. `hub/backend/app/services/jwt_service.py`**
- เพิ่ม parameter `restricted: bool = False` ใน `create_subsystem_token()`
- เพิ่ม claim `"restricted": restricted` ใน JWT payload

**3. `hub/backend/app/routers/oauth.py`** (ส่วน token exchange)
- ดึง `restricted` จาก Redis auth code และส่งเข้า `create_subsystem_token()`

### Subsystems

**4. `hub/subsystem-dorm/app/deps.py`** — เพิ่ม dependency
```python
def require_write_access(user=Depends(get_current_user)):
    if user.get("restricted"):
        raise HTTPException(403, "session ถูกจำกัดสิทธิ์ชั่วคราว กรุณา login ใหม่")
```

**5. `hub/subsystem-dorm/app/routers/reservation.py`** — เพิ่ม `Depends(require_write_access)` ใน POST endpoints

**6. `hub/subsystem-dorm/app/routers/staff.py`** — เช่นกัน

**7. `hub/subsystem-library/app/deps.py`** — pattern เดียวกับ dorm

**8. `hub/subsystem-library/app/routers/borrow.py`** — เพิ่ม dependency

**9. `hub/subsystem-library/app/routers/librarian.py`** — เพิ่ม dependency

---

## Verification

```bash
# 1. restart หลังแก้ Hub
docker compose restart hub-backend

# 2. ตรวจ JWT ที่ออกให้ user ที่มี score สูง
#    decode JWT → ต้องมี "restricted": true

# 3. ทดสอบ subsystem-dorm
#    GET  /rooms                           → 200  (read ยังได้)
#    POST /reservation/rooms/{id}/reserve  → 403  (write ถูก block)

# 4. ทดสอบ session ปกติ (score < 0.70)
#    POST /reservation/rooms/{id}/reserve  → ทำงานได้ปกติ

# 5. ตรวจ shadow mode — would_block ต้อง trigger restricted ด้วย
```

---

## หมายเหตุ

- Shadow Mode (`ML_SHADOW_MODE=true`) ยังเปิดอยู่ → `would_block` ก็ trigger restricted เช่นกัน
- ไม่ต้องเพิ่ม column ใหม่ใน DB — `restricted` อยู่ใน JWT claim เท่านั้น
- เปิด enforce ได้ทันทีที่ precision ของโมเดลดีพอ (ใช้ P1-6 threshold preview ช่วยตัดสินใจ)
- ทำต่อจาก P1 (ML Admin Endpoints) และ Week 8 (Dashboard) เสร็จก่อน
