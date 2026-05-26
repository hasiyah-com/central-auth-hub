# 🐛 Bug Report — Subsystem A (ระบบหอพัก)

> ตรวจสอบเมื่อ: 2026-05-22
> ผู้ตรวจ: Claude (Sonnet) + ผู้ใช้
> ไฟล์: `hub/subsystem-dorm/`

---

## สรุป

| Severity | Count | สถานะ |
|----------|-------|------|
| 🔴 Critical | 2 | ✅ D1, D2 fixed |
| 🟠 High | 3 | ✅ D3, D4, D5 fixed |
| 🟡 Medium | 3 | ✅ D6, D7, D8 fixed |
| 🟢 Low | 3 | ✅ D9, D10, D11 fixed |
| **รวม** | **11** | **✅ ทั้งหมด fixed** |

> หมายเหตุการ deploy: D2 (partial unique index) จะมีผลกับ DB ที่ create ใหม่เท่านั้น
> สำหรับ DB เดิม ต้อง run manually:
> ```sql
> CREATE UNIQUE INDEX uq_reservations_active_per_user
>   ON reservations (hub_user_id)
>   WHERE cancelled_at IS NULL AND status IN ('pending', 'approved', 'checked_in');
> ```

---

## 🔴 CRITICAL — Race conditions

### D1. Check-in สามารถ overshoot capacity ของห้องได้

- **File:** `routers/staff.py:199-264` (checkin_reservation)
- **Issue:** Staff 2 คน check-in reservations 2 รายการ ไปยังห้องเดียวกัน (capacity=2, มีคนอยู่แล้ว 1 คน) → ทั้งคู่ pass `room.status == "available"` (เพราะยังไม่เต็ม) → ทั้งคู่ assign `resident.room_id = room.id` → ห้องจริงๆ จะมี 3 คนทันที! status จะถูกตั้งเป็น "full" ที่หลัง — แต่ assignment เกิดไปแล้ว

  เคสที่ร้ายกว่า: ถ้าเริ่มจากห้องว่างทั้งห้อง (occupants=0) แล้ว staff check-in 3 คนพร้อมกันให้ห้อง capacity=2 → ทุกคน pass status check → ห้องลงเอยมี 3 คน

- **Fix:** ใช้ atomic UPDATE บน `rooms` row + check capacity ก่อน assign:

```python
from sqlalchemy import update, and_, select, func

# Lock room row + count occupants atomically
result = db.execute(
    update(Room)
    .where(
        Room.id == reservation.room_id,
        Room.status == "available",
        # ใช้ subquery นับ checked-in residents
        (
            select(func.count(Resident.id))
            .where(Resident.room_id == Room.id,
                   Resident.status == "checked_in")
            .scalar_subquery()
        ) < Room.capacity,
    )
    .values()  # ไม่ update อะไร แค่ lock + validate
)
# หรือใช้ SELECT ... FOR UPDATE บน room แล้วเช็ค count ใน Python
```

ทางเลือกที่ง่ายกว่า: ใช้ `with_for_update()` ตอน query room:
```python
room = (
    db.query(Room)
    .filter(Room.id == reservation.room_id)
    .with_for_update()  # SELECT ... FOR UPDATE
    .first()
)
if not room:
    raise HTTPException(404, "ไม่พบห้อง")
occupants_now = (
    db.query(Resident)
    .filter(Resident.room_id == room.id, Resident.status == "checked_in")
    .count()
)
if occupants_now >= room.capacity:
    raise HTTPException(400, f"ห้อง {room.room_number} เต็ม capacity แล้ว")
```

---

### D2. User ส่ง reservation ซ้ำได้ถ้ายิงพร้อมกัน

- **File:** `routers/reservation.py:38-52` (reserve_room)
- **Issue:** เปิด 2 tabs กดส่งคำขอจองพร้อมกัน → ทั้งคู่ pass `active reservation` check → สร้าง 2 reservations ทันที (เกินเงื่อนไข "หนึ่ง active reservation ต่อ user")
- **Fix:** เพิ่ม partial unique index ใน `models.py`:

```python
from sqlalchemy import Index, text

class Reservation(Base):
    # ... existing columns ...
    __table_args__ = (
        Index(
            "uq_reservations_active_per_user",
            "hub_user_id",
            unique=True,
            postgresql_where=text(
                "cancelled_at IS NULL AND status IN ('pending', 'approved', 'checked_in')"
            ),
        ),
    )
```

