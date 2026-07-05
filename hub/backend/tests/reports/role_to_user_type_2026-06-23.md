# Report — role_in_sub → user_type migration (subsystem)

- **วันที่:** 2026-06-23
- **ขอบเขต:** ตัด `role_in_sub` (role เฉพาะ subsystem) ออกทั้งหมด → ใช้ **`user_type`** (student/teacher/staff/admin) จาก Hub แทน ทั้ง dorm + library + **ลบข้อมูลเก่าทั้งสอง subsystem**
- **ผลรวม:** ✅ regression **33 passed** · subsystem imports clean · login pages 200 · schema = user_type · data เก่าถูกลบ

## สิ่งที่เปลี่ยน

### Hub
- `services/jwt_service.py::create_subsystem_token` — เพิ่ม claim **`user_type`** + ตั้ง `role_in_subsystem = user.user_type` (transition alias) · param `role_in_sub` → optional (เลิกใช้)

### Subsystem-dorm
- `deps.py` — `CurrentUser.role_in_sub` → `user_type` · `require_role()` เช็ค `user_type` · `get_or_create_resident` เก็บ `user_type`
- `models.py` — `residents.role_in_sub` → `user_type`
- `routers/{auth,pages,staff}.py` — อ่าน `claims["user_type"]` · staff guard = `require_role("staff","teacher","admin")` · serialize `user_type`
- `static/app.js` — `role_in_sub` → `user_type` (14 จุด) · `resident→student` (menu default)
- `templates/*` (base/home/me/room_detail/staff/residents) — rename

### Subsystem-library
- `deps.py` · `models.py` (`members.user_type`) · `routers/{auth,librarian}.py` · `templates/*` — เหมือน dorm
- **บรรณารักษ์ = staff/teacher/admin** · สมาชิก = student

### Mapping
| เดิม | ใหม่ (user_type) |
|---|---|
| resident / member | student |
| (staff) | staff |
| (teacher) | teacher |
| librarian | staff / teacher / admin |

## Data wipe (ตาม decision)
- ใช้ `TRUNCATE ... RESTART IDENTITY CASCADE` + `ALTER TABLE ... RENAME COLUMN role_in_sub TO user_type`
  (สาเหตุ: `docker compose down -v` ไม่ลบ volume จริง เพราะ volume อยู่คนละ compose-project `central-auth-starter_postgres_*_data`)
- **dorm:** wipe residents/reservations/dorm_audit_logs · คง rooms(24) · rename column
- **library:** wipe members/borrowings/library_audit_logs · reseed books(30) · rename column

## ผลทดสอบ

| ตรวจ | ผล |
|---|---|
| `pytest test_jwt_service test_oauth_passkey test_rbac` | ✅ 33 passed |
| JWT ส่ง user_type ครบทุก role | ✅ student/teacher/staff → user_type ตรง |
| subsystem imports (dorm+library) | ✅ clean |
| login pages 8001/8002 | ✅ 200 |
| dorm app.js `role_in_sub` count | ✅ 0 (user_type 14) |
| residents/members schema | ✅ column `user_type` |
| rooms/books reseed | ✅ 24 / 30 |

## แก้ test เดิม
`test_jwt_service.py::test_subsystem_token_has_audience_filter` — contract เปลี่ยน:
`role_in_subsystem` ไม่ echo param แล้ว → = `user_type`. อัปเดต assert เป็น
`payload["user_type"] == user.user_type` + `role_in_subsystem == user.user_type`

## เหลือไว้ (ตั้งใจ)
- `routers/auth.py` (ทั้ง 2 subsystem): fallback `claims.get("user_type") or claims.get("role_in_subsystem", "student")` — transition กัน JWT เก่าที่ยังไม่มี user_type claim
- comment ใน `deps.py` / `main.py` — ไม่กระทบ runtime

## ยังไม่ทำ (phase ถัดไป ตาม plan)
- Access Policy engine (all/role/attribute) + login-time check
- Roster Sync API (API key + `/api/v1/roster`)
- Frontend admin/dev: ตัด UI เลือก role ตอน add whitelist (ยังส่ง role ได้แต่ backend ไม่ใช้)
