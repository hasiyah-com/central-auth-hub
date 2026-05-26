# 🐛 Bug Report — Subsystem B (ระบบห้องสมุด)

> ตรวจสอบเมื่อ: 2026-05-22
> ผู้ตรวจ: Claude (Sonnet) + ผู้ใช้
> ไฟล์: `hub/subsystem-library/`

---

## สรุป

| Severity | Count | สถานะ |
|----------|-------|------|
| 🔴 Critical | 2 | B1 ✅ fixed |
| 🟠 High | 3 | |
| 🟡 Medium | 3 | |
| 🟢 Low | 4 | |
| **รวม** | **12** | |

---

## 🔴 CRITICAL — Race conditions (production-blocker)

### B1. `copies_available` decrement ไม่ atomic ✅ FIXED

- **File:** `routers/librarian.py:111-122` (approve_borrow) + `:192-201` (receive_return)
- **Issue:** ถ้า librarian 2 คนกด approve คำขอ 2 รายการของหนังสือ **เล่มเดียวกัน** พร้อมกัน — ทั้งคู่อ่าน `copies_available = 1`, ทั้งคู่ผ่านเช็ค, ทั้งคู่ decrement → ค่าเป็น `-1` (oversell)
- **Fix applied:** ใช้ atomic `UPDATE ... WHERE copies_available > 0` แทน read-modify-write + เช็ค `rowcount`:

```python
result = db.execute(
    update(Book)
    .where(Book.id == borrowing.book_id, Book.copies_available > 0)
    .values(copies_available=Book.copies_available - 1)
)
if result.rowcount == 0:
    raise HTTPException(400, "ไม่มี copy ว่างแล้ว — มีคนอนุมัติก่อน")
```

ทำเช่นเดียวกันใน `receive_return` (เพิ่ม +1 แต่ clamp ที่ `copies_total`).

---

### B2. ขอยืม duplicate ได้ถ้ายิงพร้อมกัน

- **File:** `routers/borrow.py:39-78` (request_borrow)
- **Issue:** กด "ขอยืม" 2 ครั้งเร็วๆ (เปิด 2 tab) → ทั้งคู่ผ่านเช็ค "existing request" + max_borrows → สร้าง 2 borrowings ทันที
- **Fix recommended:** เพิ่ม partial unique index ใน `models.py`:

```sql
CREATE UNIQUE INDEX idx_borrowings_active_per_book
  ON borrowings (hub_user_id, book_id)
  WHERE status IN ('requested', 'active');
```

SQLAlchemy:
```python
from sqlalchemy import Index, text
__table_args__ = (
    Index(
        "uq_borrowings_active_per_user_book",
        "hub_user_id", "book_id",
        unique=True,
        postgresql_where=text("status IN ('requested', 'active')"),
    ),
)
```

ใน `borrow.py` ห่อ `db.flush()` ด้วย `try/except IntegrityError` ตอบ 409 แทน 500.

---

## 🟠 HIGH — Functional bugs

### B3. `get_or_create_member` มี race condition

- **File:** `deps.py:77-88`
- **Issue:** Login พร้อมกัน 2 device → both pass `if member is None` → second INSERT crash ด้วย `IntegrityError` (unique constraint บน `hub_user_id`)
- **Fix:** wrap INSERT ใน try/except `IntegrityError`, rollback แล้ว query ใหม่:

```python
try:
    db.add(member); db.flush()
except IntegrityError:
    db.rollback()
    member = db.query(Member).filter(Member.hub_user_id == user.hub_user_id).first()
```

---

### B4. UTC offset hardcoded

- **File:** `routers/pages.py:54, 127`
- **Issue:** `datetime.utcnow()` (deprecated ใน Python 3.12+) แล้วบวก `(now.hour + 7) % 24` แบบ manual
- **Fix:** ใช้ `zoneinfo`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
now = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC สำหรับ DB
now_th = datetime.now(_BANGKOK_TZ)                       # tz-aware สำหรับ display
greeting = _greeting(now_th.hour)
```

---

### B5. Failed login ไม่มี audit log

- **File:** `routers/auth.py:76-101` (oauth_callback)
- **Issue:** เมื่อ JWT verify fail, state ไม่ตรง, token exchange fail — แค่ `raise HTTPException` ไม่บันทึก audit
- **Impact:** Hub ML model หา `failed_logins_24h` ไม่ครบ + investigate attack ยาก
- **Fix:** เพิ่ม helper `_log_failed_login(db, request, reason, detail)` เรียกก่อน raise ทุกจุด

```python
def _log_failed_login(db, request, reason, detail=""):
    try:
        log_action(db, actor_hub_user_id=None, action="library_login_failed",
                   target_type="oauth_callback", ip=get_client_ip(request),
                   metadata={"reason": reason, "detail": detail[:200]})
        db.commit()
    except Exception:
        db.rollback()
