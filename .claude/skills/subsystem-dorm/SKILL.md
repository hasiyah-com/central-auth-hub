# Subsystem A — ระบบหอพัก Skill

**Domain**: Subsystem A (port 8001) — ระบบจองห้องหอพัก
**Invoke**: `/subsystem-dorm` หรือเมื่อทำงานใน `hub/subsystem-dorm/`
**Security rules**: ดู `/central-auth-hub` (shared)

---

## Architecture

```
hub/subsystem-dorm/app/
├── main.py, config.py, database.py, deps.py
├── models.py        rooms, residents, reservations, dorm_audit_logs
├── services/
│   ├── hub_client.py   PKCE + token exchange + JWKS verify (10min cache)
│   ├── session.py      itsdangerous signed cookie
│   └── audit.py        log_action() ของ subsystem
└── routers/
    ├── auth.py          /login, /oauth/start, /oauth/callback, /logout
    ├── pages.py         /, /me, /rooms, /rooms/{id}
    ├── reservation.py   POST /reservation/rooms/{id}/reserve, /cancel
    └── staff.py         /staff/residents, /staff/reservations (approve/reject/checkin)
```

**DB**: `dorm_db` บน `postgres-dorm` (port 5433) — **ไม่มี FK ไป Hub**

## Hub Client Pattern (OAuth flow)

```python
# 1. เริ่ม OAuth
GET /oauth/start → hub_client.get_authorization_url(state, code_verifier)
                 → redirect ไป Hub /oauth/authorize

# 2. Hub callback กลับมา
GET /oauth/callback?code=...&state=...
  → hub_client.exchange_code(code, code_verifier)   # PKCE verify
  → hub_client.verify_jwt(token)                    # JWKS verify, aud=client_id
  → สร้าง/อัปเดต resident record
  → set session cookie

# 3. Protected routes
Depends(get_current_resident) → อ่าน session cookie → verify
```

## Session Cookie

```python
# services/session.py
# HttpOnly + SameSite=Lax + max_age=3600
# itsdangerous.URLSafeTimedSerializer — ไม่ใช่ JWT
# salt แยกต่างหาก: "session" vs "oauth-flow-state"
```

## Data Model

```
rooms:        id, building, floor, number, capacity, status (available/occupied/maintenance)
residents:    id, hub_user_id (UUID จาก JWT.sub), name, email, student_id, ...
reservations: id, room_id, resident_id, status (pending/approved/rejected/cancelled/checked_in),
              requested_at, approved_at, check_in_date, check_out_date
dorm_audit_logs: id, actor_id, action, target_type, target_id, ip, metadata, created_at
```

**hub_user_id**: เก็บเป็น UUID ธรรมดา — ไม่มี FK ไป Hub users table (คนละ database)

## Business Rules

```
Reserve flow:  student → POST /reserve (pending)
               staff → POST /staff/reservations/{id}/approve
               staff → POST /staff/reservations/{id}/checkin
Cancel:        student → POST /cancel (ถ้ายัง pending/approved และยังไม่ check-in)
Reject:        staff → POST /staff/reservations/{id}/reject
```

## Critical Bugs (Dorm specific)

| Bug | อาการ | กฎ |
|-----|------|-----|
| B15 | Gmail ไม่อยู่ใน Google Console test users | เพิ่มใน OAuth consent → Test users |
| B16 | OAuth state ทับกันระหว่าง tabs | state เก็บใน Redis per flow ไม่ใช่ session |
| B17 | Redirect URI ไม่ตรง | เพิ่มใน Google Console + .env |

## Common Tasks

**Seed rooms** (24 ห้อง):
```bash
docker compose exec subsystem-dorm python -m scripts.seed_rooms
```

**Test login flow**: เปิด http://localhost:8001 → คลิก Login → ผ่าน Hub → กลับมา Dorm

**Logs**:
```bash
docker compose logs -f subsystem-dorm
```