จากนั้นใน `reserve_room` ห่อ `db.flush()` ด้วย `try/except IntegrityError`:
```python
try:
    db.flush()
except IntegrityError:
    db.rollback()
    raise HTTPException(409, "คุณมี reservation อยู่แล้ว — กรุณาลองใหม่")
```

---

## 🟠 HIGH — Functional bugs

### D3. `get_or_create_resident` race condition

- **File:** `deps.py:75-111`
- **Issue:** Login พร้อมกัน 2 device → both pass `if resident is None` → second INSERT crash ด้วย `IntegrityError` (unique constraint บน `hub_user_id`)
- **Fix:** wrap INSERT ใน try/except `IntegrityError`:

```python
from sqlalchemy.exc import IntegrityError

try:
    db.add(resident); db.flush()
except IntegrityError:
    db.rollback()
    resident = (
        db.query(Resident).filter(Resident.hub_user_id == user.hub_user_id).first()
    )
    if resident is None:
        raise HTTPException(500, "ไม่สามารถสร้าง resident ได้ — ลอง login อีกครั้ง")
```

---

### D4. `checkin_reservation`: room อาจเป็น None

- **File:** `routers/staff.py:228-229`
- **Issue:**
```python
room = db.query(Room).filter(Room.id == reservation.room_id).first()
if room.status != "available":  # ← AttributeError ถ้า room = None
```
- **Scenario:** Room ถูกลบระหว่าง approve กับ check-in (rare แต่เป็นไปได้ถ้า admin จัดการห้อง)
- **Fix:** เพิ่ม null check:
```python
room = db.query(Room).filter(Room.id == reservation.room_id).first()
if not room:
    raise HTTPException(404, "ไม่พบห้องที่จองไว้ — อาจถูกลบ")
if room.status != "available":
    raise HTTPException(400, f"ห้องนี้ไม่ available แล้ว ({room.status})")
```

---

### D5. Failed login ไม่มี audit log

- **File:** `routers/auth.py:93-121` (oauth_callback)
- **Issue:** เมื่อ JWT verify fail, state ไม่ตรง (CSRF!), token exchange fail — แค่ `raise HTTPException` ไม่บันทึก audit
- **Impact:** ML model ของ Hub หา `failed_logins_24h` ไม่ครบ + investigate attack ยาก โดยเฉพาะ `csrf_state_mismatch` ซึ่งเป็น signal สำคัญ
- **Fix:** เพิ่ม helper `_log_failed_login(db, request, reason, detail)` เรียกก่อน raise ทุกจุด:

```python
def _log_failed_login(db, request, reason, detail=""):
    try:
        log_action(db, actor_hub_user_id=None, action="dorm_login_failed",
                   target_type="oauth_callback", ip=get_client_ip(request),
                   metadata={"reason": reason, "detail": detail[:200]})
        db.commit()
    except Exception:
        db.rollback()
```

จุดที่ต้อง log: `hub_error`, `missing_code_or_state`, `oauth_state_expired`, `csrf_state_mismatch` ⚠️, `token_exchange_*`, `jwt_verify_failed`

---

## 🟡 MEDIUM

### D6. ไม่มี production config validation

- **File:** `config.py`
- **Issue:** ถ้า `APP_ENV=production` แต่ `session_secret_key="dev-secret-change-me"` <!-- pragma: allowlist secret --> → server start ปกติ (เสี่ยง session forgery)
- **Fix:** เพิ่ม `model_validator`:

```python
from pydantic import model_validator

@model_validator(mode="after")
def validate_production(self):
    if self.app_env == "production":
        if self.session_secret_key == "dev-secret-change-me":
            raise ValueError("ต้องเปลี่ยน session_secret_key ใน production")
        if not self.session_cookie_secure:
            raise ValueError("session_cookie_secure ต้อง True ใน production")
        if not self.dorm_client_secret:
            raise ValueError("ต้อง set dorm_client_secret ใน production")
    return self
```

---

### D7. `api_staff_residents`: `total` รวม checked_out residents

- **File:** `routers/staff.py:62-63`
```python
total = len(rows)  # รวมทุก resident รวมทั้ง status='checked_out'
```
- **Issue:** สรุปสถิติคลาดเคลื่อน — `checked_out` ไม่ควรนับเป็น "ผู้พักทั้งหมด" ถ้าตามความหมายในหน้า dashboard อื่นๆ ที่ filter `status != 'checked_out'`
- **Fix:**
```python
total = sum(1 for r, rm in rows if r.status != "checked_out")
# หรือ filter ที่ query ตั้งแต่แรก
```

---

### D8. `home` route มี dead code หลัง redirect

