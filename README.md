# Central Auth Hub — Starter Project

ระบบจัดการสิทธิ์ผู้ใช้แบบศูนย์กลาง (Senior Project)

## โครงสร้างโปรเจค (เริ่มต้น)

```
central-auth-starter/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── hub/
    └── backend/
        ├── Dockerfile
        ├── requirements.txt
        ├── app/
        │   ├── main.py              # FastAPI entrypoint
        │   ├── config.py            # Settings จาก .env
        │   ├── database.py          # SQLAlchemy engine
        │   ├── models.py            # ตารางทั้งหมด
        │   ├── routers/
        │   │   ├── health.py
        │   │   ├── users.py
        │   │   └── admin.py
        │   └── seeds/
        │       └── seed_users.py    # สร้าง user 100 คน
        └── scripts/
            └── generate_jwt_keys.py
```

## ขั้นตอนการรันครั้งแรก

### 1. ติดตั้ง Docker Desktop
ดาวน์โหลดจาก https://www.docker.com/products/docker-desktop/ (Windows/Mac)

### 2. ตั้งค่า environment
```bash
cp .env.example .env
# แก้ไข .env ตามต้องการ (ระยะแรกใช้ default ได้)
```

### 3. รัน Docker Compose
```bash
docker compose up -d
```

ควรเห็น 3 containers รัน: `hub-postgres`, `hub-redis`, `hub-backend`

### 4. ตรวจสอบว่า Hub ทำงาน
เปิดเบราว์เซอร์ไปที่:
- http://localhost:8000 → ดูข้อมูลเบื้องต้นของ API
- http://localhost:8000/docs → Swagger UI (เอกสาร API ทั้งหมด)
- http://localhost:8000/health → ควรขึ้น `{"status": "ok"}`
- http://localhost:8000/health/db → ควรขึ้น `{"status": "ok", "database": "connected"}`

### 5. Seed ผู้ใช้ 100 คน
```bash
docker compose exec hub-backend python -m app.seeds.seed_users
```

หลัง seed:
- http://localhost:8000/admin/users/count → `{"student": 70, "teacher": 15, "staff": 10, "admin": 5}`
- http://localhost:8000/admin/users → ดูรายชื่อ user 100 คน

### 6. สร้าง JWT signing keys (RSA)
```bash
docker compose exec hub-backend python -m scripts.generate_jwt_keys
```
จะสร้าง `keys/jwt_private.pem` และ `keys/jwt_public.pem`

## คำสั่งที่ใช้บ่อย

```bash
# ดู logs
docker compose logs -f hub-backend

# Restart service เดียว
docker compose restart hub-backend

# เข้า shell ของ container
docker compose exec hub-backend bash

# Stop ทุก service
docker compose down

# Stop + ลบข้อมูล DB (เริ่มใหม่หมด)
docker compose down -v
```

## ขั้นต่อไปที่จะพัฒนา

1. ✅ Project structure + Docker Compose
2. ✅ FastAPI skeleton + Health checks
3. ✅ Database models (users, subsystems, access_list, audit_logs, ...)
4. ✅ Seed 100 users
5. ⏳ **OAuth flow** (Google → Hub → Subsystem)
6. ⏳ JWT token issuance + JWKS endpoint
7. ⏳ Subsystem registration + one-time secret link
8. ⏳ Access List CRUD
9. ⏳ ML Verifier integration
10. ⏳ Admin Dashboard (Next.js)
11. ⏳ Subsystem A (หอพัก) + Subsystem B (ห้องสมุด)

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + SQLAlchemy
- **Database**: PostgreSQL 15
- **Cache**: Redis 7
- **Auth**: OAuth 2.0 + PKCE + JWT (RS256)
- **Frontend**: Next.js (จะเพิ่มภายหลัง)
- **ML**: scikit-learn (Isolation Forest)
- **Container**: Docker Compose

## Trouble Shooting

**ปัญหา: ไม่สามารถ connect Postgres**
- ตรวจ port 5432 ไม่ถูกใช้ก่อนหน้า: `netstat -ano | findstr :5432`
- รัน `docker compose down -v` แล้ว `docker compose up -d` ใหม่

**ปัญหา: ImportError เวลา seed**
- ต้องรันใน container: `docker compose exec hub-backend python -m app.seeds.seed_users`
- ไม่ใช่ `python seed_users.py` ตรงๆ

**ปัญหา: Port 8000 ถูกใช้**
- แก้ใน `docker-compose.yml` เปลี่ยน `"8000:8000"` เป็น `"8001:8000"`
