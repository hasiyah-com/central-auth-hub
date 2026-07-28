# ค้นหาผู้ใช้แบบอิสระ (Free-text Search) — 2026-07-22

## ปัญหาเดิม

หน้า "ผู้ใช้งาน" (`/users`) ค้นหาผู้ใช้ได้จำกัดมาก:

- Backend `GET /admin/users/` รับแค่ `user_type` (ตรงตัว) และ `faculty` (**ตรงตัวเป๊ะ** `==`)
- Frontend มีช่อง input เดียวชื่อ "กรองตามคณะ…" ที่ผูกกับ `faculty` แบบ exact match

**ผลคือ:**
- พิมพ์ `วิศว` → **ไม่เจอ** (ต้องพิมพ์ `วิศวกรรมศาสตร์` เป๊ะทุกตัวอักษร)
- ค้นด้วย **ชื่อ / นามสกุล / อีเมล / รหัสนักศึกษา / สาขา / ตำแหน่ง / เบอร์โทร** → **ทำไม่ได้เลย**

## วิธีแก้

### Backend — `hub/backend/app/routers/users.py`

เพิ่มพารามิเตอร์ `q` ที่ค้นข้าม **7 ฟิลด์พร้อมกัน** (OR) ด้วย `ILIKE` (partial + case-insensitive):

```python
if q and q.strip():
    like = f"%{_escape_like(q.strip())}%"
    query = query.filter(or_(
        User.full_name.ilike(like),
        User.email.ilike(like),
        User.identifier.ilike(like),
        User.faculty.ilike(like),
        User.major.ilike(like),
        User.year_or_position.ilike(like),
        User.phone.ilike(like),
    ))
```

**ประเด็นความปลอดภัยที่จัดการ — escape LIKE wildcard:**

```python
def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
```

ถ้าไม่ escape ผู้ใช้พิมพ์ `%` จะกลายเป็น wildcard → คืนผู้ใช้ **ทุกคน** (ผลลัพธ์หลอกว่า "ค้นเจอ")
และ `_` จะ match อักษรใดก็ได้ 1 ตัว ต้อง escape `\` ก่อนเสมอ ไม่งั้นจะไป escape ตัว escape ที่เพิ่งใส่เอง

`q` ใช้ร่วมกับ filter เดิมได้ (AND) — เช่น `?q=วิศว&user_type=student`

### Frontend — `hub/frontend/app/(console)/users/page.tsx`

- เปลี่ยนช่อง "กรองตามคณะ" → ช่องค้นหาเดียว `ค้นหา ชื่อ, อีเมล, รหัส, คณะ, สาขา…`
- **debounce 300ms** — พิมพ์ต่อเนื่องยิง request ครั้งเดียวตอนหยุดพิมพ์ (เดิมยิงทุกตัวอักษร)
- ปุ่ม ✕ ล้างคำค้นหา + ไอคอน 🔍
- แสดงผลลัพธ์: `พบ N รายการ จากคำค้น "..."` และข้อความ empty ที่ระบุคำค้น

## ผลการทดสอบ

### TDD — RED → GREEN

**RED** (ก่อน implement) — 2 เทสต์ที่พิสูจน์ว่า `q` ถูกใช้จริง fail:

```
FAILED tests/test_user_search.py::test_search_no_match_returns_empty
  AssertionError: Left contains 110 more items  ← ค้นคำที่ไม่มีจริง แต่คืนทุกคน
FAILED tests/test_user_search.py::test_search_wildcard_is_escaped
  AssertionError: '%' ต้องถูกมองเป็นตัวอักษรธรรมดา ไม่ใช่ wildcard
========================= 2 failed, 8 passed in 6.19s =========================
```

> หมายเหตุ: 8 ตัวที่ "ผ่าน" ตอน RED เป็น false positive — เพราะระบบคืนผู้ใช้ทุกคนอยู่แล้ว
> การ assert ว่า "เป้าหมายอยู่ในผลลัพธ์" จึงผ่านโดยปริยาย เทสต์ 2 ตัวที่ fail คือตัวที่พิสูจน์จริง

**GREEN** (หลัง implement):

```
tests/test_user_search.py ..........                                     [100%]
============================== 10 passed in 2.46s ==============================
```

| Test | ยืนยัน |
|---|---|
| `test_search_by_partial_full_name` | ค้นบางส่วนของชื่อได้ |
| `test_search_by_partial_email` | ค้นบางส่วนของอีเมลได้ |
| `test_search_by_partial_faculty` | **พิมพ์ `วิศว` เจอ `วิศวกรรมศาสตร์`** (เดิมทำไม่ได้) |
| `test_search_by_partial_identifier` | ค้นด้วยรหัสนักศึกษา/พนักงานได้ |
| `test_search_by_partial_major` | ค้นด้วยสาขาได้ |
| `test_search_is_case_insensitive` | ตัวพิมพ์เล็ก/ใหญ่ ผลเหมือนกัน |
| `test_search_no_match_returns_empty` | ไม่เจอ → คืน list ว่าง (ไม่ใช่คืนทุกคน) |
| `test_search_empty_q_returns_all` | q ว่าง → พฤติกรรมเดิมไม่พัง |
| `test_search_wildcard_is_escaped` | `%` ถูก escape ไม่เป็น wildcard |
| `test_search_combines_with_user_type_filter` | ใช้ร่วมกับ filter เดิมได้ (AND) |

### ทดสอบกับข้อมูลจริงในระบบ

```
ค้น 'วิศว'        → 23 รายการ   (อภิลักษณ์ นามเสวตร | วิศวกรรมศาสตร์ | โยธา | 650013)
ค้น 'แพทย'        → 17 รายการ   (Jkfura Kook | แพทยศาสตร์ | จิตเวช | 650088)
ค้น 'จิตเวช'      → 1 รายการ    (ค้นด้วยสาขา)
ค้น '650088'      → 1 รายการ    (ค้นด้วยรหัสนักศึกษา)
ค้น 'U06'     → 1 รายการ    (ค้นด้วยอีเมล)
ค้น 'บรรณารักษ์'  → 1 รายการ    (ค้นด้วยตำแหน่ง)
ค้น 'ผศ.'         → 6 รายการ    (ค้นด้วยตำแหน่งวิชาการ)
```

### Regression

```
tests/test_user_search.py ..........          [ 27%]
tests/test_rbac.py ........                   [ 48%]
tests/test_user_lifecycle.py .............    [ 83%]
tests/test_totp_recovery.py ......            [100%]
============================== 37 passed in 6.80s ==============================
```

TypeScript: `npx tsc --noEmit` → ไม่มี error

## ไฟล์ที่แก้

- `hub/backend/app/routers/users.py` — เพิ่ม `q` param + `_escape_like()` helper + import `or_`
- `hub/frontend/app/(console)/users/page.tsx` — ช่องค้นหาเดียว + debounce 300ms + ปุ่มล้าง
- `hub/backend/tests/test_user_search.py` — ใหม่ (10 tests)

## หมายเหตุด้านความปลอดภัย

- Endpoint นี้อยู่หลัง `Depends(require_hub_admin)` อยู่แล้ว — เฉพาะผู้ดูแลระบบค้นข้อมูล PII ได้
- ไม่ได้เปิดให้ค้นด้วย `google_sub` / `line_sub` (identifier ของ IdP) โดยตั้งใจ — ไม่ใช่ข้อมูลที่ผู้ดูแลต้องค้น
- ใช้ SQLAlchemy parameterized query (ไม่ต่อ string เอง) + escape LIKE wildcard → ปลอดภัยจาก SQL injection