- **File:** `routers/pages.py:186-222`
- **Issue:** บรรทัด 195-196 `return RedirectResponse(url="/app.html", ...)` ตามด้วยโค้ดที่ render `home.html` template (~30 บรรทัด) ที่ไม่ทำงานเลย
- **Fix:** ลบ dead code (บรรทัด 197-222) เพื่อความสะอาด:
```python
@router.get("/", response_class=HTMLResponse)
def home(request, user, db):
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/app.html", status_code=302)
```

---

## 🟢 LOW

### D9. N+1 query ใน `api_rooms`

- **File:** `routers/pages.py:107-121`
```python
for room in rooms:
    occupancy[str(room.id)] = db.query(Resident).filter(...).count()
```
- 24 rooms → 24 SELECT COUNT queries
- **Fix:**
```python
from sqlalchemy import func
counts = dict(
    db.query(Resident.room_id, func.count(Resident.id))
    .filter(Resident.room_id.isnot(None), Resident.status != "checked_out")
    .group_by(Resident.room_id).all()
)
occupancy = {str(r.id): counts.get(r.id, 0) for r in rooms}
```

---

### D10. Reservation ไม่มี FK CASCADE — ลบ Room → orphan rows

- **File:** `models.py:78`
- `reservations.room_id` มี FK ไป `rooms.id` แต่ไม่มี `ondelete=` action
- ถ้า admin DELETE room → PostgreSQL จะ raise FK error (default RESTRICT)
- **Severity:** low (rooms ไม่ถูกลบในปกติ — ใช้ status="withdrawn" แทน)
- **Fix (optional):**
```python
room_id = Column(UUID(as_uuid=True),
                 ForeignKey("rooms.id", ondelete="RESTRICT"),
                 nullable=False, index=True)
```
หรือถ้าต้องการลบจริง: `ondelete="SET NULL"` + nullable=True

---

### D11. `hub_client.exchange_code_for_token` ไม่แยก error type

- **File:** `services/hub_client.py` + `routers/auth.py:110-111`
- **Issue:** เหมือน B12 ใน library — `httpx.HTTPStatusError` (Hub 400) กับ `httpx.RequestError` (network) ถูก wrap เป็น 502 เหมือนกัน
- **Severity:** debug ลำบาก
- **Fix:**
```python
except httpx.HTTPStatusError as e:
    status_code = 400 if 400 <= e.response.status_code < 500 else 502
    raise HTTPException(status_code, f"แลก token ล้มเหลว — Hub ตอบ {e.response.status_code}")
except httpx.RequestError as e:
    raise HTTPException(502, f"เชื่อมต่อ Hub ไม่ได้: {e}")
```

---

## ลำดับแนะนำการแก้

1. **D1** — check-in race + capacity overshoot (ผลกระทบกับ business logic)
2. **D2** — duplicate reservation (partial unique index)
3. **D3** — resident creation race
4. **D4** — room None check (defensive)
5. **D5** — audit failed login (security + ML)
6. **D6** — production config validation
7. **D7** — stats accuracy fix
8. **D8** — clean dead code
9. **D9** — N+1 query (perf)
10. **D10** — FK CASCADE policy (optional)
11. **D11** — error type differentiation (optional polish)

---

## เปรียบเทียบกับ Subsystem B (library)

| Bug pattern | Library | Dorm |
|-------------|---------|------|
| Atomic count decrement | B1 ✅ fixed | D1 (check-in capacity) |
| Duplicate request via race | B2 | D2 |
| Member/resident creation race | B3 | D3 |
| Failed login audit | B5 | D5 |
| Production config validation | B6 | D6 |
| OAuth cookie cleanup on logout | B7 | ✅ ไม่มีปัญหา (auth.py:165 ลบ cookie ตอน callback แล้ว) |
| N+1 query | B10 | D9 |
| Error type differentiation | B12 | D11 |

**ต่างกัน:**
- Dorm มี dead code ใน `home` route (D8) — library ไม่มี
- Dorm มี FK ไป rooms ที่ไม่ระบุ CASCADE policy (D10) — library ใช้ FK ปกติ
- Dorm มี race condition ที่ซับซ้อนกว่า (D1: capacity + status + assignment combined)

---

## หมายเหตุ

- ระบบทั้งสองมี B3/D3 pattern เหมือนกัน — ควรแก้พร้อมกัน
- Hub-level race conditions (เช่น OAuth atomic auth code via Redis getdel) ถูกแก้แล้วใน Week 5
- `phone` field ใน dorm `CurrentUser` ยังอยู่ — ใน library ถอดออกแล้ว (uncommitted change pending)
