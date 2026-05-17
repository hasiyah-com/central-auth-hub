# Subsystem B — ระบบห้องสมุด (Week 7)

Subsystem ตัวที่ 2 ที่ login ผ่าน Central Auth Hub

- Catalog หนังสือ + ค้นหา (title/author/isbn) + filter ตามหมวด
- Flow ยืม: `requested → active → returned` (เปรียบเทียบ Subsystem A: `pending → approved → checked_in`)
- Computed overdue (status=active AND due_at < now)
- Role: `member` (ขอยืม) / `librarian` (อนุมัติ + รับคืน)

## OAuth Flow

เหมือน Subsystem A ทุกอย่าง — ดู `hub/subsystem-dorm/README.md` สำหรับ flow diagram

## Setup (ครั้งแรก)

ขั้นตอนเหมือน Subsystem A:

### 1. รัน containers
```bash
docker compose up -d --build
```

### 2. ลงทะเบียน Subsystem B กับ Hub

ใน Swagger UI: `POST /developer/subsystems` (Bearer token จาก admin)
```json
{
  "name": "ระบบห้องสมุด",
  "description": "Subsystem B — Senior Project Week 7",
  "redirect_uris": ["http://localhost:8002/oauth/callback"],
  "scope": ["email", "name", "student_id", "faculty", "phone"]
}
```

### 3. เอา client_id + client_secret มาใส่ .env

```bash
cp hub/subsystem-library/.env.example hub/subsystem-library/.env
```

แก้:
```
LIBRARY_CLIENT_ID=cli_xxx
LIBRARY_CLIENT_SECRET=sec_xxx
```

แล้ว `docker compose restart subsystem-library`

### 4. Admin อนุมัติ + เพิ่ม whitelist

- `POST /admin/subsystems/{id}/approve`
- `POST /developer/subsystems/{id}/whitelist/user` ใส่:
  ```json
  { "email": "650001@uni.ac.th", "role": "member" }
  ```
  หรือ librarian:
  ```json
  { "email": "somchai006@uni.ac.th", "role": "librarian" }
  ```

### 5. Seed หนังสือ (30 เล่ม × 6 หมวด)

```bash
docker compose exec subsystem-library python -m scripts.seed_books
```

### 6. เปิดใช้งาน

http://localhost:8002/

## โครงสร้าง

```
hub/subsystem-library/
├── Dockerfile, requirements.txt, .env.example
├── app/
│   ├── main.py, config.py, database.py, models.py, deps.py
│   ├── services/
│   │   ├── hub_client.py    # PKCE + token exchange + JWKS verify
│   │   ├── session.py       # itsdangerous signed cookie
│   │   └── audit.py         # log_action()
│   ├── routers/
│   │   ├── auth.py          # /login, /oauth/*, /logout
│   │   ├── pages.py         # /, /books?q=&category=, /books/{id}, /me
│   │   ├── borrow.py        # POST /borrow/books/{id}/request, /cancel
│   │   └── librarian.py     # /librarian/borrows + members + approve/reject/return
│   ├── templates/           # Jinja2 + Tailwind CDN (theme: emerald)
│   └── static/style.css
└── scripts/seed_books.py
```

## Database (library_db ใน postgres-library:5432)

| Table | คำอธิบาย |
|-------|----------|
| `books` | catalog (seed 30 เล่ม × 6 หมวด) |
| `members` | สร้างจาก JWT.sub ตอน login ครั้งแรก |
| `borrowings` | requested → active → returned (cancel ผ่าน cancelled_at) |
| `library_audit_logs` | audit log |

## Borrowing lifecycle

```
[member POST /borrow/books/{id}/request]
   → status=requested
        ↓
[librarian approve]         [librarian / member reject/cancel]
   → status=active            → status=cancelled (soft delete)
   → book.copies_available--
   → set due_at = now + 14 วัน
        ↓
[librarian POST .../return]
   → status=returned
   → book.copies_available++
```

Overdue ไม่ใช่ status แยก — เป็น computed: `status='active' AND due_at < NOW()`

## Business Rules

- ยืมพร้อมกันได้สูงสุด `MAX_BORROWS_PER_MEMBER` (default = 3)
- ระยะยืม `DEFAULT_BORROW_DAYS` (default = 14 วัน)
- 1 user ยืม 1 เล่มได้ครั้งเดียวพร้อมกัน — ไม่สามารถ request เล่มเดิมซ้ำตอนยังไม่คืน
- Member ยกเลิกเองได้เฉพาะตอน `requested` — `active` แล้วต้องคืนผ่าน librarian

## Endpoints

### Member
- `GET /login`
- `GET /` — หน้าหลัก (นับยืม active/pending)
- `GET /books?q=...&category=...` — ค้นหา + filter
- `GET /books/{id}` — รายละเอียด + ฟอร์มขอยืม
- `GET /me` — โปรไฟล์ + ประวัติยืม
- `POST /borrow/books/{id}/request`
- `POST /borrow/{id}/cancel`

### Librarian (role=librarian เท่านั้น)
- `GET /librarian/members` — สมาชิกทั้งหมด
- `GET /librarian/borrows?status={requested|active|overdue|returned|all}`
- `POST /librarian/borrows/{id}/approve` — อนุมัติ → set due_at
- `POST /librarian/borrows/{id}/reject` — ปฏิเสธ
- `POST /librarian/borrows/{id}/return` — รับคืน → คืน copy
