# ระบบเกรด (Grade System) — Subsystem C

Focused demo ของ **Roster Sync + API key** — subsystem ที่ข้อมูล (เกรด) ถูกสร้าง
**ก่อน** ผู้ใช้ login (JIT provisioning อย่างเดียวไม่พอ).

```
สำนักทะเบียน กด Sync ──API key──▶ Hub /api/v1/roster ──▶ รายชื่อ student
       │                                                        │
       └──── pre-create ตารางเกรด (ผูก hub_user_id) ◀───────────┘

student Login ──OAuth PKCE──▶ Hub ──JWT(sub=hub_user_id)──▶ match เกรด → โชว์
```

ต่างจาก dorm/library: **ไม่มี business logic ครบชุด** — โฟกัสจุดขาย Roster+API key
(SQLite self-contained, ไม่มี postgres container แยก).

## Setup

### 1. ลงทะเบียนระบบเกรดใน Hub (ได้ credentials + API key)
```bash
docker compose exec hub-backend python -m scripts.register_grade_subsystem
```
คัดลอกค่า `GRADE_CLIENT_ID` / `GRADE_CLIENT_SECRET` / `GRADE_ROSTER_API_KEY`
ที่ print ออกมา → ใส่ใน `hub/subsystem-grade/.env` (คัดลอกจาก `.env.example`)

> access_policy ตั้งเป็น `role: [student]` — Roster จะคืนเฉพาะนักศึกษา

### 2. Google Console — เพิ่ม redirect URI (one-time)
subsystem OAuth flow ใช้ callback ของ Hub เดิม (`/oauth/callback`) ที่ register ไว้แล้ว
— ไม่ต้องเพิ่มอะไรใหม่ที่ Google. Hub จะ redirect กลับมาที่
`http://localhost:8003/oauth/callback` (อยู่ใน redirect_uris ของ subsystem แล้ว)

### 3. รัน stack
```bash
docker compose -f docker-compose.grade.yml up -d --build
# → http://localhost:8003
```

## ใช้งาน
1. เปิด http://localhost:8003 → กด **Sync Roster** (ดึงนักศึกษา + สร้างเกรดล่วงหน้า)
2. กด **เข้าสู่ระบบผ่าน Hub** → login ด้วยบัญชีนักศึกษา (`65xxxx@uni.ac.th`)
3. เห็นเกรด + GPA ของตัวเอง (match ด้วย Hub user ID)

## หมายเหตุ
- เกรดใน demo generate แบบ deterministic จาก hub_user_id (ค่าคงที่ต่อ user/วิชา,
  sync ซ้ำได้). ระบบจริง import จากสำนักทะเบียนแทน
- `/health` → สถานะ + สถิติ (จำนวนนักศึกษา/เกรด)
- rotate API key ใหม่: รัน register script ซ้ำ (idempotent — ค่าเก่าใช้ไม่ได้)
