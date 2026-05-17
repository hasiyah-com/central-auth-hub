# Subsystem A — ระบบหอพัก (Week 6)

Subsystem ตัวอย่างที่ login ผ่าน Central Auth Hub ทำหน้าที่:
- จัดการห้อง + ผู้พัก + การจอง
- มี Postgres ของตัวเอง (`postgres-dorm`) ไม่ใช้ DB ของ Hub
- Role-based access: `resident` (ขอจอง) / `staff` (อนุมัติ + check-in)

## OAuth Flow

```
Browser → /login → /oauth/start (PKCE + state ใน signed cookie)
       → Hub /oauth/authorize → Google → Hub
       → Subsystem /oauth/callback
          ├ exchange code → JWT (server-to-server กับ Hub)
          ├ verify JWT (signature ผ่าน JWKS, iss, aud=client_id)
          ├ upsert resident row
          └ set session cookie (HttpOnly + SameSite=Lax)
       → /
```

## Setup (ครั้งแรก)

### 1. รัน containers ขึ้นมา

```bash
# จาก root ของ central-auth-starter
docker compose up -d --build
```

จะได้: `hub-postgres`, `hub-redis`, `hub-ml`, `hub-backend`, `hub-postgres-dorm`, `hub-subsystem-dorm`

### 2. ลงทะเบียน Subsystem A กับ Hub (manual ผ่าน Developer Portal)

ใน Hub Swagger UI ที่ http://localhost:8000/docs:

**ขั้น 2.1** Login เป็น admin (`POST /auth/google/login`) — ใช้ Gmail ของ admin ใน seed users

**ขั้น 2.2** `POST /developer/subsystems` (ใส่ Bearer token จาก 2.1):
```json
{
  "name": "ระบบหอพัก",
  "description": "Subsystem A — Senior Project Week 6",
  "redirect_uris": ["http://localhost:8001/oauth/callback"],
  "scope": ["email", "name", "student_id", "faculty", "phone"]
}
```

จะได้ response:
```json
{
  "subsystem_id": "...",
  "client_id": "cli_xxx",
  "secret_retrieval_url": "http://localhost:8000/secret/retrieve?token=..."
}
```

**ขั้น 2.3** เปิด `secret_retrieval_url` ใน browser → copy `client_secret`

**ขั้น 2.4** สร้าง `.env` ของ subsystem:
```bash
cp hub/subsystem-dorm/.env.example hub/subsystem-dorm/.env
```
แล้วใส่:
```
DORM_CLIENT_ID=cli_xxx
DORM_CLIENT_SECRET=sec_xxx
```

แล้ว restart:
```bash
docker compose restart subsystem-dorm
```

**ขั้น 2.5** Admin อนุมัติ subsystem: `POST /admin/subsystems/{subsystem_id}/approve`

### 3. เพิ่มผู้ใช้เข้า whitelist

ผ่าน Hub: `POST /developer/subsystems/{subsystem_id}/whitelist/user`

ใส่ JSON:
```json
{ "email": "650001@uni.ac.th", "role": "resident" }
```

หรือ staff:
```json
{ "email": "somchai006@uni.ac.th", "role": "staff" }
```

(หรือใช้ CSV upload ผ่าน `POST /developer/subsystems/{id}/whitelist`)

### 4. Seed ห้อง (ตึก A/B × 3 ชั้น × 4 ห้อง = 24 ห้อง)

```bash
docker compose exec subsystem-dorm python -m scripts.seed_rooms
```

### 5. เปิดใช้งาน

http://localhost:8001/ — จะ redirect ไป /login → กดปุ่ม "Login ด้วย Central Auth Hub"

## โครงสร้าง

```
hub/subsystem-dorm/
├── Dockerfile, requirements.txt, .env.example, .env (gitignored)
├── app/
│   ├── main.py, config.py, database.py, models.py, deps.py
│   ├── services/
│   │   ├── hub_client.py    # PKCE + token exchange + JWKS verify
│   │   ├── session.py       # itsdangerous signed cookie
│   │   └── audit.py         # log_action() ของ subsystem
│   ├── routers/
│   │   ├── auth.py          # /login, /oauth/start, /oauth/callback, /logout
│   │   ├── pages.py         # /, /me, /rooms, /rooms/{id}
│   │   ├── reservation.py   # POST /reservation/rooms/{id}/reserve, /cancel
│   │   └── staff.py         # /staff/residents, /staff/reservations + approve/reject/checkin
│   ├── templates/           # Jinja2 + Tailwind CDN
│   └── static/style.css
└── scripts/seed_rooms.py
```

## Database (dorm_db ใน postgres-dorm:5432)

| Table | คำอธิบาย |
|-------|----------|
| `rooms` | ห้องในหอพัก (seed 24) |
| `residents` | คนที่ login เข้าระบบ (สร้างจาก JWT.sub ตอน login ครั้งแรก) |
| `reservations` | คำขอจอง — pending → approved/rejected → checked_in. ยกเลิกใช้ `cancelled_at` (soft delete) |
| `dorm_audit_logs` | audit log ทุก state-changing action |

**ไม่มี FK ไป Hub** — `hub_user_id` เก็บเป็น UUID อิสระ (จาก JWT.sub) ตามหลัก microservice

## Reservation lifecycle

```
[resident POST /reserve]
   → status=pending
        ↓
[staff approve]                  [staff reject (กรอกเหตุผล)]
   → status=approved              → status=rejected, reject_reason
        ↓
[staff check-in]
   → status=checked_in
   → resident.room_id ← room
   → resident.status=checked_in
   → ถ้าครบ capacity → room.status=full
```

Resident ยกเลิกเองได้เฉพาะตอน `pending` หรือ `approved` (หลัง `checked_in` ต้องให้ staff)

## Security

ตาม Defense in Depth (CLAUDE.md):
- **Layer 3** — OAuth 2.0 + PKCE (RFC 7636)
- **Layer 4** — JWT RS256 verify ผ่าน Hub JWKS, บังคับ `aud=client_id` กัน token ของ subsystem อื่น
- **Layer 6** — Session cookie HttpOnly + SameSite=Lax + max_age 1 ชม.
- **Layer 7** — `dorm_audit_logs` ทุก state-changing action

## Endpoints

### Resident
- `GET /login` — หน้า login
- `GET /` — home (สถานะปัจจุบัน + reservation ล่าสุด)
- `GET /me` — โปรไฟล์ + ประวัติการจอง
- `GET /rooms` — list ห้อง + ระดับการครอบครอง
- `GET /rooms/{id}` — รายละเอียดห้อง + ฟอร์มจอง
- `POST /reservation/rooms/{id}/reserve` — ขอจอง
- `POST /reservation/{id}/cancel` — ยกเลิกการจองของตัวเอง

### Staff (role=staff เท่านั้น)
- `GET /staff/residents` — list ผู้พักทั้งหมด
- `GET /staff/reservations?status={pending|approved|checked_in|rejected|all}` — list คำขอ
- `POST /staff/reservations/{id}/approve` — อนุมัติ
- `POST /staff/reservations/{id}/reject` — ปฏิเสธ (มี form กรอกเหตุผล)
- `POST /staff/reservations/{id}/checkin` — check-in ผู้พักเข้าห้อง

### System
- `GET /health` — liveness probe
- `GET /logout` — clear session
