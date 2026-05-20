# Subsystem B — ระบบห้องสมุด Skill

**Domain**: Subsystem B (port 8002) — ระบบยืม/คืนหนังสือ
**Invoke**: `/subsystem-library` หรือเมื่อทำงานใน `hub/subsystem-library/`
**Security rules**: ดู `/central-auth-hub` (shared)
**Hub client + session pattern**: เหมือน Subsystem A (/subsystem-dorm) ทุกประการ

---

## Architecture

```
hub/subsystem-library/app/
├── main.py, config.py, database.py, deps.py
├── models.py        books, members, borrowings, library_audit_logs
├── services/        hub_client.py, session.py, audit.py  (same pattern as dorm)
└── routers/
    ├── auth.py           /login, /oauth/start, /oauth/callback, /logout
    ├── pages.py          /, /books?q=&category=, /books/{id}, /me
    ├── borrow.py         POST /borrow/books/{id}/request, /cancel
    └── librarian.py      /librarian/borrows, /members, approve/reject/return
```

**DB**: `library_db` บน `postgres-library` (port 5434) — **ไม่มี FK ไป Hub**

## Data Model

```
books:    id, title, author, isbn, category, total_copies, available_copies, description
members:  id, hub_user_id (UUID จาก JWT.sub), name, email, student_id, member_since
borrowings: id, book_id, member_id, status (pending/approved/returned/cancelled/rejected),
            requested_at, approved_at, due_date, returned_at
library_audit_logs: id, actor_id, action, target_type, target_id, ip, metadata, created_at
```

**Book categories** (6 หมวด จาก seed): Computer Science, Mathematics, Physics, Literature, History, Engineering

## Business Rules

```
Borrow flow:  member → POST /borrow/books/{id}/request  (pending)
                        ตรวจ available_copies > 0
              librarian → POST /librarian/borrows/{id}/approve
                          → available_copies -= 1
              member → คืนผ่าน librarian → POST /librarian/borrows/{id}/return
                       → available_copies += 1

Cancel:  member → POST /cancel (ถ้ายัง pending เท่านั้น — ยังไม่ approved)
Reject:  librarian → POST /librarian/borrows/{id}/reject

Due date: ปกติ 14 วันหลัง approved (config ได้)
```

## Difference from Subsystem A (Dorm)

| ด้าน | Dorm | Library |
|------|------|---------|
| Resource | rooms (capacity) | books (copies count) |
| Staff role | staff (approve checkin) | librarian |
| Cancel window | before check-in | pending only |
| Count tracking | room status | available_copies |
| Theme (Tailwind) | indigo | emerald |

## Common Tasks

**Seed books** (30 หนังสือ × 6 หมวด):
```bash
docker compose exec subsystem-library python -m scripts.seed_books
```

**Test search**: http://localhost:8002/books?q=python&category=Computer+Science

**Logs**:
```bash
docker compose logs -f subsystem-library
```