```

จุดที่ต้อง log:
- `error` from Hub → `hub_error`
- missing `code`/`state` → `missing_code_or_state`
- `oauth_cookie` หมดอายุ → `oauth_state_expired`
- `state mismatch` → `csrf_state_mismatch` ⚠️ priority
- token exchange fail → `token_exchange_http_error` / `_network_error`
- JWT verify fail → `jwt_verify_failed`

---

## 🟡 MEDIUM

### B6. ไม่มี production config validation

- **File:** `config.py`
- **Issue:** ถ้า set `APP_ENV=production` แต่ `session_secret_key` ยังเป็น `"dev-secret-change-me"` → server start ปกติ (เสี่ยงโดน session forgery)
- **Fix:** เพิ่ม validator (อ้างอิงจาก Hub):

```python
from pydantic import model_validator

@model_validator(mode="after")
def validate_production(self):
    if self.app_env == "production":
        if self.session_secret_key == "dev-secret-change-me":  # pragma: allowlist secret
            raise ValueError("ต้องเปลี่ยน session_secret_key ใน production")
        if not self.session_cookie_secure:
            raise ValueError("session_cookie_secure ต้อง True ใน production")
        if not self.library_client_secret:
            raise ValueError("ต้อง set library_client_secret ใน production")
    return self
```

---

### B7. Logout ไม่ลบ OAuth state cookie

- **File:** `routers/auth.py:144-163`
- **Issue:** delete `session_cookie_name` แต่ไม่ delete `library_oauth_state` → cookie ค้างจนหมดอายุ 10 นาที
- **Fix:** เพิ่ม `response.delete_cookie(_OAUTH_COOKIE, path="/")` ใน logout handler

---

### B8. `audit.log_action` doc string ไม่ชัด (false alarm)

- **File:** `services/audit.py:17`
- comment บอก "caller commit เอง" — ไม่ใช่ bug แต่ทำให้ developer สับสน ควร rename เป็น "caller must commit afterwards"

---

## 🟢 LOW — Style/edge cases

### B9. `nickname` crash ถ้า `full_name` เป็น whitespace

- **File:** `routers/pages.py:130`

```python
(user.full_name or "").strip().split()[0]  # IndexError ถ้า full_name = "   "
```

**Fix:**
```python
parts = (user.full_name or "").strip().split()
if parts:
    nickname = parts[0]
else:
    email = user.email or ""
    nickname = email.split("@")[0] if "@" in email else (email or "user")
```

---

### B10. N+1 query ใน `list_members`

- **File:** `routers/librarian.py:31-39`
- 100 members → 100 SELECT COUNT — ยอมรับได้สำหรับ senior project
- **Fix:**

```python
counts = dict(
    db.query(Borrowing.hub_user_id, func.count(Borrowing.id))
    .filter(Borrowing.status.in_(["requested", "active"]))
    .group_by(Borrowing.hub_user_id).all()
)
active_count = {str(m.id): counts.get(m.hub_user_id, 0) for m in members}
```

---

### B11. `book_detail` ไม่บล็อกผู้ใช้ที่มี overdue

- **File:** `routers/pages.py:202-246`
- ผู้ใช้มี active borrow ที่ overdue อยู่ → ขอยืมเล่มใหม่ได้ (ถ้ายังไม่เต็ม max)
- **Severity:** ขึ้นกับ policy ของห้องสมุด — ไม่ใช่ bug ถ้า policy ตามนี้

---

### B12. `hub_client.exchange_code_for_token` ไม่แยก error type

- **File:** `services/hub_client.py:43-57` + `routers/auth.py:91`
- Hub ตอบ 400 (bad PKCE) กับ 500 (hub down) ถูก wrap เป็น `502 Bad Gateway` ทั้งคู่
- **Severity:** debug ลำบาก แต่ไม่ส่งผลต่อ runtime
- **Fix:** catch `httpx.HTTPStatusError` แยกจาก `httpx.RequestError`:

```python
except httpx.HTTPStatusError as e:
    status_code = 400 if 400 <= e.response.status_code < 500 else 502
    raise HTTPException(status_code, f"แลก token ล้มเหลว — Hub ตอบ {e.response.status_code}")
except httpx.RequestError as e:
    raise HTTPException(502, f"เชื่อมต่อ Hub ไม่ได้: {e}")
```

---

## ลำดับแนะนำการแก้

1. ✅ **B1** — atomic copies_available (DONE)
2. **B2** — partial unique index (ป้องกัน duplicate borrow request)
3. **B3** — member creation race
4. **B5** — audit failed login (สำคัญสำหรับ ML + security review)
5. **B6** — production config validation
6. **B4** — UTC timezone cleanup
7. **B7** — logout OAuth cookie
8. **B9** — nickname edge case
9. **B10** — N+1 query (optional perf)
10. **B12** — error differentiation (optional polish)
11. **B8, B11** — review/skip ตาม policy

---

## หมายเหตุ

- Subsystem A (ระบบหอพัก) มี race condition แบบเดียวกับ B3 (`get_or_create_resident`) — ควรตรวจสอบเพิ่ม
- Subsystem A ไม่มี B1/B2 equivalent เพราะ logic ต่างกัน (room.status binary แทน count)
- Hub-level race conditions (เช่น OAuth atomic auth code via Redis getdel) ถูกแก้แล้วใน Week 5
